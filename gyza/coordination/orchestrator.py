"""
K-4 executor pool, K-5 combiner, K-6 scheduler, H-1 escalation queue,
O-2 metrics, O-3 alarms.

K-3 (allocator) IS selected, by SR-2. K-7 (retry) IS selected -- SR-4's
question turned out DERIVABLE (exchangeable resamples cannot change expected
accuracy without a verifier) and the derivation is confirmed on cached data.

K-2 (decomposer) is now SPLIT, and the split is the point:

  * its STRATEGY is selected -- `DEFAULT_DECOMPOSITION_STRATEGY` = CONSERVING,
    on a CONTAINMENT basis, with its outcome effect explicitly UNMEASURED;
  * its IMPLEMENTATION still raises, for a reason that has nothing to do with
    strategy: nothing assigns a `claim_type` to a natural task, and `TaskSpec`
    carries no file list for a file-partitioned strategy to partition over.

A default nobody chose is worse than an absence somebody noticed -- and a
default that IMPLIES an outcome basis it lacks is worse than both. Hence the
basis is exported beside the constant, not buried in a findings document.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum

from gyza.containment.engine import GuardEngine, Phase
from gyza.containment.invariants import InvariantClass
from gyza.containment.staging import PromotionGate, StagingArea
from gyza.coordination.task import TaskResult, TaskSpec, Termination
from gyza.verification.scheduler import consult_tier_algebra


class NotSelectedError(NotImplementedError):
    """Raised by a component whose selection route could not be run. The
    message names the blocking artifact so the gap stays legible."""


# --------------------------------------------------------------------------- #
#  K-2 / K-3 / K-7 — declared, not defaulted                                   #
# --------------------------------------------------------------------------- #
class DecompositionStrategy(str, Enum):
    """K-2's strategy space, as SR-1 measured it on real decompositions."""

    CONSERVING = "CONSERVING"      # no file is touched by two subtasks
    REVISITING = "REVISITING"      # unconstrained; what 92.2% of humans do


#: K-2's SELECTED DEFAULT, and the basis is the whole value of naming it.
#:
#: NOTHING HERE SAYS CONSERVING PRODUCES BETTER OUTCOMES. The outcome effect has
#: since been MEASURED and is NOT SIGNIFICANT -- depth-matched over n=480 real
#: PRs, +0.0710 with overlapping CIs (research/sr1_matched/). That is an
#: UNDERPOWERED NULL: the design's smallest detectable difference is 0.167, so a
#: real effect below that could not have been seen, and the comparison is
#: observational so it cannot be causal either way.
#:
#: What IS measured is that only ~8% of real human decompositions conserve, so
#: choosing CONSERVING means diverging from ~92% of observed practice -- for
#: CONTAINMENT reasons, with the outcome cost bounded but not zero.
DEFAULT_DECOMPOSITION_STRATEGY = DecompositionStrategy.CONSERVING

DEFAULT_DECOMPOSITION_BASIS = (
    "CONSERVING is the default because the architectural principle mandates "
    "partitioning on containment grounds. Its effect on task success is now "
    "MEASURED AND NOT SIGNIFICANT, not unmeasured: depth-matched over n=480 "
    "real PRs, CONSERVING failed at 0.0732 (3/41) against REVISITING 0.1441 "
    "(32/222), a difference of +0.0710 with OVERLAPPING confidence intervals. "
    "THAT IS AN UNDERPOWERED NULL, NOT EVIDENCE OF NO EFFECT -- the design's own "
    "smallest detectable difference is 0.167, so a real effect below that could "
    "not have been seen. The observational comparison also cannot be causal: "
    "structure was not assigned. No outcome benefit is claimed."
)


