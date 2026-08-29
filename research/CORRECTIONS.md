# Corrections of record

**Every claim in this corpus that is now known to be wrong or narrower than it
reads, and where its correction lives.**

## Why this file exists

The established pattern here is right: a superseded finding **stands unedited**
and its correction lives in the new document (`FINDINGS_BOX_SCALING` §5 does
exactly this to `FINDINGS_ROUND3_DISTANCE` §4c). That preserves the record of
what was believed and when.

It also makes corrections **undiscoverable.** A reader of
`FINDINGS_BOX_SCALING` has no way to learn that §4b was later refuted. The
corpus is 144 tracked markdown files; nobody reads them in commit order.

So this is the index. It edits nothing. It applies the ledger discipline —
*cite the entry, never the tally* — to corrections rather than to artifacts.

**A claim not listed here has not been checked, not "verified correct."** This
file is sound in one direction only.

---

## 1. `aggregate/FINDINGS_BOX_SCALING.md` §4b — **REFUTED**

**Claimed:** the staleness attack *"gets harder with scale"* — the required shed
rises from 33.3% of endowment at M=2 to 99.3% at M=100, so violations should
decay as the federation grows.

**Now known:** the arithmetic is correct and **does not protect the box.** The
floor `L` falls as 1/(m−1) by the same factor, so an agent shedding *to the
floor* scales its attack exactly with the defence. They cancel. Measured
violation rate is **flat from M=8 to M=512**.

**Sharper replacement:** the box's soundness is a property of **single-threaded
principals**, not of scale. With one agent per principal it is sound at every M;
with two it is breached at every M, and n=2, 4, 8 are identical. Concurrency,
not scale, is the control parameter — and any deployment running more than one
agent per principal is outside the guarantee.

**Correction:** `research/arena/FINDINGS.md` (`b6a37b7`).

## 2. `aggregate/FINDINGS_BOX_SCALING.md` §4a — narrowed, **in-file**

"Cheaper at scale" is true per participant and false in aggregate: `(m−1)L` is
invariant in m. Already corrected by §7 of the same document. Listed so the
index is complete.

## 3. `prior_art/FINDINGS_ROUND3_DISTANCE.md` §4c — **SUPERSEDED**

Claimed planetary-scale collective-harm bounding is *"structurally obstructed."*
Superseded by `FINDINGS_BOX_SCALING` §5, which already carries the correction.
The reading error was treating *"no **exact** local test exists"* (completeness)
as *"no local bounding exists"* (soundness).

## 4. "Bounding a consequence TRANSFERS harm" — **OVERSTATED**

Stated in session summaries on 2026-08-14 as a general property of harm bounds
and a general blocker on the vision.

**Now known:** transfer follows from **conservation**, definitionally. Gyza's
vocabulary contains exactly two conserved quantities and **six of ten
declarable quantities EXTINGUISH** when bounded. The transfer result bounds one
class; it does not poison the model.

**Correction:** `research/planetary/R_B1_FINDINGS.md` (`270f391`).

## 5. PROOF-carried claim types — **DO NOT CITE ANY NUMBER FROM A DOCUMENT**

`OPEN_PROBLEM.md` §2.7 reports **61.1%** (11 of 18). That figure moved **three
times on 2026-08-15 alone**, and I wrote a correction here that was itself stale
within minutes — which is the actual lesson, so it is recorded rather than
tidied away.

| when | value | why it moved |
|---|---|---|
| as documented | 11/18 = 0.611 | — |
| after the FAIL_CLOSED cutover | 10/18 = 0.556 | `envelope_dag` routed to carrier NONE: its success condition was not fixed by the registry, since production called `verify_dag` both ways. Refusing to count an unattested carrier claim **lowered** the number honestly. |
| after the determinacy repair | 12/19 = 0.632 | `envelope_dag` split into closed/open, each proving one proposition |
| after attestation landed | **13/19 = 0.684** | `external_send_content`'s policy bound out and attested |

**A split raises the count without adding any verification capability.** Read
these as defects being repaired, not as capability gained.

> **Recompute from the registry. Never cite a number from any document,
> including this row — it will be wrong again.**

## 6. `ENGINEERING_STATUS.md` capability paragraph — **RESOLVED 2026-08-15**

The prior paragraph said Gyza *"bounds declared harm classes against declared
bounds, over a harm model currently covering 13.3% of the stateful action
vocabulary."* It was **too weak** when written (no runtime path consulted the
harm model at all) and **too strong** later (it implied enforced consequence
bounds; H1 was retired, H2 has no production existence, H3 is unmodelled, and
**no declared class is enforced at runtime**).

