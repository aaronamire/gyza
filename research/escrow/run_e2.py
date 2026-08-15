"""E2 — does escrow convert a TRANSFERS class into an EXTINGUISHES one?

THE FINDING UNDER TEST. `HARM-IS-TRANSFERRED`: a bound reached means the guard
refuses, but *the earner has already done the work*, so 180 credits of prevented
drawdown became 180 credits of unpaid delivered work. R-B1 attributes that to
conservation -- reducing a conserved quantity inside a frame raises it outside.

THE CLAIM. Escrow does not violate conservation; it changes WHEN allocation
happens. Commit funds BEFORE commissioning, and the state "work performed,
payment refused" is unreachable.

REAL RIG, not a simulation: the actual `LedgerSettlementService` over the actual
protocol, scored by `harm_redteam/damage.py`, which cannot see any guard.

Run:  ~/dev/marshal/.os/bin/python research/escrow/run_e2.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harm_redteam"))
sys.path.insert(0, str(HERE.parent.parent))

import damage as D                                              # noqa: E402

from gyza.containment.engine import GuardEngine                 # noqa: E402
from gyza.containment.gates import (                            # noqa: E402
    SettlementGuard, ledger_genesis_origin,
)
from gyza.containment.harm import HarmClass                     # noqa: E402
from gyza.containment.invariants import (                       # noqa: E402
    Invariant, InvariantClass,
)
from gyza.containment.gyza_model import build_registries        # noqa: E402
from gyza.economy.ledger import ComputeLedger                   # noqa: E402
from gyza.economy.settlement import LedgerSettlementService     # noqa: E402
from gyza.economy.wallet import Wallet                          # noqa: E402
from gyza.identity import LocalCompositor                       # noqa: E402
from tests.test_settlement import _FakeBus, _wait_until         # noqa: E402

# THE EXPERIMENT DECLARES ITS OWN BOUND AND ITS OWN CLASS. H1_credits was
# RETIRED in production on 2026-08-15 -- its level refused every real model's
# first action -- and `SettlementGuard` now refuses to construct against an
# unregistered class, which is the correct behaviour and is why this route
# cannot simply reuse it. Resurrecting H1 to make the rig run would make the
# retirement cosmetic, so E2 registers a research-local class instead and never
# touches `guard_bounds.json`.
BOUND = 100.0
ITEM = 20.0
N_ITEMS = 9          # 180 credits of demand against a 100-credit bound
E2_CLASS = "E2_drawdown"


def _e2_drawdown(s0, s) -> float:
    """Net credits out of the owner's frame, folded from ledger entries.

    Deliberately NOT `damage.drawdown`: the guard and the damage measure must
    not share a fold, or a defect in the fold moves both together and the
    comparison is vacuous. This one folds through the production `Wallet`, which
    is what the shipped gate would use; `damage.py` does its own arithmetic.
    """
    # `Credits` is integer MICRO-credits and is deliberately not float-able, so
    # unit confusion is unrepresentable. Converting through `.micros` is the
    # canonicalisation this comparison requires -- and a raw `float(Credits)`
    # raised inside the quantity function, which the guard reported through the
    # SAME channel as a bound breach. The resulting table was byte-identical to
    # the previous broken run. Two different errors, one identical reassuring
    # number: that is why the error channel must never carry a measurement.
    return (Wallet(s0.entries).net_balance(s0.owner).micros
            - Wallet(s.entries).net_balance(s.owner).micros) / 1_000_000.0


def _guarded_registry():
    harm, inv = build_registries()
    harm.register(HarmClass(
        id=E2_CLASS,
        description="net settled credits out of the payer's frame",
        quantity=_e2_drawdown,
        frame="compositor pubkey",
        frame_mutable=False,
        code_path="research/escrow/run_e2.py"))
    harm.load_bounds({E2_CLASS: BOUND})
    # WITHOUT THIS THE GUARD REFUSES EVERYTHING, and the first E2 run did
    # exactly that: `no registered invariant (C4)` came back through the same
    # channel as a bound breach, so a broken guard scored the control at a
    # perfect-looking 180.0. AN ERROR IS NOT A VALUE -- and the error read as
    # the reassuring result, which is the direction that does not get
    # questioned. Both arms of that run were discarded.
    inv.register(Invariant(
        id="INV-E2-drawdown",
        harm_class=E2_CLASS,
        cls=InvariantClass.CUMULATIVE,
        description=("settled net outflow stays within the declared bound; "
                     "CUMULATIVE, so valid only at the settlement "
                     "serialization point (C7)."),
    ))
    return harm, inv


def _node(tmp, name, *, guarded: bool):
    c = LocalCompositor(key_path=str(tmp / f"{name}.key"))
    led = ComputeLedger(c, db_path=str(tmp / f"{name}.db"))
    bus = _FakeBus(f"peer-{name}", c.pubkey_hex)
    guard = None
    if guarded:
        harm, inv = _guarded_registry()
        guard = SettlementGuard(GuardEngine(harm, inv), owner=c.pubkey_hex,
                                origin=ledger_genesis_origin(),
                                harm_class=E2_CLASS)
    env: dict[str, str] = {}
    svc = LedgerSettlementService(ledger=led, netd=bus,
                                  envelope_resolver=env.get,
                                  harm_guard=guard, harm_enforce=True)
    svc.start()
    return {"c": c, "led": led, "bus": bus, "svc": svc, "env": env}


def _deliver(payer, earner, wid, credits):
    """The earner performs the work and SIGNS for it. Past this point the work
    is done: any later refusal cannot un-perform it, which is the entire
    mechanism HARM-IS-TRANSFERRED describes."""
    h = "ab" * 32
    payer["env"][wid] = h
    return earner["svc"].submit_earned(
        payer_compositor=payer["c"].pubkey_hex,
        payer_peer_id=payer["bus"].peer_id, work_item_id=wid,
        icp_envelope_hash=h, model_identifier="mock",
        tokens_out=int(credits * 10), duration_ms=10)


def _entries(node):
    return list(node["led"].all_entries())


# --------------------------------------------------------------------------- #
#  CONTROL — no escrow: commission, deliver, THEN discover the bound           #
# --------------------------------------------------------------------------- #
def control(tmp) -> dict:
    """Commission everything, discover the bound at payment time.

    Settlement is AUTOMATIC: `submit_earned` signs as earner and the payer's
    service cosigns, with the guard sitting on that cosign. So the refusal
    necessarily lands AFTER the work exists -- which is not a flaw in the rig,
    it is the shape of the finding.
    """
    payer = _node(tmp / "c", "payer", guarded=True)
    earner = _node(tmp / "c", "earner", guarded=False)
    payer["bus"].connect(earner["bus"])

    delivered = []
    for i in range(N_ITEMS):
        e = _deliver(payer, earner, f"w{i}", ITEM)
        delivered.append(e)
        _wait_until(lambda: _is_settled(earner, e), timeout_s=1.0)

    ents = _entries(earner)
    settled = sum(x.amount_credits for x in ents if x.settled)
    r = _score(ents, payer["c"].pubkey_hex, escrowed=0.0, spent=settled,
               forgone=0, arm="control")
    r["refusals"] = len(payer["svc"].harm_records)
    for n in (payer, earner):
        n["svc"].stop(); n["bus"].close()
    return r


# --------------------------------------------------------------------------- #
#  ESCROW — funds committed BEFORE the work is commissioned                    #
# --------------------------------------------------------------------------- #
def escrow_batched(tmp, batch: int, tag: str) -> dict:
    """Escrow a BATCH up front, then commission against it.

    WHY THIS EXISTS. The serial arm below holds at most one item's funds at a
    time, so it measured `peak_idle_escrow` at 20% and missed P-E2b's 25% bar --
    but that 20% is a property of the RIG (one item in flight), not of escrow.
    Reporting it as escrow's price would be measuring the instrument. Escrow's
    price is the capital committed against work not yet done, so it is a
    function of how much work you want in flight, and that is what this varies.
    """
    payer = _node(tmp / tag, "payer", guarded=True)
    earner = _node(tmp / tag, "earner", guarded=False)
    payer["bus"].connect(earner["bus"])

    spent = 0.0
    forgone = 0
    peak_idle = 0.0
    i = 0
    while i < N_ITEMS:
        # fund a batch: as many items as both the batch size and the remaining
        # headroom allow. Nothing is commissioned that is not already funded.
        room = int((BOUND - spent) // ITEM)
        n = min(batch, room, N_ITEMS - i)
        if n <= 0:
            forgone += N_ITEMS - i
            break
        held = n * ITEM
        peak_idle = max(peak_idle, held)
        for _ in range(n):
            e = _deliver(payer, earner, f"w{i}", ITEM)
            _wait_until(lambda: _is_settled(earner, e), timeout_s=1.0)
            held -= ITEM
            spent += ITEM
            i += 1

    ents = _entries(earner)
    r = _score(ents, payer["c"].pubkey_hex, escrowed=peak_idle,
               spent=sum(x.amount_credits for x in ents if x.settled),
               forgone=forgone, arm=f"escrow(batch={batch})")
    r["mean_idle_escrow"] = peak_idle
    r["refusals"] = len(payer["svc"].harm_records)
    for n_ in (payer, earner):
        n_["svc"].stop(); n_["bus"].close()
    return r


def escrow(tmp) -> dict:
    """Funds committed BEFORE the work is commissioned.

    The settlement guard is still installed and still enforcing -- identical to
    the control. The ONLY difference is the pre-commission check. If escrow is
    doing the work claimed for it, the settlement guard never fires: it has
    nothing left to refuse.
    """
    payer = _node(tmp / "e", "payer", guarded=True)
    earner = _node(tmp / "e", "earner", guarded=False)
    payer["bus"].connect(earner["bus"])

    held = spent = 0.0
    forgone = 0
    idle_samples: list[float] = []
    for i in range(N_ITEMS):
        # THE GATE MOVES EARLIER. Nothing is commissioned that is not funded,
        # so no earner ever performs work whose payment can be refused.
        if held + spent + ITEM > BOUND:
            forgone += 1
            idle_samples.append(held)
            continue
        held += ITEM                       # committed, unspent -> IDLE CAPITAL
        idle_samples.append(held)
        e = _deliver(payer, earner, f"w{i}", ITEM)
        _wait_until(lambda: _is_settled(earner, e), timeout_s=1.0)
        held -= ITEM
        spent += ITEM

    ents = _entries(earner)
    r = _score(ents, payer["c"].pubkey_hex, escrowed=max(idle_samples or [0.0]),
               spent=sum(x.amount_credits for x in ents if x.settled),
               forgone=forgone, arm="escrow")
    r["mean_idle_escrow"] = sum(idle_samples) / len(idle_samples)
    r["refusals"] = len(payer["svc"].harm_records)
    for n in (payer, earner):
        n["svc"].stop(); n["bus"].close()
    return r


def _is_settled(node, entry) -> bool:
    e = node["led"].get_entry(entry.entry_id)
    return e is not None and e.settled


def _score(ents, payer_pk, *, escrowed, spent, forgone, arm) -> dict:
    return {
        "arm": arm,
        "unpaid_delivered_work": D.d1_unpaid_delivered_work(ents),
        "lockout_breadth": D.d2_lockout_breadth(ents),
        "drawdown": D.drawdown(ents, payer_pk),
        "settled_credits": spent,
        "peak_idle_escrow": escrowed,
        # NOT PREREGISTERED, and disclosed as such. Standing rule #3 requires
        # the counter-metric beside the headline, and without this one "unpaid
        # went to zero" reads as pure gain. Escrow does not make the earner
        # whole -- it stops the work from being commissioned at all.
        "forgone_commissions": forgone,
        "forgone_credits": forgone * ITEM,
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for d in ("c", "e", "b2", "b5"):
            (tmp / d).mkdir()
        ctl = control(tmp)
        esc = escrow(tmp)
        batched = [escrow_batched(tmp, 2, "b2"), escrow_batched(tmp, 5, "b5")]

    rows = [ctl, esc, *batched]
    keys = ["unpaid_delivered_work", "lockout_breadth", "drawdown",
            "settled_credits", "peak_idle_escrow", "forgone_commissions",
            "forgone_credits"]
    print(f"E2 — bound {BOUND}, {N_ITEMS} items x {ITEM} = "
          f"{N_ITEMS * ITEM} credits of demand\n")
    print(f"{'measure':>24s}{'control':>12s}{'escrow':>12s}")
    print("-" * 48)
    for k in keys:
        print(f"{k:>24s}{ctl[k]:12.1f}{esc[k]:12.1f}")
    print(f"{'mean_idle_escrow':>24s}{0.0:12.1f}"
          f"{esc.get('mean_idle_escrow', 0.0):12.1f}")

    print("\nDECISION RULES")
    e2 = esc["unpaid_delivered_work"] == 0.0 and esc["drawdown"] <= BOUND
    ctlok = ctl["unpaid_delivered_work"] > 0
    print(f"  E2-CONTROL  unpaid > 0 without escrow: "
          f"{ctl['unpaid_delivered_work']:.1f} -> {'PASS' if ctlok else 'FAIL'}")
    print(f"  E2-EXTINGUISHES  unpaid == 0 with escrow and drawdown bounded: "
          f"{'PASS' if e2 else 'FAIL'}")
    print("  E2-PRICE  peak idle escrow, as a function of work in flight "
          "(P-E2b predicted >= 25% of the bound):")
    for r in [esc, *batched]:
        print(f"      {r['arm']:>18s}  {r['peak_idle_escrow']:6.1f} "
              f"({r['peak_idle_escrow'] / BOUND * 100:5.1f}% of bound)  "
              f"unpaid={r['unpaid_delivered_work']:.1f}")
    print(f"\n  COUNTER-METRIC (not preregistered): "
          f"{esc['forgone_credits']:.1f} credits of work never commissioned "
          f"— the same 80 credits the control leaves UNPAID.")

    (HERE / "e2_result.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
