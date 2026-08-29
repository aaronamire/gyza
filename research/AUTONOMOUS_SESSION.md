# Autonomous session — O1 and O2

Three routes, all preregistered before data, all zero model calls.
**Credit balance: $3.1718 at start, $3.1718 at end** — no route required
generation, so the $30 cap was never approached.

**Stop condition fired: both O1 and O2 reached terminal decisions.**

## The routes

| route | question | decision |
|---|---|---|
| **AR-1** | Is the depth curve an artifact of uniform sampling? | **SAMPLING-ARTIFACT** — and the reframing gives nothing back |
| **AR-2** | Is a claim semantic intrinsically, or as stated? | **ENVELOPE-ABSORBS fires; the mixture says don't believe it** |
| **AR-3** | Is there a non-text signal for type assignment? | **NO-SIGNAL** |

## What moved

**AR-1 replaced §2.7's headline with a more precise and worse one.** Real
audited chains are 100% PROOF-carried and the depth curve is flat at 1.0000 —
against uniform's 0.0091 at depth 8. But correctness coverage of the audited
work is **0.0 at every depth, including depth 1**, because `gyza/audit.py`
composes five checks and none asks whether an output is right.

> **Provenance composes to arbitrary depth. Correctness is absent at depth 1,
> not decaying with depth.**

§2.7 was interpolating between two things not on one axis: 61.1% counts *claim
types with a verifier*; 0.9% counts *hypothetical uniform chains*. Real chains
draw from neither — they exercise the same five PROOF types forever, and the
semantic types are **never links in the chain**, only the payload it carries.

**AR-2 closed the respecification lever.** A type-level envelope — the only
granularity C11 can pay for — catches **18.6%** of genuinely wrong answers among
programs that actually ran, at FPR 0.0000. Semantic-ness is **intrinsic**, not
an artifact of how the claim was stated.

**AR-3 gave O2 a two-part answer** where it previously had one number. Non-text
assignment reaches **0.70** where claim types differ in what they *touch*, and
**0.0000** where they differ in what they *assert about the same object* — the
latter definitional, since byte-identical objects admit no separating function.

## What did not move

The 4-of-18 semantic fraction. **Neither route reduced it**, and AR-2 established
that respecification will not. The composition ceiling stands.

## Negatives, at full strength

- **AR-2's headline refuted its own prediction and the decomposition reinstated
  it.** P1 predicted TPR < 0.25; the headline was 0.5128 (refuted) and the
  marginal was 0.1857 (confirmed). 78% of the headline was "the program
  crashed" — an execution failure any runtime surfaces, not a respecified
  semantic claim.
- **AR-3 refuted P3.** I predicted SIGNAL-PARTIAL; NO-SIGNAL fired because
  TOUCH-differing types reached 0.70 against a 0.75 bar. P1 (the envelope-family
  collision) was right harder than I had allowed for.
- **AR-1's flat curve is good-looking and means nothing**, exactly as P3
  predicted before data.

## Disclosed defects in my own work

1. **AR-1's first chain used empty `input_hashes`** and the production verifiers
   correctly refused it. No result came from the refused chain.
2. **AR-2's oracle compared `repr` strings** and scored an impossible FPR of
   0.0633. **Artifact #15's species, for the third time, in the session that
   wrote the rule down.** Fixed by comparing values; TYPE-ONLY and STRUCTURAL
   were unchanged, so no envelope was tuned.
3. **AR-3's two signals were one signal.** APPLICABILITY was defined as a
   function of SHAPE, so identical columns are construction, not corroboration.
   One signal was tested, not two.

## Is O1 or O2 closer to closed?

**O1 is closer, and it closed in the direction that makes the problem harder.**
It began as *"can a vocabulary be designed so deep chains retain a correctness
claim?"* — which presumed correctness was in the chain and eroding. AR-1 showed
it is not in the chain at all, and AR-2 showed the obvious way to put it there
(respecify a semantic claim into a mechanical envelope) recovers 18.6% of real
failures at the only affordable granularity. So the question is no longer
"how do we make it survive depth" but "can a correctness claim be *in* a chain
at all", and both routes point at no. **That is a stronger and more constraining
result than the one the session started with**, and it is a negative. O2 moved
less: it gained a decomposition and an argument for why half of it is
permanently closed, but its touch-differing half sits at 0.70 with one untested
signal (a runtime touch-set) that could plausibly beat it — the single cheapest
open thread either objective leaves behind.
