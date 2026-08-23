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
import logging
import os
import random
import threading
import time
import traceback

LOG = logging.getLogger("gyza.runner")
import uuid
from typing import Any, Callable

import blake3
import numpy as np

from gyza.blackboard import Blackboard, ClaimLostError
from gyza.containment.projection import AuthorityViolation
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import ICPEnvelope, compute_envelope_hash
from gyza.identity import AgentIdentity
from gyza.memory import Episode, EpisodicMemory, build_enriched_prompt
from gyza.schema import Artifact, HLC, WorkItem

# BUILD_PLAN E2 — process-wide default for the bounds-proof refusal policy.
# Production entry points set this True (or pass require_enforcement=True);
# unit tests with mock executors leave it False. Moves into the signed guard
# configuration (C-8) once that trust domain exists.
#: The window `action_rate_cap` is measured over. A RATE needs two numbers and
#: the manifest declares one, so the second lives here as a constant.
#:
#: DELIBERATELY NOT READ FROM THE MANIFEST. A principal that could widen its own
#: window could restore the lifetime-quota semantics this replaced, or erase the
#: cap entirely by declaring a window longer than the deployment. The window is
#: a property of the enforcement, not of the grant.
#: Hard ceiling on task-decomposition depth. Distinct from
#: MAX_DELEGATION_DEPTH (which bounds AUTHORITY hops) because this bounds
#: WORK hops -- an agent may decompose without delegating any authority --
#: but it is the same hazard, unbounded recursion, so it gets its own
#: explicit constant rather than silently reusing the other one.
MAX_TASK_DEPTH = 3

SELECTION_TIE_EPSILON = 1e-3
#: Candidates fetched per poll. Bounds O(backlog) work per agent per poll.
POLL_CANDIDATES = 128

RATE_WINDOW_NS = 3600 * 1_000_000_000   # one hour

