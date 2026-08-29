# Respecification 4 — two refusals, and a live underdetermination found in a PROOF-carried type

**Both parts refuse. Nothing was built. One real defect in my own census was found
and is corrected here.**

Zero credits. No production code changed.

---

## 0. The premise, checked first

The task states a prediction was committed at `f8e19a0` for a claim type
`envelope_chain_verified`, four parameters confirmed 4/4, and that
`verify_chain` accepts `require_signatures=False` with call sites at
`runner.py:2517` and `cli.py:1148`. Verified against the tree:

| cited | reality |
|---|---|
| commit `f8e19a0` | `fatal: Not a valid object name` |
| `envelope_chain_verified` | absent from all 28 branches |
| `require_signatures` | **zero occurrences in the entire tree** |
| `icp.py:709` | file is **621 lines** |
| `runner.py:2517` | file is **848 lines** |
| `cli.py:1148` | a bare `"""` |

**The criterion has had ZERO prospective uses, not two.**

**But the question underneath Part A is real**, and pursuing it found something.
*Is "the chain/DAG verified" underdetermined about which check ran?* The
hypothesised mechanism (`require_signatures`) does not exist. **A different one
does, and it is live.**

---

## 1. THE FINDING — `envelope_dag` is PROOF-carried and UNDERDETERMINED

`verify_dag` (`gyza/icp.py:217-221`) carries a real policy parameter with a
**permissive default**:

```python
def verify_dag(envelopes, *, require_closed: bool = False) -> DagVerification:
```

The registered verifier (`gyza/verification/adapters.py:30-33`) forwards
**arbitrary kwargs**:

```python
def _envelope_dag(envelopes, **kw) -> bool:
    res = verify_dag(envelopes, **kw)
```

**Production genuinely uses both policies:**

| call site | policy |
|---|---|
| `gyza/resilience.py:202` | `require_closed=False` — permissive |
| `gyza/audit.py:101` | `require_closed=<caller>`, **default `True`** |
| `gyza/verification/adapters.py:32` | **`**kw` — whatever the caller passes** |

> **So "the DAG verified" is two different claims with two different verdicts,
> and the claim records neither.** The registry marks `envelope_dag`
> **PROOF-carried**; the proof is of an unnamed policy.

### This corrects my own census, and the correction is named

`research/census/census.py:44` classifies `envelope_dag` as
**DECLARATIVE × INTERNAL, basis `inspection`**, with the note *"As above, DAG
form"* — classified **by analogy** to `envelope_chain` without examining that
`verify_dag` takes a policy argument production actually varies.

Applying the **frozen, unmodified** criterion:

- **Q2** — evaluable over stored state + fields **the claim itself names**?
  **No.** The claim names the envelopes; it does not name `require_closed`, and
  the two settings disagree.
- **Q3** — would naming a parameter fix that, without an outside fact? **Yes** —
  name the policy. → **UNDERDETERMINED**

**This is not criterion refinement. It is a misapplication I made**, and the
basis label `inspection` was itself wrong: the call required judgement I did not
perform.

**Impact on the census: NONE of the headline numbers move.** `envelope_dag` is
DECLARATIVE, and `f` is computed over the ASSERTIVE row.
`f(gyza, registered) = 2/7 = 0.2857` is unchanged; the DECLARATIVE row goes
10 INTERNAL → 9 INTERNAL + 1 UNDERDETERMINED. `FINDINGS_CLAIMS_CENSUS.md` is
committed and not edited; this is the correction of record.

---

## 2. PART A — the two gates

### A2, POWER GATE: **PASSES.** The divergence is real, not hypothetical.

`resilience.py:202` verifies with `require_closed=False`; `audit.py:101`
defaults to `True`. Two live production paths, opposite policies, same claim
text. A verifier that recomputed under the *wrong* policy would return a verdict
the producer never made — the D2 shape (*which metric is the arbiter*) at the
DAG boundary.

**The hypothesised `require_signatures` divergence does NOT exist** and could not
have served: there is no such parameter.

### A1, CONSUMER GATE: **FAILS.**

> **Nothing in production consumes any claim of any type.**
> `build_registries()` — the whole V-1 verifier surface — has **0 production
> callers and 14 test callers.**

