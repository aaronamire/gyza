"""
AgentRunner — claim-execute-sign loop wiring all the Phase 1 layers.

One AgentRunner instance corresponds to one running agent process. The
loop is:

    for unclaimed work that fits this agent's specialization:
        try_claim → execute → hash output → store artifact →
        sign ICP envelope → complete work item → write episode →
        drift specialization

Concurrency: the loop runs on a daemon thread spawned by start(). The
blackboard's BEGIN IMMEDIATE in try_claim makes claim contention safe
across multiple AgentRunner threads/processes — exactly one claims any
given item.

Executors are pluggable. The runner doesn't care whether the model
actually runs locally, hits a cloud API, or is mocked — it just needs
a callable with the (prompt, context) → result_dict contract.

For Phase 3 onward, when accepting work claims from strangers, wrap
the executor in ``gyza.sandbox.make_sandboxed_executor`` (or one of
the convenience presets ``sandboxed_mock_executor`` /
``sandboxed_anthropic_executor``). The runner's contract is unchanged
— same callable signature — but the work happens inside a bubblewrap
subprocess with explicit FS / network / resource constraints. See
``gyza/sandbox/runner.py`` for the threat model.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from typing import Any, Callable

import blake3
import numpy as np

from gyza.blackboard import Blackboard
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import ICPEnvelope, compute_envelope_hash
from gyza.identity import AgentIdentity
from gyza.memory import Episode, EpisodicMemory, build_enriched_prompt
from gyza.schema import Artifact, HLC, WorkItem


# Observability hooks. The module-private wrappers fail closed so an
# import-time error in gyza.observability (e.g. prometheus_client
# missing on a stripped-down install) doesn't take down the runner —
# the metrics simply stop updating.
try:
    from gyza.observability import (
        AGENT_COMPLETIONS_TOTAL as _AGENT_COMPLETIONS_TOTAL,
        CLAIM_TO_COMPLETE_LATENCY as _CLAIM_TO_COMPLETE_LATENCY,
    )

    def _obs_completion(outcome: str) -> None:
        _AGENT_COMPLETIONS_TOTAL.labels(outcome=outcome).inc()

    def _obs_claim_latency(duration_s: float) -> None:
        _CLAIM_TO_COMPLETE_LATENCY.observe(max(0.0, duration_s))
except Exception:  # noqa: BLE001
    def _obs_completion(outcome: str) -> None:  # type: ignore[misc]
        pass

    def _obs_claim_latency(duration_s: float) -> None:  # type: ignore[misc]
        pass


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class AgentRunner:
    def __init__(
        self,
        identity: AgentIdentity,
        blackboard: Blackboard,
        memory: EpisodicMemory,
        specialization: SpecializationTracker,
        lsh: LSHIndex,
        executor: Callable[[str, dict], dict],
        min_reward_threshold: float = 0.1,
        min_similarity_threshold: float = 0.3,
        poll_interval_s: float = 1.0,
        on_envelope_signed: Callable[[ICPEnvelope], None] | None = None,
        verify_chain_before_claim: bool = True,
        strict_chain_verification: bool = False,
        hlc: HLC | None = None,
        reputation_store=None,
    ):
        self._identity = identity
        self._bb = blackboard
        self._mem = memory
        self._spec = specialization
        self._lsh = lsh
        self._executor = executor
        self._min_reward = min_reward_threshold
        self._min_sim = min_similarity_threshold
        self._poll_s = poll_interval_s
        # Caller-provided hook fired after every successful envelope
        # signing. Used by GlobalCluster.runner_envelope_hook for
        # ledger-settlement plumbing.
        self._on_envelope_signed = on_envelope_signed
        # Pre-claim chain verification — Phase 3 Session 8.5.
        #
        # When enabled, the runner walks the parent_id chain of any
        # candidate work item, fetches the corresponding ICP envelopes
        # from the blackboard's persistent log, and calls
        # verify_chain_multi_compositor before claiming. This closes
        # the gap where verify_chain was implemented but never invoked
        # at runtime — a malicious peer could otherwise post work items
        # whose chain points at fabricated history.
        #
        # ``strict_chain_verification``:
        #   False (default): if envelopes are missing from the local log
        #     (e.g. the ancestor was completed by a remote node and we
        #     haven't yet received its envelope via gossip), claim
        #     proceeds with a logged warning.
        #   True: missing envelopes are treated as verification failure;
        #     the claim is skipped. Use this when running with strict
        #     security requirements and a fully-gossiped envelope log.
        self._verify_chain_before_claim = verify_chain_before_claim
        self._strict_chain_verification = strict_chain_verification
        # Optional reputation store. When supplied, every successful
        # completion bumps this agent's score; every failed/released
        # completion bumps it down. Discovery-side filters (DHT
        # find_agents min_reputation, free-rider scoring) read from
        # the same store. None disables — backward compatible with
        # existing tests that don't care about reputation.
        self._reputation_store = reputation_store

        self._signer = identity.get_icp_signer()
        # Phase 3 Session 8.5 — when the blackboard is gossip-attached,
        # callers should pass ``hlc=blackboard.gossip_hlc()`` so this
        # runner's claims advance the SAME clock as cross-cluster
        # delta merges. Without that, local claims can produce HLC
        # tuples lex-smaller than concurrent remote claims and break
        # the cross-cluster total-order invariant.
        #
        # Single-node deployments (no gossip attached) get a per-agent
        # HLC keyed on the agent_id — adequate because the only
        # contention is with other local agents, and Raft already
        # serializes claim writes.
        self._hlc = hlc if hlc is not None else HLC(node_id=identity.agent_id)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._completed_count = 0

        # Items this runner has just released back to the blackboard after
        # a local executor failure. We skip them in future scoring rounds
        # so we don't loop on the same poisoned item; another agent (or
        # this one after restart) can still pick them up.
        self._recently_failed: set[str] = set()

        # Last envelope this agent signed; new envelopes parent-link to it.
        # Only the agent's own chain — cross-agent linkage is a future-phase
        # concern.
        self._last_envelope: ICPEnvelope | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"gyza-runner-{self._identity.agent_id[:8]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            # Generous join window — _complete may be mid-write to mem
            # (LanceDB) or spec (SQLite) when stop is requested. Cutting
            # those writes short loses an episode AND drops the
            # _completed_count increment that observers (tests, demos)
            # poll for, even though the work item is already committed
            # to the blackboard via Raft.
            self._thread.join(timeout=self._poll_s + 15.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def completed_count(self) -> int:
        return self._completed_count

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        tier = int(self._identity.manifest.get("attestation_tier", 0))
        while not self._stop.is_set():
            try:
                items = self._bb.get_unclaimed(
                    min_reward=self._min_reward, tier=tier,
                )
            except Exception:
                time.sleep(self._poll_s)
                continue

            # Drop items this runner has already failed on locally — keeps
            # the loop from re-claiming a deterministically-poisoned item.
            if self._recently_failed:
                items = [w for w in items if w.id not in self._recently_failed]

            if not items:
                if self._stop.wait(self._poll_s):
                    return
                continue

            best_item, score = self._score_items(items)
            if score < self._min_sim:
                if self._stop.wait(self._poll_s):
                    return
                continue

            # Pre-claim chain verification — refuse to build on top of
            # a chain we can't verify. Only walks if the item has a
            # parent (intent-root items have nothing to verify).
            if (
                self._verify_chain_before_claim
                and best_item.parent_id is not None
                and not self._verify_lineage(best_item)
            ):
                # Skip this item; another agent (with the missing
                # envelopes, or with strict mode off) may still claim.
                self._recently_failed.add(best_item.id)
                continue

            try:
                claimed = self._bb.try_claim(
                    best_item.id, self._identity.agent_id, self._hlc,
                )
            except Exception:
                # Transient DB failure — back off briefly.
                if self._stop.wait(self._poll_s):
                    return
                continue

            if not claimed:
                # Lost the race; loop immediately for the next-best.
                continue

            t_claim = time.monotonic()
            try:
                result = self._execute(best_item)
                self._complete(best_item, result, success=True)
                _obs_completion("success")
            except Exception as e:
                # Executor failure: release the claim back to the
                # blackboard so another agent can try, write an episode
                # so the failure feeds drift, and remember the item
                # locally so we don't immediately re-claim it.
                err_repr = f"{type(e).__name__}: {e}"
                traceback.print_exc()
                self._release(best_item, error=err_repr)
                _obs_completion("released")
            finally:
                _obs_claim_latency(time.monotonic() - t_claim)

    # ------------------------------------------------------------------
    # Scoring / execution
    # ------------------------------------------------------------------

    def _verify_lineage(self, item: WorkItem) -> bool:
        """
        Walk this work item's parent chain, fetch each ancestor's
        envelope from the local log, and verify the resulting chain.

        Returns True if the chain verifies cleanly OR if envelopes are
        missing AND ``strict_chain_verification`` is False (fail-open
        for cross-cluster work whose envelopes haven't gossiped to us
        yet). Returns False on cryptographic failure or on missing
        envelopes when strict mode is on.

        Why not at gather-inputs time: artifact-level signatures are
        already checked at fetch (artifact_client). The CHAIN check is
        a higher-level invariant — "this work descends from a verifiable
        sequence of authored steps" — and naturally lives at the claim
        boundary, before we burn local compute on something we can't
        prove came from honest history.
        """
        # Reconstruct only the ANCESTOR chain; the work item itself
        # hasn't been completed and has no envelope yet. We walk from
        # parent_id up. (parent_id is non-None: we only call this
        # method for items with a parent.)
        parent_id = item.parent_id or ""
        ancestors_chain, missing = self._bb.reconstruct_chain(parent_id)
        if missing:
            if self._strict_chain_verification:
                print(
                    f"[{self._identity.agent_id[:8]}] strict-verify: "
                    f"chain incomplete for {item.id[:8]} "
                    f"(missing envelope for action {missing[:8]}); skipping",
                    flush=True,
                )
                return False
            # Fail-open: log once per item, accept the claim.
            print(
                f"[{self._identity.agent_id[:8]}] verify: chain incomplete "
                f"for {item.id[:8]} (missing envelope for action "
                f"{missing[:8]}); proceeding (strict=False)",
                flush=True,
            )
            return True
        if not ancestors_chain:
            # No ancestors — nothing to verify.
            return True

        # Use verify_chain (the single-key verifier) here. It checks:
        #   1. Each envelope's signature against its declared agent_pubkey.
        #   2. parent_envelope_hash linkage from one hop to the next.
        #   3. input_hashes non-empty (rules out the "stamped without
        #      reading" attack).
        # We deliberately do NOT call verify_chain_multi_compositor at
        # this layer — it requires a TrustRegistry + ArtifactStore that
        # the runner doesn't carry. Compositor-trust checks happen at
        # the network layer (GlobalCluster._verify_peer_attestation);
        # artifact availability is checked at gather-inputs time.
        from gyza.icp import verify_chain
        valid, first_bad = verify_chain(ancestors_chain)
        if not valid:
            print(
                f"[{self._identity.agent_id[:8]}] verify: chain INVALID "
                f"for {item.id[:8]} at index {first_bad}",
                flush=True,
            )
            return False
        return True

    def _score_items(self, items: list[WorkItem]) -> tuple[WorkItem, float]:
        spec = self._spec.current
        best = items[0]
        best_score = _cosine(spec, best.desc_embedding)
        for it in items[1:]:
            s = _cosine(spec, it.desc_embedding)
            if s > best_score:
                best_score = s
                best = it
        return best, best_score

    def _gather_inputs(self, item: WorkItem) -> list[Artifact]:
        out: list[Artifact] = []
        for h in item.input_hashes:
            a = self._bb.get_artifact(h)
            if a is not None:
                out.append(a)
        return out

    def _execute(self, item: WorkItem) -> dict[str, Any]:
        t0 = time.monotonic_ns()
        inputs = self._gather_inputs(item)

        prompt = build_enriched_prompt(
            base_prompt=item.description,
            memory=self._mem,
            current_task=item.description,
            max_episodes=5,
        )
        context = {"item": item, "inputs": inputs}
        raw = self._executor(prompt, context)

        if not isinstance(raw, dict) or "text" not in raw:
            raise RuntimeError(
                f"executor must return dict with 'text' key; got {type(raw).__name__}"
            )

        # Bounds-proof soundness gate. A sandboxed executor's host-side
        # wrapper stamps a trustworthy ``__enforcement__`` record. If
        # one is present, the work was supposed to run bounded — so we
        # REFUSE to sign unless that enforcement is consistent with
        # (no wider than) this agent's capability manifest. Raising
        # here means _complete is never reached: the claim is released
        # (see _run_loop), and no envelope is ever produced for
        # execution we can't prove stayed in bounds. A valid signed
        # envelope therefore IMPLIES bounded execution.
        #
        # Back-compat by trigger: plain / mock / deterministic
        # executors don't stamp __enforcement__, so this is a no-op
        # for them — the artifact below is byte-identical to before
        # and the existing test suite is unaffected.
        enforcement = raw.get("__enforcement__")
        if enforcement is not None:
            from gyza.sandbox.config import enforcement_satisfies_manifest
            ok, why = enforcement_satisfies_manifest(
                enforcement, self._identity.manifest,
            )
            if not ok:
                raise RuntimeError(
                    f"refusing to sign — sandbox enforcement is not "
                    f"consistent with the agent manifest: {why}"
                )

        # Canonical JSON for the output so the BLAKE3 hash is stable
        # across runs / processes. When an enforcement record is
        # present we fold it into the artifact so the envelope's
        # output_hash cryptographically commits to the (verified)
        # bounds the work ran under — the bounds-proof lives inside
        # the signed bytes, not in trust of the runner's behavior.
        artifact_obj: dict = {"text": raw.get("text", "")}
        if enforcement is not None:
            artifact_obj["__enforcement__"] = enforcement
        canonical = json.dumps(
            artifact_obj, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        output_hash = blake3.blake3(canonical).hexdigest()

        # Persist the artifact so downstream agents can fetch it by hash.
        # Sign the artifact bytes with the agent's identity key — distinct
        # from the ICP envelope signature, but lets standalone artifact
        # consumers verify provenance without walking the chain.
        artifact_sig = self._identity.sign_bytes(canonical)
        self._bb.store_artifact(Artifact(
            hash=output_hash,
            data=canonical,
            signature=artifact_sig,
            signer_pubkey=self._identity.pubkey_hex,
            parent_hashes=list(item.input_hashes),
            timestamp_ns=time.time_ns(),
        ))
        # Mirror to the content-addressed file store if attached. Phase-2
        # cross-machine verification needs raw bytes addressable by hash
        # outside SQLite — verify_chain_multi_compositor reads from
        # ArtifactStore, not the per-node `artifacts` table.
        cas = getattr(self._bb, "_artifact_store", None)
        if cas is not None:
            try:
                cas.store(canonical)
            except Exception:
                pass

        duration_ms = max(1, (time.monotonic_ns() - t0) // 1_000_000)
        return {
            "output": raw.get("text", ""),
            "output_hash": output_hash,
            "duration_ms": int(duration_ms),
            "tokens_in": int(raw.get("tokens_in", 0)),
            "tokens_out": int(raw.get("tokens_out", 0)),
            "model_identifier": str(raw.get("model_identifier", "unknown")),
            "inference_backend": str(raw.get("inference_backend", "mock")),
        }

    # ------------------------------------------------------------------
    # Release: executor failure → unclaim → episode → drift
    # ------------------------------------------------------------------

    def _release(self, item: WorkItem, error: str) -> None:
        try:
            self._bb.release_claim(item.id)
        except Exception:
            pass

        self._recently_failed.add(item.id)

        try:
            self._mem.write(Episode(
                episode_id=str(uuid.uuid7()),
                agent_id=self._identity.agent_id,
                task_embedding=item.desc_embedding.astype(np.float32),
                intent_text=item.description,
                input_hashes=list(item.input_hashes) or ["00" * 32],
                output_hash="00" * 32,
                action_types=[],
                success=False,
                duration_ms=0,
                model_identifier="error",
                icp_envelope_hash="",
                timestamp_ns=time.time_ns(),
            ))
        except Exception:
            pass

        try:
            self._spec.update(item.desc_embedding, success=False)
        except Exception:
            pass

        # Reputation: count an executor failure as an ordinary failure
        # (not a dispute) — this isn't a protocol violation, the
        # agent's executor just couldn't produce a valid output.
        if self._reputation_store is not None:
            try:
                self._reputation_store.record_failure(self._identity.agent_id)
            except Exception:
                pass

        self._completed_count += 1
        print(
            f"[{self._identity.agent_id[:8]}] ✗ {item.description[:60]} "
            f"(released) — error: {error}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # Completion: ICP sign → blackboard complete → episode → drift
    # ------------------------------------------------------------------

    def _complete(
        self,
        item: WorkItem,
        result: dict | None,
        success: bool,
        error: str = "",
    ) -> None:
        # On failure, hash the error string so the chain still records *something*
        # rather than punching a hole in it. Empty input_hashes would also break
        # verify_chain's "must read something" rule, so we synthesize a
        # zero-hash placeholder if the item carried none.
        if result is None:
            err_payload = json.dumps(
                {"error": error}, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            output_hash = blake3.blake3(err_payload).hexdigest()
            duration_ms = 0
            tokens_in = 0
            tokens_out = 0
            model_id = "n/a"
            backend = "error"
        else:
            output_hash = result["output_hash"]
            duration_ms = result["duration_ms"]
            tokens_in = result["tokens_in"]
            tokens_out = result["tokens_out"]
            model_id = result.get("model_identifier", "unknown")
            backend = result.get("inference_backend", "mock")

        # ICP envelope. parent_envelope is this agent's previous envelope
        # — the per-agent local chain. (Cross-agent chains are stitched
        # by a future indexer that walks parent_envelope_hash links.)
        input_hashes = item.input_hashes if item.input_hashes else [
            "00" * 32  # placeholder for "read nothing", keeps verify_chain happy
        ]
        envelope = self._signer.sign_action(
            intent_id=item.lineage_root,
            action_id=item.id,
            input_hashes=input_hashes,
            output_hash=output_hash,
            parent_envelope=self._last_envelope,
            inference_backend=backend,
            model_identifier=model_id,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        envelope_hash = compute_envelope_hash(envelope)
        self._last_envelope = envelope

        # Persist to the blackboard's envelope log so future runners
        # (this one, after restart, or any other agent on this node)
        # can verify chains rooted in our completions. Best-effort:
        # if the blackboard is in a broken state we still want
        # complete_work_item below to fire so the work item itself
        # becomes visible.
        try:
            self._bb.store_envelope(envelope)
        except Exception:
            pass

        if self._on_envelope_signed is not None:
            try:
                self._on_envelope_signed(envelope)
            except Exception:
                # Settlement / observability hook — never break completion.
                pass

        # Bump the completion counter HERE — before bb.complete_work_item
        # publishes the work item's completion to other nodes via Raft.
        # Why: a coordinator that polls for completed_at_ns can race with
        # the rest of this method. The moment complete_work_item commits,
        # the coordinator may already drop the "done" sentinel; the
        # executor's main loop sees it within poll_interval_s and calls
        # runner.stop(). If join times out before _completed_count is
        # incremented, the daemon thread is killed on process exit and
        # the counter stays stale. Incrementing before the Raft commit
        # makes the invariant: any observer that can see this work item
        # complete also sees the counter bumped.
        self._completed_count += 1

        # Reputation: bump up on success, down on failure. Done before
        # complete_work_item so an observer that sees the bump always
        # sees a consistent post-completion state.
        if self._reputation_store is not None:
            try:
                if success:
                    self._reputation_store.record_success(self._identity.agent_id)
                else:
                    self._reputation_store.record_failure(self._identity.agent_id)
            except Exception:
                pass

        # Mark the work item complete on the blackboard.
        try:
            self._bb.complete_work_item(
                item.id, output_hash, envelope_hash, success, self._hlc,
            )
        except Exception:
            pass  # DB write is best-effort; the signed envelope is the
                  # source of truth.

        # Write an episode and drift the specialization vector.
        try:
            self._mem.write(Episode(
                episode_id=str(uuid.uuid7()),
                agent_id=self._identity.agent_id,
                task_embedding=item.desc_embedding.astype(np.float32),
                intent_text=item.description,
                input_hashes=list(input_hashes),
                output_hash=output_hash,
                action_types=[],  # no GoalSpec actions wired in Phase 1
                success=success,
                duration_ms=duration_ms,
                model_identifier=model_id,
                icp_envelope_hash=envelope_hash,
                timestamp_ns=time.time_ns(),
            ))
        except Exception:
            pass

        try:
            self._spec.update(item.desc_embedding, success=success)
        except Exception:
            pass

        mark = "✓" if success else "✗"
        desc = item.description[:60]
        print(
            f"[{self._identity.agent_id[:8]}] {mark} {desc} "
            f"({duration_ms}ms)"
            + (f" — error: {error}" if error and not success else ""),
            flush=True,
        )


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def make_mock_executor(response: str = "mock output") -> Callable[[str, dict], dict]:
    def _executor(_prompt: str, _context: dict) -> dict:
        return {
            "text": response,
            "tokens_in": 10,
            "tokens_out": 5,
            "model_identifier": "mock",
            "inference_backend": "mock",
        }
    return _executor


def make_anthropic_executor(
    api_key: str | None = None,
    model: str = "claude-sonnet-4-5",
) -> Callable[[str, dict], dict]:
    """
    Pluggable Anthropic executor. The runner stays unaware of the
    transport — it just calls executor(prompt, context).

    Imports `anthropic` lazily so the module loads cleanly on machines
    that don't have the SDK installed (everyone using the mock executor).
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError(
            "anthropic executor needs an api key (arg or ANTHROPIC_API_KEY env)"
        )

    def _executor(prompt: str, context: dict) -> dict:
        from anthropic import Anthropic  # lazy import
        client = Anthropic(api_key=key)

        # Inline any input artifact contents so the model can see them —
        # the runner stores artifacts as canonical JSON bytes.
        input_blocks: list[str] = []
        for art in context.get("inputs", []):
            try:
                snippet = art.data.decode("utf-8", errors="replace")[:4000]
            except Exception:
                snippet = f"<{len(art.data)} bytes, hash={art.hash[:8]}…>"
            input_blocks.append(
                f"## input artifact ({art.hash[:8]}…)\n{snippet}"
            )

        full_prompt = prompt
        if input_blocks:
            full_prompt = "\n\n".join(input_blocks) + "\n\n" + prompt

        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": full_prompt}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        usage = getattr(msg, "usage", None)
        return {
            "text": text,
            "tokens_in": int(getattr(usage, "input_tokens", 0)) if usage else 0,
            "tokens_out": int(getattr(usage, "output_tokens", 0)) if usage else 0,
            "model_identifier": model,
            "inference_backend": "anthropic",
        }

    return _executor


__all__ = [
    "AgentRunner",
    "make_mock_executor",
    "make_anthropic_executor",
]
