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
        # Optional hook fired after every successful envelope signing.
        # Used by Phase-2 cross-process demos to persist envelopes so a
        # coordinator can reconstruct the chain without in-process state.
        self._on_envelope_signed = on_envelope_signed

        self._signer = identity.get_icp_signer()
        self._hlc = HLC(node_id=identity.agent_id)

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
            self._thread.join(timeout=self._poll_s + 5.0)
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

            try:
                result = self._execute(best_item)
                self._complete(best_item, result, success=True)
            except Exception as e:
                # Executor failure: release the claim back to the
                # blackboard so another agent can try, write an episode
                # so the failure feeds drift, and remember the item
                # locally so we don't immediately re-claim it.
                err_repr = f"{type(e).__name__}: {e}"
                traceback.print_exc()
                self._release(best_item, error=err_repr)

    # ------------------------------------------------------------------
    # Scoring / execution
    # ------------------------------------------------------------------

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

        # Canonical JSON for the output so the BLAKE3 hash is stable
        # across runs / processes.
        canonical = json.dumps(
            {"text": raw.get("text", "")}, sort_keys=True, separators=(",", ":"),
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

        if self._on_envelope_signed is not None:
            try:
                self._on_envelope_signed(envelope)
            except Exception:
                # Demo/observability hook — never break completion.
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

        self._completed_count += 1

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
