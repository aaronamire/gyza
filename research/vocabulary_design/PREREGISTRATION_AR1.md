# Preregistration — AR-1: is the depth curve an artifact of uniform sampling?

**Committed before any AR-1 result exists.** Discovery route; terminal condition
stated below. Autonomous session, O1 (claim-vocabulary design).

## The fence check, done first

`OPEN_PROBLEM.md` §2.7 states the closed result — verifiability does not survive
composition, 61.1% isolated → 0.9% at depth 8 — **and states its own caveat**:
the number is ANALYTIC and assumes chains are **sampled uniformly** from the
claim vocabulary, which real chains do not obey. It is labelled "a shape
argument, not a forecast."

This route attacks **the caveat, not the result**. It does not build a
correctness verifier, does not test whether unverified chains decay (they do,
derivably), and does not touch either face of the competence bound. If the
empirical curve is flat, the closed result is **not** overturned — its scope is
narrowed, and §2.7 already says where.

## Question

What is the claim-type distribution of chains the system **actually produces and
audits**, and what is the depth curve under it?

## Method — the distribution must not be authored by me

Ground truth comes from production code and real runs, never from my judgement:

1. **Real chains.** Run existing demos (`gyza demo pipeline`, the DDIL
   partition demo) that emit genuine signed ICP chains. These predate this
   session.
2. **Which claim types a chain exercises is determined by `gyza/audit.py`**
   (dated 2026-07-03, predating this session), not by me. `ActionAudit` fixes
   the per-action composition: `verify_dag` (signature + linkage), `binding_ok`
   (content address), `manifest_bound_ok` (manifest identity), `within_bounds`
   (enforcement ⊆ manifest, executions only).
3. Map each audited check to its registered claim type and carrier via the V-1
   registry. **The carrier is a property of the check** (recomputes vs samples),
   not a choice made here.
4. Compute the depth curve under the empirical distribution and compare with
   uniform.

**What IS mine and is disclosed:** the 18-type vocabulary and which checks are
registered. The route measures the distribution *within* that vocabulary; it
cannot measure a vocabulary nobody wrote.

## Metrics

1. **Empirical carrier distribution** over audited claim types in real chains.
2. **Depth curve** under it, at depths 1, 2, 4, 8, compared with uniform.
3. **THE COUNTER-METRIC, and it is the one that matters:** the fraction of the
   actual WORK whose *correctness* the chain covers. A flat depth curve over
   provenance claims says nothing about whether outputs are right. Reporting
   curve-flatness without this would be the TPR-without-FPR trap in a new place.

## Feasibility ceiling, checked before thresholds

- Requires **at least one real chain of depth ≥ 2** with a successful audit. If
  the demos produce no multi-envelope chain, the route reports NOT-MEASURABLE.
- If the empirical distribution turns out to be a **single** claim type, the
  depth curve is trivially flat and the cell is DEFINITIONAL, not measured —
  labelled as such.

## Decision rule

- **SAMPLING-ARTIFACT** — empirical depth-8 tier-1 fraction ≥ 0.50 (vs uniform's
  0.009). The 0.9% is then substantially an artifact of the uniform model, and
  §2.7's scope narrows to "chains drawn uniformly from the vocabulary", which is
  not what the system does.
- **UNIFORM-IS-FAIR** — empirical depth-8 fraction < 0.10. The uniform model is
  a reasonable proxy and the closed result stands as stated.
- **INTERMEDIATE** — between 0.10 and 0.50. Report the number; no reframing.

## Point predictions, with a prior

- **P1** — real audited chains are **overwhelmingly PROOF-carried**, because the
  audit composes cryptographic and content-address checks and nothing else.
- **P2** — the empirical depth curve is **flat or near-flat**; SAMPLING-ARTIFACT
  fires.
- **P3 — the counter-metric kills the good news.** Correctness coverage of the
  actual work will be ≈ 0, because the audit never checks whether an output is
  right. **The curve is flat because the chain never carried a correctness claim
  at any depth, not because correctness survives depth.**

**Prior: 70% SAMPLING-ARTIFACT / 20% INTERMEDIATE / 10% UNIFORM-IS-FAIR.**

**What would falsify P2:** a real chain containing a TEST-carried or semantic
claim type in its audited composition.

## Terminal condition

The route ends when the empirical distribution is measured from at least one
real audited chain and the curve is computed. It does not iterate on chain
sources: if the first real source gives a degenerate distribution, that is the
finding.

## What this cannot establish

One repository, its own demos, its own 18-type vocabulary. It measures the
distribution *within* a vocabulary I did not draw from life. A system whose
work is semantically richer would chain different things, and this says nothing
about that.
