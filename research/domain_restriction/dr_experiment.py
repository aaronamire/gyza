"""Route DR — domain restriction vs the general architecture.

Runs exactly PREREGISTRATION_DR.md (sha256 225add96...), committed before any
result. Deterministic, SEED = 1, ZERO model calls -- semantic ground truth is
reused from `research/corpus/stochastic.json` (K=5 at T=0.7, MBPP asserts
RE-EXECUTED, external to this program).

GATE 0b. Every verifier is imported from `gyza.verification.adapters`, which
pre-exists this route. Nothing here authors a verifier.
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from gyza.canon import values_equal                                  # noqa: E402
from gyza.verification.adapters import (                             # noqa: E402
    HUMAN_SPECS, NATIVE, NO_VERIFIER,
)

SEED = 1
DEPTHS = (1, 2, 4, 8)
FAULT_RATES = (0.00, 0.05, 0.20)
N_TASKS = 4000
COMPOSING = ("PROOF", "SPEC")          # SR-3: TEST scores 0.000 and does not compose


def vocabulary() -> dict[str, str]:
    """claim_type -> carrier, read from the SHIPPED registry, never redeclared."""
    v: dict[str, str] = {}
    for x in NATIVE:
        v[x.claim_type] = x.carrier
    for s in HUMAN_SPECS:
        v[s.claim_type] = "SPEC"
    for n in NO_VERIFIER:
        v[n] = "NONE"
    return v


def semantic_outcomes() -> list[bool]:
    """The MEASURED reliability of a semantic step: every per-sample outcome
    from the corpus's stochastic arm, executed against MBPP's own asserts.

    Errors were recorded as None there and are EXCLUDED here -- an error is not
    a failed sample.
    """
    st = json.loads((ROOT / "research/corpus/stochastic.json").read_text())
    return [o for r in st["records"] for o in r["per_sample_outcome"]
            if o is not None]


@dataclass
class ArmResult:
    arm: str
    depth: int
    fault_rate: float
    n_total: int = 0
    n_attempted: int = 0
    n_refused: int = 0
    n_correct: int = 0
    n_caught: int = 0            # wrong AND detected (chain aborted, not output)
    n_silent_wrong: int = 0      # wrong AND undetected -- the dangerous cell
    steps_by_carrier: dict = field(default_factory=dict)

    def as_dict(self):
        d = dict(self.__dict__)
        d["coverage"] = self.n_attempted / self.n_total if self.n_total else None
        d["correctness_on_attempted"] = (
            self.n_correct / self.n_attempted if self.n_attempted else None)
        d["useful_work"] = (
            (d["coverage"] or 0.0) * (d["correctness_on_attempted"] or 0.0))
        return d


def run_arm(arm: str, depth: int, f: float, vocab: dict[str, str],
            sem: list[bool], n_tasks: int = N_TASKS) -> ArmResult:
    rng = random.Random(SEED)
    types = sorted(vocab)
    res = ArmResult(arm, depth, f, n_total=n_tasks)
    admits = {"GENERAL": lambda c: True,
              "RESTRICTED": lambda c: c in COMPOSING,
              "RESTRICTED_PROOF_ONLY": lambda c: c == "PROOF"}[arm]

    for _ in range(n_tasks):
        chain = [rng.choice(types) for _ in range(depth)]
        carriers = [vocab[t] for t in chain]
        for c in carriers:
            res.steps_by_carrier[c] = res.steps_by_carrier.get(c, 0) + 1

        if not all(admits(c) for c in carriers):
            res.n_refused += 1
            continue                      # REFUSED: no output, not a failure

        res.n_attempted += 1
        ok, detected = True, False
        for c in carriers:
            if c == "NONE":
                # semantic step: real MBPP sample, no verifier to catch it
                if not rng.choice(sem):
                    ok = False            # wrong, and NOTHING detects it
            else:
                # mechanical step: fault injected at rate f, verifier is exact
                if rng.random() < f:
                    ok = False
                    detected = True       # the registered verifier catches it
        if ok:
            res.n_correct += 1
        elif detected:
            res.n_caught += 1
        else:
            res.n_silent_wrong += 1
    return res


def main():
    vocab = vocabulary()
    sem = semantic_outcomes()
    cells = []
    for f in FAULT_RATES:
        for depth in DEPTHS:
            for arm in ("GENERAL", "RESTRICTED", "RESTRICTED_PROOF_ONLY"):
                cells.append(run_arm(arm, depth, f, vocab, sem).as_dict())

    # crossover: smallest depth at which RESTRICTED useful work >= GENERAL's
    cross = {}
    for f in FAULT_RATES:
        c = None
        for depth in DEPTHS:
            g = next(x for x in cells if x["arm"] == "GENERAL"
                     and x["depth"] == depth and values_equal(x["fault_rate"], f))
            r = next(x for x in cells if x["arm"] == "RESTRICTED"
                     and x["depth"] == depth and values_equal(x["fault_rate"], f))
            if r["useful_work"] >= g["useful_work"]:
                c = depth
                break
        cross[str(f)] = c

    out = {
        "preregistration_sha256":
            "225add96d0abf16ba43c7e9b7c6d31eb4a87396071f0ab8bd85f86f813bdbf15",
        "seed": SEED, "n_tasks_per_cell": N_TASKS,
        "vocabulary": vocab,
        "vocabulary_composition": {
            c: sum(1 for v in vocab.values() if v == c)
            for c in ("PROOF", "SPEC", "TEST", "NONE")},
        "semantic_reliability_measured": sum(sem) / len(sem),
        "n_semantic_samples": len(sem),
        "crossover_depth_useful_work": cross,
        "cells": cells,
    }
    (HERE / "dr_result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "cells"}, indent=1))
    return out


if __name__ == "__main__":
    main()
