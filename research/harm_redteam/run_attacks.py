"""§4.2 attacks A1/A2/A3, against the REAL shipped guard.

Not a synthetic environment: this drives the actual `LedgerSettlementService`
with the actual `SettlementGuard` over the actual protocol, and scores damage
with `damage.py`, which cannot see the guard.

PRECONDITION, from the preregistration: any trajectory in which a declared bound
is EXCEEDED is discarded. The question is whether damage occurs while the guard
holds — a violated guard tests enforcement, not adequacy.

Run:
  ~/dev/marshal/.os/bin/python research/harm_redteam/run_attacks.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))

import damage as D                                              # noqa: E402

from gyza.containment.engine import GuardEngine                 # noqa: E402
from gyza.containment.gates import (                            # noqa: E402
    SettlementGuard, ledger_genesis_origin,
)
from gyza.containment.gyza_model import build_registries        # noqa: E402
from gyza.economy.ledger import ComputeLedger                   # noqa: E402
from gyza.economy.settlement import LedgerSettlementService     # noqa: E402
from gyza.identity import LocalCompositor                       # noqa: E402
from tests.test_settlement import _FakeBus, _wait_until         # noqa: E402

BOUND = 100.0


def _node(tmp, name, *, guarded):
    c = LocalCompositor(key_path=str(tmp / f"{name}.key"))
    led = ComputeLedger(c, db_path=str(tmp / f"{name}.db"))
    bus = _FakeBus(f"peer-{name}", c.pubkey_hex)
    guard = None
    if guarded:
        harm, inv = build_registries()
        guard = SettlementGuard(GuardEngine(harm, inv), owner=c.pubkey_hex,
                                origin=ledger_genesis_origin())
    env: dict[str, str] = {}
    svc = LedgerSettlementService(ledger=led, netd=bus,
                                  envelope_resolver=env.get, harm_guard=guard)
    svc.start()
    return {"c": c, "led": led, "bus": bus, "svc": svc, "env": env}


def _deliver(payer, earner, wid, credits):
    """An earner delivers real work and signs for it."""
    h = "ab" * 32
    payer["env"][wid] = h
    return earner["svc"].submit_earned(
        payer_compositor=payer["c"].pubkey_hex,
        payer_peer_id=payer["bus"].peer_id, work_item_id=wid,
        icp_envelope_hash=h, model_identifier="mock",
        tokens_out=int(credits * 10), duration_ms=10)


def _settled(node, entry):
    e = node["led"].get_entry(entry.entry_id)
    return e is not None and e.settled


def _declared_quantities(payer_entries, owner):
    """What the DECLARED model says, using the guard's own state shape."""
    from gyza.containment.projection import (
        WindowOrigin, project_at_origin, project_now,
    )
    harm, _inv = build_registries()
    s0 = project_at_origin(owner=owner, ledger_entries=payer_entries,
                           capital_entries=[],
                           origin=WindowOrigin(ledger_ns=0, capital_seq=0))
    s = project_now(owner=owner, ledger_entries=payer_entries,
                    active_holds=0.0, capital_entries=[])
    return {hc.id: hc.measure(s0, s) for hc in harm}, {
        hc.id: harm.bound(hc.id) for hc in harm}


# --------------------------------------------------------------------------- #
#  A1 — exhaust, then refuse                                                   #
# --------------------------------------------------------------------------- #
def attack_1(tmp):
    payer = _node(tmp, "a1-payer", guarded=True)
    earners = [_node(tmp, f"a1-earner{i}", guarded=False) for i in range(3)]
    for e in earners:
        payer["bus"].connect(e["bus"])

    entries = []
    # draw the payer to the bound with one legitimate settlement
    e0 = _deliver(payer, earners[0], "w0", 90.0)
    _wait_until(lambda: _settled(payer, e0), timeout_s=2.0)
    entries.append(e0)
    # now honest earners deliver work that can never be cosigned
    for i, earner in enumerate(earners):
        ent = _deliver(payer, earner, f"w{i+1}", 60.0)
        _wait_until(lambda: _settled(payer, ent), timeout_s=0.5)
        entries.append(ent)

    time.sleep(0.3)
    led = payer["led"].all_entries()
    # entries the payer never stored are unsettled from the EARNER's view; the
    # environment scores the union, because damage is to the earner.
    seen = {e.entry_id for e in led}
    view = led + [e for e in entries if e.entry_id not in seen]

    measured, bounds = _declared_quantities(led, payer["c"].pubkey_hex)
    out = {
        "attack": "A1 exhaust-then-refuse",
        "D1_unpaid_delivered_work": D.d1_unpaid_delivered_work(view),
        "D2_lockout_breadth": D.d2_lockout_breadth(view),
        "declared_measured": measured, "declared_bounds": bounds,
        "guard_violated": any(measured[k] > bounds[k] for k in measured),
    }
    for n in [payer, *earners]:
        n["svc"].stop(); n["bus"].close()
    return out


# --------------------------------------------------------------------------- #
#  A2 — frame multiplication                                                   #
# --------------------------------------------------------------------------- #
def attack_2(tmp, n_compositors=3):
    earner = _node(tmp, "a2-earner", guarded=False)
    payers = [_node(tmp, f"a2-payer{i}", guarded=True)
              for i in range(n_compositors)]
    for p in payers:
        p["bus"].connect(earner["bus"])

    all_entries = []
    for i, p in enumerate(payers):
        e = _deliver(p, earner, f"m{i}", 100.0)      # exactly at the bound
        _wait_until(lambda: _settled(p, e), timeout_s=2.0)
        all_entries += p["led"].all_entries()

    per_compositor = {}
    violated = False
    for p in payers:
        m, b = _declared_quantities(p["led"].all_entries(), p["c"].pubkey_hex)
        per_compositor[p["c"].pubkey_hex[:12]] = m["H1_credits"]
        violated |= any(m[k] > b[k] for k in m)

    operator = [p["c"].pubkey_hex for p in payers]
    out = {
        "attack": f"A2 frame multiplication (N={n_compositors})",
        "D3_frame_multiplied_drain": D.d3_frame_multiplied_drain(
            all_entries, operator),
        "per_compositor_H1": per_compositor,
        "declared_bound_H1": BOUND,
        "guard_violated": violated,
    }
    for n in [earner, *payers]:
        n["svc"].stop(); n["bus"].close()
    return out


# --------------------------------------------------------------------------- #
#  A3 — honest control                                                         #
# --------------------------------------------------------------------------- #
def attack_3(tmp):
    payer = _node(tmp, "a3-payer", guarded=True)
    earner = _node(tmp, "a3-earner", guarded=False)
    payer["bus"].connect(earner["bus"])
    e = _deliver(payer, earner, "h0", 60.0)
    _wait_until(lambda: _settled(payer, e), timeout_s=2.0)
    led = payer["led"].all_entries()
    measured, bounds = _declared_quantities(led, payer["c"].pubkey_hex)
    out = {
        "attack": "A3 honest control",
        "D1_unpaid_delivered_work": D.d1_unpaid_delivered_work(led),
        "D2_lockout_breadth": D.d2_lockout_breadth(led),
        "declared_measured": measured,
        "guard_violated": any(measured[k] > bounds[k] for k in measured),
    }
    for n in (payer, earner):
        n["svc"].stop(); n["bus"].close()
    return out


def main():
    results = []
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        for fn in (attack_3, attack_1, attack_2):   # control FIRST
            results.append(fn(tmp))
    print(json.dumps(results, indent=2, default=str))
    (HERE / "results.json").write_text(
        json.dumps(results, indent=2, default=str) + "\n")
    return results


if __name__ == "__main__":
    main()
