# Artifact ledger

Cases where a clean number turned out to be **definitional, coupled, or
contaminated**, and what caught each one. The ledger exists because every entry
would have produced a specific false headline that survived until a specific
check killed it.

**Provenance of the count.** Entries 1–8 are enumerated in
`PAPER_READINESS.md` §5 (forced collision, degenerate weak-model outputs, the
MBPP function-name harness bug, the sentinel collision, the trust-lift selection
confound, the T1/T2 detector coupling, the 33% canonicalization contamination,
the R8 `__ERR__` generation-failure contamination). Entries 9–12 accrued across
R12–R14 and are recorded in those routes' own findings — the running tally was
"ten" at R13, "eleven" at R14's preregistration, and twelve by R14's close. This
file does not re-derive a canonical numbering for 1–12; it records **#13 in
full**, because #13 is the first of a new kind.

---

## #13 — the SR-5 moving-frame defect

**The first artifact found in BUILT CODE rather than in an experiment.** Every
prior entry was a measurement artifact in a research harness. This one was a
defect in a shipped component (`gyza/containment/staging.py`, C-6 promotion
gate) that a preregistered research check happened to expose.

### What it would have falsely shown

SR-5 would have reported a **clean three-way tie at effective throughput 1.0**
across per-action, per-task and per-batch promotion, and concluded that
**promotion granularity does not matter**. That conclusion would have been
recorded as a closed selection route and used to parameterize C-6.

Underneath it, the system was worse than wrong: **promotion after every action
bought unlimited drain.** The gate measured cumulative harm from
`baseline_state()` — the *moving* rollback checkpoint — so every promotion
silently re-based the measurement. Each batch saw a fresh, tiny delta; the
run-level total was never anyone's frame; the cumulative bound was not enforced
at all. A perfect throughput score would have been reported for a guard that
bounded nothing.

### What caught it

The **preregistered feasibility check**: SR-5's preregistration required the
harness to produce refusals at k = 1 *before* the comparison could be trusted,
on the reasoning that a metric sitting at its ceiling means the harness is
broken rather than the question answered. The first run reported **zero
refusals**. That number was diagnosed rather than reported, per the
diagnose-any-exact-0-or-1 rule.

Nothing else in the pipeline would have caught it. All 43 tests passed. The
component looked correct, the acceptance criteria it was written against were
satisfied, and the defect was invisible to every test that did not ask the
system to spend more than its budget across multiple promotions.

### The generalized lesson

> **THE FRAME LEMMA APPLIES TO MOVING FRAMES, NOT ONLY PINNED ONES.**

R9's G4′ **pinned** its frame at `s₀` and lost 175000 where G4, reading the
current frame, bounded at 50. The instinctive reading of that result is "do not
pin the frame — let it float." SR-5 is the mirror image: this gate **let the
frame float when it should have been fixed**, re-basing at every promotion, and
lost the bound entirely.

Both are frame drift. The lemma is not "float the frame" and not "pin the
frame" — it is that **the invariant's frame must be the harm's frame**, and
which one that is depends on the harm:

- an **instantaneous** harm (what does this agent own *now*) has a moving
  frame, and pinning it is the G4′ error;
- a **cumulative** harm (how much has been spent *over this period*) has a fixed
  origin, and floating it is the SR-5 error.

Reading R9 as "frames should float" is exactly how this defect was written.

### Standing discipline added

> **Any cumulative measurement must name its origin explicitly, and that origin
> must be immutable for the lifetime of the bound.**

A cumulative bound whose origin can move is not a bound. Naming the origin makes
the question "is this the harm's frame?" answerable by inspection instead of by
a feasibility check that happens to be preregistered.

Recorded in `BUILD_PLAN.md` §6 and in `CLAUDE.md`'s standing discipline.

---

## #14 — the carrier mixture read as a class property

**Species: an aggregate over a heterogeneous population, read as a property of
the population.** The same shape as the trust-lift selection confound (entry 5).

### What it would have falsely shown

