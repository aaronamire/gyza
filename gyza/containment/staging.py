"""
C-5 staging area, C-6 promotion gate, C-7 checkpoint/rollback.

These are one mechanism described three ways, and the architecture says so:
the promotion gate is SIMULTANEOUSLY the irreversibility gate and the
serialization point that cumulative bounding requires. Those are the same place
by necessity, not by convenience --

  * the interior can be ungated because nothing in it is irreversible (C9), so
    all gating collapses onto one boundary you can afford to guard;
  * no stateless local check bounds a cumulative quantity (C7), so cumulative
    bounds need a serialization point;
  * the cheapest serialization point is the boundary you were already forced to
    guard.

STATE IS ALWAYS A FOLD. The staging area never stores a projected state; it
stores events and projects on demand. That is what makes the guard and the harm
measure structurally unable to disagree about the frame (C3), and it is why
`projector` is a required constructor argument rather than an optional one.

ROLLBACK PRESERVES CONTENT. Abandoning staged work appends a ROLLBACK marker;
the abandoned events REMAIN IN THE LOG and the fold skips them. Nothing is
deleted. R10 measured the difference: under mutable storage two agents can each
pass a local check and jointly destroy content, and under append-only that race
cannot be constructed at all. Rollback bounds resource and ownership loss;
only append-only bounds CONTENT loss (R11 Part A2).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from gyza.containment.engine import Decision, GuardEngine, Phase
from gyza.containment.log import (
    KIND_PROMOTE, KIND_ROLLBACK, AppendOnlyLog, Event,
)
from gyza.containment.reversibility import Reversibility, ReversibilityTable


class NotInteriorError(RuntimeError):
    """Raised when an irreversible or egressing action is staged directly.
    Such actions must be SUBMITTED to the gate, never written to the interior."""


@dataclass
class Escalation:
    """H-1 payload. Must present the claim, its provenance, and the SPECIFIC
    bound that would be exceeded -- an escalation a human cannot act on is a
    dropped alarm."""
    reason: str
    action_types: list[str]
    bounds_cited: list[str]
    provenance: list[str]                 # event hashes, third-party checkable
    batch_size: int


@dataclass
class PromotionResult:
    promoted: bool
    batch_size: int
    decision: Decision | None = None
    escalation: Escalation | None = None
    rolled_back: int = 0


class StagingArea:
    """The append-only interior. Nothing written here is visible to
    `baseline_state()` until it is promoted."""

    def __init__(self, projector: Callable[[list[Event]], object],
                 reversibility: ReversibilityTable | None = None,
                 log: AppendOnlyLog | None = None):
        self._log = log or AppendOnlyLog()
        self._project = projector
        self._rev = reversibility or ReversibilityTable()
        self._watermark = -1               # last promoted seq; -1 == nothing
        self._abandoned: set[int] = set()
        self._pending_gate: list[tuple[str, str, dict]] = []

    # -- interior ----------------------------------------------------------
    def stage(self, partition: str, action_type: str,
              payload: dict | None = None) -> Event:
        r = self._rev.classify(action_type)
        if r is not Reversibility.REVERSIBLE_INTERIOR:
            raise NotInteriorError(
                f"action {action_type!r} is {r.value} and cannot be staged in "
                f"the reversible interior; submit it to the promotion gate"
            )
        return self._log.append(partition, action_type, payload)

    def submit(self, partition: str, action_type: str,
               payload: dict | None = None) -> None:
        """Queue an irreversible or egressing action for the gate. It is NOT
        applied to the interior and NOT visible anywhere until promoted."""
        self._pending_gate.append((partition, action_type, dict(payload or {})))

    # -- projections (derived, never stored) -------------------------------
    def _live(self, upto: int) -> list[Event]:
        return [e for e in self._log.events()
                if e.seq <= upto and e.seq not in self._abandoned]

    def baseline_state(self) -> object:
        """State as of the last promotion -- the checkpoint (C-7)."""
        return self._project(self._live(self._watermark))

    def staged_state(self) -> object:
        """State including everything currently staged."""
        return self._project(self._live(self._log.last_seq))

    @property
    def staged_events(self) -> list[Event]:
        return [e for e in self._log.events()
                if e.seq > self._watermark and e.seq not in self._abandoned]

    @property
    def pending_gate(self) -> list[tuple[str, str, dict]]:
        return list(self._pending_gate)

    @property
    def log(self) -> AppendOnlyLog:
        return self._log

    @property
    def watermark(self) -> int:
        return self._watermark

    # -- C-7 ---------------------------------------------------------------
    def rollback(self, reason: str = "") -> int:
        """Return the interior to the last promotion.

        The abandoned events STAY IN THE LOG. Content is not destroyed, which
        is the whole point: rollback frequency bounds resource loss, but only
        append-only storage bounds content loss.
        """
        victims = [e.seq for e in self._log.events()
                   if e.seq > self._watermark and e.seq not in self._abandoned]
        if victims or self._pending_gate:
            self._log.append("__control__", KIND_ROLLBACK,
                             {"from_seq": self._watermark + 1,
                              "to_seq": self._log.last_seq,
                              "abandoned": victims, "reason": reason})
        self._abandoned.update(victims)
        self._pending_gate.clear()
        return len(victims)

    def _mark_promoted(self, batch: int) -> None:
        self._log.append("__control__", KIND_PROMOTE,
                         {"through_seq": self._log.last_seq, "batch": batch})
        self._watermark = self._log.last_seq


class PromotionGate:
    """C-6. Batched, SERIALIZED, and the only place cumulative invariants are
    evaluated."""

    def __init__(self, engine: GuardEngine, staging: StagingArea):
        self._engine = engine
        self._staging = staging
        self._lock = threading.Lock()      # the serialization point (C7)
        self.escalations: list[Escalation] = []

    def promote(self, harm_classes: list[str] | None = None) -> PromotionResult:
        # Serialized on purpose. Concurrency here would reintroduce exactly the
        # shape R13 measured: N individually-safe lookaheads against the same
        # pre-round state composing into an unsafe joint state.
        with self._lock:
            return self._promote_locked(harm_classes)

    def _promote_locked(self, harm_classes) -> PromotionResult:
        st = self._staging
        batch = len(st.staged_events) + len(st.pending_gate)
        if batch == 0:
            return PromotionResult(promoted=True, batch_size=0)

        s0 = st.baseline_state()
        s_next = st.staged_state()

        # (1) The staged batch, against CUMULATIVE bounds. This is the
        #     evaluation the interior deliberately refused to perform.
        decision = self._engine.evaluate(
            s0, s_next, "stage_artifact", Phase.PROMOTION, harm_classes)

        # (2) Every irreversible / egressing action queued for the gate.
        for _part, action_type, _pl in st.pending_gate:
            d = self._engine.evaluate(s0, s_next, action_type,
                                      Phase.PROMOTION, harm_classes)
            if not d.admit:
                decision.admit = False
                decision.reasons.extend(d.reasons)
            decision.evaluated.extend(d.evaluated)
            decision.measured.update(d.measured)

        if not decision.admit:
            esc = Escalation(
                reason="; ".join(decision.reasons),
                action_types=sorted({a for _p, a, _x in st.pending_gate}
                                    | {e.kind for e in st.staged_events}),
                bounds_cited=[r for r in decision.reasons
                              if "bound" in r or "USER DECISION" in r],
                provenance=[e.hash for e in st.staged_events],
                batch_size=batch,
            )
            self.escalations.append(esc)
            n = st.rollback(reason="promotion refused")
            return PromotionResult(promoted=False, batch_size=batch,
                                   decision=decision, escalation=esc,
                                   rolled_back=n)

        # Admitted: the queued irreversible actions become real, then the
        # watermark advances past everything in this batch.
        for part, action_type, pl in st.pending_gate:
            st.log.append(part, action_type, pl)
        st._pending_gate.clear()
        st._mark_promoted(batch)
        return PromotionResult(promoted=True, batch_size=batch,
                               decision=decision)
