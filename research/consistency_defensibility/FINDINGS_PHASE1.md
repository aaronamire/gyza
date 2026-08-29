# Channel A — Phase 1 FREE cache pilot (plumbing + false-positive side only)

**Not a Route 2 rescue.** The Route 2 terminal decision
(UNFALSIFIABLE-IN-PRACTICE) stands. This is a **different channel**: single-agent
CONSISTENCY (does a claim survive semantics-preserving transformation?), which
needs no independence between agents. Phase 1 is zero-generation, cache-only.

## This pilot CANNOT validate detection — the circularity (1a), stated first

The only base↔perturbed comparison the round-3 cache supports is **COT
(CONTROL = base/original) vs COT (perturbed)**. And the comparison is
**definitionally tied** to the outcome it would "detect":

- **Competence/invariance items (NoOp)**: base and perturbed share the *same*
  true answer. Conditioned on base-correctness, "answer changed" ⟺ "perturbed
  wrong" **by construction**. The numbers confirm it exactly: NoOp
  P(change | wrong) = **1.0**, P(change | correct) = **0.0**, J = **1.0**
  (permutation p=0.0). That J=1.0 is the circularity made numeric, **not**
  evidence that consistency detects error.
- **Memorized items (substitution)**: the true answer is *designed* to change
  base→perturbed, so *everyone* changes: P(change | wrong) = P(change | correct)
  = **1.0**, J = **0.0**. The change signal carries zero information here — the
  opposite definitional artifact.

So the pooled base↔perturbed association (ALL: J=0.582, p=0.0) is a **definitional
artifact driven by the NoOp cell** and must never be read as detection. Real
detection is Phase 2 (metamorphic transforms with declared relations on the
*same* item), preregistered separately.

## What IS non-circular (computed)

**Evaluable:** 312 of 320 (model, item) COT pairs; 8 excluded as non-answers.

**(1c) Canonicalization matters, a little.** Of 142 pairs whose raw answer
strings differ, **1** collapses to "no change" under the validated canonicalizer
(a formatting variant). Uncanonicalized comparison would have manufactured that
one as a violation. Small here, non-zero, and load-bearing at scale.

**(1b) Answer mobility base rate** — P(canonical answer changes base→perturbed):

| stratum | mobility |
|---|---|
| overall | 0.452 |
| ii_noop (invariance) | **0.156** |
| i_classic | 0.500 |
| iii_substitution (change by design) | **1.000** |
| llama-3.1-70b | 0.397 |
| gemma-2-27b | **0.625** |
| mistral-small-3.2 | 0.408 |
| phi-4 | 0.372 |

gemma-2 moves its answer most (0.625) — consistent with it being the most
error-prone model in round 3, i.e. the model that will carry most of the
detectable signal in Phase 2.

**(1b) False-positive rate (specificity bound; non-definitional).** Among (agent,
item) pairs where the agent is **correct on the perturbed item**, how often its
answer nonetheless differs from base (a "violation" that is not an error):

- **Pure NoOp (true-invariant): FPR = 0.000** — clean; a correct NoOp answer
  never spuriously trips the invariance check here.
- **Competence-pooled: FPR = 0.124** (n=193). This is **inflated** by 5
  fence-post items whose base ("how many sections") and perturbed ("how many
  posts") legitimately have *different* true answers — so they are not true
  invariance items and a change there is not a false positive. Flagging this:
  the honest invariance FPR is ≈0 for NoOp, and the 0.124 pooled figure includes
  a mislabeled-invariance contribution. Phase 2 measures FPR properly (declared
  relations on the same item).
- Memorized change-relation FPR (correct-but-did-not-change) = **0.000** (n=76).

## GATE 1 status

Phase 1 delivered: cache + item inventory, the circularity statement, mobility
base rates, and the false-positive side. It establishes plumbing and specificity,
**not** detection — by design. Detection is Phase 2. This file will be
superseded/extended by `FINDINGS_CHANNEL_A.md` after Phase 2.
