# SR-4 closes for free, and the four-route pattern **does not hold**

**Branch `sr4-scope`.** **ZERO CREDITS** — cached data and arithmetic.
**93/93 tests pass.**

---

## 1. A3 — THE DERIVABILITY CHECK, RUN FIRST: **SR-4 IS DERIVABLE**

**A1, from the source.** SR-4 asks *"Does retry recover failures, or does it burn
budget on reproducible errors?"* over variants **(a) no retry / (b) bounded retry
/ (c) retry-with-decomposition**, decision rule **"equivalence bound 3 percentage
points on recovery rate; if (b) is not meaningfully better than (a), pick (a)"**
(`BUILD_PLAN.md:232-238`). `BLOCKED_SR1_SR2_SR4.md:14` records it as needing *"a
task corpus + ground-truth outcomes + an executor with reproducible failures."*

### The prior it was going to test is HALF WRONG, and the tree already said so

`BUILD_PLAN.md:238` states the prior: *"Resampling does not fix systematic errors
— a reproducible failure reproduces."* **Channel A measured that this holds for
one error class and fails for another:**

| stratum | self-consistency J | Channel A's finding |
|---|---|---|
| **surface-keyed** (`ii_noop`) | 0.448 | *"resample-stable — the model gives the same attractor at temp 0.7"*, SC TPR 0.56 |
| **concept-keyed** (`i_classic`) | 0.520 | *"unstable under both"* — A1−SC gap +0.024, CI includes 0 |

So concept errors are **not** reproducible under resampling. **The blanket prior
is false for them.**

### But the real derivation is stronger, and it makes the measurement unnecessary

> **Two samples drawn from the same model at the same temperature are
> EXCHANGEABLE.** Nothing makes the first "the attempt" and the second "the
> retry". So `P(fix a wrong answer)` and `P(break a right one)` are **equal in
> expectation**, and swapping in a resample **cannot change expected accuracy**.
>
> **Retry helps only if you can SELECT the better attempt — and selecting
> requires a verifier, which is the competence bound.**

### Confirmed on cached data — ZERO CREDITS, no generation

The Channel-A self-consistency cache holds **2 independent samples per item per
model** at temp 0.7 (80 items × 5 models), and `route3_attractor/items.json`
holds `true_answer` for all 80. **That is variant (b) at k=1, already paid for.**
Scored with the committed `extract_boxed` / `_sym_equal` — imported, not
restated.

| stratum | usable | attempt-0 wrong | recovered | recovery rate | newly broken | net |
|---|---|---|---|---|---|---|
| `i_classic` (concept) | 77 | 11 | 4 | **0.3636** | 3 | +1 |
| `ii_noop` (surface) | 159 | 22 | 4 | **0.1818** | 9 | −5 |
| `iii_substitution` | 78 | 9 | 1 | 0.1111 | 2 | −1 |

**The prediction, stated before the numbers were read, held directionally:**
concept (0.3636) > surface (0.1818), difference **+0.1818** — matching Channel
A's resample-stability result.

> ### DIAGNOSING THE NET COLUMN, WHICH IS THE PART THAT COULD MISLEAD
> Overall **9 recovered vs 14 broken** looks like retry is harmful. **It is
> not — and it cannot be.** Under exchangeability `E[recovered] = E[broken]`
> **definitionally**. **McNemar exact two-sided p = 0.4049** over the 23
> discordant pairs, and every stratum individually non-significant (1.0000,
> 0.2668, 1.0000). **The net is noise around a structural zero.**
>
> Reporting "retry breaks more than it fixes" would have been an artifact.

**A2 — the blocker classification: `DERIVABLE`.** Not ground truth, not budget,
not design. **The most valuable of the four answers, and it closes the route for
free.**

---

## 2. A4/A5 — K-7 SHIPS `NO_RETRY`

```
DEFAULT_RETRY_POLICY = RetryPolicy.NO_RETRY
```

**The basis, exported beside the constant and returned in the docstring:**

> *"NO_RETRY is the default because retry WITHOUT A VERIFIER cannot improve
> expected accuracy: independent resamples are EXCHANGEABLE, so a retry is as
> likely to break a correct answer as to fix a wrong one. MEASURED on 314 cached
> sample-pairs — 9 recovered vs 14 broken, McNemar exact p = 0.4049, consistent
> with a net effect of ZERO. **This is NOT a claim that NO_RETRY produces better
> outcomes**; it is a claim that retry produces NO DIFFERENT outcome, and SR-4's
> own decision rule then picks (a) because it is simpler and cheaper."*

