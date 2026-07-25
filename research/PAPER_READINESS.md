# Paper-readiness audit

An honest audit of what is publishable and what is missing. **Not the paper.** For each
candidate contribution: the claim, the strongest evidence, the single biggest weakness a
reviewer will attack, and what would fix it *without new experiments*. Then the three things
reviewers will raise, and a GO / SCOPE-DOWN / NOT-YET verdict per candidate plus a recommended
paper shape.

The governing honesty rule: **the value of this work is the application and the discipline,
not the novelty of any single tool.** Overclaiming novelty is the one thing that would sink it.

## Candidate contributions

### 1. The conditional-independence null (method)
- **Claim.** Agreement between models should be scored against a *conditional-independence*
  baseline (what independent errors would produce given each model's marginal error rate and
  the wrong-answer cardinality), not a permutation/label-shuffle null. Against it, apparent
  cross-model agreement-on-wrong is ≈ 0 excess.
- **Strongest evidence.** MBPP: raw 0.56 agreement → excess ≈ 0; the 0.56 → 0.17 collapse once
  restricted to items with ≥ 3 distinct wrong answers (`correlated_failure`, `d484d74`).
- **Biggest weakness a reviewer attacks.** "This is standard meta-analysis / latent-class
  reasoning; the permutation null was a strawman you built." Partly fair.
- **Fix without new experiments.** Frame explicitly as *applying* a known baseline to the
  LLM-agreement setting and showing the field's usual permutation null answers the wrong
  question; cite the meta-analysis lineage. Do not claim the null itself as novel.
- **Verdict: GO (as method-application, not method-invention).**

### 2. The cardinality law
- **Claim.** Agreement informativeness is governed by the size of the wrong-answer space:
  convergence is near-guaranteed (and uninformative) when there are few ways to be wrong.
  Report wrong-answer cardinality beside any convergence figure.
- **Strongest evidence.** MATH mean 2.0 distinct wrong answers / 10 solvers, Simpson ≈ 0;
  the ≥3-distinct-wrong restriction that collapses the MBPP signal; the ≥3-agent-committee
  scope line (`5231be5`).
- **Biggest weakness.** "Obvious once stated" — a reviewer may see it as a corollary of #1.
- **Fix without new experiments.** Present #1 and #2 as one packaged diagnostic ("score
  agreement against conditional independence, and always report cardinality"), not two claims.
- **Verdict: GO, merged with #1.**

### 3. LR-over-J as the mechanism-relevant statistic
- **Claim.** For a bonded/deterrence mechanism, feasibility is governed by the likelihood
  ratio `q/f`, not Youden's J or TPR/FPR individually; two checkers with identical J can have
  opposite feasibility.
- **Strongest evidence.** The `LR ≥ g/w` feasibility derivation and the same-J-different-LR
  worked example (`audit_mechanism`, `212f35d`); measured LR_in 19.8 vs LR_out 1.25.
- **Biggest weakness.** **This is elementary decision theory (Neyman–Pearson).** A reviewer
  will rightly say the statistic is not new.
- **Fix without new experiments.** State plainly that the LR is elementary; the contribution
  is (a) noticing the program *itself* optimized J for nine phases before correcting, and
  (b) tying LR to the joint deter-and-retain feasibility with *measured* operating points. Sell
  the self-correction narrative, not the statistic.
- **Verdict: SCOPE-DOWN — include as a framing/discussion point, not a headline contribution.**

### 4. The competence bound across six families (the MAIN result)
- **Claim.** Cheap black-box verification of natural-language reasoning is bounded by the
  verifier's competence; six structurally independent mechanisms all fail for the same reason.
- **Strongest evidence.** Six preregistered decisions converging; the one well-powered
  out-of-competence demonstration (R8 cell (b), n = 127–290, ESCAPE-ILLUSORY); the durable
  positive inside competence (6B cell (a), J = 0.777, LR = 19.8, n = 433, perm p = 0).
- **Biggest weakness.** **External validity** (mid-tier open-weight models, two task families
  — see below). A reviewer will ask whether this is a fact about *weak* checkers.
- **Fix without new experiments.** Scope the claim precisely to the tested regime and present
  the frontier-model question as explicitly open (do not claim it generalizes upward). The
  six-family *convergence* is the argument that it is not a fluke of any one mechanism; lean on
  that, plus the well-powered R8 cell.
- **Verdict: GO, scoped. This is the paper.**

### 5. The eight-artifact ledger (methodological discipline)
- **Claim.** Preregister, then treat any suspiciously-clean number as a suspected artifact and
  diagnose before reporting — a discipline that caught eight artifacts, each of which would
  have produced a false result.
- **Strongest evidence.** The ledger: forced collision (curated-list matching), degenerate
  weak-model outputs, the MBPP function-name harness bug, the sentinel collision, the
  trust-lift selection confound, the T1/T2 detector coupling, the 33% canonicalization
  contamination, and the R8 `__ERR__` generation-failure contamination (17 gemma programs).
  Each has a "what it would have falsely shown / what caught it" entry.
