"""
C-1 — harm model registry.

A harm class declares four things and the registry refuses anything less:

  quantity      a PURE FUNCTION OF STATE, (s0, s) -> float. It is a MEASURE,
                not a boolean (C5): a boolean has no dial and forces the corner.
  frame         what the quantity is measured over, and whether that frame is
                MUTABLE. A mutable frame is the R9 G4' hazard and is flagged.
  bound         the level at which the quantity is too much. LOADED from a
                declaration, never invented by this module (D1).
  code_path     the file:line witness that computes the quantity.

GATE (discipline #5): this module imports nothing from any guard module. Harm
must be definable without reference to the thing that checks it, or adequacy is
tautological. The permitted direction is the reverse -- a guard may call a harm
function, and C-4 deliberately does.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class UnsetBoundError(RuntimeError):
    """Raised when containment is claimed over a harm class with no declared
    bound. FAILS CLOSED: an undeclared bound is not an infinite bound."""


@dataclass(frozen=True)
class HarmClass:
    id: str
    description: str
    quantity: Callable[[object, object], float]
    frame: str
    frame_mutable: bool
    code_path: str
    bound: float | None = None          # None == UNSET, fails closed

    def measure(self, s0: object, s: object) -> float:
        v = self.quantity(s0, s)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError(
                f"harm class {self.id!r} returned {type(v).__name__}; harm must "
                f"be a MEASURE, not a boolean (C5)"
            )
        return float(v)


class HarmModelRegistry:
    def __init__(self) -> None:
        self._classes: dict[str, HarmClass] = {}

    def register(self, hc: HarmClass) -> None:
        if hc.id in self._classes:
            raise ValueError(f"harm class {hc.id!r} already registered")
        if not callable(hc.quantity):
            raise TypeError(f"harm class {hc.id!r} has no quantity function")
        if not hc.frame:
            raise ValueError(f"harm class {hc.id!r} declares no frame (C3)")
        self._classes[hc.id] = hc

    def __contains__(self, cid: str) -> bool:
        return cid in self._classes

    def __iter__(self):
        return iter(self._classes.values())

    def get(self, cid: str) -> HarmClass:
        if cid not in self._classes:
            raise KeyError(f"no such harm class: {cid!r}")
        return self._classes[cid]

    # -- bounds: LOADED, never invented ------------------------------------
    def load_bounds(self, bounds: dict[str, float]) -> None:
        """Apply declared bound levels. This is the ONLY way a bound enters the
        registry; nothing here derives a default. Unknown ids are an error
        rather than a silent no-op, because a typo'd id would leave the class
        it was meant to bound silently unbounded."""
        for cid, level in bounds.items():
            if cid not in self._classes:
                raise KeyError(f"bound declared for unknown harm class {cid!r}")
            if isinstance(level, bool) or not isinstance(level, (int, float)):
                raise TypeError(f"bound for {cid!r} must be numeric (C5)")
            hc = self._classes[cid]
            self._classes[cid] = HarmClass(
                id=hc.id, description=hc.description, quantity=hc.quantity,
                frame=hc.frame, frame_mutable=hc.frame_mutable,
                code_path=hc.code_path, bound=float(level),
            )

    def load_bounds_file(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text())
        self.load_bounds(data.get("bounds", data))

    def bound(self, cid: str) -> float:
        hc = self.get(cid)
        if hc.bound is None:
            raise UnsetBoundError(
                f"harm class {cid!r} has no declared bound. Containment cannot "
                f"be claimed over it. Bound levels are a USER DECISION and must "
                f"be loaded, not invented (BUILD_PLAN D1)."
            )
        return hc.bound

    def unbounded(self) -> list[str]:
        return sorted(c.id for c in self._classes.values() if c.bound is None)

    def assert_complete(self) -> None:
        missing = self.unbounded()
        if missing:
            raise UnsetBoundError(
                f"{len(missing)} harm class(es) have no declared bound: "
                f"{missing}. Every containment claim is scoped to a declared "
                f"model; nothing downstream can be claimed until these are set."
            )

    def mutable_frames(self) -> list[str]:
        """Classes whose frame can move. R9's G4' hazard: an invariant pinned to
        a stale frame is not conservative, it is catastrophic."""
        return sorted(c.id for c in self._classes.values() if c.frame_mutable)
