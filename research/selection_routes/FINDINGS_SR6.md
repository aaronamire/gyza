# Findings — SR-6: per-carrier depth cap

**DERIVED, NOT MEASURED.** The prompt is explicit that this route "sets a
PARAMETER, not a theory", and that whether a threshold theorem exists is not to
be re-litigated — it does not (redundancy cannot push chain error below the
common-mode rate; nested failure sets make majority vote equal the best single
replica). What follows derives the parameter from results already measured
elsewhere, and says so.

## DECISION: the cap is PER CARRIER, and two carriers do not cap at all

| carrier | per-stage escape rate | end-to-end correctness at depth n | **depth cap** |
|---|---|---|---|
| **PROOF** | 0.000 (SR-3, n=21) | does not decay — a violation is caught at the stage that commits it | **none** |
| **SPEC** | 0.000 (SR-3, n=2) | does not decay | **none** |
| **TEST** | 1.000 (SR-3, n=4) | (1−p)ⁿ at the natural error rate p | **10** |
| **NONE** | n/a — nothing is checked | (1−p)ⁿ | **10** |

The 10 comes from C14: at the measured capability tier (p ≈ 0.35) depth beyond
~10 is worthless, since 0.65¹⁰ ≈ 0.013. It is inherited, not re-measured.

**The correction this route makes to the existing scheduler**: caps were keyed
on TIER (`{1: None, 2: 32, 3: 10}`). That is wrong for the same reason Part A is
about — a **tier-1, TEST-carried** chain would have been given *no cap* while
being exactly the chain that decays fastest. Keyed on carrier, it caps at 10.

## Why PROOF does not cap — and the honest limit of that claim

A proof-carried check recomputes its property, so an error is caught at the
stage that commits it and cannot propagate. Depth therefore costs nothing *for
the proven property*.

**What that does not say**, and must not be read as saying: the chain's
*output* is not thereby correct. Each stage's proof covers its own property —
a signature proves authorship, a content address proves integrity — and the
conjunction of those properties is not "the work is right". Non-decay is a claim
about the *checks*, not about the *semantics*. The competence bound is
untouched and terminal.

## Status of the cell

**DERIVED.** It composes SR-3's measured per-carrier escape rates with C14's
inherited error rate. It is not an independent measurement and is not counted as
one. A genuinely measured version needs the executor and corpus that
`BLOCKED_SR1_SR2_SR4.md` records as missing; it would measure *p* per carrier
rather than inheriting it.