**A5 — blast radius: one test.** `retry_policy` raised, so nothing called it.
The test that asserted the raise now asserts the default.

### A guard of mine was testing a proxy, and it fired on the wrong thing

`test_neither_default_claims_an_outcome_benefit` scanned for the substring
`"better outcome"` — and **failed on K-7's basis, because that phrase appears
inside its DENIAL**: *"This is NOT a claim that NO_RETRY produces better
outcomes."*

> **A substring scan cannot distinguish an assertion from a negation.** That is
> the label-versus-quantity species **inside the guard itself**. Fixed to check
> per sentence with negation handling, **and given a negative control** that
> demonstrates it still fires on a real benefit claim.

---

## 3. A6 — K-2's BASIS CORRECTED, but **not to the figures given**

| stated in the task | committed source (`research/sr1_matched/`) |
|---|---|
| n = 1042 | **n = 480** |
| difference 0.0072 | **+0.0710** |
| decision floor 0.05 | **preregistered detectable difference 0.167** |
| "CI narrower than the floor" | **CIs OVERLAP** — [0.0252, 0.1943] vs [0.1040, 0.1964] |

**Fourteenth premise of this shape, and it matters here because the instruction
built on it.** The task asked me to restate the basis as *"measured-and-null at
the decision-relevant scale."* **The tree does not support that.** What the data
supports is:

> **MEASURED AND NOT SIGNIFICANT — and an UNDERPOWERED NULL, NOT EVIDENCE OF NO
> EFFECT.** The design's own smallest detectable difference is **0.167**, so a
> real effect below that could not have been seen. It is also observational, so
> it cannot be causal either way.

That is what the basis now says, pinned by a test asserting `NOT SIGNIFICANT`,
`UNDERPOWERED NULL`, `NOT EVIDENCE OF NO EFFECT`, and the literal `0.167`.
**"Unmeasured" understated it; "null at the decision scale" would overstate it.**

---

## 4. PART B — THE PATTERN **DOES NOT HOLD**. It is two, not four.

### B2 — the four cases, from the committed source

| route | what it needed | what was unavailable | **class** |
|---|---|---|---|
| **SR-1 observational** | ~1150 records for a 50/50 split at the 0.167 floor (`FINDINGS_SR1.md:167`) | **nothing unavailable** — CI verdicts are free via `gh api`; the constraint was **PREVALENCE (7.8%) and wall-clock** | **VOLUME — and now partly resolved** (181→480, H1 evaluable) |
| **SR-1 causal** | externally-determined outcomes for **agent-produced** work | no CI channel will run a speculative patch; reproducing a 12-job matrix locally is 390 suite-runs on 2 cores | **GROUND TRUTH** |
| **egress q** | a discriminating signal for **exogenous** egress correctness | *"no ground truth and no safe way to induce it"* — inducing on the live mesh violates C15; on loopback the harness author supplies both sides | **GROUND TRUTH** |
| **SR-4** | recovery rate under retry | **nothing** — the question is derivable and the confirming data was already cached | **DERIVABLE** |

> ### THE HYPOTHESIS FAILS, AND THE FAILURE IS THE FINDING.
> **Two of four are ground-truth blocks. One was a volume block that this
> program has now partly cleared for free. One was never blocked at all.**
>
> Calling all four "blocked on ground truth" would have been a pattern imposed on
> the data — and it would have discouraged exactly the two cheap moves that
> worked: expanding the corpus, and deriving the retry answer.

### B3 — the two genuine cases ARE structurally the same, and the shared structure is narrower than "ground truth"

**Is the missing thing the same in both?** They look different — *outcomes for
agent code* versus *a signal for exogenous claims*. **They are the same
structure:**

> **Both need an EXTERNAL ADJUDICATOR of work THIS SYSTEM produced.**

The decomposition corpus works precisely because **GitHub's CI had already
adjudicated human work** before the corpus existed. 1.B works for the same
reason — *"the verifier is reality"*, and reality had already ruled. **Nothing
adjudicates agent-produced work here**, and for exogenous egress **nothing
adjudicates at all**, which is what makes those correctness claims exogenous in
the first place.

**The pattern does not dissolve under B3's question — it sharpens.**

### B4 — the reachable scope, as a bounded claim