def decompose(task: TaskSpec):
    """K-2. STILL RAISES, and the strategy question is no longer why.

    THE STRATEGY IS SELECTED: `DEFAULT_DECOMPOSITION_STRATEGY` is CONSERVING,
    on the basis above. That half of the blocker is resolved.

    WHAT REMAINS IS INDEPENDENT OF SR-1 AND IS NOT A STRATEGY QUESTION:
    nothing assigns a `claim_type` to a natural task. `TaskSpec.claim_type` is
    required (`task.py:35`) and `grep claim_type gyza/` finds it declared there
    and produced nowhere. `TaskSpec` also carries no file list, so a
    FILE-PARTITIONED strategy has nothing to partition over -- CONSERVING is
    not mechanically applicable to the input this function receives.

    So a working decomposer is not one strategy decision away. Returning a
    fabricated decomposition here would be worse than raising: the stub was
    honest about not knowing, and a default that silently implied an outcome
    basis it lacks would be the failure mode this module exists to avoid.
    """
    raise NotSelectedError(
        f"K-2 strategy IS selected ({DEFAULT_DECOMPOSITION_STRATEGY.value}; "
        f"{DEFAULT_DECOMPOSITION_BASIS}). K-2 remains unimplementable for a "
        f"DIFFERENT and independent reason: nothing assigns a claim_type to a "
        f"natural task, and TaskSpec carries no file list for a "
        f"file-partitioned strategy to operate over. See "
        f"research/selection_routes/BLOCKED_SR1_SR2_SR4.md")


_rr_cursor = {"i": 0}


def allocate(task: TaskSpec, handlers: list[str]) -> str:
    """K-3 — ROUND-ROBIN, per SR-2.

    Type-routing was the design default and SR-2 measured it 13 points WORSE
    than round-robin (0.3261 vs 0.4565), because the allocable taxonomy carries
    two claim types across 196 tasks and cannot discriminate four handlers.
    Routing by a taxonomy too coarse to discriminate converts a spread into a
    bet on one handler; round-robin, which knows nothing, diversifies.

    This is NOT an argument against type-routing in general -- with a taxonomy
    fine enough to discriminate, the sign could reverse, and that is untested.
    It is the decision for THIS taxonomy, and it is revisited when the taxonomy
    changes.
    """
    if not handlers:
        raise ValueError("no handlers to allocate to")
    h = handlers[_rr_cursor["i"] % len(handlers)]
    _rr_cursor["i"] += 1
    return h


class RetryPolicy(str, Enum):
    """K-7's variants, exactly as SR-4 specified them (BUILD_PLAN.md:234)."""

    NO_RETRY = "NO_RETRY"                  # (a) fail to escalation immediately
    BOUNDED_RETRY = "BOUNDED_RETRY"        # (b) k attempts, then escalate
    RETRY_WITH_DECOMPOSITION = "RETRY_WITH_DECOMPOSITION"   # (c) decompose, retry parts


#: K-7's SELECTED DEFAULT. Unlike K-2's, this basis IS measured.
DEFAULT_RETRY_POLICY = RetryPolicy.NO_RETRY

DEFAULT_RETRY_BASIS = (
    "NO_RETRY is the default because retry WITHOUT A VERIFIER cannot improve "
    "expected accuracy: independent resamples are EXCHANGEABLE, so a retry is "
    "as likely to break a correct answer as to fix a wrong one. MEASURED on 314 "
    "cached sample-pairs -- 9 recovered vs 14 broken, McNemar exact p = 0.4049, "
    "consistent with a net effect of ZERO. This is NOT a claim that NO_RETRY "
    "produces better outcomes; it is a claim that retry produces NO DIFFERENT "
    "outcome, and SR-4's own decision rule then picks (a) because it is simpler "
    "and cheaper. Escalation target is H-1."
)


def retry_policy(task: TaskSpec, attempts: int) -> RetryPolicy:
    """K-7 — NO_RETRY, and the basis is DERIVED then confirmed on cached data.

    SR-4 asked whether retry recovers failures or burns budget on reproducible
    errors, with an equivalence bound of 3 percentage points on recovery rate
    (BUILD_PLAN.md:232-238). It never ran. **The question turned out derivable.**

    THE DERIVATION: two samples drawn from the same model at the same
    temperature are EXCHANGEABLE. There is nothing that makes the first one
    "the attempt" and the second "the retry". So P(fix a wrong answer) and
    P(break a right one) are equal in expectation, and swapping in a resample
    cannot change expected accuracy. **Retry helps only if you can SELECT the
    better attempt -- and selecting requires a verifier, which is the
    competence bound.**

    CONFIRMED, not assumed: 9 recovered vs 14 broken over 23 discordant pairs
    (McNemar exact p = 0.4049). See research/sr4_scope/.

    WHAT THIS DOES NOT SAY: that retry is harmful. The net is statistically
    indistinguishable from zero, which is exactly why the cheaper variant wins.
    """
    return DEFAULT_RETRY_POLICY


