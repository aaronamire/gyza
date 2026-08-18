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

Standing rule #4 now has **four** instances, and the fourth is a new species of
the same error.

| rule | defect |
|---|---|
| R10 θ\* | threshold unreachable under the environment's parameters |
| R10 TUNABLE clause | trivially satisfiable |
| R11 economy bar 0.40 | exceeded what *any* router could achieve on 2 of 6 MBPP cells |
| **E1-HOLDS** ("within 2× of the M=2 value") | **the BASELINE was exactly 0.000, so the ratio is undefined and the rule is unscorable.** I checked the feasibility ceiling of the measured quantity and not of the baseline the rule divides by. |

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