REQUIRE_ENFORCEMENT_DEFAULT = False


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
        require_enforcement: bool | None = None,
        review_queue=None,
        harm_registry=None,
        cadence_origin_ns: int = 0,
        rate_window_ns: int = RATE_WINDOW_NS,
    ):
        # BUILD_PLAN E2 — the fail-open gate.
        #
        # The bounds check historically ran only `if enforcement is not None`,
        # so an executor that stamped no record skipped it entirely and still
        # produced a signed envelope. That is non-repudiation of a claim rather
        # than refusal to proceed without one.
        #
        # `require_enforcement` makes the policy EXPLICIT and refusable:
        #   True  — refuse to sign any work item lacking a valid record.
        #   False — permit it (the historical behaviour), for unit tests and
        #           mock/deterministic executors that do not sandbox at all.
        #   None  — take the process-wide default below.
        #
        # The default is deliberately NOT flipped here: 18 test files drive the
        # runner with non-sandboxing executors, and flipping it silently would
        # convert a security decision into test churn.
        #
        # "Production entry points set it True explicitly" WAS FALSE FROM THE
        # DAY THIS COMMENT WAS WRITTEN UNTIL 2026-08-21. `require_enforcement`
        # appeared nowhere in gyza/ outside this file, so the bounds-proof
        # requirement rested entirely on every executor branch in `cli.py`
        # happening to sandbox -- true, and enforced by nothing. A fourth branch
        # added without a sandbox would have signed envelopes carrying no
        # bounds-proof, silently.
        #
        # It is now supplied by `run_local_task` as `_built_sandboxed`, tied to
        # the branch that already refuses to run without bubblewrap, so the
        # guarantee is structural there. It is NOT unconditional: an injected
        # executor stamps no record, and refusing those is what would have made
        # this test churn.
        #
        # `tests/test_declared_is_wired.py` now DERIVES the guard-consumer list
        # from constructor signatures instead of holding three literals, which
        # is how this parameter walked past the check that exists to catch
        # exactly it. When C-8 (guard configuration in a separate trust domain)
        # lands, this policy moves there and stops being a constructor argument.
        self._require_enforcement = (
            REQUIRE_ENFORCEMENT_DEFAULT if require_enforcement is None
            else bool(require_enforcement)
        )
        self._identity = identity
        # H4's measurand. APPEND-ONLY and never cleared: authority exceedance
        # is monotone non-cumulative -- once exceeded it cannot be un-exceeded
        # -- so a counter that could be reset would be a bound whose origin
        # moves, which is not a bound (ledger artifact #13).
        self._authority_violations: list[AuthorityViolation] = []
        # H6's consumer. None means the cadence is not watched -- which is the
        # honest default for a runner with no review path attached, not a
        # silently-disabled guard.
        self._review_queue = review_queue
        self._harm_registry = harm_registry
        self._cadence_origin_ns = int(cadence_origin_ns)
        # Injectable so tests can exercise the window without sleeping an hour.
        # A non-positive window would make the rate cap unenforceable by making
        # the lookback empty, so it is rejected rather than silently ignored.
        if int(rate_window_ns) <= 0:
            raise ValueError(
                f"rate_window_ns must be positive, got {rate_window_ns}; a "
                f"non-positive window disables the rate cap silently")
        self._rate_window_ns = int(rate_window_ns)
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
                # REAP BEFORE POLLING. A claim is a lease, and a runner that
                # died holding one leaked its item permanently -- there is
                # exactly one caller of `release_claim` (the in-process failure
                # path below), and `get_unclaimed`'s TTL filter only applies to
                # rows that are already unclaimed.
                #
                # WIRED HERE RATHER THAN IN A SWEEPER because a sweeper is one
                # more thing that must be constructed, and this file's own
                # history is a list of mechanisms that existed and were never
                # called. Every live runner reaps for every dead one, so the
                # recovery path cannot be left unwired without also leaving the
                # work loop unwired. The write is cheap and happens once per
                # poll, against a 305 ms action.
                self._bb.reclaim_expired_claims()
                items = self._bb.get_unclaimed(
                    min_reward=self._min_reward, tier=tier,
                    limit=POLL_CANDIDATES,
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
                    claimant_tier=int(
                        self._identity.manifest.get("attestation_tier", 0)),
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
                LOG.warning(
                    "[%s] strict-verify: chain incomplete for %s "
                    "(missing envelope for action %s); skipping",
                    self._identity.agent_id[:8],
                    item.id[:8],
                    missing[:8],
                )
                return False
            # Fail-open: log once per item, accept the claim.
            LOG.warning(
                "[%s] verify: chain incomplete for %s "
                "(missing envelope for action %s); proceeding (strict=False)",
                self._identity.agent_id[:8],
                item.id[:8],
                missing[:8],
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
            LOG.warning(
                "[%s] verify: chain INVALID for %s at index %d",
                self._identity.agent_id[:8],
                item.id[:8],
                first_bad,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Decomposition — the producer side of the work DAG
    # ------------------------------------------------------------------
    def _spawn_subtasks(self, parent: WorkItem,
                        specs: list[dict]) -> list[str]:
        """Post child work items for `parent`, bounded by the SIGNED manifest.

        Until now nothing in `gyza/` ever wrote a non-None `parent_id`: the
        work-DAG edge was schema'd, indexed, gossiped and deserialized, and no
        producer existed. This is that producer.

        THE BOUNDS COME FROM THE MANIFEST, NOT FROM THIS FILE.
        `spawn.permitted` and `spawn.resource_budget.max_children` have been in
        the compositor-signed manifest since identity.py and had NO consumer
        anywhere -- declared authority that bound nothing. They are the
        fork-bomb bound, and this is the first code to read them, so a
        decomposition is now attenuated by the same signed authority that
        bounds every other capability.

        Refusals are RuntimeErrors and therefore reach the same place a bounds
        violation does: no envelope is produced, so a signed envelope continues
        to imply the action stayed inside its grant.
        """
        if not specs:
            return []
        cap = self._manifest_max_children()
        if cap <= 0:
            raise RuntimeError(
                f"refusing to decompose {parent.id}: this agent's manifest "
                f"grants no spawn authority (max_children={cap})")
        if len(specs) > cap:
            raise RuntimeError(
                f"refusing to decompose {parent.id} into {len(specs)} "
                f"subtasks: the manifest caps children at {cap}")

        depth = self._bb.lineage_depth(parent.id)
        if depth + 1 > MAX_TASK_DEPTH:
            # Termination.DEPTH_CAP_REACHED -- an explicit reason, not a
            # timeout. A task that ends without a recorded reason cannot be
            # audited (gyza/coordination/task.py).
            raise RuntimeError(
                f"refusing to decompose {parent.id}: depth {depth + 1} "
                f"exceeds MAX_TASK_DEPTH={MAX_TASK_DEPTH} "
                f"(DEPTH_CAP_REACHED)")

        made: list[str] = []
        for sp in specs:
            emb = sp.get("embedding")
            if emb is None:
                emb = np.array(parent.desc_embedding, dtype=np.float32)
            child = WorkItem(
                id=str(uuid.uuid7()),
                lineage_root=parent.lineage_root,
                parent_id=parent.id,
                description=str(sp.get("description", "subtask")),
                desc_embedding=np.asarray(emb, dtype=np.float32),
                reward=float(sp.get("reward", parent.reward)),
                reward_updated_ns=time.time_ns(),
                # A child may never require a HIGHER tier than its parent:
                # that would let a low-tier decomposer mint work only
                # better-attested agents may take, manufacturing demand for
                # authority it does not hold.
                required_tier=min(int(sp.get("required_tier",
                                             parent.required_tier)),
                                  parent.required_tier),
                input_hashes=list(sp.get("input_hashes", [])),
                output_spec=self._child_output_spec(sp, parent),
                streaming_ok=False, claimed_by=None, claimed_at_ns=None,
                claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
                completed_at_ns=None, output_hash=None,
                icp_envelope_hash=None, success=None,
                created_at_ns=time.time_ns(), ttl_ns=parent.ttl_ns)
            self._bb.post_work_item(child)
            made.append(child.id)
        LOG.info("[runner] %s decomposed %s into %d subtask(s)",
                 self._identity.agent_id[:8], parent.id[:14], len(made))
        return made

    @staticmethod
    def _child_output_spec(sp: dict, parent: WorkItem) -> dict:
        """A combiner's `of` pointer is set by the RUNNER, never by the caller.

        The dependency gate resolves siblings through `of`/`parent_id`; letting
        an executor name a different parent would let it gate a combine on
        someone else's children, or on none at all. It is the same rule as the
        tier: the value a check depends on is not self-declared.
        """
        spec = dict(sp.get("output_spec", {"kind": "subtask"}))
        if spec.get("kind") == Blackboard.COMBINE_KIND:
            spec["of"] = parent.id
        return spec

    def _manifest_max_children(self) -> int:
        spawn = (self._identity.manifest.get("capabilities", {})
                 .get("spawn", {}) or {})
        if not spawn.get("permitted"):
            return 0
        return int((spawn.get("resource_budget", {}) or {})
                   .get("max_children", 0) or 0)

    def _score_items(self, items: list[WorkItem]) -> tuple[WorkItem, float]:
        """Best-matching item for this agent, WITH TIES BROKEN AT RANDOM.

        A strict argmax is the wrong rule for a shared queue. `get_unclaimed`
        is deterministically ordered, so when several items score equally --
        which is the normal case for homogeneous work, and the eventual case
        for agents whose specializations have converged -- every agent's argmax
        is the SAME row. Measured 2026-08-23: the claim win rate then falls as
        1/N almost exactly (100%, 50.4%, 27.9%, 19.9%, 11.4% for 1..16 agents),
        which is the algebraic signature of N agents contending for one row.

        Randomising only among TIES, rather than sampling among the top-K, is
        deliberate: where a genuine best exists this returns it and match
        quality is unchanged, so the fix costs nothing in the case it is not
        needed. It is a decorrelation of agents, not a weakening of selection.
        """
        spec = self._spec.current
        scored = [(_cosine(spec, it.desc_embedding), it) for it in items]
        best_score = max(s for s, _ in scored)
        tied = [it for s, it in scored
                if s >= best_score - SELECTION_TIE_EPSILON]
        if len(tied) == 1:
            return tied[0], best_score
        chosen = random.choice(tied)
        # The CHOSEN item's own score, not the band's maximum: the caller
        # compares it against `min_similarity_threshold`, and reporting the
        # best score for a different item would admit work below the bar.
        return chosen, _cosine(spec, chosen.desc_embedding)

    @property
    def authority_violations(self) -> list[AuthorityViolation]:
        """H4's measurand, for a guard to project into `GyzaState`.

        A copy: the list is append-only and the caller must not be able to
        shorten the thing a bound is measured over.
        """
        return list(self._authority_violations)

    def _gather_inputs(self, item: WorkItem) -> list[Artifact]:
        # A COMBINER RESOLVES ITS SIBLINGS' OUTPUTS AT EXECUTE TIME.
        #
        # Its inputs cannot be declared when it is spawned -- the children have
        # not run, so their output hashes do not exist yet. They are resolved
        # here and written onto `item.input_hashes`, which is what `_complete`
        # signs into the envelope. That is the point: the combine action's
        # envelope then COMMITS to precisely which child outputs it consumed,
        # so a verifier can check that a combination really used the children
        # it claims to have used, rather than taking the combiner's word.
        #
        # The dependency gate in `get_unclaimed` guarantees every sibling has
        # completed before this item is servable, so this cannot silently
        # combine a partial result. It is re-checked here anyway, because the
        # gate protects the POLLING path and an item reached any other way --
        # gossip, a direct id, a reclaim -- has not passed through it.
        spec = item.output_spec if isinstance(item.output_spec, dict) else {}
        if spec.get("kind") == Blackboard.COMBINE_KIND and item.parent_id:
            pending = self._bb.pending_siblings(item)
            if pending:
                raise RuntimeError(
                    f"refusing to combine {item.id}: {len(pending)} sibling(s) "
                    f"have not completed. Combining a partial result and "
                    f"signing it would attest to a whole that does not exist."
                )
            resolved = [c.output_hash
                        for c in self._bb.children_of(item.parent_id)
                        if c.id != item.id and c.output_hash]
            merged = list(item.input_hashes)
            merged += [h for h in resolved if h not in merged]
            item.input_hashes = merged

        out: list[Artifact] = []
        for h in item.input_hashes:
            a = self._bb.get_artifact(h)
            if a is not None:
                out.append(a)
        return out

    def _attest_context(self, prompt: str) -> "str | None":
        """Store the assembled context content-addressed; return its hash.

        Returns None when no content-addressed store is attached, which is the
        honest state for a runner with no CAS rather than a silent skip: the
        caller then adds nothing to `input_hashes` and the envelope makes no
        claim about context it cannot produce.
        """
        cas = getattr(self._bb, "_artifact_store", None)
        if cas is None:
            return None
        try:
            return cas.store(prompt.encode("utf-8"))
        except Exception:                                    # noqa: BLE001
            LOG.warning("context not attested", exc_info=True)
            return None

    def _require_attested_tier(self, item: WorkItem) -> None:
        """Refuse work whose `required_tier` exceeds this agent's ATTESTED tier.

        THE TIER IS A PRECONDITION, NOT A CAPABILITY. It was tempting to add it
        to `CapabilitySpec` as a sixth attenuated dimension; that is a category
        error and Arena 2's write-up records why. Attenuation is a CEILING on a
        delegate (`child <= parent`), and the hazard here is a FLOOR on the
        executor (`granted >= required`). The two constrain different things at
        different moments, and the attenuated form would have refused the SAFE
        direction -- a tier-1 agent subcontracting to a better-attested tier-3
        agent -- while permitting the actual hazard, a tier-3 agent handing
        tier-3 work to a tier-0 one. `CapabilitySpec` also projects from a
        bubblewrap enforcement record, which has no notion of attestation at
        all, so the sixth dimension would be undefined for one of its three
        sources.

        REFUSED BEFORE THE WORK RUNS, which is strictly better than the bounds
        gate below can manage. That gate can only withhold the signature after
        the fact -- "the work ALREADY RAN outside its declared bounds" -- but a
        tier is knowable from the manifest and the item alone, so high-tier work
        is never executed, and its inputs are never even read.

        NOT recorded as an H4 authority violation. H4 counts executed actions
        whose enforcement exceeded the manifest; nothing ran here, and widening
        H4 to cover refusals would break the property that makes it the one real
        harm class -- a benign rate of exactly 0.000.

        The absent-tier default is 0, so a manifest that does not declare a tier
        can only take tier-0 work. "I did not say" fails closed, as it does for
        the enforcement record.
        """
        granted = int(self._identity.manifest.get("attestation_tier", 0))
        required = int(getattr(item, "required_tier", 0) or 0)
        if required > granted:
            raise RuntimeError(
                f"refusing to execute {item.id}: it requires attestation tier "
                f"{required} and this agent is attested at tier {granted}. The "
                f"tier is a precondition on the executor, not an attenuated "
                f"capability."
            )

    def _execute(self, item: WorkItem) -> dict[str, Any]:
        # BEFORE anything else, including reading the inputs.
        self._require_attested_tier(item)
        t0 = time.monotonic_ns()
        inputs = self._gather_inputs(item)

        prompt = build_enriched_prompt(
            base_prompt=item.description,
            memory=self._mem,
            current_task=item.description,
            max_episodes=5,
        )
        # ATTESTED CONTEXT. `build_enriched_prompt` injects up to five
        # RETRIEVED EPISODES into this prompt, and until now nothing signed
        # covered them: the envelope's `input_hashes` commits to the work
        # item's DECLARED inputs only, so the system could not prove what
        # context produced an output. An inference-time control action that
        # cannot be shown to the verifier is applied, not auditable.
        #
        # The assembled prompt is stored content-addressed and its hash joins
        # `input_hashes`, which is DELIBERATELY ADDITIVE (icp.py's DAG note):
        # no schema change, no re-signing, and the Rust byte-parity fixtures
        # are untouched. It creates no spurious DAG edge either -- a data
        # dependency edge forms only when an input hash matches another
        # envelope's `output_hash`, and an artifact hash never does.
        #
        # SCOPE, stated rather than implied: this attests what the RUNNER
        # assembled and handed to the executor. An executor that further
        # transforms the prompt -- `make_anthropic_executor` inlines artifact
        # contents -- is not covered by this hash. Closing that requires the
        # executor to report its final payload and is the next step, not this
        # one.
        context_hash = self._attest_context(prompt)
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
        if enforcement is None and self._require_enforcement:
            # FAIL CLOSED. Under this policy an absent record is a refusal,
            # not a skip: we cannot prove the work stayed in bounds, so no
            # envelope is produced for it.
            raise RuntimeError(
                "refusing to sign — no sandbox enforcement record was "
                "stamped and require_enforcement is set; an unenforced "
                "execution cannot carry a bounds-proof"
            )
        if enforcement is not None:
            from gyza.sandbox.config import enforcement_satisfies_manifest
            ok, why = enforcement_satisfies_manifest(
                enforcement, self._identity.manifest,
            )
            if not ok:
                # RECORD BEFORE REFUSING. H4's quantity is "count of executed
                # actions whose enforcement exceeded the manifest", and until
                # now nothing anywhere produced that count -- the harm class
                # read `getattr(s, "authority_violations", ())`, measured 0
                # against a bound of 0, and passed by measuring nothing.
                #
                # The work ALREADY RAN outside its declared bounds; refusing to
                # sign withholds the attestation but does not un-run it. So the
                # breach is recorded here, at the point of detection, and the
                # refusal below is unchanged.
                self._authority_violations.append(AuthorityViolation(
                    action_id=item.id, agent_pubkey=self._identity.agent_id,
                    reason=why, at_ns=time.time_ns(),
                ))
                raise RuntimeError(
                    f"refusing to sign — sandbox enforcement is not "
                    f"consistent with the agent manifest: {why}"
                )

        # THE RATE CAP, ENFORCED AT THE SERIALIZATION POINT C7 REQUIRES.
        #
        # R-M1 measured that a cross-principal aggregate is boundable by local
        # checks exactly when concurrent activity per principal is bounded. A2
        # then measured that the bound is a COMPLIANCE ASSUMPTION unless that
        # limit is ENFORCED: one principal ignoring it breaks the aggregate at
        # every scale. R-B measured the tolerable non-compliance at ~1.6 per
        # cluster, so the quantity to bound is PER-PRINCIPAL rate.
        #
        # IT IS A RATE, AND UNTIL 2026-08-21 IT WAS A LIFETIME QUOTA.
        #
        # This block counted envelopes since `_cadence_origin_ns`, which
        # `default_cadence_wiring` pins at GENESIS and documents as immovable.
        # So `used` was every envelope the agent had ever signed, compared
        # against a number called a rate: an agent granted `action_rate_cap:
        # 1000` was PERMANENTLY REFUSED at its 1000th action, for the rest of
        # its life, with no way back.
        #
        # The justification three paragraphs up is what makes that wrong rather
        # than merely misnamed. R-M1/A2/R-B establish that a cross-principal
        # aggregate is boundable when PER-PRINCIPAL RATE is bounded. A lifetime
        # quota does not bound rate at all -- an agent may spend the whole
        # budget in one second and then stop -- so the aggregate argument the
        # dimension exists to serve did not go through.
        #
        # Found by R-EVID's drift criterion (research/evidence/THEOREMS_C.md):
        # benign rate is 1 envelope per action, so the fold had positive drift
        # with no compensation and was a TIMER with false-alarm probability 1.
        #
        # THE WINDOW ORIGIN ADVANCES WITH THE WALL CLOCK AND NOTHING ELSE.
        # That is what separates it from ledger artifact #13, where a gate
        # measured from a checkpoint the AGENT could advance by acting and so
        # bought unlimited drain. Here no action moves the origin: an agent
        # cannot buy budget by working, only by waiting. `_rate_window_ns` is
        # not read from the manifest for the same reason -- a principal that
        # could widen its own window could restore the quota semantics.
        #
        # A cumulative bound needs a serialization point (C7), and signing is
        # this agent's: it is inside its own loop and every action passes it.
        # The count is folded from the append-only envelope log, per agent --
        # a node-wide count would let one busy agent exhaust everyone's budget.
        #
        # REFUSING TO SIGN DOES NOT UN-RUN THE WORK, exactly as with the
        # authority gate above. What it withholds is the attestation.
        from gyza.economy.delegation import spec_from_manifest
        rate_cap = spec_from_manifest(self._identity.manifest).rate_cap
        if rate_cap is not None:
            window_start = max(0, time.time_ns() - self._rate_window_ns)
            used = self._bb.count_agent_envelopes_since(
                self._identity.agent_id, window_start)
            if used >= rate_cap:
                self._authority_violations.append(AuthorityViolation(
                    action_id=item.id, agent_pubkey=self._identity.agent_id,
                    reason=(f"action rate cap {rate_cap} reached "
                            f"({used} signed in the last "
                            f"{self._rate_window_ns // 1_000_000_000}s)"),
                    at_ns=time.time_ns(),
                ))
                raise RuntimeError(
                    f"refusing to sign — this agent has signed {used} actions "
                    f"in the last {self._rate_window_ns // 1_000_000_000}s "
                    f"against a declared rate cap of {rate_cap}")

        # Canonical JSON for the output so the BLAKE3 hash is stable
        # across runs / processes. When an enforcement record is
        # present we fold it into the artifact so the envelope's
        # output_hash cryptographically commits to the (verified)
        # bounds the work ran under — the bounds-proof lives inside
        # the signed bytes, not in trust of the runner's behavior.
        artifact_obj: dict = {"text": raw.get("text", "")}
        if enforcement is not None:
            artifact_obj["__enforcement__"] = enforcement

        # DECOMPOSITION IS AN ORDINARY SIGNED ACTION. An executor asks for one
        # by returning `__subtasks__`, exactly as the sandbox wrapper stamps
        # `__enforcement__`. The child ids are folded into the artifact, so the
        # envelope's output_hash COMMITS to the decomposition: who split this
        # task, under which manifest, into precisely which children, is
        # signed and offline-verifiable. No new envelope type, no schema
        # change, and the DAG's shape becomes as accountable as its actions.
        #
        # Spawned BEFORE the artifact is hashed, and a refusal raises, so an
        # over-wide decomposition produces no envelope at all.
        subtasks = raw.get("__subtasks__")
        if subtasks:
            artifact_obj["__subtasks__"] = self._spawn_subtasks(
                item, list(subtasks))
        canonical = json.dumps(
            artifact_obj, sort_keys=True, separators=(",", ":"), allow_nan=False,
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
                # Also persist this agent's manifest content-addressed, so
                # an independent `gyza audit` can later resolve it by the
                # envelope's capability_manifest_hash (== blake3 of these
                # exact bytes) and re-run enforcement_satisfies_manifest.
                # Without this the bounds half of the audit can verify only
                # the demo's in-memory store, never real on-disk work.
                # Idempotent (content-addressed dedup); cheap.
                from gyza.identity import manifest_canonical_bytes
                cas.store(manifest_canonical_bytes(self._identity.manifest))
            except Exception:
                pass

        duration_ms = max(1, (time.monotonic_ns() - t0) // 1_000_000)
        return {
            "context_hash": context_hash,
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
        LOG.warning(
            "[%s] ✗ %s (released) — error: %s",
            self._identity.agent_id[:8],
            item.description[:60],
            error,
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
                {"error": error}, sort_keys=True, separators=(",", ":"), allow_nan=False,
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
        input_hashes = list(item.input_hashes) if item.input_hashes else [
            "00" * 32  # placeholder for "read nothing", keeps verify_chain happy
        ]
        # The attested context joins the declared inputs. It is appended, never
        # substituted: a verifier must still see everything the work item
        # declared, and the context is an ADDITIONAL input to the inference.
        _ctx = result.get("context_hash")
        if _ctx and _ctx not in input_hashes:
            input_hashes.append(_ctx)
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

        # THE REVIEW CADENCE, checked WHERE THE ACTION HAPPENS. It was first
        # wired only into `gyza review`, which meant an operator discovered they
        # were due a review by ASKING WHETHER THEY WERE DUE A REVIEW -- a passive
        # queue is the same unconsumed-surface defect one layer up.
        #
        # One indexed COUNT per signature. `check_cadence` is idempotent, so a
        # bound already escalated does not re-fire; the cost is the count, not
        # the escalation.
        if self._review_queue is not None:
            try:
                from gyza.containment.review import check_cadence
                # `_harm_registry` here is the CADENCE INTERVAL since H6's
                # retirement; check_cadence accepts an int or a legacy registry
                # and resolves either, so a stale caller degrades to the old
                # lookup rather than silently disabling the cadence.
                check_cadence(self._review_queue, self._harm_registry,
                              self._bb.count_envelopes_since(
                                  self._cadence_origin_ns))
            except Exception:  # noqa: BLE001 - never break completion
                LOG.debug("cadence check failed", exc_info=True)

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

        # Mark the work item complete on the blackboard, AS ITS OWNER.
        #
        # `expected_owner` refuses a completion by anyone who does not hold the
        # claim. It matters now that claims are LEASES: a runner slower than
        # the lease could otherwise overwrite the result of whoever
        # legitimately reclaimed its item, silently and last-write-wins.
        try:
            self._bb.complete_work_item(
                item.id, output_hash, envelope_hash, success, self._hlc,
                expected_owner=self._identity.agent_id,
            )
        except ClaimLostError:
            # NOT SWALLOWED WITH THE REST. Every other failure here is a
            # storage problem and the signed envelope remains the source of
            # truth. THIS one says another runner now owns the item, which
            # means the work was done twice -- an operational fact, and the
            # only signal that the lease is mis-sized for this workload.
            # Logging it costs nothing when it never happens.
            LOG.warning(
                "[runner] completed %s but its lease had expired and another "
                "runner holds it; the envelope stands and the board row does "
                "not. If this recurs, CLAIM_LEASE_NS is too short for this "
                "workload.", item.id[:16])
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
        log_fn = LOG.info if success else LOG.warning
        log_fn(
            "[%s] %s %s (%dms)%s",
            self._identity.agent_id[:8],
            mark,
            desc,
            duration_ms,
            f" — error: {error}" if error and not success else "",
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


def make_command_executor(
    argv: list[str],
    max_output_bytes: int = 1_000_000,
    cwd: str | None = None,
) -> Callable[[str, dict], dict]:
    """
    Run one arbitrary command as the agent's action — the `gyza exec`
    executor. Designed to be instantiated INSIDE the sandbox (via
    ``make_sandboxed_executor``), so the child process inherits the
    sandbox's namespaces and rlimits: bwrap's mount/net isolation and
    RLIMIT_AS/RLIMIT_CPU apply to the command, not just to this wrapper.

    The command line itself is folded into the artifact text (the
    ``$ ...`` header), so the signed ``output_hash`` commits to WHAT ran,
    not just what it printed. A non-zero exit raises — surfacing as an
    execution failure so no envelope is signed: a valid signed envelope
    keeps implying completed, bounded work.

    ``argv[0]`` should be an absolute path (the sandbox has a fresh
    environment; the CLI resolves it host-side before entering).

    ``cwd`` is the directory to run the command in. It must be a path
    that is visible (bound) inside the sandbox — the CLI passes the host
    working directory only when that directory is among the granted
    paths, so a relative-path command (``cat notes.txt``) works exactly
    where the user launched it. ``None`` runs in the fresh /workspace
    tmpfs.
    """
    def _executor(_prompt: str, _context: dict) -> dict:
        import shlex
        import subprocess

        run_cwd = cwd if cwd and os.path.isdir(cwd) else None
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": run_cwd or os.getcwd(),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        proc = subprocess.run(
            argv, capture_output=True, env=env, check=False, cwd=run_cwd,
        )
        out = proc.stdout[:max_output_bytes]
        truncated = len(proc.stdout) > max_output_bytes
        if proc.returncode != 0:
            tail = proc.stderr[-2000:].decode("utf-8", "replace")
            raise RuntimeError(
                f"command exited {proc.returncode}: {tail.strip()}"
            )
        text = f"$ {shlex.join(argv)}\n[exit 0]\n" + out.decode("utf-8", "replace")
        if truncated:
            text += f"\n[output truncated at {max_output_bytes} bytes]"
        return {
            "text": text,
            "tokens_in": 0,
            "tokens_out": 0,
            "model_identifier": f"exec:{os.path.basename(argv[0])}",
            "inference_backend": "subprocess",
        }
    return _executor


def make_anthropic_executor(
    api_key: str | None = None,
    model: str = "claude-sonnet-4-5",
    egress_recorder: "Any | None" = None,
) -> Callable[[str, dict], dict]:
    """
    Pluggable Anthropic executor. The runner stays unaware of the
    transport — it just calls executor(prompt, context).

    Imports `anthropic` lazily so the module loads cleanly on machines
    that don't have the SDK installed (everyone using the mock executor).

    THE ONE GENUINELY EXTERNAL SEND IN THIS PROCESS, and until 2026-08-19
    nothing measured it. `_executor` inlines up to 4000 bytes of EVERY input
    artifact into the prompt and posts it to a third-party provider. That is an
    `OUTSIDE_PROTOCOL` egress in H3's vocabulary -- it leaves modelled state
    entirely -- and `outside_send` had no caller anywhere.

    IN PRODUCTION THIS RUNS SANDBOXED (`cli.py` wraps it via
    `make_sandboxed_executor`), where the parent cannot observe per-send bytes
    and the honest record is the `UNBOUNDED_GRANT` instead. This recorder is
    for the IN-PROCESS path -- an injected executor, or any caller importing
    this factory directly -- which bypasses the sandbox and was therefore
    invisible to both classes at once.

    The byte count is a LOWER BOUND: it measures the prompt handed to the SDK,
    not the SDK's framing, headers or system prompt. Stated rather than implied,
    because a measurand that silently understates is the reassuring direction.
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

        # RECORD AROUND THE CALL, NOT AFTER SUCCESS. Once the request is
        # handed to the transport the bytes have left, whether or not a
        # response comes back -- so a `finally` is the honest placement. The
        # peer-send paths record only on success because a refused RPC never
        # left the host; an HTTPS request that errors mid-flight did.
        _n_bytes = len(full_prompt.encode("utf-8"))
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": full_prompt}],
            )
        finally:
            if egress_recorder is not None:
                try:
                    egress_recorder.outside_send(
                        f"inference:{model}", "api.anthropic.com", _n_bytes)
                except Exception:                            # noqa: BLE001
                    LOG.warning("[runner] inference egress not recorded",
                                exc_info=True)
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
