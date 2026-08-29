# The M > 3 arena — preregistration (Gate 0)

**Committed BEFORE the arena exists.** Nothing else is in this directory. The
adversary is specified here, before the environment is written, because the trap
is known: **I would otherwise author the fixture I am then measured against**
(the R14 Part B4 defect). `FINDINGS_BOX_SCALING.md` §11 named this exact
requirement when it stopped the M-sweep at Gate 0.

**Zero credits.** Construction and measurement only.

---

## 1. Why this exists

Every planetary claim this program holds is **analytic**. The scope line is
explicit: *N ≤ 8 agents, M ≤ 3 principals*. `env_federation.principals(m)` slices
a 3-tuple, so requesting M = 100 silently yields 3 — the Gate 0 stop that saved
`FINDINGS_BOX_SCALING` from publishing the opposite of the truth.

**The committed environments are READ-ONLY.** `env_federation.py` and
`env_aggregate.py` are not modified; the arena is new code that imports
`box_bounds` and `concentration` from the committed source so the property under
test cannot drift from the one already published.

## 2. Two experiments, sequenced

Per the decision: **the box sweep runs first as a calibration check that the
arena is sound**, and only then the federation-capacity experiment. If the arena
cannot reproduce an already-established analytic result, nothing it says about a
new one is worth reading.

### Part 1 — CALIBRATION: does the box behave at real M as the arithmetic says?

`FINDINGS_BOX_SCALING` §4b derived, without measuring, that the staleness attack
gets **harder** with scale: a principal breaches only by shedding below `L`, and
the required shed rises from 33.3% of endowment at M=2 to 99.3% at M=100.

AG-3 measured that stale-read admission is unsound at M=3. This asks whether
that unsoundness **decays with M** as the arithmetic predicts.

### Part 2 — THE CLAIM THAT MATTERS: does review capacity federate?

`N ≤ M·h·A / ε`. If each principal brings its own review capacity, throughput
grows linearly with the federation and planetary scale is reachable. If
cross-principal coupling degrades it, it is not.

**The discriminant, stated now:** a bound over **per-principal** state should
federate; a bound over **shared** state should not, because a cumulative bound on
a shared pool does not compose (C7, R13). Both are run.

## 3. THE ADVERSARY — specified before the arena

Fixed here so the environment cannot be shaped to it afterwards.

| | |
|---|---|
| **capability** | may act concurrently with all other principals; reads its own state exactly and others' state only as of the last round (stale) |
| **objective** | drive concentration above κ (Part 1); maximise actions per human review (Part 2) |
| **NOT permitted** | modifying the guard, forging state, reading another principal's private state, or exceeding its own declared bound — an attack that violates a bound tests enforcement, not adequacy |
| **collusion** | N adversarial principals coordinate their shedding within one round; the colluding fraction is swept |

## 4. Damage and capacity measures — computed by the environment

- **`violation_rate`** — fraction of rounds in which `concentration(s) > κ` while
  every principal's local box check passed. Computed by folding state, never by
  reading guard state.
- **`actions_per_review`** — total admitted actions ÷ total escalations. An
  escalation is a round in which any principal's bound is reached.
- **`review_capacity`** — `M · h`, where `h` is reviews per principal per round.

## 5. Decision rules and feasibility ceilings

Checked before the run (discipline #4; three defects of this species have already
occurred here).

| rule | threshold | ceiling | trivially satisfiable? |
|---|---|---|---|
| **R-1 calibration** | `violation_rate` at M=100 is **< half** that at M=2 | violation_rate ∈ [0,1]; AG-3 measured non-zero at M=3, so both ends are attainable | **No** — requires the decay the arithmetic predicts, and a flat or rising rate refutes it |
| **R-2a per-principal** | `actions_per_review` varies **< 2×** across M ∈ [2, 512] | unbounded above; flat is the prediction | **No** — any global coupling breaks flatness |
| **R-2b shared-pool** | `actions_per_review` **falls at least 10×** from M=2 to M=512 | falls as 1/M if fully serialized, so ~256× available | **No** — requires the C7 degradation to be real, not assumed |

**A precondition, not a threshold:** any run in which a principal exceeds its own
declared bound is discarded and rerun. That tests enforcement, not adequacy.

## 6. Point predictions, fixed before data

| | prediction | call |
|---|---|---|
| **P1** | violation_rate falls monotonically in M | **YES** — §4b's required-shed arithmetic |
| **P2** | violation_rate at M=2 is **> 0** | **YES** — AG-3 measured stale-read admission unsound |
| **P3** | per-principal bound: actions_per_review flat in M (R-2a met) | **YES** — no shared term to serialize |
| **P4** | shared-pool bound: actions_per_review falls ≈ 1/M (R-2b met) | **YES** — C7/R13; a cumulative bound over one pool serializes |
| **P5** | the arena reproduces `box_bounds` soundness exactly — **zero** in-box states exceed κ when reads are FRESH | **YES, and DEFINITIONALLY so.** Recorded so the exact 0 is diagnosed rather than reported as evidence |

**P5 is an exact-value prediction and is flagged now** (discipline #2). A clean
zero there is the construction, not a finding.

## 7. What this cannot establish

1. **Not planetary.** M = 512 is three orders below planetary. It tests whether
   the *trend* matches the arithmetic, not the endpoint.
2. **I authored the arena.** Mitigated by specifying the adversary first and by
   testing a **structural** property (does a stated predicate hold under
   concurrent admission) rather than a behavioural one — but not eliminated.
3. **Simulated principals.** No real agents, no real work, no real humans. `h` is
   a parameter, not a measurement of anyone's actual review capacity.
4. **Nothing about correctness.** The arena bounds consequences; whether the work
   was right is the competence bound and is out of scope by construction.
