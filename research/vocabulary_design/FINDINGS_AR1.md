# Findings — AR-1: is the depth curve an artifact of uniform sampling?

Per `PREREGISTRATION_AR1.md` (`778f752`), committed before any result.
Deterministic, zero model calls.

## DECISION: **SAMPLING-ARTIFACT** — and the reframing gives nothing back

| depth | empirical | uniform |
|---|---|---|
| 1 | **1.0000** | 0.5556 |
| 2 | **1.0000** | 0.3086 |
| 4 | **1.0000** | 0.0953 |
| 8 | **1.0000** | 0.0091 |

Real audited chains are **100% PROOF-carried** and the depth curve is **flat**.
The decision rule fires: §2.7's 0.9% describes chains drawn *uniformly from the
vocabulary*, which is not what the system does.

**And it changes nothing that matters, because of the counter-metric.**

## THE COUNTER-METRIC, which is the actual result

**Correctness coverage of the audited work: 0.0 — at every depth, including
depth 1.**

The production audit (`gyza/audit.py`, composition fixed there and not chosen
here) exercises exactly five claim types per action: `envelope_signature`,
`envelope_chain`, `artifact_content_address`, `manifest_identity`,
`enforcement_within_manifest`. **None of them asks whether the output is right.**

So the flat curve is not correctness surviving depth. It is:

> **Provenance composes to arbitrary depth. Correctness is absent at depth 1,
> not decaying with depth.**

This was **predicted before data** (P3) and it is the finding, not a caveat on
it.

## The exact 1.0000, diagnosed

**DEFINITIONAL, not measured.** `p_proof = 1.0` follows from `audit.py`'s
composition: all five checks *recompute* their property, so all five are
PROOF-carried by construction. There is no distribution here with variance —
there is a fixed set of five checks, none of which is TEST-carried or semantic.

The preregistration anticipated this shape ("if the empirical distribution turns
out to be a single claim type, the cell is DEFINITIONAL"). It is five claim
types of one carrier, which is the same species. **A definitional cell
illustrates; it does not confirm.** What it illustrates is what `audit.py`
checks — which is worth knowing precisely, and is not a measurement of a
distribution.

## What this does to §2.7

§2.7's number was interpolating between two things that turn out not to be on
the same axis:

| | what it counts |
|---|---|
| 61.1% isolated | fraction of **claim types** that have a verifier |
| 0.9% at depth 8 | fraction of **hypothetical uniform chains** that stay tier-1 |

Real chains draw from neither population. They exercise **5 of the 18** types,
always the same five, always PROOF-carried. **The semantic types are never in
the chain at all** — they are the payload the chain carries, not links in it.

So §2.7 should be read as: *if you built chains by drawing claim types uniformly,
correctness would decay like this.* Nothing builds chains that way. The honest
replacement is the boxed statement above, and it is **worse news stated more
precisely**: the original implied correctness existed at shallow depth and
eroded. It does not exist at any depth.

## What this does to O1

It reframes the question. O1 asked *"can a vocabulary be designed so deep chains
retain a correctness claim?"* AR-1 says Gyza's chains contain **no** correctness
claim to retain, so the prior question is:

> **Can a correctness claim be IN a chain at all — i.e. can any claim type whose
> verification is chain-composable also be about whether work is right?**

That is what AR-2 tests, and it is a sharper question than the one O1 started
with.

## Honest limits

One repository, its own demos, its own 18-type vocabulary, one chain
construction. The chain is built the way the runner builds one (canonical-JSON
artifact, folded enforcement record, content-addressed output, parent linkage,
each step consuming the prior output) and audits clean under
`require_closed=True, require_all_artifacts=True` — but it is a constructed
chain, not one harvested from a long-running deployment. A deployment whose
audit composition differed would give a different distribution; the composition
here is production code's, the chain is mine.

**Disclosed harness correction.** The first chain used empty `input_hashes` and
the production verifiers **correctly refused it** (`icp.py:129` requires
non-empty inputs; `verify_dag` builds data-dependency edges from them). No
result was produced from the refused chain; the corrected chain has each step
consume its predecessor's output, which is what real work does.
