# The box at scale — a Gate 0 STOP, and the correction it rescued

**Zero credits.** Deterministic arithmetic and adversarial construction over the
committed `env_aggregate.box_bounds`. **The planned M-sweep was NOT run**, for
the reason in §1, and that refusal is the most valuable thing here.

---

## 1. GATE 0 FAILED — the environment is silently capped at M = 3

The experiment was: sweep M ∈ {2,3,10,50,100} and measure whether violations and
throughput cost fall as the federation grows. **It cannot be run.**

```python
def principals(m: int) -> tuple[str, ...]:
    return ("A", "B", "C")[:m]          # env_federation.py:49
```

**Python slicing past the end returns the whole tuple. No error.** Measured:

| requested m | actual principals |
|---|---|
| 2 | 2 |
| 3 | 3 |
| **5, 10, 100** | **3** |

`arena(m)` likewise yields 4 distinct owners at every m.

### What running it anyway would have produced

The guard computes its floor from the *requested* `m`; the arena has 3.

| requested M | floor the guard would enforce | floor M=3 actually needs | |
|---|---|---|---|
| 10 | 1.4815 | 6.6667 | **box unsound by 4×** |
| 100 | 0.1347 | 6.6667 | **box unsound by 50×** |

> **The sweep would have shown violations rising with M and I would have
> concluded "the box fails at scale" — the exact opposite of the truth (§3).**
> The failure would have been a **fixture artifact**, invisible in the output,
> produced by a silent slice.
>
> **STOPPED at the gate rather than improvised past it.** This is the same
> species as every other artifact in this program: an absent thing read as a
> permissive value.

---

## 2. WHY THIS MATTERS: I HAD ALREADY PUBLISHED THE WRONG CONCLUSION

`FINDINGS_ROUND3_DISTANCE.md` §4c claims that bounding a collective ratio-type
quantity *"requires a serialization point whose width is the whole
federation,"* and therefore that a planetary-scale collective-harm-bounded
system is **structurally obstructed**.

**That is wrong, and §3 shows why.** The error: I read *"no **exact** local test
exists"* (AG-3 / I-confluence — a statement about **completeness**) as *"no local
bounding exists"* (a statement about **soundness**). **They are different
claims, and only the first is true.**

---

## 3. THE BOX IS SOUND AT EVERY SCALE — adversarially tested

`box_bounds(m, κ)` returns `L = U(1−κ)/(κ(m−1))`, `U` = the endowment. The claim:
**every principal inside [L, U] implies concentration ≤ κ, with no principal
reading any other's state.**

**Tested by construction, not by evaluating its own formula:**

| m | L | analytic worst case | worst of 3000 random in-box configs | |
|---|---|---|---|---|
| 2 | 13.3333 | 0.600000 | 0.598889 | SOUND |
| 10 | 1.4815 | 0.600000 | 0.356401 | SOUND |
| 100 | 0.13468 | 0.600000 | 0.023843 | SOUND |
| 1000 | 0.01335 | 0.600000 | 0.002128 | SOUND |

**33,000 random in-box configurations across 11 federation sizes. Zero exceeded
κ.**

**Diagnosing the exact 0.600000 at every m: DEFINITIONAL.** The formula solves
`U(1−κ) = κ(m−1)L` for equality, so the worst case is *always* exactly at the
boundary. **It is not evidence that the box is well-calibrated — it is the
construction.** What *is* evidence is that no random configuration exceeded it.

**NEGATIVE CONTROL — the test has power:**

| perturbation | detected? |
|---|---|
| m=10, floor shrunk 0.5× | worst case → 0.7500 → **UNSOUND, detected** |
| m=100, floor shrunk 0.1× | worst case → 0.9375 → **UNSOUND, detected** |

---

## 4. THREE SCALING RESULTS, ALL DERIVED

### 4a. The constraint decays as 1/(m−1)

| M | 2 | 10 | 100 | 1000 | 10000 |
|---|---|---|---|---|---|
| floor as % of endowment | **66.7%** | 7.4% | 0.67% | 0.07% | **0.01%** |

### 4b. The attack margin grows toward the full endowment

A principal breaches only by shedding below `L`. Required shed = `U − L`:

| M | 2 | 3 | 10 | 100 | 1000 |
|---|---|---|---|---|---|
| **shed needed to breach** | **33.3%** | 66.7% | 92.6% | **99.3%** | 99.9% |

> **AG-3's violations came from N concurrent agents jointly shedding past L
> against a stale read. The joint shed required grows monotonically toward U —
> 2.98× harder at M=100 than at M=2, asymptoting at "give away everything."**
>
> **So the staleness attack gets harder with scale, and this is derived, not
> hoped.**

### 4c. Dynamic membership is handled — underestimating M is conservative

| true M | assumed M | enforced floor | required floor | |
|---|---|---|---|---|
| 100 | 10 | 1.4815 | 0.1347 | **safe** |
| 1000 | 100 | 0.1347 | 0.0133 | **safe** |

**A planetary federation needs only a *lower bound* on its own size — never a
live count, never a membership consensus.** `L` is monotone decreasing in `m`, so
any underestimate over-constrains.

---

## 5. THE CORRECTED CLAIM

> ### Planetary scale is the FAVOURABLE regime for local collective bounding, not the obstructed one.
>
> Bounding a collective ratio-type quantity requires **no coordination at all**.
> It requires a static box whose constraint **decays as 1/(m−1)**, whose attack
> margin **grows toward the full endowment**, and which is **sound under
> underestimated membership**.

**What AG-3 actually proved, restated precisely:** no **exact** (sound *and*
complete) local test exists for a two-sided quantity. **Over-blocking is the
price, and the price falls as the federation grows.**