> **This program can measure any question whose ground truth an EXISTING
> EXTERNAL ADJUDICATOR has already produced** — project CI, merged PRs, issue
> outcomes, benchmark answer keys. It has done so repeatedly and at zero cost.
>
> **It cannot measure any question requiring a NEW adjudication of work the
> program itself produced**, because it has no adjudicator and cannot safely
> manufacture one: a self-authored judge measures the judge (R14 Part B4), and
> an induced live egress cannot be taken back (C15).

That boundary is **not** about budget, and it is **not** about ideas.

### B5 — what would unblock each, and which are obtainable

| route | what would unblock it | obtainable? |
|---|---|---|
| SR-1 observational | ~4 more hours of `gh api` against both repos, balanced | **YES — free, just time** |
| **SR-1 causal** | a repo willing to run its CI on agent patches, **or** a local runner able to execute a project test matrix 390× | **plausibly yes** — a fork with CI enabled on a private branch is a real path, and needs a machine with network + compute, not new science |
| **egress q** | an adjudicator of whether an emission *should* have happened | **NO for the exogenous three** — that is the competence bound; **the two INTERNAL egress types need only a checker written** |
| SR-4 | — | **already answered** |

**So one is free, one needs infrastructure rather than research, one is partly
impossible and partly just unwritten, and one is done.** Three of four have a
path.

---

## 5. PART C — WHERE COORDINATION STANDS

### C1. Component by component

| id | component | status | if stub, what blocks it |
|---|---|---|---|
| K-1 | `TaskSpec` / `Termination` | **BUILT** | |
| **K-2** | `decompose` | **STRATEGY selected, IMPLEMENTATION stub** | **not strategy** — nothing assigns `claim_type`; `TaskSpec` has no file list |
| K-3 | `allocate` | **BUILT + MEASURED** (SR-2: round-robin beat type-routing 0.4565 vs 0.3261) | |
| K-4 | `ExecutorPool` | **BUILT** | |
| K-5 | `Combiner` | **BUILT** | |
| K-6 | `Scheduler` | **BUILT** | |
| **K-7** | `retry_policy` | **BUILT + DEFAULT on a DERIVED basis** (this session) | |
| K-8 | `Termination` | **BUILT** | |
| H-1 | `EscalationQueue` | **BUILT** | |
| O-2 / O-3 | `RunMetrics` / `alarms` | **BUILT** | |

### C2. **BUILT-WITH-UNMEASURED-DEFAULTS — and that is now partly too weak**

Three strategy choices, three different epistemic statuses, and **describing them
uniformly would be wrong in both directions**:

| choice | status |
|---|---|
| **K-3 allocate** | **MEASURED** — SR-2 ran, round-robin won by 13pp |
| **K-7 retry** | **DERIVED, then confirmed** — exchangeability, McNemar p=0.4049 |
| **K-2 decompose** | **DEFAULT on a containment basis**, outcome effect measured and **not significant at an underpowered n** |

> **The honest label is: coordination is BUILT, with one measured choice, one
> derived choice, and one default whose outcome basis is an underpowered null.**
> **Not "measured."** But **no longer "unmeasured defaults" either** — that
> understates K-3 and K-7.

### C3. Coordination work NOT blocked on ground truth

1. **K-2's implementation** — blocked on `claim_type` assignment and a file list
   on `TaskSpec`. **That is a representation problem, not a ground-truth one**,
   and `BLOCKED_SR1_SR2_SR4.md` records the deeper part: assigning a claim type
   to a natural task is itself a tier-3 claim.
2. **The two INTERNAL egress checkers** (`publish_delta`, `send_message`) —
   recompute-and-compare, q=1 and f=0 by construction. **Free to write**, though
   B1's consumer gate still fails for them.
3. **Balancing the SR-1 corpus expansion across both repos** — free, and the
   current 480 is scikit-learn-skewed.

---

## 6. Honest limits

1. **The retry measurement is k=1 only.** The cache holds 2 samples. **The
   exchangeability argument covers all k**, but the *confirmation* covers k=1.
2. **n is small**: 23 discordant pairs total. The McNemar p=0.4049 is consistent
   with zero **and would also be consistent with a modest real effect** — it does
   not prove exchangeability, it fails to contradict it. **The derivation carries
   the weight; the data only fails to refute it.**
3. **The strata are Channel A's, on MATH-style items** — not Gyza claims.
   Transfer is a judgement.
4. **K-2 still raises.** Two of three coordination strategy choices are settled;
   the decomposer's implementation is not.
