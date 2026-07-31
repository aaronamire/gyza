"""SR-5 — promotion granularity. Deterministic, SEED=1, zero model calls."""
from __future__ import annotations
import json, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gyza.containment import (
    GuardEngine, HarmClass, HarmModelRegistry, Invariant, InvariantClass,
    InvariantRegistry, PromotionGate, StagingArea,
)

SEED = 1
N_ACTIONS = 240
BOUND = 100.0
VARIANTS = {"per-action": 1, "per-task": 4, "per-batch": 32}


class Bal:
    def __init__(self, total): self.total = total


def projector(events):
    return Bal(sum(e.payload.get("delta", 0.0) for e in events))


def engine():
    h = HarmModelRegistry()
    h.register(HarmClass(id="spend", description="credits spent",
                         quantity=lambda s0, s: float(s0.total - s.total),
                         frame="account", frame_mutable=False,
                         code_path="sr5"))
    h.load_bounds({"spend": BOUND})
    i = InvariantRegistry()
    i.register(Invariant(id="INV-spend", harm_class="spend",
                         cls=InvariantClass.CUMULATIVE, description="d"))
    return GuardEngine(h, i)


def workload():
    """Fixed across variants: identical action sequence, so any difference is
    the granularity and nothing else."""
    rng = random.Random(SEED)
    return [-rng.choice([2.0, 5.0, 9.0, 14.0]) for _ in range(N_ACTIONS)]


def run(k: int) -> dict:
    st = StagingArea(projector=projector)
    gate = PromotionGate(engine(), st)
    deltas = workload()
    promoted = rolled = attempts = refusals = 0
    peak = 0.0
    baseline_ref = 0.0

    pending = 0
    for idx, d in enumerate(deltas):
        # A refused batch consumed budget that a fresh baseline would not have;
        # model a run as a sequence of promotions from a moving checkpoint.
        st.stage("p", "stage_artifact", {"delta": d})
        pending += 1
        if pending < k and idx != len(deltas) - 1:
            continue
        attempts += 1
        before = st.watermark
        res = gate.promote()
        if res.promoted:
            promoted += pending
            if res.decision:
                peak = max(peak, max(res.decision.measured.values(), default=0.0))
        else:
            refusals += 1
            rolled += pending
            # The batch rolls back and the run CONTINUES. It is not reset: the
            # accounting period's budget is spent, so later batches refuse too.
            # (An earlier harness rebuilt the staging area here, which silently
            # granted a fresh budget per refusal -- the same frame error the
            # gate itself had.)
        pending = 0

    return {
        "k": k,
        "actions": len(deltas),
        "attempts": attempts,
        "refusals": refusals,
        "promoted_effective": promoted,
        "rolled_back": rolled,
        "effective_throughput": promoted / len(deltas),
        "nominal_admission": (promoted + rolled) / len(deltas),
        "escalation_rate": refusals / attempts if attempts else None,
        "gate_evals_per_promoted": (attempts / promoted) if promoted else float("inf"),
        "peak_harm_fraction_of_bound": peak / BOUND,
    }


def main():
    # FEASIBILITY CHECK (preregistered): the harness must produce refusals at
    # k=1, or effective throughput sits at its 1.0 ceiling for every variant and
    # the comparison is vacuous.
    probe = run(1)
    measurable = probe["refusals"] > 0
    rows = [run(k) for k in VARIANTS.values()]
    out = {"seed": SEED, "bound": BOUND, "n_actions": N_ACTIONS,
           "feasibility": {"refusals_at_k1": probe["refusals"],
                           "measurable": measurable},
           "variants": {name: r for name, r in zip(VARIANTS, rows)}}
    Path(__file__).with_name("sr5_result.json").write_text(json.dumps(out, indent=1))
    print(f"FEASIBILITY: refusals at k=1 = {probe['refusals']} -> "
          f"{'MEASURABLE' if measurable else 'NOT-MEASURABLE'}\n")
    hdr = f"{'variant':11} {'k':>3} {'effective':>10} {'nominal':>8} {'escal':>7} {'evals/prom':>11} {'peak/bound':>11}"
    print(hdr); print("-" * len(hdr))
    for name, r in zip(VARIANTS, rows):
        print(f"{name:11} {r['k']:>3} {r['effective_throughput']:>10.4f} "
              f"{r['nominal_admission']:>8.4f} {r['escalation_rate']:>7.3f} "
              f"{r['gate_evals_per_promoted']:>11.4f} "
              f"{r['peak_harm_fraction_of_bound']:>11.4f}")


if __name__ == "__main__":
    main()
