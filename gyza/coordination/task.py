"""
K-1 task representation and K-8 termination states.

A task carries CARRIER alongside tier, because SR-3 established that carrier is
what governs composition and Part A quantified the cost of ignoring it: 61.1%
tier-1 coverage in isolation is 0.9% at depth 8.

`claim_type` is NOT self-declared by a producing agent. `WorkItem.required_tier`
(gyza/schema.py) already is, and a self-reported tier is exactly what a router
must not trust -- the same shape as the self-reported attestation_tier that
verify-on-fetch exists to stop trusting. The assignment is audited or absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from gyza.containment.invariants import InvariantClass


class Termination(str, Enum):
    """K-8. Four EXPLICIT states. There is deliberately no TIMEOUT member:
    a timeout is not a reason, it is the absence of one, and a task that ends
    without a recorded reason cannot be audited."""
    GOAL_SATISFIED = "GOAL_SATISFIED"
    DEPTH_CAP_REACHED = "DEPTH_CAP_REACHED"
    HARM_BUDGET_EXHAUSTED = "HARM_BUDGET_EXHAUSTED"
    ESCALATED = "ESCALATED"


@dataclass
class TaskSpec:
    task_id: str
    goal: str
    claim_type: str
    tier: int
    carrier: str                                  # PROOF | SPEC | TEST | NONE
    harm_classes: list[str] = field(default_factory=list)
    invariant_classes: list[InvariantClass] = field(default_factory=list)
    parent_id: str | None = None
    depth: int = 0
    assignment_audited: bool = False

    def __post_init__(self):
        if self.carrier not in ("PROOF", "SPEC", "TEST", "NONE"):
            raise ValueError(f"unknown carrier {self.carrier!r}")

    @property
    def composes(self) -> bool:
        """Whether this task's evidence survives being chained (SR-3)."""
        return self.carrier in ("PROOF", "SPEC")


@dataclass
class TaskResult:
    task_id: str
    state: Termination
    detail: str = ""
    tier_achieved: int = 3
    provenance: list[str] = field(default_factory=list)