# --------------------------------------------------------------------------- #
#  K-4 — executor pool                                                         #
# --------------------------------------------------------------------------- #
class ExecutorPool:
    """Concurrency is governed by the invariant CLASS tag, never by the carrier.

    That split is the whole point of the two-dimensional taxonomy: CLASS says
    what may run at the same time (C6/C7), CARRIER says whether the evidence
    survives chaining (SR-3). Using carrier here would serialize proof-carried
    work for no reason and run cumulative work concurrently, which is the
    failure R13 measured.
    """

    def __init__(self):
        self._cumulative_lock = threading.Lock()
        self.ran_concurrent: list[str] = []
        self.ran_serialized: list[str] = []

    def submit(self, task: TaskSpec, fn):
        if any(c is InvariantClass.CUMULATIVE for c in task.invariant_classes):
            with self._cumulative_lock:
                self.ran_serialized.append(task.task_id)
                return fn()
        self.ran_concurrent.append(task.task_id)
        return fn()


# --------------------------------------------------------------------------- #
#  K-5 — combiner                                                              #
# --------------------------------------------------------------------------- #
@dataclass
class Combination:
    tier: int
    reasons: list[str]
    requires_promotion_gate: bool
    permitted: bool


class Combiner:
    """Consults TIER_ALGEBRA before claiming anything about a combination."""

    def combine(self, tasks: list[TaskSpec], depth: int | None = None) -> Combination:
        d = consult_tier_algebra(
            carriers=[t.carrier for t in tasks],
            tiers=[t.tier for t in tasks],
            classes=[c for t in tasks for c in t.invariant_classes],
            depth=depth if depth is not None else len(tasks),
        )
        return Combination(d.tier, d.reasons, d.requires_promotion_gate,
                           d.depth_permitted)


# --------------------------------------------------------------------------- #
#  H-1 — escalation queue                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class EscalationItem:
    task_id: str
    claim: str
    provenance: list[str]
    bound_cited: str
    detail: str


class EscalationQueue:
    """An escalation a human cannot act on is a dropped alarm, so an item
    without a cited bound is REFUSED rather than queued silently."""

    def __init__(self):
        self._q: list[EscalationItem] = []

    def push(self, item: EscalationItem) -> None:
        if not item.bound_cited:
            raise ValueError(
                f"refusing to queue an escalation for {item.task_id!r} with no "
                f"cited bound: an escalation without the specific bound that "
                f"would be exceeded is not actionable")
        if not item.provenance:
            raise ValueError(
                f"refusing to queue an escalation for {item.task_id!r} with no "
                f"provenance: a third party must be able to check the claim")
        self._q.append(item)

    def __len__(self) -> int:
        return len(self._q)

    def items(self) -> list[EscalationItem]:
        return list(self._q)


# --------------------------------------------------------------------------- #
#  O-2 metrics / O-3 alarms                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class RunMetrics:
    tier_distribution: dict = field(default_factory=dict)
    carrier_distribution: dict = field(default_factory=dict)
    depth_reached: int = 0
    harm_fraction_of_bound: dict = field(default_factory=dict)
    promotion_batch_sizes: list = field(default_factory=list)
    escalations: int = 0
    admitted: int = 0
    rolled_back: int = 0

    @property
    def effective_throughput(self) -> float:
        """Admitted AND NOT rolled back. Nominal admission is a trap: SR-5
        measured nominal 1.0000 for every variant while effective ranged
        0.0542 -> 0.0000."""
        total = self.admitted + self.rolled_back
        return (self.admitted / total) if total else 0.0

    def observe(self, task: TaskSpec) -> None:
        self.tier_distribution[task.tier] = self.tier_distribution.get(task.tier, 0) + 1
        self.carrier_distribution[task.carrier] = \
            self.carrier_distribution.get(task.carrier, 0) + 1
        self.depth_reached = max(self.depth_reached, task.depth)


ALARM_HARM_FRACTION = 0.8
ALARM_UNVERIFIED_FRACTION = 0.5
ALARM_ESCALATION_RATE = 0.25


