# The conditional-independence null for model-error correlation

A methodological note, extracted from the Gyza correlated-failure study so it
stands on its own. It concerns a measurement error that is easy to make and
that systematically manufactures evidence of "shared blind spots" between
models where there is none.

## The problem

You want to know whether two models **share a blind spot** — whether, beyond
each being individually fallible, they fail *together on the same problems in
the same way* more than chance would predict. The natural test is a null: shuffle
the labels and see whether the observed co-failure exceeds the shuffled
baseline.

The obvious shuffle — the **permutation null** — permutes one model's answers
across problems and recomputes the same-wrong-answer rate. It is wrong for this
question. Permuting across problems asks:

> *Are the collisions problem-aligned?* — i.e. do the two models tend to be
> wrong on the **same problems**, and when both wrong, land on answers drawn
> from each problem's own wrong-answer distribution?

That is **trivially true** whenever some problems are harder than others and
each hard problem has a small set of plausible wrong answers. Two independent
models will pile onto the same few wrong answers on the same hard problems, and
the permutation null — which destroys the problem alignment — reads this as a
large excess. In the Gyza MBPP code battery the permutation null was 0.044 and
observed convergence 0.56, making shared failure look **~13× chance**. It was an
artifact of the question the null answered, not of shared cognition.

The question you actually meant is different:

> *Are these two models correlated **beyond the problem**?* — given the
> per-problem wrong-answer distribution, do *these two* agree more than two
> arbitrary wrong models would?

The permutation null cannot see this, because it has no notion of per-problem
pair-specificity. It conflates "the problem is hard and narrow" with "these two
share something."

## The correct null: per-problem conditional independence

Condition on the problem. For each problem, estimate the population's
wrong-answer distribution from the **other** models (leave the measured pair
out), and ask how often two *independent* draws from that distribution would
agree. The excess of the pair's observed agreement over this baseline is the
pair-specific correlation — the thing "shared blind spot" is supposed to mean.

Two estimator details matter:

1. **Unbiased pairwise agreement (Simpson), not Σ p̂².** For a problem where the
   other wrong models produce signature counts `c_s` over `m = Σ c_s` wrong
   models, the probability two *distinct* random wrong models agree is the
   unbiased pair-counting estimator

   ```
   baseline_q = Σ_s C(c_s, 2) / C(m, 2)
   ```

   not `Σ_s p̂_s²` (which is biased upward at small `m` because it includes the
   "draw the same model twice" diagonal). At the small per-problem `m` typical
   of these studies the bias is large; use the pair-counting form.

2. **Ratio-of-sums aggregation**, to match the observed estimator. Aggregate as
   `Σ_q agreeing_pairs_q / Σ_q total_pairs_q` over the problems where the pair is
   both-wrong, rather than averaging per-problem ratios — so observed and
   baseline are the same functional of the data and their difference is a clean
   excess.

Report the excess with a bootstrap CI over pairs. Excess ≈ 0 ⇒ the convergence
is entirely problem-structural (a constrained wrong-answer space); excess > 0 ⇒
genuine pair-specific correlation beyond the problem.

The sentinel discipline carries over unchanged: a "no answer produced" signature
(timeout / import error / unparseable) must never count as agreement, in the
observed rate **or** the baseline, or two models that both fail to answer will
be scored as agreeing.

## The demonstration

On the MBPP code battery (9 capable models, capability-banded), the two nulls
give opposite readings of the same data:

| null | value | reading |
|---|---|---|
| permutation | 0.044 | observed 0.56 ⇒ "~13× chance", shared blind spot |
| **conditional-independence (leave-pair-out)** | ≈ observed | **excess ≈ 0** (cross −0.024 [−0.052, +0.001]; within +0.026 [−0.013, +0.065]) ⇒ problem-structural, no pair-specific correlation |

The causal evidence that the convergence was space-driven, not model-driven, is
the **cardinality restriction**: recomputing on only the problems with ≥3
distinct wrong answers collapses observed convergence from **0.56 to 0.17**. The
convergence lived entirely on problems whose wrong-answer space was tiny (median
1 distinct wrong answer, Simpson 0.60); where the space opened, it vanished.

## The general lesson

For anyone measuring model-error correlation (ensembling, LLM-judge agreement,
multi-agent "consensus", diversity claims):

1. **Report excess over a conditional-independence null**, not a raw convergence
   rate and not excess over a permutation null. The permutation null answers a
   question you did not ask.
2. **Report the output-space cardinality alongside any convergence figure** —
   distinct wrong answers per item, Simpson agreement among wrong models, and
   effective number of wrong answers (1/Σ p̂²). A convergence number is
   **uninterpretable without it**: 0.56 convergence means "shared blind spot" in
   an open space and "there was only one wrong answer to give" in a constrained
   one, and only the cardinality tells you which.

## Honest limit

The conditional-independence null bounds exactly one thing: whether pair or group
identity adds correlation **beyond** the per-problem wrong-answer structure. It
**cannot by itself** separate "genuine shared cognition across models" from "an
intrinsically small wrong-answer space" — both produce high raw convergence and
near-zero excess. What distinguishes them is the cardinality report (the "Layer
2" measurement above): a small measured space *is* the constrained-space
explanation, and bounds how much genuine shared cognition could be hiding. Report
both layers; claim only what the excess plus the cardinality jointly support.

---

*Provenance: extracted from `research/correlated_failure/` (estimator:
`conditional_independence_null.py`; results: `FINDINGS_CI_NULL.md`,
`FINDINGS.md`). The cross-task consequence — that agreement's informativeness is
governed by this cardinality — is written up in `research/CARDINALITY_LAW.md`.*
