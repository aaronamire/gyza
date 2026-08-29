# Amendment to PREREGISTRATION_R10 — declared BEFORE any result artifact

Committed before `env_breadth.py` and every result. `PREREGISTRATION_R10.md`
(`2708379`) is **not edited**; this file records one design refinement, made after
writing the preregistration and **before running anything**, with its reason.

## The issue: the flat token set has a unit-granularity artifact

§1.1 declared `H_lost` over a **flat token set** — "so magnitudes weight
themselves; no arbitrary weights." Writing the implementation surfaced a
consequence I had not thought through when committing that sentence.

RESOURCE assets are counted in **units of one credit**. R9's task-suite states hold
100–1000 credits, so a task's asset total is dominated by resource tokens: in a
T-D state (`P0 = 1000`), one CHANNEL asset is `1/1004 ≈ 0.001` of the total. Under
the flat definition, **a wealthy principal destroys documents and discloses
channels essentially for free**, and the θ sweep would be measuring the arbitrary
choice of credit denomination rather than reversibility.

That is a real property of a flat token set and it is worth reporting. It is not a
good basis for a θ sweep on its own.

## The refinement: two variants, both declared now, both reported

- **`flat` (PRIMARY — the preregistered definition, unchanged).**
  `H_lost = |lost tokens| / |all tokens|` over the flat union of the four classes.
- **`classmean` (SECONDARY — declared here).** Normalize each class to `[0,1]`
  independently and take the **unweighted mean over the classes that are non-empty
  at `s_0`**:
  `H_lost = mean_over_classes( |lost in class| / |class at s_0| )`.
  Equal weight across classes is a stated choice, not a derived one.

Both are computed for every cell. Neither is selected after seeing results: the
**decision rules in §5 are evaluated on `classmean`**, because `flat` is known
*a priori* to be denomination-dependent, and this file records that choice before
any number exists. `flat` is reported alongside in every table, and where the two
give different answers **that difference is itself a reported finding about how a
harm measure must be declared**.

## Why this is disclosed rather than silently implemented

This program has caught nine artifacts where a clean number was definitional,
coupled, or contaminated. A measure whose sweep is dominated by the denomination of
one asset class is precisely that kind of trap. Declaring both variants in advance,
and fixing which one the decision rule reads, is the same discipline R9 applied to
its `events` decomposition and R12 to its V1/V2 analyzer variants.

Nothing else changes: θ values, checkpoint intervals, task suite, guards, agent
counts, concurrency semantics, and all decision rules and point predictions stand
as committed in `2708379`.
