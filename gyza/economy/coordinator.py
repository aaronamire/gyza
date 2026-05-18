"""
SubcontractCoordinator — the brain of the dual-role subcontract
loop, composed from proven parts, with all effects injected.

WHY THIS SHAPE
--------------
The runner is Phase-1 code that knows nothing about the economy or
the mesh (per the project's architecture; settlement/delivery
already live in injected GlobalCluster hooks, NOT inside the
runner's signing path). So the subcontract loop is an orchestration
component driven ALONGSIDE the runner — it does not touch
``runner._execute`` or the brick-3 gate at all. Zero blast radius
on the most safety-critical file in the tree.

The loop's I/O (post a child intent + signed grant, await the
result, cosign-as-payer) is injected as a tiny effects interface,
exactly the codebase's proven testable pattern (injected ``sign``
callables, ``_FakeBus``, ``_StubLedger``). This module is the
deterministic STATE MACHINE; the real libp2p/gossip/settlement
adapter is a separate thin wiring pass.

RESPONSIBILITY SPLIT (rigorous, deliberate)
-------------------------------------------
* Upstream / injected computes the signature+hash facts the
  result-delivery path ALREADY computes with proven code:
  ``chain_ok`` (icp.verify_chain) and ``manifest_hash_ok``
  (blake3(canonical manifest) == envelope.capability_manifest_hash).
  The coordinator must NOT re-derive that crypto.
* The coordinator computes the pure, already-proven delegation
  predicates: ``verify_grant``, ``grant_binds_to``,
  ``verify_delegation``.
* The coordinator OWNS: the proactive over-delegation precheck,
  the reserve/settle/release accounting, idempotency, timeout and
  every-failure handling, and the single pay/no-pay decision.

PAY IFF (PoUC at the subcontract level)
---------------------------------------
A subcontractor is paid only if
  chain_ok ∧ manifest_hash_ok ∧ verify_grant ∧ grant_binds_to
  ∧ verify_delegation
all hold. Unverifiable or out-of-bounds sub-work earns nothing —
exactly the network-level PoUC rule, applied one level down. Any
failure path releases the reservation (refunding the task budget)
and pays nothing.

OPEN WIRING DECISION (surfaced, not baked)
------------------------------------------
At subcontract time the parent has NOT yet signed its own envelope
for the work it is doing (it signs after folding in the
sub-result). So ``parent_envelope_hash`` cannot be that envelope.
The stable anchor (the parent's chain head, or agent-pubkey +
work-item-id) is a wiring-layer choice. This module takes the
anchor as an injected ``ParentRef`` and binds consistently with
whatever it is given; choosing it is the adapter's job and is
flagged for an explicit decision, not silently assumed here.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from gyza.economy.delegation import (
    CapabilitySpec,
    DelegationGrant,
    DelegationHop,
    capability_subset,
    grant_binds_to,
    sign_grant,
    spec_from_enforcement,
    spec_from_manifest,
    verify_delegation,
    verify_grant,
)
from gyza.economy.subcontract import ReservationBook
from gyza.economy.wallet import Credits


@dataclass(frozen=True)
class ParentRef:
    """The subcontracting agent's stable self-reference + its own
    bounds. ``manifest_spec`` is the ceiling on what it may delegate;
    ``enforcement_spec`` feeds the root hop of verify_delegation."""

    agent_pubkey: str
    agent_seed: bytes               # to sign the grant as the parent
    envelope_hash: str              # the chosen stable anchor (wiring)
    manifest_hash: str
    work_item_id: str
    manifest_spec: CapabilitySpec
    enforcement_spec: CapabilitySpec


@dataclass(frozen=True)
class SubtaskSpec:
    payload: dict                   # the child intent body (opaque here)
    required: CapabilitySpec        # capability the subtask needs
    bounty: Credits


@dataclass(frozen=True)
class ResultBundle:
    """What the wiring builds from a received result delivery. The
    signature/hash facts are PRE-COMPUTED upstream by the proven
    result-delivery path; the coordinator consumes them, it does not
    recompute crypto."""

    child_work_item_id: str
    child_agent_pubkey: str
    child_envelope_hash: str
    child_manifest: dict
    child_enforcement: dict
    sub_result: dict
    chain_ok: bool                  # icp.verify_chain, computed upstream
    manifest_hash_ok: bool          # trustless manifest-hash check, upstream


@dataclass(frozen=True)
class SubResult:
    ok: bool
    reason: str
    child_work_item_id: str
    payload: dict | None = None


class SubcontractEffects(Protocol):
    def post_subtask(
        self, child_work_item_id: str,
        subtask: SubtaskSpec, grant: DelegationGrant,
    ) -> None: ...

    def await_result(
        self, child_work_item_id: str, timeout_s: float
    ) -> ResultBundle | None: ...

    def cosign_as_payer(
        self, child_work_item_id: str, earner_pubkey: str,
        amount: Credits, child_envelope_hash: str,
    ) -> bool: ...


class SubcontractCoordinator:
    def __init__(
        self,
        parent: ParentRef,
        book: ReservationBook,
        effects: SubcontractEffects,
        *,
        now_ns: int = 0,
    ) -> None:
        self._p = parent
        self._book = book
        self._fx = effects
        self._now_ns = now_ns

    def _fail(self, wid: str, reason: str) -> SubResult:
        # Any failure after a reservation exists releases it (which
        # refunds the task budget) so a flaky/hostile subcontractor
        # never permanently burns the job. release() is idempotent
        # and refuses to undo a paid one.
        self._book.release(wid)
        return SubResult(False, reason, wid)

    def subcontract(
        self, subtask: SubtaskSpec, *, timeout_s: float = 60.0
    ) -> SubResult:
        # 0. Idempotent child id up front so reserve/grant/post all
        #    agree and a retry is deduped by the book.
        child_wid = str(uuid.uuid7())

        # 1. PROACTIVE over-delegation block: A may never delegate
        #    authority wider than its OWN manifest. This stops
        #    capability laundering BEFORE anything is posted — the
        #    cheapest and earliest point to refuse.
        ok, why = capability_subset(subtask.required, self._p.manifest_spec)
        if not ok:
            return SubResult(
                False,
                f"refusing to delegate beyond own manifest: {why}",
                child_wid,
            )

        # 2. Solvency + budget gate (no I/O yet — fail before posting).
        out = self._book.reserve(child_wid, subtask.bounty)
        if not out.ok:
            return SubResult(False, f"cannot reserve: {out.reason}",
                             child_wid)

        # 3. Sign the delegation grant as the parent.
        grant = sign_grant(
            DelegationGrant(
                parent_envelope_hash=self._p.envelope_hash,
                parent_agent_pubkey=self._p.agent_pubkey,
                parent_manifest_hash=self._p.manifest_hash,
                child_work_item_id=child_wid,
                delegated_authority=subtask.required.to_canonical(),
                created_at_ns=self._now_ns,
            ),
            self._p.agent_seed,
        )

        # 4. Post. Any exception here → release (budget refunded).
        try:
            self._fx.post_subtask(child_wid, subtask, grant)
        except Exception as e:  # noqa: BLE001
            return self._fail(child_wid, f"post failed: {e}")

        # 5. Await the result (timeout → release + refund).
        bundle = self._fx.await_result(child_wid, timeout_s)
        if bundle is None:
            return self._fail(child_wid, "timed out awaiting sub-result")

        # 5a. Guard a late/duplicate delivery for an already-terminal
        #     reservation: never re-verify, never re-pay.
        r = self._book.reservation(child_wid)
        if r is not None and r.state.name != "ACTIVE":
            return SubResult(
                False, f"duplicate/late delivery ignored "
                f"({r.state.value})", child_wid)

        # 6. THE pay-iff gate. Every predicate must hold; the first
        #    failure releases and pays nothing (PoUC one level down).
        if not bundle.chain_ok:
            return self._fail(child_wid, "child envelope chain invalid")
        if not bundle.manifest_hash_ok:
            return self._fail(
                child_wid, "child manifest hash ≠ envelope commitment")

        ok, why = verify_grant(grant)
        if not ok:
            return self._fail(child_wid, f"grant self-verify failed: {why}")

        ok, why = grant_binds_to(
            grant,
            parent_envelope_hash=self._p.envelope_hash,
            parent_agent_pubkey=self._p.agent_pubkey,
            parent_capability_manifest_hash=self._p.manifest_hash,
            child_work_item_id=child_wid,
        )
        if not ok:
            return self._fail(child_wid, f"grant binding failed: {why}")

        chain = [
            DelegationHop(
                self._p.agent_pubkey,
                manifest=self._p.manifest_spec,
                enforcement=self._p.enforcement_spec,
            ),
            DelegationHop(
                bundle.child_agent_pubkey,
                manifest=spec_from_manifest(bundle.child_manifest),
                enforcement=spec_from_enforcement(bundle.child_enforcement),
                delegated=CapabilitySpec.from_canonical(
                    grant.delegated_authority),
            ),
        ]
        ok, why = verify_delegation(chain)
        if not ok:
            # The subcontractor's work was not bounded by what we
            # delegated (e.g. laundering through its own wide
            # manifest). It earns NOTHING.
            return self._fail(child_wid, f"bounds did not compose: {why}")

        # 7. All five hold → pay. cosign-as-payer runs the durable
        #    settlement payer path (the ONLY payment authority).
        try:
            paid = self._fx.cosign_as_payer(
                child_wid, bundle.child_agent_pubkey,
                subtask.bounty, bundle.child_envelope_hash,
            )
        except Exception as e:  # noqa: BLE001
            return self._fail(child_wid, f"cosign raised: {e}")
        if not paid:
            return self._fail(child_wid, "cosign-as-payer rejected")

        # 8. Settle the hold: the real settled debit is now in the
        #    wallet via the cosigned entry — drop the hold WITHOUT a
        #    second debit (the no-double-count identity).
        self._book.settle(child_wid)
        return SubResult(True, "", child_wid, payload=bundle.sub_result)


__all__ = [
    "ParentRef",
    "ResultBundle",
    "SubResult",
    "SubcontractCoordinator",
    "SubcontractEffects",
    "SubtaskSpec",
]
