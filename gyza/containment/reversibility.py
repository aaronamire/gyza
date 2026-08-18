"""
C-3 — reversibility classifier.

A STATIC TABLE over the action vocabulary. Not a prediction, not a model call,
not a heuristic over action text: R11 established that routing by predicted
difficulty fails even with a literal oracle (AUROC 1.000 buying economy 0.320
against a 0.40 bar), so nothing here is allowed to predict. Lookup only.

UNKNOWN ACTION TYPE => IRREVERSIBLE. A vocabulary that grows past its table is
exactly when fail-closed matters, and a rising unknown rate is the drift alarm
(O-3).

EGRESS is separated from IRREVERSIBLE because they differ in what containment
can even mean. An irreversible local action is still inside the modelled state
and can be bounded. An egress leaves modelled state entirely: a guard can refuse
to emit, and after emission there is no containment and no detector helps (C15).
"""
from __future__ import annotations

from enum import Enum


class Reversibility(str, Enum):
    REVERSIBLE_INTERIOR = "REVERSIBLE_INTERIOR"
    IRREVERSIBLE = "IRREVERSIBLE"
    EGRESS = "EGRESS"


# Gyza's action vocabulary, from the Part C enumeration (R14).
_DEFAULT: dict[str, Reversibility] = {
    # interior: staged, append-only, reversible by rollback to last promotion
    "read": Reversibility.REVERSIBLE_INTERIOR,
    "stage_artifact": Reversibility.REVERSIBLE_INTERIOR,
    "stage_envelope": Reversibility.REVERSIBLE_INTERIOR,
    "compute": Reversibility.REVERSIBLE_INTERIOR,
    "retrieve_memory": Reversibility.REVERSIBLE_INTERIOR,
    "claim_work_item": Reversibility.REVERSIBLE_INTERIOR,
    "reserve_credits": Reversibility.REVERSIBLE_INTERIOR,   # a hold, released

    # irreversible but still inside modelled state
    "sign_envelope": Reversibility.IRREVERSIBLE,      # non-repudiable once made
    "settle_credits": Reversibility.IRREVERSIBLE,
    "delete_artifact": Reversibility.IRREVERSIBLE,
    "grant_delegation": Reversibility.IRREVERSIBLE,
    "rotate_key": Reversibility.IRREVERSIBLE,
    "update_guard_config": Reversibility.IRREVERSIBLE,  # maximally gated (C-8)

    # egress: leaves modelled state; containment ends here (C15)
    "publish_agent": Reversibility.EGRESS,
    "send_message": Reversibility.EGRESS,
    "publish_delta": Reversibility.EGRESS,
    "publish_attestation": Reversibility.EGRESS,
    "external_send": Reversibility.EGRESS,
    "write_outside_sandbox": Reversibility.EGRESS,
}


class ReversibilityTable:
    def __init__(self, table: dict[str, Reversibility] | None = None):
        self._t = dict(_DEFAULT if table is None else table)
        self._unknown_seen: set[str] = set()

    def classify(self, action_type: str) -> Reversibility:
        r = self._t.get(action_type)
        if r is None:
            self._unknown_seen.add(action_type)
            return Reversibility.IRREVERSIBLE      # fail closed
        return r

    def is_interior(self, action_type: str) -> bool:
        return self.classify(action_type) is Reversibility.REVERSIBLE_INTERIOR

    def register(self, action_type: str, r: Reversibility) -> None:
        self._t[action_type] = r

    @property
    def unknown_seen(self) -> list[str]:
        """Drift signal for O-3: action types the table has never heard of."""
        return sorted(self._unknown_seen)

    @property
    def vocabulary(self) -> list[str]:
        return sorted(self._t)
