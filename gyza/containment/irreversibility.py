"""
C-2 — an irreversibility measure, and the honest limit on what it can claim.

Until now `gyza_model.UNMODELLED` said plainly that **no function in `gyza/`
computes an irreversibility measure**, so the guard could not distinguish
computing a sum from issuing a command that cannot be taken back. Both were one
signed envelope. Every bound the system did enforce — authority, storage, egress
rate — was therefore a PROXY for the thing anyone actually cares about.

THE MEASURAND IS THE SIGNED ENFORCEMENT RECORD, AND THAT CHOICE IS THE DESIGN.
An action's reversibility is not a property of its intent, its prompt or its
output text — all of which are the agent's own words about itself, and none of
which a verifier can check. It is a property of WHAT THE ACTION WAS PERMITTED TO
TOUCH, which the sandbox stamps and the envelope's `output_hash` commits to. So:

  * it is computed from state, never from guard state (discipline #5);
  * a third party can recompute it from a bundle alone, with no trust in us;
  * it cannot be argued with, because nothing is being asked — only looked up.

WHAT THIS DOES NOT DO. It does not measure how BAD an irreversible action was,
and it never will: severity is a judgement about consequences in the world, and
this program measured that class of judgement as not cheaply verifiable. It
measures whether an action COULD have left modelled state. An agent granted the
network that sends nothing is counted the same as one that exfiltrates, because
`bwrap`'s network control is all-or-nothing and the substrate cannot tell them
apart (`research/H3_BLIND_CHANNEL.md`). **The measure is an upper bound on
irreversible effect, and an upper bound is the only side of this a verifier can
be sound about.**
"""
from __future__ import annotations

from dataclasses import dataclass

#: The action could not have left modelled state: no network, and no writes
#: outside the content-addressed store. `iota = 0` in Sahoo's formulation
#: (`research/evidence/PRIOR_ART.md`), which is prior art for the idea that a
#: reversible action should cost a budget nothing.
REVERSIBLE = "REVERSIBLE"
#: The action could write or delete state that has no restorable record. Local,
#: and in principle compensatable by a system that kept tombstones — which
#: `ArtifactStore` does for evictions and ordinary filesystem writes do not.
DESTRUCTIVE = "DESTRUCTIVE"
#: The action was granted the network. Whatever it sent has left the system,
#: there is no state left to fold over, and no guard can retract it. This is
#: C15's hard boundary stated as a measurement rather than a caveat.
IRREVERSIBLE = "IRREVERSIBLE"
#: No enforcement record, so reversibility CANNOT BE ESTABLISHED. Counted with
#: the irreversible, never with the reversible: "I did not say" must not read
#: as "nothing left the system", which is the rule the enforcement record
#: already follows at the signing gate.
UNPROVEN = "UNPROVEN"

#: Classes that consume the irreversibility budget.
COUNTED = frozenset({DESTRUCTIVE, IRREVERSIBLE, UNPROVEN})


@dataclass(frozen=True)
class Reversibility:
    action_id: str
    verdict: str
    reason: str

    @property
    def counted(self) -> bool:
        return self.verdict in COUNTED


def _outside_store(path: str, store_paths: tuple[str, ...]) -> bool:
    p = (path or "").rstrip("/")
    return not any(p == s.rstrip("/") or p.startswith(s.rstrip("/") + "/")
                   for s in store_paths if s)


def classify(enforcement: "dict | None", *, action_id: str = "",
             store_paths: tuple[str, ...] = ()) -> Reversibility:
    """Classify ONE action from its signed enforcement record.

    `store_paths` names content-addressed locations whose writes are
    append-only and therefore recoverable. It is passed in rather than
    discovered, because this module must not import anything that knows where
    a particular deployment keeps its store — a harm function that reads
    configuration is a harm function a configuration change can silence.
    """
    if not isinstance(enforcement, dict) or not enforcement:
        return Reversibility(action_id, UNPROVEN,
                             "no enforcement record; reversibility cannot be "
                             "established and is not assumed")
    if enforcement.get("requires_network"):
        return Reversibility(action_id, IRREVERSIBLE,
                             "the sandbox granted network access; anything "
                             "sent has left modelled state (C15)")
    rw = [p for p in (enforcement.get("rw_paths") or [])
          if _outside_store(p, store_paths)]
    if rw:
        return Reversibility(action_id, DESTRUCTIVE,
                             f"writable paths outside any append-only store: "
                             f"{sorted(rw)}")
    return Reversibility(action_id, REVERSIBLE,
                         "no network and no writes outside an append-only "
                         "store; nothing left the system")


def fold_irreversible(records: "list[tuple[str, dict | None]]", *,
                      store_paths: tuple[str, ...] = ()) -> int:
    """COUNT of actions whose effects cannot be shown to be recoverable.

    A pure fold over append-only input, per the architectural principle: the
    same function the guard consults computes the harm, so the two cannot
    drift apart, and there is no stored aggregate for an unmodelled path to
    write behind the guard's back.
    """
    return sum(1 for aid, enf in records
               if classify(enf, action_id=aid, store_paths=store_paths).counted)


def benign_rate_is_zero(enforcement: "dict | None") -> bool:
    """Is an agent under THIS grant capable of an irreversible action at all?

    R-EVID Part C decides whether a level on an accumulating quantity is a
    BOUND or merely a TIMER by the sign of the benign drift, not by the level
    chosen. For irreversibility the answer is a property of the GRANT, and it
    splits cleanly:

      * no network and no writes outside an append-only store  ->  b = 0,
        SOUND-BY-SILENCE. A compliant agent cannot increment the quantity, so
        no level can false-alarm and a bound of 0 is a real bound.
      * anything else  ->  b > 0. Every action consumes budget, so any
        cumulative level is a TIMER: it refuses the agent at `ceil(L/b)`
        whatever it did.

    **That is the whole result, and it is a statement about grants rather than
    about agents.** Containment over irreversible effect is claimable exactly
    for agents that were never given the means, which is a narrower claim than
    "we bound irreversible harm" and is the one the architecture can support.
    """
    return classify(enforcement).verdict == REVERSIBLE
