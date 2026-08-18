# Correction — R-M1's INFEASIBLE cells were a scan artifact

**`research/margin/FINDINGS.md` stands unedited**, per the practice this corpus
follows. This document carries the correction; `research/CORRECTIONS.md` indexes
it. Found while building R-H1, by a test written to assert the opposite pole
existed.

---

## 1. What was claimed

R-M1 reported **INFEASIBLE** — "no margin below the feasibility ceiling is safe"
— in four cells, and built a headline on it:

> `MARGIN-GROWS-WITH-M-AND-RUNS-OUT` … *"At ε = 4, or with 4 agents per
> principal, **no margin suffices** at M = 512. The box empties before it
> becomes sound."*

## 2. What is actually true

The δ scan stepped by `COARSE = 1/40` from 0 while `delta < ceiling`. Against a
ceiling of **0.5980** the last point tested is **0.575**; the next stride lands
at 0.600, the loop exits, and the cell is declared INFEASIBLE — **without
(0.575, 0.598) ever being tested.**

Every affected cell is safe inside that untested gap:

| cell | ceiling | published | measured |
|---|---|---|---|
| M=512, ε=4, n=1 | 0.5980 | INFEASIBLE | **safe at 0.590** |
| M=512, ε=1, n=4 | 0.5980 | INFEASIBLE | **safe at 0.595** |
| M=512, ε=2, n=4 | 0.5980 | INFEASIBLE | **safe at 0.595** |
| M=512, ε=4, n=4 | 0.5980 | INFEASIBLE | **safe at 0.595** |

## 3. What survives, and what does not

**SURVIVES — M-GROWTH.** δ\* rising 0.130 → 0.280 → 0.295 (ε=1) and 0.190 →
0.480 → 0.480 (ε=2) is unaffected; those cells were found well inside the grid.

**SURVIVES — the step function, the cost analysis, the closed form's failure,
every control** (P-M0, monotonicity over 48 cells, duration to 1000 rounds, seed
robustness). None of them touched the ceiling region.

**DOES NOT SURVIVE — "and runs out".** The margin does **not** run out. It
approaches the ceiling asymptotically: at ε = 4, M = 512 it needs **99.2%** of
every margin the box can give. That is a real and severe cost, and it is a
**different, weaker claim than infeasibility** — "you must spend essentially all
of it" is not "no amount is enough."

The corrected headline is `MARGIN-GROWS-WITH-M-AND-APPROACHES-THE-CEILING`.

## 4. The species, and why it is not the same as the earlier ones

This is **not** a feasibility-ceiling defect of the kind standing rule #4
addresses — the ceiling was computed correctly, stated in advance, and used. It
is a **search-coverage** defect: a correct bound, a correct rule, and a scan that
did not cover the interval the rule ranged over.

> **A negative verdict must be established over the whole admissible range, not
> over the part a stride happened to land on.**

R-M1's own §5 lists "monotonicity of violations in δ verified over 48 cells" as
a control. It was — but monotonicity says nothing about coverage, and the two
were treated as if the first implied the second. Monotonicity in fact makes this
*worse*: under a monotone response, the existence of a safe point at 0.590
guarantees safety everywhere above it, so the untested interval was the one
region where a positive result was most likely.

**The fix**, applied in `research/hierarchy/run_tree.py`, refines downward from
the ceiling at fine resolution before returning INFEASIBLE.