There is no call site to name. To wire a consumer I would have to build the
consumer *and* its production entry point, which is the coordination layer, not
a respecification.

**The precedent is not theoretical:** send claims were written at 5 sites, read
at 0, paid a full BLAKE3 per send, and were removed. A DAG claim would be worse
— chain verification is on a hotter path.

### A3 DECISION: **RECORD AND STOP. Registry entry stays NONE… and `envelope_dag` stays PROOF.**

A design that would be correct if built, recorded so it is not re-derived:

| parameter | why it must be named |
|---|---|
| **verification policy** | `require_closed` — the live divergence above |
| **artifact policy** | `require_all_artifacts` (`audit.py:77`) — same shape, second flag |
| **DAG identity** | *which* envelope set — the movable reference set; pin by content-address (artifact #13) |
| **expected head** | a caller may know it; the claim does not record it |

**What would have to become true to justify building it:** a production caller of
`build_registries()`. That is the same blocker as every other claim type, and it
is not respecification's to solve.

---

## 3. PART B — the fourth selection, by the unchanged rule

**The NONE list** (`gyza/verification/adapters.py:178-181`) — unchanged, still two:

| # | type | producer | production call volume |
|---|---|---|---|
| 1 | `execution_output_content` | `AgentRunner` | **5 constructions** |
| 2 | `routing_match_quality` | `DemandOracle` | **0 constructions** |

**Rule (unmodified): highest production call volume, tie-broken by earliest
definition.** It selects `execution_output_content` — **already declined in
RESPEC-3** (EXOGENOUS, `8fd277b`). Per B1, skip to the next by the same rule
without re-litigating: **`routing_match_quality`.**

### B2/B3 — this is NOT a prospective use, and saying otherwise would be false

`routing_match_quality` was classified in the first census's Part C
retrodiction and again as index 18 of the Gyza vocabulary census
(**ASSERTIVE × EXOGENOUS**). Committing a "prediction" now would be recording an
answer I already hold. **No prediction commit was made.**

### B4 — the criterion returns **EXOGENOUS**. **REFUSED.**

The referent of *match **quality*** is a counterfactual — *which handler would
have succeeded*. Not stored state, and no parameter naming reaches it; you would
have to run the alternatives. R11 ROUTER-DEAD measured that the restated
property does not deliver even with an AUROC-1.000 oracle.

**And its producer never runs:** `DemandOracle` is injected into `supervisor.py`
and constructed **nowhere** in `gyza/`. Even were it respecifiable, there is
nothing to demonstrate against.

---

## 4. The honest triple, unchanged

| | |
|---|---|
| composable | **0.8333** (12 PROOF + 3 SPEC of 18) |
| emitted, production | **0.0000** |
| consumed, production | **0/0** — nothing is produced, so nothing can be consumed |

**Scope:** these are registry-wide figures. Nothing was emitted or consumed this
session because nothing was built.

## 5. What this session establishes

**Two refusals, on independent grounds** — one for lack of a consumer with the
power demonstration *passing*, one for exogeneity with the power demonstration
never reached.

> **B5's warning was the right one: "four builds in a row would be evidence of a
> loose gate, not a good method."** The gates fired. RESPEC-3 refused, RESPEC-4
> refuses twice.

**The one durable product is §1** — a live underdetermination in a type the
registry calls PROOF-carried, found by applying the criterion to a real code path
rather than to a claim's name. That correction stands independently of whether
anything is ever built on it.

## 6. Honest limits

1. **§1 is a classification correction, not a demonstrated failure.** No
   verification has *actually* disagreed across the two policies in production —
   `resilience.py` and `audit.py` verify different DAGs for different purposes.
   The claim is that the type **cannot express which check ran**, not that a
   wrong verdict has been observed.
2. **"Nothing consumes any claim" is static analysis** over `build_registries()`
   call sites. A reflective or dynamically-constructed registry would not appear.
   With 14 call sites all in `tests/`, I judge the risk low — **authored
   judgement.**
3. The census correction in §1 was **not** applied to `census.py`'s data table;
   that file is a committed result artifact. The correction lives here.
