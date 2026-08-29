# A2 — the defector route: preregistration (Gate 0)

**Committed before any experiment code exists.** Nothing else is in this
directory. **Zero credits**; exact rational arithmetic, no model call.

---

## 0. What is open, and what this is not

R-M1 measured δ\* — the margin a local stale admission check needs to hold a
cross-principal aggregate — and found the constructive result that **bounded
concurrent activity makes the aggregate unreachable at M ≥ 64**. That is the
first positive result this program has produced on the vision's core obstacle.

**Every cell assumed universal compliance with the admission rule.** No principal
ever ignored its own guard. `research/margin/FINDINGS.md` §9.5 disclaims
enforcement explicitly — "nothing here *enforces* bounded activity" — but it does
not ask the prior question:

> **Is the aggregate bound a SECURITY property, or a COMPLIANCE assumption?**

If one non-compliant principal breaks it, R-M1 described an assumption. If it
degrades gracefully in the number of defectors, it is a statistical security
property of the BFT species, and the action-rate manifest dimension it implies is
worth building.

**This is not a re-run of R-M1.** δ\* is taken as measured, not re-derived. The
only new variable is how many principals ignore it.

## 1. The structural asymmetry, derived before any run

Concentration is `max / sum`. Two defections move it through different terms:

- **Shedding** removes the defector's own holding from the **denominator**:
  impact **O(1/M)**. Large M is *protective*.
- **Hoarding** raises the **numerator** directly: impact **O(1)**, independent of
  M.

So "does one defector break it" is the wrong question at planetary M. The right
one is **how many**, and whether that number scales.

### 1a. D-SHED has a closed form

Compliant principals land at `F = L(δ*)`, and `L(δ) = U(1−κ+δ)/((κ−δ)(M−1))`, so
`F·(M−1) = C` where **`C = U(1−κ+δ*)/(κ−δ*)` is M-independent**. With `k`
defectors shedding to zero and the target at `x_t`:

```
x_t / (x_t + (M−1−k)F) > κ   ⟺   k > (M−1)·[ 1 − x_t(1−κ)/(κC) ]
```

so **`k* ∝ (M−1)`** and

```
φ*  =  k*/(M−1)  =  1 − x_t(1−κ)/(κC)
```

Because R-M1 measured δ\* as *rising* with M, `C` rises with M, so **φ\* rises
with M**: a larger federation tolerates a larger *fraction* of shedding
defectors, because it was already carrying more margin.

| M | δ\* (R-M1) | C | **predicted φ\*** (x_t = 20 … 14) |
|---|---|---|---|
| 8 | 0.130 | 22.553 | **0.409 – 0.586** |
| 64 | 0.280 | 42.500 | **0.686 – 0.780** |
| 512 | 0.295 | 45.574 | **0.707 – 0.795** |

The M=8 and M=512 intervals are **disjoint**, so "φ\* rises with M" is falsifiable
without resolving x_t. `x_t` is bracketed rather than fixed because the target's
pool claim erodes during a run — 20 at genesis, 14 once the pool is empty.

**The closed form is on trial with everything else.** R-M1's was conservative by
≈2× and changed sign at the feasibility boundary; disagreement here is a finding,
never patched.

### 1b. D-HOARD's ceiling, checked BEFORE fixing any threshold

Withdrawal moves pool → holdings and is **sum-conserving** in this environment. A
principal's maximum reachable total is its own account plus the entire pool, so:

```
c_max = (ACCT + CONTRIB·M) / (U·M)   →   CONTRIB/U = 0.30  as M → ∞
```

| M | 8 | 64 | 512 |
|---|---|---|---|
| `c_max` | 0.3875 | 0.3109 | 0.3014 |

**All below κ = 0.60.** So **hoarding alone cannot breach at any M**, and a rule
requiring it to would be unsatisfiable — standing rule #4, which has now failed
four times, most recently on R-M1's own denominator. The informative cell is
therefore **SHED+HOARD combined**, and D-HOARD alone is run as a *derivable
control*, not as a candidate.

## 2. Defection modes

| mode | behaviour | why it is in scope |
|---|---|---|
| **D-SHED** | ignores the floor entirely; sheds to 0 | the natural defection: R-M1's adversary already sheds, this removes its limit |
| **D-SKEW** | respects `L(0)` but not `L(δ*)` | **not malicious** — a node running older software with no margin. The most likely real case in a federation |
| **D-HOARD** | withdraws pool beyond its ceiling | the O(1) term; derivably bounded (§1b) |
| **D-BOTH** | k shedders plus one hoarder | the only combination that can plausibly breach |

## 3. Environment

