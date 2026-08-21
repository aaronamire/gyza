"""
C-4 — guard evaluation engine.

Evaluates invariants per STATE TRANSITION and per ACTION -- not at grant time.
R9's ScopeGate result is that a bound checked only when authority is issued is
not a bound at all; and Gyza's own execution gate is already per work item
(gyza/runner.py:406-416), which is the shape to preserve.

Three properties are structural rather than conventional:

1. FRAME ALIGNMENT (C3). The engine measures harm by calling the registry's own
   quantity function and hands the RESULT to the invariant. An invariant cannot
   re-measure, so it cannot drift to a stale frame.

2. PHASE SEPARATION (C7). Cumulative invariants are refused in the interior and
   evaluated only at the serialized promotion gate. This is not a performance
   choice: no stateless local check bounds a cumulative quantity, so evaluating
   one per-action would look like a check while bounding nothing -- the exact
   shape R13 measured when signature-gated local checks left a joint pool
   overdrawn by 180-1134 while every local check passed.

3. FAIL CLOSED ON AN UNSET BOUND (D1). A harm class with no declared bound
   cannot be contained, so any action touching it is refused with that reason.
   An undeclared bound is not an infinite bound.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from gyza.containment.harm import DriftClass, HarmModelRegistry, UnsetBoundError
from gyza.containment.invariants import InvariantRegistry
from gyza.containment.reversibility import Reversibility, ReversibilityTable


class Phase(str, Enum):
    INTERIOR = "INTERIOR"       # staging; concurrent; reversible only
    PROMOTION = "PROMOTION"     # serialized gate; everything evaluated here


@dataclass
class Decision:
    admit: bool
    reasons: list[str] = field(default_factory=list)
    evaluated: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    measured: dict[str, float] = field(default_factory=dict)
    reversibility: Reversibility | None = None

    def __bool__(self) -> bool:
        return self.admit


class GuardEngine:
    def __init__(self, harm: HarmModelRegistry, invariants: InvariantRegistry,
                 reversibility: ReversibilityTable | None = None):
        self._harm = harm
        self._inv = invariants
        self._rev = reversibility or ReversibilityTable()

    # -- the one public predicate ------------------------------------------
    def evaluate(self, s0: object, s_next: object, action_type: str,
                 phase: Phase = Phase.INTERIOR,
                 harm_classes: list[str] | None = None) -> Decision:
        """Decide whether `action_type` may be admitted, given that applying it
        yields `s_next` from baseline `s0`."""
        d = Decision(admit=True)
        d.reversibility = self._rev.classify(action_type)

        # (a) Only reversible actions belong in the interior. Anything
        #     irreversible or egressing is routed to the promotion gate, which
        #     is simultaneously the irreversibility gate and the serialization
        #     point -- the same place by necessity (C7 + C9).
        if phase is Phase.INTERIOR and d.reversibility is not Reversibility.REVERSIBLE_INTERIOR:
            d.admit = False
            d.reasons.append(
                f"action {action_type!r} is {d.reversibility.value} and may not "
                f"be admitted in the reversible interior; it must go through "
                f"the promotion gate"
            )
            return d

        targets = (list(harm_classes) if harm_classes is not None
                   else [c.id for c in self._harm])

        for cid in targets:
            hc = self._harm.get(cid)
            invs = self._inv.for_harm_class(cid)
            if not invs:
                # C4: adequacy is per harm class. An uncovered class is
                # unbounded, and silence about it would be the bug.
                d.admit = False
                d.reasons.append(
                    f"harm class {cid!r} has no registered invariant (C4)")
                continue

            try:
                bound = self._harm.bound(cid)
            except UnsetBoundError as e:
                d.admit = False
                d.reasons.append(str(e))
                continue

            # FRAME ALIGNMENT: measured once, by the harm model's own function.
            h = hc.measure(s0, s_next)
            d.measured[cid] = h

            for inv in invs:
                if phase is Phase.INTERIOR and not inv.cls.composes_statelessly:
                    # C7 -- refuse to pretend. Defer, do not evaluate.
                    d.deferred.append(inv.id)
                    continue
                d.evaluated.append(inv.id)
                if not inv.predicate(h, bound, s0, s_next):
                    d.admit = False
                    d.reasons.append(
                        f"invariant {inv.id!r} ({inv.cls.value}) violated for "
                        f"harm class {cid!r}: measured {h} against bound {bound}"
                    )
        return d

    # -- introspection used by the scheduler and by O-3 --------------------
    def concurrency_plan(self) -> dict[str, list[str]]:
        return {
            "interior_concurrent": [i.id for i in self._inv.interior()],
            "promotion_serialized": [i.id for i in self._inv.promotion_only()],
        }

    def readiness(self, authority_key_search: "list[str] | None" = None) -> dict:
        """What this guard can and cannot currently claim.

        `can_claim_containment` REQUIRES SIGNED BOUNDS (C-8), and that is a
        strengthening, not a formality. Every containment argument here is an
        induction over admitted transitions; if the constrained system can
        rewrite the bound, the induction has no base case. Bounds read from an
        ordinary repo file are exactly that case, so a guard holding them may
        report its levels and must not claim containment over them.

        The FOUR obstacles are reported separately -- unbounded classes,
        uncovered classes, unsigned bounds, and a colocated authority key --
        because they have different remedies and a single boolean would hide
        which one is in force. The fourth was checked only by a print statement
        until 2026-08-21.
        """
        prov = self._harm.bounds_provenance
        # R-EVID Part C: a level is a BOUND only if its quantity has
        # non-positive benign drift with reflection; otherwise it is a TIMER
        # that refuses every benign agent at ceil(L/b). Reported beside the
        # levels because a level without its drift class does not say whether
        # the number means anything -- H6 carried a SIGNED 10,000 while its
        # benign and adversarial rates were identical.
        # C-8'S BASE CASE, IN THE PREDICATE RATHER THAN IN A PRINT STATEMENT.
        #
        # The containment induction rests on one premise: the constrained system
        # does not hold the key that signs its bounds. `authority_key_is_colocated`
        # was written to check exactly that -- and its ONLY production caller was
        # a print block in `gyza status` (cli.py:986). `readiness()` never asked,
        # so `can_claim_containment` required signed bounds and said nothing
        # about separation. Bound H3 tomorrow and the claim would have flipped
        # TRUE with the authority private key sitting in ~/.gyza next to the
        # agents it constrains.
        #
        # Signed-but-colocated is still strictly better than unsigned: tampering
        # without the key remains detectable. What it cannot support is the
        # CLAIM, because a local compromise re-signs any bounds it likes.
        colocated = None
        if prov.trusted and prov.authority_pubkey_hex:
            try:
                from gyza.containment.guardconfig import (
                    authority_key_is_colocated,
                )
                colocated = authority_key_is_colocated(
                    prov.authority_pubkey_hex, authority_key_search)
            except Exception:                                # noqa: BLE001
                # An error here is NOT a value. Failing to determine
                # separation must not read as "separated" -- that is the
                # reassuring direction. Report the uncertainty as if
                # colocated, which is the conservative reading for a claim.
                colocated = "UNDETERMINED"

        timers = [c.id for c in self._harm
                  if c.bound is not None and c.drift_class == DriftClass.TIMER]
        unclassified = [c.id for c in self._harm if c.drift_class is None]
        return {
            "harm_classes": [c.id for c in self._harm],
            "drift_classes": {c.id: c.drift_class for c in self._harm},
            "bounded_but_only_a_timer": timers,
            "unclassified_drift": unclassified,
            "unbounded": self._harm.unbounded(),
            "mutable_frames": self._harm.mutable_frames(),
            "uncovered": self._inv.uncovered([c.id for c in self._harm]),
            "bounds_provenance": prov.as_dict(),
            "bounds_signed": prov.trusted,
            "authority_key_colocated": colocated,
            "can_claim_containment": (not self._harm.unbounded()
                                      and not self._inv.uncovered(
                                          [c.id for c in self._harm])
                                      and prov.trusted
                                      and colocated is None),
        }
