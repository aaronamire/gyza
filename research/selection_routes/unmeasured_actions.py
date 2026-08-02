"""
The SOUND HALF of the harm-model completeness question (OPEN_PROBLEM §4.2).

R12 established that blind channels are NOT mechanically discoverable, so
completeness cannot be established by a tool. But the converse direction IS
sound and is cheap: for each action type in the vocabulary, apply it and ask
whether ANY registered harm quantity moves. If none does, the declared model
does not measure that action.

  * A GAP FOUND IS DEFINITE -- the action changes state and no declared harm
    measure reads the change.
  * A GAP NOT FOUND PROVES NOTHING -- the harm may be real and unmodelled, which
    is precisely R12's UNSOUND result. This audit cannot certify completeness
    and does not try.

That asymmetry is the whole design. It is sound in one direction only, and the
other direction is what still needs a human adversary independent of the model's
author.

Deterministic, zero model calls.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gyza.containment.gyza_model import UNMODELLED, build_registries  # noqa: E402
from gyza.containment.reversibility import ReversibilityTable         # noqa: E402


@dataclass
class St:
    """Minimal state carrying every field a registered harm quantity reads."""
    owner: str = "A"
    entries: list = field(default_factory=list)
    active_holds: float = 0.0
    capital: float = 100.0
    authority_violations: tuple = ()
    # state the vocabulary touches that NO declared quantity reads:
    artifacts: int = 10
    envelopes: int = 0
    emitted: int = 0
    keys_rotated: int = 0
    guard_version: int = 1


class _Entry:
    """Stands in for a settled LedgerEntry the Wallet fold will count."""
    def __init__(self, frm, to, amt):
        self.from_compositor, self.to_compositor = frm, to
        self.amount_credits, self.settled = amt, True
        self.entry_id = f"{frm}-{to}-{amt}"
        self.from_signature = self.to_signature = "x"


# What each action type DOES. Authored here, and that is fine: the finding is
# about whether the declared HARM MODEL reads these effects, not about whether
# the semantics are the only possible ones.
def apply_action(s: St, kind: str) -> St:
    n = St(**{k: getattr(s, k) for k in s.__dataclass_fields__})
    n.entries = list(s.entries)
    if kind == "settle_credits":
        n.entries.append(_Entry("A", "B", 10.0))          # A pays out
    elif kind == "reserve_credits":
        n.active_holds = s.active_holds + 5.0
    elif kind == "delete_artifact":
        n.artifacts = s.artifacts - 1
    elif kind == "sign_envelope":
        n.envelopes = s.envelopes + 1
    elif kind in ("publish_agent", "send_message", "publish_delta",
                  "publish_attestation", "external_send",
                  "write_outside_sandbox"):
        n.emitted = s.emitted + 1
    elif kind == "rotate_key":
        n.keys_rotated = s.keys_rotated + 1
    elif kind == "update_guard_config":
        n.guard_version = s.guard_version + 1
    elif kind == "grant_delegation":
        n.authority_violations = s.authority_violations   # grant alone: no breach
    elif kind in ("stage_artifact", "stage_envelope"):
        n.artifacts = s.artifacts + 1
    # read / compute / retrieve_memory / claim_work_item: no modelled effect
    return n


NO_EFFECT = {"read", "compute", "retrieve_memory", "claim_work_item"}


def main() -> None:
    harm, _inv = build_registries()
    rev = ReversibilityTable()
    s0 = St()

    rows = []
    for kind in rev.vocabulary:
        s1 = apply_action(s0, kind)
        moved, errors = {}, {}
        for hc in harm:
            try:
                before, after = hc.measure(s0, s0), hc.measure(s0, s1)
            except Exception as e:                          # noqa: BLE001
                # An exception is an ERROR, not a harm movement. Counting it as
                # one reported 0 gaps -- the exact-zero artifact class.
                errors[hc.id] = f"{type(e).__name__}: {e}"
                continue
            if abs(after - before) > 1e-12:
                moved[hc.id] = round(after - before, 6)
        changes_state = (kind not in NO_EFFECT)
        rows.append({
            "action": kind,
            "reversibility": rev.classify(kind).value,
            "changes_state": changes_state,
            "harm_classes_that_move": moved,
            "harm_classes_that_ERRORED": errors,
            "UNMEASURED_GAP": bool(changes_state and not moved and not errors),
            "UNSCORABLE": bool(errors),
        })

    gaps = [r for r in rows if r["UNMEASURED_GAP"]]
    broken = [r for r in rows if r["UNSCORABLE"]]
    if broken:
        raise SystemExit(
            f"REFUSING TO REPORT: {len(broken)} action(s) could not be scored "
            f"because a harm quantity raised. A gap count computed over "
            f"erroring quantities is not a measurement. First: "
            f"{broken[0]['action']} -> {broken[0]['harm_classes_that_ERRORED']}")
    stateful = [r for r in rows if r["changes_state"]]
    out = {
        "soundness": ("one-directional: a gap found is DEFINITE; a gap not "
                      "found proves nothing (R12 UNSOUND)"),
        "n_action_types": len(rows),
        "n_changing_state": len(stateful),
        "n_unmeasured_gaps": len(gaps),
        "gap_fraction_of_stateful": round(len(gaps) / len(stateful), 4) if stateful else None,
        "declared_harm_classes": [c.id for c in harm],
        "declared_but_unmodelled": list(UNMODELLED),
        "gaps": [g["action"] for g in gaps],
        "rows": rows,
    }
    Path(__file__).with_name("unmeasured_actions.json").write_text(
        json.dumps(out, indent=1))

    print(f"action types: {out['n_action_types']}   "
          f"changing state: {out['n_changing_state']}   "
          f"UNMEASURED: {out['n_unmeasured_gaps']} "
          f"({out['gap_fraction_of_stateful']:.1%} of stateful actions)\n")
    print(f"{'action':26} {'reversibility':22} {'harm classes that move'}")
    print("-" * 78)
    for r in rows:
        if not r["changes_state"]:
            continue
        m = r["harm_classes_that_move"] or "**NONE — UNMEASURED**"
        print(f"{r['action']:26} {r['reversibility']:22} {m}")


if __name__ == "__main__":
    main()