`research/margin/env_margin.py` is **imported READ-ONLY**; R-M1's findings were
measured on it and a copy would be a second frame free to drift. Defection modes
live in this directory and manipulate `Fed` through its public surface. **Exact
integer nano-units, no tolerance parameter anywhere** — the precondition R-M1
established after five float-boundary artifacts.

δ\* is **taken from `research/margin/margin_result.json`**, not re-derived, at the
configuration where it is defined at all three scales: `FIXED_FRACTION`, n = 1,
ε = 1.

**Gate 0 (harm independence):** violations are computed by
`Fed.concentration_exceeds`, exactly, which imports no guard and cannot see who
defected.

## 4. Measures

**Harm — environment-computed:**
- `violations` — rounds with `concentration > κ`, exact.
- `k*` — the **smallest integer** number of defectors producing any violation
  across all seeds.
- `φ* = k*/(M−1)` — reported, but see §5 on why it is not the decision variable.
- `peak_concentration`, `undefined_rounds` (GATE 0c: excluded, never scored).

**The counter-metric, and it is the one that matters most:**
- **`defector_advantage`** — a defector's final total minus the mean compliant
  total.

> A bound nobody wants to break is a different object from one everybody wants to
> break. Shedding to zero **destroys the defector's own position** to move a
> ratio; if `defector_advantage` is negative, the shedding attack is not
> individually rational and requires principals willing to burn themselves. That
> changes what "compliance assumption" even means, and reporting k\* without it
> would be reporting containment without cost — the AG-3 defect this program
> already recorded.

## 5. Decision rules, with feasibility ceilings checked BEFORE the run

**The decision variable is `k*`, not `φ*`, and that is a deliberate correction.**
φ is quantised at `1/(M−1)`: **0.143 at M = 8 against 0.002 at M = 512**, a 70×
difference in resolution. A cross-M rule on φ would compare a quantity measurable
to 14% against one measurable to 0.2% — the same species as E1-HOLDS, whose
baseline came out exactly 0.000 and made the rule unscorable. `k*` is an integer
and exactly comparable at every M.

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **FRAGILE** | `k*` ≤ 2 at every M | k ∈ [1, M−1] | No — would mean a fixed, tiny number of defectors breaks any size system |
| **STATISTICAL** | `k*` grows with M, at least 4× from M=8 to M=512 | k ≤ M−1; range differs per M and is stated | No |
| **HOARD-CANNOT** | D-HOARD alone produces 0 violations at every M | derivable ceiling 0.30–0.39 < κ (§1b) | **It is derivable** — run as a control; failure means the arithmetic or the instrument is wrong |
| **THEORY** | measured φ\* inside the §1a predicted interval | — | No |
| **INCENTIVE** | `defector_advantage` reported for every mode | — | Not a bar; a reporting obligation |

**The k = 0 column is the control** and must show **zero violations** — that is
δ\* by construction (P-A2e). If it does not, the instrument is broken and no
other cell is read.

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P-A2e** | k = 0 ⇒ zero violations | **YES, DEFINITIONAL** — flagged in advance (rule #2); this is δ\* restated, not a result |
| **P-A2a** | `k*` grows roughly linearly in M | **YES** — derived in §1a; the shedding term is O(1/M) |
| **P-A2b** | φ\* **rises** with M; the M=8 and M=512 intervals do not overlap | **YES**, and counterintuitive: larger federations tolerate a larger *fraction* of defectors because they already run more margin |
| **P-A2c** | D-HOARD alone breaches at **no** M | **YES, DERIVABLE** (§1b), run as a control |
| **P-A2d** | D-SKEW needs **more** defectors than D-SHED | **YES** — it is a strictly weaker defection, still respecting `L(0)` |
| **P-A2f** | `defector_advantage` is **negative** for D-SHED and **positive** for D-HOARD | **YES**, and if it holds the headline is `DEFECTION-IS-NOT-INCENTIVE-COMPATIBLE`: **the attack that works is not rational, and the attack that is rational does not work** |

**P-A2f is the risky one and the valuable one.** It is stated now so that a
convenient result cannot be discovered after the fact.

## 7. What this route cannot establish

1. **No detection or ejection.** A real mesh would identify and evict defectors;
   nothing here models that, so every k\* is a **lower bound** on real tolerance.
2. **No attestation model.** H3 already establishes that the mesh's containment
   claim rests on attestation; a defector here is simply a principal that ignores
   its guard, not one that forged a credential.
3. **Simultaneous, non-adaptive defection.** Defectors do not coordinate, adapt,
   or respond to the guard.
4. **One aggregate**, one conserved total, simulated principals, uniform
   staleness — R-M1's limits carry over unchanged.
5. **Nothing about correctness.** Consequence only; the competence bound remains
   terminal.
