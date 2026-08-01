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
