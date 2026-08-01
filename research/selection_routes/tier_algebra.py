"""
SR-3 — tier algebra over GYZA'S OWN claim types. Deterministic, SEED=1,
zero model calls.

Stage kinds are drawn from the R14 Part C enumeration of Gyza's action
vocabulary. Each carries a TIER, an invariant CLASS, and a CARRIER -- the kind
of evidence its per-stage check rests on:

  PROOF  the check RECOMPUTES the property (a signature, a content address).
         Sound for all inputs.
  TEST   the check runs a FINITE test suite. Sound only on the sampled inputs.
  SPEC   the check runs a registered partial property.
  NONE   no correctness claim (tier 3).

The carrier is the variable H1/H2 are about, and it is deliberately orthogonal
to the tier: `tested_transform` is tier 1 (a mechanical check exists) but
TEST-carried, which is exactly the case H2 predicts will degrade.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

SEED = 1
PER_STAGE_SPEND_MAX = 2.0
E2E_SPEND_BUDGET = 4.0          # tighter than 3 x per-stage: the C7 gap
REAL_INPUT = 50                 # the pipeline's actual payload
TEST_SUITE = ((1, 2), (2, 4), (3, 6))   # tested_transform's finite sample


def _h(b: bytes) -> str:
    return hashlib.blake2b(b, digest_size=16).hexdigest()


def new_state(payload: int = REAL_INPUT) -> dict:
    return {"payload": payload, "chain": [], "artifacts": {}, "spend": 0.0,
            "hlc": 0, "origin_payload": payload}


@dataclass
class Stage:
    name: str
    tier: int
    cls: str            # CONSERVATION | MONOTONE | CUMULATIVE | NONE
    carrier: str        # PROOF | TEST | SPEC | NONE
    apply: Callable[[dict], dict]
    check: Callable[[dict, dict], bool]


# --------------------------------------------------------------------------- #
#  Stage implementations                                                       #
# --------------------------------------------------------------------------- #
def _sign(s):
    s = dict(s, chain=list(s["chain"]))
    prev = s["chain"][-1] if s["chain"] else "genesis"
    s["chain"].append(_h(f"{prev}|{s['payload']}".encode()))
    return s


def _sign_check(a, b):
    """PROOF: recompute the linkage. Sound for every input."""
    if len(b["chain"]) != len(a["chain"]) + 1:
        return False
    prev = a["chain"][-1] if a["chain"] else "genesis"
    return b["chain"][-1] == _h(f"{prev}|{a['payload']}".encode())


def _store(s):
    s = dict(s, artifacts=dict(s["artifacts"]))
    data = str(s["payload"]).encode()
    s["artifacts"][_h(data)] = data
    return s


def _store_check(a, b):
    """PROOF: recompute every content address."""
    return all(k == _h(v) for k, v in b["artifacts"].items())


def _settle(s):
    return dict(s, spend=s["spend"] + 1.0)


def _settle_check(a, b):
    """The per-stage share of a global budget -- the ONLY thing a local check
    can express about a cumulative quantity."""
    return (b["spend"] - a["spend"]) <= PER_STAGE_SPEND_MAX


def _hlc(s):
    return dict(s, hlc=s["hlc"] + 1)


def _hlc_check(a, b):
    return b["hlc"] >= a["hlc"]


def _tested(s):
    return dict(s, payload=s["payload"] * 2)


def _tested_check(a, b):
    """TEST: a FINITE sample. Sound only where it sampled."""
    return all(_tested({"payload": x, **{k: v for k, v in a.items()
                                          if k != "payload"}})["payload"] == y
               for x, y in TEST_SUITE)


def _output(s):
    return dict(s, payload=s["payload"])


STAGES: dict[str, Stage] = {
    "sign_envelope": Stage("sign_envelope", 1, "MONOTONE", "PROOF", _sign, _sign_check),
    "store_artifact": Stage("store_artifact", 1, "CONSERVATION", "PROOF", _store, _store_check),
    "settle_credits": Stage("settle_credits", 1, "CUMULATIVE", "PROOF", _settle, _settle_check),
    "hlc_stamp": Stage("hlc_stamp", 2, "MONOTONE", "SPEC", _hlc, _hlc_check),
    "tested_transform": Stage("tested_transform", 1, "CONSERVATION", "TEST", _tested, _tested_check),
    "produce_output": Stage("produce_output", 3, "NONE", "NONE", _output, lambda a, b: True),
}


# --------------------------------------------------------------------------- #
#  Single-stage mutations                                                      #
# --------------------------------------------------------------------------- #
def _mut_sign(s):
    s = _sign(s)
    s["chain"] = s["chain"][:-1] + ["forged" + s["chain"][-1][6:]]
    return s


def _mut_store(s):
    s = _store(s)
    k = next(iter(s["artifacts"]))
    s["artifacts"][k] = b"tampered"
    return s


def _mut_settle(s):
    """Stays INSIDE the per-stage allowance (2.0 <= 2.0) while pushing the
    3-stage total to 6 against a budget of 4. The gap is unobservable locally
    BY DEFINITION -- this cell is definitional, not measured."""
    return dict(s, spend=s["spend"] + 2.0)


def _mut_hlc(s):
    return dict(s, hlc=s["hlc"] - 1)


def _mut_tested(s):
    """Correct on every sampled input, wrong on the pipeline's real one.
    This is H2's construction and it is MEASURED: the mutation is caught by no
    test in the suite, so a finite-sample check cannot see it."""
    x = s["payload"]
    return dict(s, payload=x * 2 if x < 10 else x * 3)


MUTATIONS: dict[str, Callable[[dict], dict]] = {
    "sign_envelope": _mut_sign,
    "store_artifact": _mut_store,
    "settle_credits": _mut_settle,
    "hlc_stamp": _mut_hlc,
    "tested_transform": _mut_tested,
    "produce_output": lambda s: dict(s, payload=s["payload"] + 1),
}


# --------------------------------------------------------------------------- #
#  End-to-end properties                                                       #
# --------------------------------------------------------------------------- #
def e2e_holds(pipeline: list[str], s0: dict, sN: dict) -> bool:
    """The conjunction of the class properties the pipeline actually claims."""
    classes = {STAGES[n].cls for n in pipeline}
    if "MONOTONE" in classes:
        if sN["hlc"] < s0["hlc"]:
            return False
        prev = "genesis"
        cur = dict(s0)
        for name in pipeline:                      # replay the honest chain
            if name == "sign_envelope":
                expect = _h(f"{prev}|{cur['payload']}".encode())
                idx = len([x for x in pipeline[:pipeline.index(name) + 1]])
                if expect not in sN["chain"]:
                    return False
                prev = expect
            cur = STAGES[name].apply(cur)
    if "CONSERVATION" in classes:
        if any(k != _h(v) for k, v in sN["artifacts"].items()):
            return False
        if "tested_transform" in pipeline:
            expect = s0["payload"] * (2 ** pipeline.count("tested_transform"))
            if sN["payload"] != expect:
                return False
    if "CUMULATIVE" in classes:
        if (sN["spend"] - s0["spend"]) > E2E_SPEND_BUDGET:
            return False
    return True


def run(pipeline: list[str], mutate_at: int | None = None) -> tuple[dict, dict, bool]:
    """Returns (s0, sN, per_stage_conjunction_accepts)."""
    s0 = new_state()
    cur = s0
    ok = True
    for i, name in enumerate(pipeline):
        st = STAGES[name]
        nxt = MUTATIONS[name](cur) if i == mutate_at else st.apply(cur)
        if not st.check(cur, nxt):
            ok = False
        cur = nxt
    return s0, cur, ok


# --------------------------------------------------------------------------- #
#  12 pipelines over Gyza claim types                                          #
# --------------------------------------------------------------------------- #
PIPELINES: list[list[str]] = [
    ["sign_envelope", "store_artifact", "sign_envelope"],          # 1,1,1 proof
    ["store_artifact", "sign_envelope", "store_artifact"],         # 1,1,1 proof
    ["sign_envelope", "sign_envelope", "sign_envelope"],           # 1,1,1 proof
    ["settle_credits", "settle_credits", "settle_credits"],        # 1,1,1 cumulative
    ["sign_envelope", "settle_credits", "store_artifact"],         # 1,1,1 mixed cls
    ["settle_credits", "store_artifact", "settle_credits"],        # 1,1,1 mixed cls
    ["tested_transform", "sign_envelope", "store_artifact"],       # 1(test),1,1
    ["sign_envelope", "tested_transform", "store_artifact"],       # 1,1(test),1
    ["tested_transform", "tested_transform", "sign_envelope"],     # test,test,1
    ["hlc_stamp", "sign_envelope", "store_artifact"],              # 2,1,1
    ["sign_envelope", "hlc_stamp", "produce_output"],              # 1,2,3
    ["sign_envelope", "store_artifact", "produce_output"],         # 1,1,3
]
