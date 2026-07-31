"""
C-2 — invariant registry with CLASS TAGS.

The tag is machinery, not documentation. The scheduler reads it to decide
concurrency, because the classes behave differently under composition and that
difference is measured, not assumed:

  CONSERVATION             composes statelessly across depth, breadth and
  MONOTONE_NON_CUMULATIVE  principals (C6). Safe to evaluate concurrently in
                           the interior.
  CUMULATIVE               does NOT compose (C6/C7). No stateless local check
                           bounds a cumulative quantity, so evaluating one
                           per-action in the interior is not merely useless --
                           it is misleading, because it looks like a check and
                           bounds nothing. Cumulative invariants are evaluated
                           ONLY at the serialized promotion gate.

An untagged invariant is REJECTED AT LOAD. There is no default tag: guessing
would silently place a cumulative bound in the concurrent interior, which is
exactly the failure R13 measured at the federation layer.

FRAME ALIGNMENT (C3) is structural. A predicate never receives raw state to
measure -- it receives the harm value the registry already computed, plus the
declared bound. There is no second frame for it to drift against.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class InvariantClass(str, Enum):
    CONSERVATION = "CONSERVATION"
    MONOTONE_NON_CUMULATIVE = "MONOTONE_NON_CUMULATIVE"
    CUMULATIVE = "CUMULATIVE"

    @property
    def composes_statelessly(self) -> bool:
        """C6: conservation and monotone compose; cumulative does not."""
        return self is not InvariantClass.CUMULATIVE


class UntaggedInvariantError(TypeError):
    """Raised at load for an invariant with no valid class tag."""


def bounded_by(h: float, bound: float, s0: object, s: object) -> bool:
    """The default predicate: the measured harm stays within the declared
    bound. Takes the harm VALUE, never the state, so it cannot re-measure in a
    different frame."""
    return h <= bound


@dataclass(frozen=True)
class Invariant:
    id: str
    harm_class: str                       # C4: one invariant, one harm class
    cls: InvariantClass
    description: str
    predicate: Callable[[float, float, object, object], bool] = bounded_by


class InvariantRegistry:
    def __init__(self) -> None:
        self._inv: dict[str, Invariant] = {}

    def register(self, inv: Invariant) -> None:
        if not isinstance(inv.cls, InvariantClass):
            raise UntaggedInvariantError(
                f"invariant {inv.id!r} carries no valid class tag "
                f"(got {inv.cls!r}). One of "
                f"{[c.value for c in InvariantClass]} is required: the "
                f"scheduler reads the tag to decide concurrency (C6/C7), so "
                f"there is no safe default."
            )
        if inv.id in self._inv:
            raise ValueError(f"invariant {inv.id!r} already registered")
        if not inv.harm_class:
            raise ValueError(
                f"invariant {inv.id!r} names no harm class; adequacy is PER "
                f"HARM CLASS (C4)"
            )
        self._inv[inv.id] = inv

    def __iter__(self):
        return iter(self._inv.values())

    def __len__(self) -> int:
        return len(self._inv)

    def get(self, iid: str) -> Invariant:
        return self._inv[iid]

    def for_harm_class(self, cid: str) -> list[Invariant]:
        return [i for i in self._inv.values() if i.harm_class == cid]

    def interior(self) -> list[Invariant]:
        """Evaluable concurrently in the staging interior (C6)."""
        return [i for i in self._inv.values() if i.cls.composes_statelessly]

    def promotion_only(self) -> list[Invariant]:
        """Cumulative -- valid ONLY at the serialized gate (C7)."""
        return [i for i in self._inv.values() if not i.cls.composes_statelessly]

    def uncovered(self, harm_ids) -> list[str]:
        """Harm classes with no invariant. C4: conjunction is free by
        induction, but a class nobody covers is simply unbounded."""
        covered = {i.harm_class for i in self._inv.values()}
        return sorted(set(harm_ids) - covered)