**Replaced** by an owner-selected statement that leads with the aggregate-
alignment results, states the substrate as working, and names what is not
claimed. The prior text stands unedited beneath it. The suspension is lifted:
the new paragraph **is** the one to reuse.

## 7. `HARM_MODEL_GAP.md` — two entries now have code

Listed storage growth and several others as "declarable, existing code: **none**."
`H5_storage_growth` now exists and is bounded at 10 GB
(`gyza/containment/gyza_model.py`). `H6_unsupervised_actions` is new and was not
in that enumeration at all.

## 8. `guard_bounds.json` `H1_credits: 100.0` — **RETIRED**

The level refused every real model's first action (Sonnet 40,000 credits, Opus
120,000 against a bound of 100). Credits are `TOKEN_IS_FAKE`, so no level in
them is checkable. Retired 2026-08-15 by owner decision; listed in `UNMODELLED`
so the gap stays reported.

**Correction:** `research/planetary/R_D1b_FINDINGS.md` (`923a388`), retirement
in `a29f2e5`.

## 9. `aggregate/FINDINGS_RESERVATION.md` — **NARROWED to M ≤ 3**

**Stands as measured.** Every cell in it ran at M ≤ 3, because
`env_federation.principals` silently sliced a fixed 3-tuple.

**Now known:** reservation is exact at M = 2 because there is exactly **one**
other principal, so no other-caused change exists inside a round and its pinned
origin cannot be stale. The mechanism §3 correctly identified needs **≥ 2 other
actors** and first appears at M = 4 — where reservation becomes
**indistinguishable from no guard at all** (0.975 vs naive's 0.975) and stays so
to M = 512. `PARTITIONED_READ` dominates it at every M ≥ 4.

`RESERVATION-PARTIAL` is therefore not wrong; it was measured in the one regime
where the guard's own failure mode is unreachable.

**Correction:** `research/escrow/FINDINGS.md` §2.

## 10. `harm_redteam/damage.py` D2 `lockout_breadth` — **UNDER-REPORTS**

D2 is `{earners who delivered} − {earners who were paid}`, so an earner paid for
*some* entries and not others counts as not locked out. Measured **0.0 while D1
was 80.0** — in exactly the case it was built to illuminate. Sound only for
earners paid nothing at all.

**Correction:** `research/escrow/FINDINGS.md` §3.4.

## 24. `churn/FINDINGS.md` §3 — the adversary caveat is REMOVED

R-C refuted CHURN-BREAKS but weakened its own refutation: defectors migrated to
the fullest pool, collided in one cluster, and a concentrated attack is weaker.
R-C named deliberate dispersion as the untested case that could overturn it.

**Now known: dispersal is STRICTLY WORSE for the attacker.** It never breaches
at any k in [1, 511], against 511 for colliding and 103 for stationary. R-C's
conclusion stands WITHOUT its stated limitation.

**Correction:** `research/disperse/FINDINGS.md`.

## 25. My own cluster-visit argument was in the wrong currency

R-D's preregistration §1 predicted k* ~ 20 by computing cluster-visits x
damage-per-visit. Measured: no k breaches at all, while destroying 96% of all
federation value.

**Damage is the wrong currency for a RATIO.** Concentration is scale-invariant,
so uniform destruction is inert; an attacker must maximise ASYMMETRY. The
argument would have been correct for a bound on total value -- and a total-value
bound would have been breached catastrophically by the same attack.

## 23. `horizon/FINDINGS.md` §6.5 — the churn caveat is NOT needed

R-N listed churn as its largest untested dependency and expected it to restore
the horizon.

**Now known: it does not.** Under maximal adversarial churn the tree's margin
still saturates -- 68.9% of ceiling against R-N's 68.68%, identical at eps=32
and 128. Churn breaks compartmentalisation of REACH completely (a defector
touches 41 of 64 clusters) and that turns out not to be load-bearing: migration
relocates a principal's entitlement rather than duplicating it.

The corrected mechanism: a stale reader's error is bounded by THE ENTITLEMENT IT
HOLDS, not by the set of pools it can reach.

**Correction:** `research/churn/FINDINGS.md`. R-N stands unqualified.

## 22. `hierarchy/FINDINGS.md` — composability is NOT what makes it work

R-H1 made composability look like the sufficient condition for hierarchical
enforceability. It is not.

**Now known:** concentration composes at EVERY staleness -- the inequality does
not depend on eps -- yet flat enforcement fails at eps=16 with no feasible
margin anywhere below the ceiling. A second condition is required: the shared
resource a stale reader is stale ABOUT must be bounded. Composition is a
property of the aggregate; that is a property of the PARTITION.

**Correction:** `research/horizon/FINDINGS.md`.

## 20. `defector/FINDINGS.md` — narrowed by topology

A2 concluded the aggregate bound is a compliance assumption because ONE defector
breaks it at every scale, and that "the profitable defection is also the
effective one".

**Now known: both statements are properties of a FLAT federation.** Under a
3-level tree the same shed attack needs **103** defectors rather than 2, the
invariant is **~1.6 defectors per CLUSTER**, and the hoarding attack -- the
profitable one -- **stops breaching entirely**, because a hoarder can capture
only its own cluster's commons (payoff 3086 -> 61.88).

A2 is not overturned: defectors still break the bound. What changes is the
price, and that cluster size is the security parameter.

**Correction:** `research/blast/FINDINGS.md`.

## 21. R-B repeated E1-HOLDS's defect one route after recording it

R-B's preregistration asserted "k* >= 1 by construction, so a ratio is
well-defined here -- unlike E1-HOLDS, whose baseline came out exactly 0.000."
It then divided by zero for the same reason: at delta=0 the flat topology
already breaches with ZERO defectors, so k*(d=1)=0.

Recorded because the failure mode was NAMED IN THE SAME SENTENCE that walked
into it. Citing a defect is not checking for it.

## 18. `margin/FINDINGS.md` "and runs out" — **REFUTED (scan artifact)**

R-M1 reported **INFEASIBLE** in four cells and built a headline on it. The delta
scan stepped by 1/40 from 0 and, against a ceiling of 0.5980, tested 0.575 and
then exited — **never testing (0.575, 0.598)**. All four cells are safe there
(0.590-0.595).

**Now known:** the margin does **not** run out; it approaches the ceiling
asymptotically, needing **99.2%** of it at eps=4, M=512. Severe, and a weaker
claim than infeasibility. M-GROWTH and every control survive untouched.

A **search-coverage** defect, not a feasibility-ceiling one: correct bound,
correct rule, scan that did not cover the interval the rule ranged over. R-M1
listed monotonicity-in-delta as a control, and monotonicity makes it *worse* --
under a monotone response the untested interval was where a positive result was
most likely.

**Correction:** `research/margin/CORRECTION_INFEASIBLE.md`.

## 19. R-H1's positive control agreed with R-M1 *including on the bug*

R-H1's d=1 arm reproduces R-M1's delta* exactly at every eps -- and reproduced
its false INFEASIBLE too, because both implementations shared the scan
structure. **A positive control confirms what two instruments share, which
includes their shared mistakes.** Recorded because the agreement was cited as
the strongest validation either route had, and it was, for everything except the
one thing they had in common.

## 16. `margin/FINDINGS.md` — its constructive result needs ENFORCEMENT, not compliance

Not a refutation. R-M1's finding that bounded activity makes a cross-principal
aggregate unreachable is intact — **among principals that run the check.** Every
cell assumed universal compliance.

**Now known:** **one** principal ignoring its guard breaks the bound at every
scale to M = 512 (k\* = 1, 1, 2), because its damage travels through the
**shared pool**, not through its own term in `max/sum`. Impact is O(1), not the
O(1/M) I derived. A node running *old* software (floor but no margin) is far more
tolerable — 23 of them at M = 512 — so honest heterogeneity is survivable and
malice is not.

**Correction:** `research/defector/FINDINGS.md`.

## 17. Both closed forms in this program have now failed

R-M1 §2c was conservative by ≈2× and **changed sign at the feasibility
boundary**. A2 §1a predicted φ\* ∈ [0.409, 0.586] at M = 8 against a measured
**0.1429**, because it computed a ceiling against a denominator held at `U·M`
while the compliant population was simultaneously shrinking it.

Recorded together because the species is one: **a closed form derived over the
wrong denominator looks exactly like a correct one until it is measured.** Both
stand unpatched; the simulator is ground truth in both routes.

## 14. `HARM_MODEL_DRAFT.md` §H3 "external network sends" — **MIS-CLASSIFIED**

Cites `send_message`, `publish_agent`, `publish_delta` and `publish_attestation`
as sends that *"leave the modeled system entirely"*.

**All four are mesh-INTERNAL.** `send_message` writes to a libp2p `peer_id`;
`publish_agent` and `publish_attestation` are DHT puts under `/gyza/`;
`publish_delta` is gossipsub. Every one lands on another `gyza-netd` with its own
chain and gate. They are federation, not exit.

**Now known:** C15's boundary is a property of **deployment topology, not a
law** — the set of destinations lacking a model shrinks as the mesh grows,
making H3 the only declared quantity that *improves* with scale. H3 is
reclassified three ways (attested / unattested / outside-protocol) and measures
the latter two.

**Correction:** `research/H3_MESH_EXIT.md`, implemented in
`gyza/containment/egress.py`.

## 15. `ENGINEERING_STATUS.md` §5 said "kernel-enforced" — **CORRECTED**

The v0.1.2 release swept all five occurrences from `README.md`. **Eleven
survived elsewhere**, including user-facing `gyza` CLI output and the bounds
demo. Ten corrected to "OS-enforced (bubblewrap: namespaces + seccomp)".

**One left standing on purpose:** `gyza/sandbox/config.py:382` says *RLIMIT_AS is
kernel-enforced*, which is **true**. A blanket replace would have introduced an
error while removing one — the reason this was done per-site rather than by
`sed`.

## 13. R-M1 confirms `escrow/FINDINGS.md` §2.6 from an independent instrument

Not a correction — a **cross-instrument confirmation**, recorded because this
index is where such things stay discoverable. The escrow route found that
`env_federation`'s `pool_claim` reads `contrib`, which withdrawal never reduces,
so a principal cannot fully divest. `research/margin/`, built afterwards and
transcribing the same arithmetic independently, reproduces it exactly: the pool
decays geometrically (24 → 18 → 13.5 → 10.1 → 7.6 at M=4) and never empties.

Found because I wrote a test asserting the opposite. **The test was wrong, not
the code**, in both instruments.

## 12. `escrow/FINDINGS.md` — `PARTITIONED_READ` "improves with scale" — **REFUTED**

Claimed partitioned-read admission *"strictly dominates at every M ≥ 4 and
**improves** with scale"* (0.000 from M = 8).

**Now known:** the zeros are a **float-boundary artifact**. Partitioned sheds to
exactly `L`, and `L` is *defined* as the floor where concentration equals κ, so
it drives the system to the bound and holds it: M = 512 settles at
κ − 4.8e-10, M = 64 at κ + 5.6e-9, against a check with a 1e-9 tolerance. The
gap between "0%" and "98%" is **1e-8 of concentration**. A tolerance sweep flips
partitioned 0.81 → 0.00 between 1e-9 and 1e-6 while `naive` and `reserved` stay
flat across nine orders of magnitude. It is also *slower*, not safer: at M = 64 it
reaches 0.981 given 1000 rounds instead of 40.

**The E1 verdict is unaffected** — it rests on the two tolerance-insensitive arms.

**Fifth float-boundary instance, and the second misdiagnosed as structural**
(first as a "seed effect", now as a scaling trend). Both readings were the
flattering one.

**Correction:** `research/escrow/CORRECTION_E1_PARTITIONED.md`.

## 11. "Bounding a consequence TRANSFERS harm" — **third refinement**

Entry #4 narrowed this from a general blocker to a consequence of conservation.
It now has a constructive counterpart *and* its limit, both measured: escrow
drives `unpaid_delivered_work` to exactly 0, but the same 80 credits reappear as
work **never commissioned**. Escrow converts a **realized loss** into a
**forgone gain**; it does not make the counterparty whole. Under R-B1's
quantity taxonomy that is an EXTINGUISHES conversion; under a welfare measure it
is still a transfer, and **no one has chosen which measure governs.**

**Correction:** `research/escrow/FINDINGS.md` §3.2.

---

## Predictions I made and got wrong

Recorded because a program that only publishes its confirmed predictions is not
running the discipline it claims.

| prediction | outcome |
|---|---|
| **P-D1c** amortization is a *larger* lever than human capacity | **WRONG** — `H` and `A` enter as a product; identical. The real asymmetry is that one is bounded by hiring and the other by the harm bound. |
| **P-A1** `A` is order 1–100, "the lever is near-unused" | **WRONG** — measured 0.0008–1.0. Not near-unused; *inverted*. |
| **P1** (arena) violation rate falls monotonically in M | **REFUTED** — flat from M=8 to M=512. |
| **P-E1** reservation's violation rate is roughly flat in M | **REFUTED at the M=2→4 step** (0.000 → 0.975). Flat only *above* the step. |
| **P-E2b** `idle_escrow` ≥ 25% of the bound | **MALFORMED, not merely wrong.** The quantity is a free deployment parameter: 20% / 40% / 100% for 1 / 2 / 5 items in flight. A single number could not have been right. |

## Decision rules that failed their own feasibility check

Standing rule #4 now has **five** instances. The fourth and fifth are each a new
species: the fourth checked the measured quantity but not the baseline the rule
divides by, and the fifth checked the ceiling of the system under test but not
of the route's own liveness bar.

| rule | defect |
|---|---|
| R10 θ\* | threshold unreachable under the environment's parameters |
| R10 TUNABLE clause | trivially satisfiable |
| R11 economy bar 0.40 | exceeded what *any* router could achieve on 2 of 6 MBPP cells |
| **E1-HOLDS** ("within 2× of the M=2 value") | **the BASELINE was exactly 0.000, so the ratio is undefined and the rule is unscorable.** I checked the feasibility ceiling of the measured quantity and not of the baseline the rule divides by. |
| **R-H3L liveness bar** (`N = 1000` benign actions) | **satisfiable but not meaningful.** 1000 actions is under an hour at this program's own 26k/day figure, so the bar made Q-BYTES look adequate over a horizon nobody would deploy. |

## Apparatus defects found in my own instruments

Four in the M>3 arena, each producing a publishable-looking number, **all
failing in the reassuring direction**: an adversary too weak to shed at all, one
actor per principal where the box is sound *by construction*, symmetric shedding
that cannot move a ratio, and a float boundary at exactly `L` — which I
diagnosed in print as a "seed effect" in the same output whose data refuted it.

Detail: `research/arena/FINDINGS.md` §4.

**Five more in the escrow route**, same direction. Three in the coupled arena: a
rotating target (so concentration could not accumulate and *all three arms*
scored 0.0000 at M ≥ 8), an ungated pool drain (so every arm scored identically),
and shedders that could not divest their pool claim (so the box looked sound at
M ≥ 4 for reasons internal to the instrument). Two in E2, **both of the AN ERROR
IS NOT A VALUE species**: a harm class registered with no invariant, and
`float(Credits)` raising inside the quantity function — the engine reported each
through the same channel as a bound breach, and **the two runs produced
byte-identical tables.** Neither was visible in the result; both were found only
in stderr.

Detail: `research/escrow/FINDINGS.md` §6.

## 26. R-M1's stride defect recurred in R-E, in code written by someone who had recorded it

`research/extensive/run_extensive.py` set the top of its delta scan to
`(int(ceiling/GRID) - 1) * GRID`. At d=1 the ceiling is 0.5980, so the scan
stopped at 0.5900 -- and the ONLY feasible delta is 0.5950. The route reported
**INFEASIBLE at every epsilon for both bound types**, for a feasible band that
exists.

It was caught by the COVERAGE rule the preregistration itself carries ("every
INFEASIBLE swept ceiling-down THEN interior"): an exhaustive 119-point grid
sweep found 1/119 safe, at the point the scan had excluded.

This is the SAME SPECIES as R-M1's original defect -- a scan stride that never
tests the feasible band -- committed one route after `research/margin/
CORRECTION_INFEASIBLE.md` was written about it. **Knowing a defect species does
not prevent it; only the mechanical coverage rule caught it.** Pinned by
`test_top_of_grid_is_below_ceiling_and_is_the_largest_such_point`.

## 27. `hierarchy/FINDINGS.md` -- the benefit is the LEAF FLOOR, not the internal checks

R-H1 established that a d-level tree of local box checks outperforms a flat
box. R-E instrumented the internal admission checks over 47,523 divest attempts
across four (delta, epsilon) configurations and **they fired zero times.**

- Level 1 is unfireable BY CONSTRUCTION: with `want = believed - floor`, the
  check reduces to `(cum_div - v_div) < 0` and cumulative divestment is
  monotone non-decreasing.
- Levels >= 2 never bind because `box_floor_at` scales the floor with the level
  endowment exactly as that level's value drains.

So the tree's advantage is carried entirely by `kappa_level(d)` tightening every
LEAF's own floor -- 0.5304 at d=3 against 0.0261 at d=1, a 20x difference.
**R-H1's result stands; the mechanism attributed to it does not.** A reader who
concluded "internal nodes catch what leaves miss" would be wrong, and would
build the checks rather than the floor.

This also mis-specified R-E's own preregistered flat control, which disabled
internal checks while keeping the d=3 floor and therefore tied 6/6 cells
exactly. Diagnosed under standing rule #2 rather than reported. Pinned by
`test_internal_admission_checks_never_fire`.

## 28. `blast/FINDINGS.md` -- the governing quantity is CLUSTER COVERAGE, not defectors per cluster

R-B's headline: *"k* rises 2 -> 37 -> 103 while k*/clusters is flat at ~1.6.
The governing quantity is defectors per cluster, not defectors total."*

R-T ran five placement rules over the identical environment. `k*/clusters`
ranges over **0.86 to 1.70, a factor of two**. `clusters_covered` at k* is
**55 in all five arms**:

| arm | k* | k*/clusters | clusters covered |
|---|---|---|---|
| CONCENTRATE | 109 | 1.70 | 55 |
| RANDOM (R-B) | 103 | 1.61 | 55 |
| SPARE | 105 | 1.67 | 55 |
| EVEN_ALL | 55 | 0.86 | 55 |
| SPARE_EVEN | 55 | 0.87 | 55 |

Coverage predicts breach **per seed**, not merely in aggregate: at k = 102 the
three RANDOM seeds cover [53, 48, 54] and none breaches; at k = 103 they cover
[53, 49, 55] and only the 55 breaches, with 11 violations.

**1.61 is what a Poisson process costs to reach 55-cluster coverage**, because
random placement wastes defectors by doubling them into already-covered
clusters. R-B's DIRECTION stands -- topology bounds damage, k* rises with depth
-- but the quantity it named is placement-dependent and the invariant is not.

**Safety consequence: R-B's k* = 103 is LOOSE BY 1.87x.** The honest tolerance
for that environment is 55. Every k* this program published against a
randomly-placing adversary is an over-estimate of what the federation survives.

This is the SECOND correction of this species -- a quantity that CORRELATES with
the protected one being reported in place of it (see the GuardConfigStore note
in CLAUDE.md, where a version integer stood in for permissiveness). Pinned by
`test_cluster_coverage_is_55_in_every_arm`.

## 29. R-T's OWN headline was the species R-T's own CORRECTIONS 28 names

`targeted/FINDINGS.md` was first published with the verdict
`COVERAGE-IS-THE-INVARIANT`, on evidence of `clusters_covered = 55` in all five
placement arms at d=3, confirmed per seed.

**Its own Sec 6.1 said the check that would falsify it had not been run:**

> *55/64 = 0.859 was measured at d = 3 only. Whether the FRACTION is stable
> across depth, fan-out and margin is untested -- R-B's 1.61 looked stable
> across d = 2 and d = 3 too, and it was an artifact.*

Running d=2 (f=23) falsified it immediately:

| d | arm | k | covered | total | breach |
|---|---|---|---|---|---|
| 2 | EVEN_ALL | 24 | **23 (full)** | 23.598 | **no** |
| 2 | EVEN_ALL | 25 | **23 (full)** | 23.252 | **yes** |

**Identical coverage, opposite verdicts** -- and the 1.000 is a saturated metric,
the third occurrence of that species here (R-B's `clusters_damaged` 64/64, R-D's
`clusters_below_half` 64/64).

The invariant that survives both depths is **total remaining value**: `max` is
inert at 14.000-14.003 across every arm, k and depth, so breach is governed by
the denominator alone. Coverage, defectors-per-cluster and defector count are
all topology-specific proxies for it.

**Two lessons, and the second is the one that cost something.** First, this is
the same species as 28 -- a correlate reported in place of the protected
quantity -- committed in the same commit that named it. Second: **the limitation
was correctly written down and the claim was published anyway. Writing the caveat
is not a substitute for running the check**, and a Sec 'what this cannot
establish' entry that is one cheap run away from being resolved is a TODO, not a
disclosure. Pinned by `test_coverage_is_not_invariant_across_depth`.


## 30. R-H3L's liveness bar was checked for the system and not for itself

`research/h3_level/PREREGISTRATION.md` §3 does standing rule #4 properly for the
system under test. C1 derives, from the code and before any data, that Q-COUNT
rises by exactly 1 per action — and the run reproduced 1.000 exactly. That check
worked and it decided the route.

**The decision rule's own threshold got no such treatment.** §6 fixes liveness
at "a benign node completes ≥ 1000 actions" with an argument only about why 1000
is not *too small* for Q-COUNT. Nobody asked whether it was large enough to
mean anything. At 26,000 actions/day — this program's own planetary figure —
**1000 actions is under an hour.**

The consequence is not a wrong verdict; `Q-BYTES-CARRIES` is correct as scored.
The consequence is a verdict that reads as adequacy and is not:

| benign lifetime | catches only adversaries above |
|---|---|
| 1,000 actions (~1 hour) | 10× benign |
| 26,000 actions (1 day) | 260× benign |
| 9,490,000 actions (1 year) | **94,900× benign** |

A separating level exists iff `b_adv/b_benign > N/K`, so the threshold ratio of
10 that the sweep located is not a fact about Gyza — **it is `1000/100`, the two
numbers in my own rule.** A rule can be feasible, non-trivial, and still measure
a horizon nobody operates over.

**The generalisation is the useful part:** a feasibility ceiling must be computed
for the *decision rule's parameters*, not only for the quantity the rule scores.
Both R-H3L and E1-HOLDS put the check on one side of the comparison and left the
other side unexamined.

Reported as preregistered rather than rescored — `FINDINGS.md` §3a carries the
correction beside the verdict, and `test_h3_level.py` pins the linear
degradation so the ratio cannot be quoted without its horizon.


## 31. R-EVID Part A said the cumulative level "is dominated". It is dominated ONLY where the measurand already carries evidence

`research/evidence/THEOREMS.md` §3 states that CUSUM over the same log buys
benign lifetime exponentially while paying linearly in delay, and concludes the
cumulative level "is not merely suboptimal — it is dominated by a statistic
computable from exactly the same log."

**Part B measured it and the flat claim is wrong at the low end.** At matched
detection delay (K = 100 actions):

| `ρ` | CUSUM lifetime | LEVEL ceiling | advantage |
|---|---|---|---|
| **1.05** | 45.8 | 105.0 | **0.4× — WORSE** |
| **1.20** | 223.7 | 120.0 | 1.9× |
| 1.50 | 21,204.8 | 150.0 | 141× |

The preregistered bar was ≥10×; it fails at ρ ≤ 1.2 and holds from ρ ≈ 1.5.

**The failure was derivable from Part A's own §4 and I did not derive it.** As
ρ → 1 the evidence D → 0, so by Wald's identity the observations required
diverge and no threshold meets the delay budget without collapsing the
false-alarm rate. §3 was written about the *asymptotic* regime and stated
without its domain of validity; §4, two sections later, contains exactly the
condition that bounds it.

**The corrected statement is stronger than the one it replaces:** the optimal
test is bounded by the same evidence that bounds the naive one, so *the
measurand, not the test, is the binding constraint.* That is the route's thesis,
and stating domination flatly obscured it.

**Species:** a claim asserted in its asymptotic regime and reported without the
condition, where the condition was already written down elsewhere in the same
document. Related to 29 — writing the caveat is not a substitute for running the
check — but distinct: here the caveat was not even written where the claim was,
though the material for it was two sections away.

Not scored as a failure of standing rule #4: the preregistered bar (10×) was
feasibility-checked on both sides and did its job by *catching* this. The defect
is in Part A's prose, and Part B's data is what found it.


## 32. "Six theorems, first ever" — the mathematics is classical and the application was published five months earlier

R-EVID Parts A and C separated classical from contributed in their own §6 and
cited Wald, Page, Lorden, Moustakides, Lindley, Cramér–Lundberg and Kingman. The
documents were not dishonest. **The framing around them drifted anyway**, and by
the end of the session the claim in play was that the route had produced six new
theorems.

A prior-art pass (`research/evidence/PRIOR_ART.md`) refutes it:

- **Theorem 5, presented as the deepest contribution, is Neely's virtual-queue
  technique** — `Q(t+1) = max(0, Q(t) + a − b)` with Lyapunov drift, foundational
  in stochastic network optimization and textbook since ~2010. "Safety virtual
  queues" already exist in network control.
- **Theorem 6 is queue stability**, `λ < μ`.
- **Theorem 2 is why token buckets exist** — the quota-vs-rate-limit distinction
  is standard systems engineering.
- **The agent application is prior art**: Sahoo's Irreversibility Budget (ICLR
  2026 workshop, arXiv 2603.03515, March 2026) defines `IC(t) = Σ ι(aⱼ)` with
  human re-authorization at `IC ≥ I_B`, and `ι = 0` for reversible actions — our
  SILENCE case as a design feature.

**The species is not a false measurement.** Every number R-EVID reports still
stands; `b = 0.000`, `ρ = 1.000`, the two live defects, all reproduce. What
failed was the NOVELTY claim wrapped around them, and it failed because the
citation work was done inside the documents and then not carried into how the
result was described.

**Generalisable lesson:** citing prior art in a §6 does not protect a claim if
the headline is written as though §6 were not there. `FINDINGS_PRIOR_ART.md` §3
had already reached exactly this conclusion about the competence bound — *"it has
a name, and it is not ours"* — and that precedent should have been applied to
R-EVID before the framing hardened, not after.

**What survives is in `PRIOR_ART.md` §4** and it is narrower: the
classification-as-audit-method, the measured finding that a real system's signed
bounds are mostly timers, and the defects the method found.

---

## #33 — I proposed the wrong remedy for the tier gap, and the label agreed with me (2026-08-23)

Arena 2 found that `required_tier` was enforced only in `get_unclaimed`'s WHERE
clause. `FRONTIER_LEDGER.md` offered two remedies: **(a)** make the tier a sixth
attenuated dimension of `CapabilitySpec` and extend the monotone-attenuation
theorem to cover it, or **(b)** rename it to a routing hint carrying no
authority. I described (a) as "what the name promises".

**(a) is a category error, and it would have made the system worse.** Three
independent reasons, each checkable against the tree:

1. **The hazard is a FLOOR, the theorem is a CEILING.** `required_tier` means
   "this work needs an executor attested *at least* this well" — a floor on the
   executor at the moment of execution. Attenuation is `child ⊆ parent`, i.e.
   `child.tier ≤ parent.tier` — a ceiling on a delegate at the moment of
   delegation. Different quantities, different moments, sharing an integer.
2. **It refuses the safe direction and permits the hazard.** Under (a) a tier-1
   agent delegating to a *better*-attested tier-3 agent is REFUSED (`3 ≤ 1` is
   false), though that subcontractor is exactly what a tier-3 work item wants.
   Meanwhile a tier-3 agent handing tier-3 work to a tier-0 agent — the real
   hazard — passes cleanly, since `0 ≤ 3`.
3. **It is undefined for one of the three projections.** `CapabilitySpec` is
   projected from a manifest, a delegation grant, and a bubblewrap enforcement
   record (`delegation.py:179`); that is what buys "one predicate covers every
   edge". A bwrap record has no notion of attestation, so the sixth dimension
   would carry a `None` meaning *not applicable*, colliding with the `mem_cap` /
   `rate_cap` `None` that means *not declared* — an asymmetry the module calls
   load-bearing precisely so an omission cannot launder a granted cap.

**What was implemented instead** is neither (a) nor (b): the tier is a
**precondition on the executor**, refused at `AgentRunner._require_attested_tier`
*before the work runs*, reading the compositor-signed manifest. The claim-time
filter is advisory, self-reported, and documented as defeated by a liar.

**The species.** This is the same shape the program keeps meeting — a check
landing on something that CORRELATES with the protected quantity rather than the
quantity itself — but one level up, in the *remedy* rather than in the code.
Both (a) and the correct fix compare the same two integers; only one of them
compares them at the moment and in the direction that the hazard occurs. **The
integers agreeing is not the mechanism agreeing**, which is precisely what
Arena 2's own A8 defect had taught, four hours earlier, about attributing a
refusal to a mechanism that did not fire.

**Not a ledger artifact:** it produced no clean number that turned out false. It
was found by re-deriving a recommendation when asked to justify it, which is the
same move that caught three defects in the CLAUDE.md rewrite session.

---

## #34 — our own proposal quoted the mock-runner ceiling as the deployment envelope (2026-08-24)

`research/scale/FINDINGS_COORDINATION_CEILING.md` is careful. It decomposes
throughput **by agent kind**, states that a sandboxed action costs 305 ms, that
one core sustains **3.3 such actions per second**, and — in bold — that *"this
dominates everything else by 3,362×; coordination throughput is irrelevant next
to it for any agent doing real work."* It converts honestly: 500 real agents at
one action per second is **~150 cores**, and 500,000 sandboxed runners is *"not
feasible in any configuration measured here."*

**The DICE technical volume then quoted the other row.** Its §3.3 read:

> *"That places 500 agents comfortably inside the envelope (400× headroom) and
> 500,000 AgentRunners about 2.5× beyond a single blackboard."*

Those figures are the **mock-runner poll ceiling measured on an empty board** —
a read that returns nothing, scores nothing and claims nothing. Presented as a
deployment envelope, they overstate capacity by roughly the 3,362× the source
document had already flagged.

**The species is artifact #17's**, and this is its second appearance: two
numbers with compatible units and a plausible ordering, joined into one story
about different populations. The first instance plotted a coverage statistic
against a chain-survival statistic. This one plotted *polls* against *actions*.

**What makes it worth recording rather than quietly fixing:** the research was
right and the summary of it was wrong. The error entered at the boundary where
a measurement is restated for a different audience — which is exactly where
`#32` entered too (*"citing prior art in a §6 does not protect a claim if the
headline is written as though §6 were not there"*). **The restatement is a
distinct artifact from the measurement and needs its own check.**

Fixed by carrying the source document's own decomposition table into the
proposal verbatim, leading with the sandbox row, and stating the ~150-core
figure rather than the 400× one.

**Not a ledger artifact:** the ledger is for clean numbers that turned out
false. Both numbers here are true; only their application was wrong.