SR-3's by-class table reads CONSERVATION **0.667**, MONOTONE **1.000**. Taken at
face value that is a clean, publishable-looking claim — *conservation composes
less reliably than monotone* — and it would have been written into
`ARCHITECTURAL_PRINCIPLE.md` as a refinement of the existing class taxonomy,
which already had class governing composition. It fits the prior so well it
would not have looked like a finding at all.

It is an artifact. CONSERVATION decomposes into **PROOF 1.000 (n=8)** and
**TEST 0.000 (n=4)**. The 0.667 is the mixing ratio of two populations with
nothing between them. There is no conservation-class effect; there is a carrier
effect, and conservation happened to be the class where both carriers appeared.

### What caught it

Recording the CARRIER as a first-class variable alongside the class, so the
by-class number could be decomposed instead of only being reported. Had the
harness tracked class alone — which is what the existing taxonomy would have
suggested tracking — the aggregate would have been the finest available grain
and the artifact would have been invisible.

### The generalized lesson

> **An aggregate is only a property when the population is homogeneous in every
> variable that affects the outcome. Decompose before believing.**

The prior entries of this species (trust-lift selection confound; the T1/T2
detector coupling) were caught the same way: by having recorded the variable
that turned out to matter. The rule that follows is not "distrust aggregates" —
it is that a taxonomy which tells you what to record determines which artifacts
you *can* catch, so a measurement should carry the variables a competing theory
would need, not only the ones the current theory predicts.

---

## #15 — repr-equality mistaken for value-equality (a RECURRENCE of #7)

**Species: an equality test between two REPRESENTATIONS of a value, read as a
test on the value.** This is artifact #7 (the 33% canonicalization
contamination) reappearing in a different codebase, and the recurrence is the
part worth recording — the discipline caught it the second time, but did not
prevent it.

### The defect

`research/native_verifier/native_verifier.py:219` computes

```python
return "CORRECT" if signature == expected else "WRONG"
```

where both sides are lists of **string reprs** of call results. Two cases where
the value compares equal and the repr does not:

- `{1: 2, 2: 3, 3: 1, ...}` vs `{2: 3, 1: 2, 5: 2, ...}` — the same dict, a
  different insertion order in the repr;
- `(1, 0.0)` vs `(1.0, 0.0)` — `1 == 1.0` is True in Python.

### The measurement

Re-executing all **196** (model, problem) pairs against MBPP's own asserts
(`research/selection_routes/mbpp_truth.json`):

| | |
|---|---|
| agreement with the cached label | **0.9439** |
| **false WRONG** (cache said wrong, asserts pass) | **11** |
| **false CORRECT** | **0** |

### Why the direction confirms the diagnosis

**Repr equality can only be STRICTER than value equality, never looser.** A
defect of this species therefore predicts errors in exactly one direction, and
that is what was found: 11 and 0. A two-directional error would have meant
something else was also wrong. **The sign of the residual is evidence about the
mechanism, not merely evidence that numbers moved** — and checking it is cheaper
than any other diagnostic available here.

### What it touches, stated rather than assumed away

R8 (ESCAPE-ILLUSORY) and R14 (SPEC-COLLAPSES) both assigned cell (a)/(b) from
this label. A false WRONG places a **solved** problem into cell (b),
contaminating the out-of-competence cell with items the model actually handled.
That biases cell (b) to look **better** than it is, so both results are
**conservative — if anything understated.**

**Neither was re-run.** The direction is favourable to their conclusions and
re-running was out of scope for the session that found this, so the correction
is recorded and the decisions stand on their prior evidence. Any future re-run
of R8 or R14 must read `selection_routes/mbpp_truth.json` rather than the cached
`status`, or it inherits the same eleven.

### How it was caught

The corpus's hand-verification gate landed on **exactly 0.950** against a 0.95
threshold. An exactly-at-threshold number was diagnosed instead of accepted, per
the diagnose-any-clean-number rule — and the two disagreements it surfaced were
both the repr case.

### Standing discipline added

> **Canonicalize before comparing, or compare semantically. An equality test
> between representations is a claim about the representation.**

Already implied by #7; made explicit here because implication was not enough to
prevent the recurrence.
