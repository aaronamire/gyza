"""
C-5 staging area, C-6 promotion gate, C-7 checkpoint/rollback.

STATUS: REFERENCE IMPLEMENTATION OF A NON-ADOPTED EXECUTION MODEL.
=================================================================
`StagingArea`, `PromotionGate` and `coordination.Scheduler` have **zero
production constructors** -- every one is in `tests/`. That is deliberate and
recorded here so it stops reading as an oversight, because an unconsumed
component that LOOKS like it should be running is the artifact-#16 species
("registering a checker is not evidence that it runs").

These implement a **staged-interior / promotion-boundary** execution model.
`AgentRunner` implements a different one: execute, then sign. They are not an
unwired copy of production; they are an alternative production did not adopt.

The classes this module would gate are covered by other means today:

    H4 authority   `runner.py`'s bounds gate -- refuses to SIGN when the
                   enforcement record is wider than the manifest (ENFORCED)
    H5 storage     `ArtifactStore.max_bytes`, sourced from the DECLARED bound
                   (`gyza_model.storage_cap_bytes`) (ENFORCED)
    H6 cadence     `check_cadence` at the runner's signing boundary, escalating
                   to the durable `ReviewQueue` (RECORD-ONLY by owner decision)
    H3 egress      `containment/egress.py`, recorded at the send sites
                   (MEASURED, deliberately unbounded)

**What is kept and why.** The research this encodes is real and is not
reproducible from the tests alone: C-7's "no stateless local check bounds a
cumulative quantity", C-9's ungated interior, R10's mutable-vs-append-only
content-loss result, and SR-5's per-action promotion decision. Deleting the
module would delete the only executable statement of those findings.

`tests/test_staging_is_unadopted.py` asserts the absence, so the day someone
wires it, that test fails and this header must be corrected rather than
silently becoming false.


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
    KIND_PROMOTE, KIND_ROLLBACK, KIND_WINDOW_OPEN, AppendOnlyLog, Event,
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

    # -- the accounting window (C-6 frame identity) ------------------------
    def open_window(self, reason: str = "") -> int:
        """Open a new accounting window. Returns its immutable identifier.

        THE IDENTIFIER IS THE MARKER'S SEQ, and that is why it cannot move:
        `AppendOnlyLog.append` assigns `seq = len(self._events)` and never
        rewrites one, so a window id is fixed the moment it exists.

        WHAT THIS DECOUPLES, and it is the point. Cumulative bounds are stated
        "per window". Before this, no window existed as a named thing, so the
        only available boundary was a promotion -- and `promote()` is a public
        method any caller may invoke at any moment. A bound anchored there is
        anchored to a caller's timing. Windows now close ONLY on an explicit
        `open_window`, so promoting more often does not re-base anything.
        """
        e = self._log.append("__control__", KIND_WINDOW_OPEN,
                             {"reason": reason})
        return e.seq

    def current_window(self) -> int:
        """The id of the window in force. DERIVED from the log, never stored.

        0 means "the genesis window" -- no marker has been appended, so the
        accounting origin is the run origin. That is a real window, not a
        missing one, and it is why this returns 0 rather than None: an absent
        window must not read as "unbounded" (the empty-record hole).
        """
        # include_control=True is REQUIRED: events() hides control kinds by
        # default, so without it the marker is invisible and every window
        # silently reads as genesis -- an absent frame reading as the most
        # permissive one. Caught by the frame-stability check, not by review.
        opens = [e.seq for e in self._log.events(include_control=True)
                 if e.kind == KIND_WINDOW_OPEN]
        return opens[-1] if opens else 0

    def window_origin_state(self) -> object:
        """State as of the CURRENT window's origin.

        Distinct from `baseline_state()` (the moving rollback checkpoint) and
        from `origin_state()` (the run origin). A cumulative bound stated "per
        window" must be measured from here, and this value is constant for the
        window's whole lifetime because `current_window()` is.
        """
        w = self.current_window()
        return self._project([e for e in self._live(self._log.last_seq)
                              if e.seq < w])

    def windows(self) -> list[dict]:
        """Append-only record of every window and the promotions inside it.

        Reconstructed by folding the log rather than kept as a side table, so
        it cannot disagree with the log it summarises.
        """
        out: list[dict] = [{"window_id": 0, "opened_at_seq": 0,
                            "reason": "genesis", "promotions": []}]
        for e in self._log.events(include_control=True):
            if e.kind == KIND_WINDOW_OPEN:
                out.append({"window_id": e.seq, "opened_at_seq": e.seq,
                            "reason": e.payload.get("reason", ""),
                            "promotions": []})
            elif e.kind == KIND_PROMOTE:
                out[-1]["promotions"].append(e.seq)
        return out

    def origin_state(self) -> object:
        """State at the ORIGIN of the accounting period.

        Distinct from `baseline_state()`, and the distinction is load-bearing.
        The rollback checkpoint moves forward with every promotion; the frame a
        CUMULATIVE bound is measured over must not. Measuring cumulative harm
        from the last promotion lets an agent defeat the bound entirely by
        promoting after every action -- each batch measures a fresh, tiny drain
        and the run-level total is never anyone's frame.

        That is R9's G4' failure in this codebase's own shape: an invariant
        evaluated over a frame that is not the harm's frame. G4' pinned at s0
        and lost 175000; here the error is the mirror image -- pinning at the
        MOVING checkpoint instead of the origin -- and it was found by SR-5's
        preregistered feasibility check reporting zero refusals at k=1.
        """
        return self._project([])

    def baseline_state(self) -> object:
        """State as of the last promotion -- the ROLLBACK checkpoint (C-7).
        Correct for rollback; wrong as a cumulative-harm frame (see above)."""
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
        # The window id is recorded ON the promotion so the association is in
        # the append-only record rather than inferred later from ordering.
        self._log.append("__control__", KIND_PROMOTE,
                         {"through_seq": self._log.last_seq, "batch": batch,
                          "window_id": self.current_window()})
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

        # CUMULATIVE harm is measured from the accounting-period ORIGIN, not
        # from the moving rollback checkpoint. See StagingArea.origin_state --
        # using the checkpoint here lets an agent defeat the bound by promoting
        # after every action.
        s0 = st.origin_state()
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
