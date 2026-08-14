"""R-B1 — the conservation taxonomy.

THE QUESTION. HARM-IS-TRANSFERRED showed that bounding H1 relocates harm onto
counterparties rather than removing it. Is that a property of harm bounds in
general, or of CONSERVED quantities specifically?

THE DISCRIMINANT, and it is definitional rather than empirical. A quantity is
CONSERVED if what leaves one frame enters another, so the total over all frames
is invariant. For such a quantity, refusing to move it inside your frame leaves
it outside: the reduction inside IS an increase outside. That is what
conservation means, so bounding a conserved quantity NECESSARILY transfers.

Three outcomes follow, and they have very different value:

  TRANSFERS         the harm moves to a party outside the frame.
                    A bound relocates; it does not remove.
  EXTINGUISHES      the harm does not occur at all. A bound REMOVES.
  ALREADY_REALIZED  the harm occurred before the guard could act. A bound
                    yields non-repudiation, not containment.

Only EXTINGUISHES supports a genuine harm bound, which is why this
classification is the precondition for Track C.
"""
from __future__ import annotations

from dataclasses import dataclass

TRANSFERS = "TRANSFERS"
EXTINGUISHES = "EXTINGUISHES"
ALREADY_REALIZED = "ALREADY_REALIZED"


@dataclass(frozen=True)
class Quantity:
    id: str
    conserved: bool           # does what leaves one frame enter another?
    prevented: bool           # can the guard act BEFORE the harm occurs?
    basis: str                # why, in one sentence

    @property
    def outcome(self) -> str:
        """The classification is DERIVED from the two structural facts, never
        assigned. If it were assigned, this would be a table of opinions."""
        if not self.prevented:
            return ALREADY_REALIZED
        return TRANSFERS if self.conserved else EXTINGUISHES


#: The C-3 action vocabulary's harm quantities, declared and declarable.
#: `conserved` and `prevented` are structural facts about each quantity; the
#: outcome column is computed from them.
QUANTITIES: list[Quantity] = [
    # --- declared -----------------------------------------------------------
    Quantity("H1_credits", True, True,
             "the ledger is zero-sum: my settled outflow is exactly another "
             "compositor's settled inflow"),
    Quantity("H2_market_capital", True, True,
             "capital moves between agents via CapitalEntry; stake leaving one "
             "agent lands on another or on escrow"),
    Quantity("H4_authority", False, False,
             "an exceedance is a COUNT of events, not a substance; and the "
             "sandboxed work has already run when the runner refuses to sign"),
    # --- declarable, from HARM_MODEL_GAP ------------------------------------
    Quantity("H3_content_loss", False, True,
             "deleted content is DESTROYED, not moved; nobody else gains it"),
    Quantity("key_rotation_unreachable_credits", False, True,
             "the credits still exist but become unreachable; access is "
             "destroyed rather than transferred"),
    Quantity("outstanding_delegated_authority", False, True,
             "granting does not remove the parent's authority; it is copied "
             "under attenuation, not moved"),
    Quantity("storage_growth", False, True,
             "append-only bytes are CREATED; no other frame loses them"),
    Quantity("guard_permissiveness", False, True,
             "loosening a bound creates admissible states; it takes nothing "
             "from anyone"),
    Quantity("signed_envelope_count", False, True,
             "signing CREATES a non-repudiable claim; no other party holds one "
             "fewer, so the count rises rather than moving between frames"),
    Quantity("emission_volume", False, False,
             "containment ends at emission (C15): once bytes leave modelled "
             "state the guard has already lost its opportunity"),
]


def classify() -> dict[str, str]:
    return {q.id: q.outcome for q in QUANTITIES}


def summary() -> dict[str, int]:
    out: dict[str, int] = {}
    for q in QUANTITIES:
        out[q.outcome] = out.get(q.outcome, 0) + 1
    return out


__all__ = ["Quantity", "QUANTITIES", "classify", "summary",
           "TRANSFERS", "EXTINGUISHES", "ALREADY_REALIZED"]
