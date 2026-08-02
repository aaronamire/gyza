# SR-1, SR-2, SR-4 — BLOCKED ON SUBSTRATE (not run; not preregistered)

**No preregistration was committed for these three, because preregistering a
route that cannot be run would be theatre.** This file records why, what
specifically is missing, and what would unblock them — so the next session
does not rediscover it.

## The three routes and what each needs

| route | primary metric | requires |
|---|---|---|
| SR-1 decomposition | fraction of subtasks PROOF/SPEC-carried | a task corpus + a decomposer + **a mapping from subtask → Gyza claim type** |
| SR-2 allocation | task success, escalation rate, throughput | the above **plus ground-truth outcomes** per task |
| SR-4 retry | recovery rate, wasted-token fraction | the above **plus an executor with reproducible failures** |

## What is actually missing, verified against the tree

1. **Nothing assigns a claim type to a task.** `grep claim_type gyza/` returns
   hits only inside `gyza/verification/`. The verification layer knows what a
   claim type *is*; nothing produces one from work. `WorkItem`
   (`gyza/schema.py:34`) carries `description` (free text) and `required_tier`
   (an int) and no claim type.
2. **No task corpus with ground-truth outcomes exists.** SR-2's success rate and
   SR-4's recovery rate are both defined against ground truth. There is none in
   the repository. MBPP is present but MBPP tasks are not Gyza claims.
3. **No executor produces Gyza claims from natural tasks.** The demos exercise
   fixed, hand-built workflows; there is no path from "a task" to "a sequence of
   typed claims".

## Why a simulator would not be an acceptable substitute

Any corpus I author, I author with properties in mind, and SR-1 would then
measure the corpus rather than the decomposition strategies. **This is exactly
the failure that voided R14 Part B4's conservation cell**: the prompt said
"preserved" while the pipelines added elements, so all 24 model specs rejected
the correct pipeline — the cell measured the prompt, not the models, and was
reported void.

The same trap is sharper here, because the metric is *the carrier distribution
of subtasks* and I would be choosing the subtasks. A route whose answer is
determined by the harness author is not a route.

## The deeper obstacle, which is a finding rather than a gap

**Assigning a claim type to a natural task is itself a tier-3 claim.** The tier
router is a type check and is sound *given* a claim type. Nothing verifies that
the type assigned to a task is the right one, and no mechanical check can: it is
a judgement about what a piece of work *means*, which is semantic content — the
competence bound, closed across six families and terminal.

So the verified tier does not merely need human-authored specs (C11). **It needs
a human-authored, or at least human-audited, TYPE ASSIGNMENT per task**, and
that cost is per *task*, not per *type* — which is the cost model C11 said was
the affordable one. This is a real constraint on the architecture and it belongs
in the open-problem document rather than being absorbed silently.

A related smell, recorded while here: `WorkItem.required_tier` is
**self-declared**. A self-reported tier is precisely what a tier router must not
trust — the same shape as the self-reported `attestation_tier` that verify-on-
fetch was built to stop trusting. If K-1 grows a `claim_type` field, it must not
be self-declared by the producing agent.

## What would unblock them, in order

1. **K-1 with an audited claim-type assignment.** Built this session as a
   representation; the *assignment* is the open part.
2. **A task corpus of ≥ 50 tasks with ground-truth outcomes**, expressed in the
   claim vocabulary. This is the single blocking artifact for SR-2 and SR-4.
3. **An executor** that runs a typed claim and produces a checkable result.

Until (2) exists, SR-2 and SR-4 cannot be run at all. SR-1 could be run the
moment (1) and a corpus exist, even without ground truth, since its metric is
structural rather than outcome-based.