def alarms(m: RunMetrics, *, invariants_evaluated: int = 0,
           invariants_enforced: int = 0,
           guard_loosenings: list[str] | None = None) -> list[str]:
    out = []
    # A guard loosening is ALWAYS an alarm, even when fully authorized. The
    # authorization makes it permitted; the alarm makes it visible.
    for a in (guard_loosenings or []):
        out.append(a)
    for cls, frac in m.harm_fraction_of_bound.items():
        if frac >= ALARM_HARM_FRACTION:
            out.append(f"HARM-NEAR-BOUND: {cls} at {frac:.0%} of its bound")

    n = sum(m.carrier_distribution.values())
    if n:
        unverified = (m.carrier_distribution.get("TEST", 0)
                      + m.carrier_distribution.get("NONE", 0)) / n
        if unverified >= ALARM_UNVERIFIED_FRACTION:
            out.append(
                f"VOCABULARY-DRIFT: {unverified:.0%} of claims are TEST-carried "
                f"or unverifiable; chains containing them are tier 3")

    total = m.admitted + m.rolled_back
    if total and (m.escalations / total) >= ALARM_ESCALATION_RATE:
        out.append(f"ESCALATION-SPIKE: {m.escalations / total:.0%} of work escalated")

    if invariants_evaluated > invariants_enforced:
        out.append(
            f"EVALUATED-NOT-ENFORCED: {invariants_evaluated - invariants_enforced} "
            f"invariant(s) were evaluated but their verdict was not acted on")
    return out


# --------------------------------------------------------------------------- #
#  K-6 — scheduler                                                             #
# --------------------------------------------------------------------------- #
class Scheduler:
    """Enforces per-carrier depth caps (SR-6), serialization at cumulative
    checks (C7), and per-action promotion (SR-5's decision)."""

    #: See StagingArea.NON_ADOPTED for the convention.
    NON_ADOPTED = (
        "IT SCHEDULES OVER A STAGED EXECUTION MODEL THAT IS ITSELF NOT "
        "ADOPTED. Its constructor requires a `StagingArea` and a "
        "`PromotionGate`, and both carry their own NON_ADOPTED markers -- "
        "gyza's production path executes an action and signs it, with no "
        "staging/promotion step for this to serialize. Wiring it would mean "
        "adopting that whole model, which is a design decision and not a "
        "wiring one. The research it encodes (SR-5, SR-6, C7) stands "
        "independently of whether this class runs."
    )

    def __init__(self, engine: GuardEngine, staging: StagingArea,
                 gate: PromotionGate, queue: EscalationQueue | None = None):
        self._engine = engine
        self._staging = staging
        self._gate = gate
        self.queue = queue or EscalationQueue()
        self.metrics = RunMetrics()
        self.pool = ExecutorPool()
        self.combiner = Combiner()

    def run_chain(self, tasks: list[TaskSpec],
                  harm_classes: list[str] | None = None) -> TaskResult:
        for t in tasks:
            self.metrics.observe(t)

        comb = self.combiner.combine(tasks, depth=len(tasks))
        if not comb.permitted:
            return TaskResult(tasks[0].task_id, Termination.DEPTH_CAP_REACHED,
                              "; ".join(comb.reasons), comb.tier)

        for t in tasks:
            self.pool.submit(t, lambda: self._staging.stage(
                t.task_id, "stage_artifact", {"delta": 0.0}))

        # SR-5: per-action promotion (Occam; per-task is the recorded override
        # if gate cost is expensive).
        res = self._gate.promote(harm_classes)
        if res.promoted:
            self.metrics.admitted += res.batch_size
            self.metrics.promotion_batch_sizes.append(res.batch_size)
            return TaskResult(tasks[0].task_id, Termination.GOAL_SATISFIED,
                              "promoted", comb.tier,
                              [e.hash for e in self._staging.log.events()])

        self.metrics.rolled_back += res.rolled_back
        self.metrics.escalations += 1
        esc = res.escalation
        self.queue.push(EscalationItem(
            task_id=tasks[0].task_id, claim=tasks[0].goal,
            provenance=esc.provenance if esc and esc.provenance else ["(none)"],
            bound_cited="; ".join(esc.bounds_cited) if esc and esc.bounds_cited
            else (esc.reason if esc else "unknown"),
            detail=esc.reason if esc else ""))
        return TaskResult(tasks[0].task_id, Termination.HARM_BUDGET_EXHAUSTED,
                          esc.reason if esc else "", comb.tier)