- **Biggest weakness.** "This is just good practice, not a contribution." True in the abstract;
  compelling in the concrete because each artifact produced a *specific* false headline that
  survived until a specific check killed it.
- **Fix without new experiments.** Present as a methods / "lessons" section or a standalone
  short note; its value is pedagogical and reproducibility-oriented.
- **Verdict: GO as a methods section / short companion note, not a standalone research claim.**

### 6. Route 6's calibrated audit mechanism (competence-bounded q as first-class)
- **Claim.** Given a competence-bounded verifier, the loss-minimizing audit policy, the ε(r)
  floor set by the out-of-competence mass, and the LR feasibility frontier follow; the
  contribution is treating the *measured* competence-bounded `q` as a first-class parameter.
- **Strongest evidence.** The proofs + numerical verification (`audit_mechanism`, `212f35d`,
  `f46445c`); the calibrated ε(r) plateau and the two-tier routing floor.
- **Biggest weakness.** **The framework is known** (Townsend costly-state-verification, Becker,
  Stackelberg security games); a reviewer will say the theory is standard and the calibration
  is on toy parameters. Also: it is a *different kind* of contribution (theory/econ) from the
  empirical main result — bolting it onto the same paper risks incoherence.
- **Fix without new experiments.** Either (a) a separate short theory note "optimal audit under
  a competence-bounded verifier, calibrated from measurement," honestly labeled KNOWN-framework
  + empirical-calibration; or (b) a single discussion section in the main paper. Do not sell it
  as novel mechanism design.
- **Verdict: SCOPE-DOWN — separate note or discussion section, not co-headline.**

## The three things reviewers WILL raise

### External validity
- **What generalizes (argued, not proven):** the *structural* claim — that a black-box
  verifier which must itself understand the claim cannot cheaply verify it — is mechanism-level
  and the six-family convergence supports it beyond any one task.
- **What is scoped to the apparatus (do not claim beyond it):** every *number* (J, LR, validity
  rates, ε values), and the *magnitude* of the bound. Two task families (MBPP code, MATH) + one
  hand-built fixture set (NoOp); one open-weight capability tier (pass 0.32–0.40); English;
  numeric / collection answers. No proofs, no long-form argument, no multilingual, no
  interactive tasks. **Claim the structure, scope the numbers.**

### Prior-art honesty (per contribution)
| Contribution | Class | Novelty argument (honest) |
|---|---|---|
| 1 Conditional-independence null | KNOWN-VARIANT | Standard baseline; novelty = applying it to LLM agreement and showing the permutation null misleads. |
| 2 Cardinality law | KNOWN-VARIANT | Corollary of #1; novelty = making it an explicit reporting rule. |
| 3 LR-over-J | **KNOWN (elementary)** | Neyman–Pearson. Novelty = the nine-phase self-correction and the measured feasibility frontier, *not* the statistic. Flag as weaker than it looks. |
| 4 Competence bound, six families | **PLAUSIBLY-NOVEL (empirical)** | The synthesis + preregistered six-family convergence + one well-powered cell is the contribution; the individual intuition is old, the systematic falsification is not. |
| 5 Artifact ledger | KNOWN (practice) | Value is concrete pedagogy, not a claim. |
| 6 Calibrated audit mechanism | KNOWN-framework + novel calibration | Townsend/Becker/Stackelberg are standard; novelty = competence-bounded measured `q` + tier-routing corollary. |

### The frontier-model gap
Every model was a mid-tier open-weight model (pass 0.32–0.40). **Stated plainly: the
competence bound might *shift* — not vanish — with frontier models.** A stronger checker has a
wider competence region, so cell (a) grows and cell (b) shrinks; the *bound* (cheap
verification fails outside the checker's competence) is expected to hold, but the *location*
of the boundary, and therefore how much of a real workload falls in the deployable cell (a),
is untested and is **the single most important untested variable.** Do not hand-wave it: the
paper must say the numbers are lower bounds on what a frontier checker achieves inside
competence, and that where the competence boundary sits for frontier models is future work.

## Recommended paper shape

- **One coherent paper — "The competence bound: limits of cheap verification for
  natural-language reasoning."** Main result = contribution 4 (six families, scoped), with
  contributions 1+2 as the agreement-analysis method section, contribution 5 as a methods /
  reproducibility section, and contributions 3 and 6 compressed into a single discussion
  section ("the economic reading: LR feasibility and where a bonded market is viable"). This is
  a **GO**, conditioned on scoping the numbers and foregrounding the frontier-model caveat.
- **Optional companion note** — the audit mechanism (contribution 6) as a standalone
  theory-note if a venue wants it, honestly labeled KNOWN-framework + empirical-calibration.
- **NOT-YET as a *general* claim about all AI verification** — it is a claim about
  black-box cheap verification of NL reasoning at one capability tier. The internals channel
  (`FRONTIER_LEDGER.md`) and the frontier-model gap are the two things that would have to be
  addressed before any broader claim, and both require new apparatus.

**Bottom line:** one honest, scoped empirical paper is publishable now from the existing data.
Its integrity depends on claiming the *structure* generally and the *numbers* narrowly, and on
never selling the elementary pieces (LR, the null) as invented here.