**§4c of `FINDINGS_ROUND3_DISTANCE.md` is superseded by this file.** The prior
text stands unedited there; this is the correction of record.

---

## 6. WHAT THIS DOES **NOT** ESTABLISH

1. **No empirical concurrency result at M > 3.** §4b says the required shed
   grows; it does **not** say a real adversary in a real arena fails to achieve
   it. **That is the open question and it needs apparatus that does not exist.**
2. **The `U` side is untested at scale.** In this environment principals cannot
   grow, so only `L` binds. **In a federation where authority or holdings can be
   acquired, the upper bound binds too and none of §4 applies to it.**
3. **One quantity, one κ, one endowment shape.** Concentration under a uniform
   endowment. A skewed initial distribution may behave differently and is
   untested.
4. **The box is conservative by construction.** It refuses states that satisfy
   the true constraint. §4a says the refusal shrinks with m; it never reaches
   zero.

---

## 7. THE CHEAPNESS IS REDISTRIBUTION, NOT CREATION — correcting §4a

§4a says the floor decays as 1/(m−1) and calls the constraint cheap at scale.
**That is true per participant and false in aggregate.**

| M | individual floor `L` | **aggregate floor `(m−1)L`** |
|---|---|---|
| 2 | 13.33333 | **13.3333** |
| 10 | 1.48148 | **13.3333** |
| 100 | 0.13468 | **13.3333** |
| 1000 | 0.01335 | **13.3333** |
| 10000 | 0.00133 | **13.3333** |

> **`(m−1)L = U(1−κ)/κ` is invariant in m.** The federation's total committed
> floor never shrinks — it is **redistributed** over more participants.

**This is still the right shape for planetary scale** — a fixed collective cost
spread across a billion participants is individually negligible, which is how
planetary systems work at all. **But "it gets cheaper with scale" was too
generous and is withdrawn.** It gets cheaper *per participant*. It does not get
cheaper.

Pinned by `test_the_AGGREGATE_floor_is_INVARIANT_in_m`.

---

## 8. THE EXIT HOLE — the sharp edge of the entire result

§4c establishes that **underestimating m is conservative**. The converse is the
danger, and it is severe:

> **`L` is DECREASING in m. So a floor that was safe at m = 1000 is
> catastrophically unsafe at m = 100.** Underestimating is safe; **the estimate
> going stale downward is not.**

| assumed M | actual M | enforced floor | worst-case concentration | |
|---|---|---|---|---|
| 1000 | 100 | 0.0133 | **0.9380** | breach (κ = 0.60) |
| 1000 | 10 | 0.0133 | **0.9940** | breach |
| 100 | 3 | 0.1347 | **0.9867** | breach |

**Not a marginal breach — near-total concentration.**

> ### So "no coordination required" is not quite the claim. The honest claim is: **no coordination required except a membership failure detector.**
>
> Reliable failure detection at planetary scale is a **classically hard**
> problem — you cannot distinguish a slow participant from a departed one. This
> is a **real dependency**, and it is the thing most likely to be attacked in
> diligence.

**One mitigating observation, recorded as design rather than result:** Gyza's
network layer already carries `AgentAdvertisement` with `ttl_seconds` and
`last_seen`. **TTL expiry is an exit detector with a bounded staleness window**,
which is exactly the shape required — the floor must track the count of
*unexpired* advertisements. **Not built, not tested, and it converts the problem
from "unsolvable" to "bounded by TTL."**

Pinned by `test_underestimating_the_federation_size_is_conservative` and
`test_negative_control_m_FALLING_breaks_the_box`.

---

## 9. THE BOUNDARY — this result does not extend to cumulative quantities

**C7 (`BUILD_PLAN.md:32`, from R13) stands unchanged:**

> *"**Statelessness ⊥ cumulative bounding.** No stateless local check bounds a
> cumulative quantity. Cumulative bounds require a serialization point."*

And AG-3 says so of its own data: *"the cumulative column is a CONTROL and is
**DEFINITIONAL**. No guard here bounds cumulative drain."*

| quantity class | example | locally boundable? |
|---|---|---|
| **instantaneous ratio** | concentration — max share of the federation | ✅ **yes, via the box, at any scale** |
| **cumulative** | total value drained over a trajectory | ❌ **no, at any scale, without serialization** |

Pinned by `test_the_box_is_a_statement_about_an_INSTANTANEOUS_quantity_only`.

---

## 10. THE ANSWER, STATED PRECISELY

> **Instantaneous ratio harms — "no agent controls too much" — are boundable at
> planetary scale, with no coordination, at a fixed collective cost spread
> arbitrarily thin, PROVIDED exits are detected.**
>
> **Cumulative harms — "no more than X total damage" — are not boundable at any
> scale without a serialization point.**

**Note which is which.** The boundable class is a *distribution* property. The
unboundable class is the one people usually mean by *"beneficial."*

**On the trajectory of this claim**, recorded because it matters: I said
*obstructed*, then *favourable*, now this. **The first two were single global
verdicts and both were wrong.** This one decomposes by quantity class and names
its dependency, and that is why I expect it to hold.

---

## 11. What would close it

**A federation environment that expresses M > 3.** That is a *build*, not a
sweep — `principals` and `arena` must generalise, and building it means
authoring the fixture I would then be measured against (the R14 Part B4 trap).

**Mitigating that is easier here than usual**, because the property under test is
**structural** (does a stated predicate hold under concurrent admission) rather
than **behavioural** (do agents do something). A synthetic arena is a weaker
threat to a structural claim. **But it needs its own preregistration, and the
adversary must be specified before the arena is written.**
