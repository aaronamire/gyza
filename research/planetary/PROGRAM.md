# The planetary program — what would have to be true

**Status: an agenda, not a result.** Every claim here is either derived and
labelled derived, measured and cited, or a conjecture and labelled conjecture.
Nothing in this document has been established by it.

**Written before R-D1 and R-B1 were run.** §6 states point predictions so the
results cannot be fitted to them afterwards.

---

## 1. The organizing equation

The whole program reduces to one inequality. It is a **scaling argument, not a
theorem** — its assumptions are stated in §1.2 and each is itself a research
direction.

Let

| symbol | meaning |
|---|---|
| **N** | actions per unit time the system processes |
| **p** | fraction of actions **mechanically verifiable** (PROOF-carried) |
| **c** | fraction of the *unverified remainder* whose **consequences are bounded**, or which are confined to reversible interior |
| **H** | human review capacity per unit time |

Actions that reach a human are those neither verified nor contained:
`N(1−p)(1−c)`. Liveness requires this not exceed capacity, giving

> ### N ≤ H / [(1−p)(1−c)]

**Two levers only, and they enter multiplicatively.** For planetary
N ≈ 10⁹/day against H ≈ 10⁴/day, `(1−p)(1−c) ≤ 10⁻⁵` — five nines of combined
coverage.

### 1.1 The amortization term

The equation above assumes one human decision covers one action. Gyza already
violates that assumption in the right direction: a **capability manifest** is one
human decision that constrains every action an agent takes under it. Writing
**A** for actions covered per human decision,

> ### N ≤ H·A / [(1−p)(1−c)]

and **A is not free.** A policy is safe for as many actions as its declared bound
tolerates, so `A ≈ B / h̄` where `B` is the declared bound and `h̄` the mean harm
per uncontained action. Raising A means either raising the bound — the thing you
do not want — or lowering per-action harm, which is exactly what containment
does. **The amortization factor and the harm bound are the same dial.**

### 1.2 Assumptions, each a research direction

1. Human capacity fixed and non-substitutable → R-D1, R-E4.
2. Escalations independent; no aggregation → R-D1.
3. Sampling not permitted. **Relaxable exactly when deterrence holds** — Route 6's
   `LR ≥ g/w`, measured LR = 19.8 in competence and 1.25 out. So sampling buys
   scale *inside* competence and nothing outside it, which ties Track D back to
   Track A.
4. p and c independent. Almost certainly false; unverifiable actions are
   plausibly the harder-to-contain ones, which makes the bound optimistic.

### 1.3 What may NOT be done with this equation

Our measured p (over **claim types**) and measured harm coverage (over **stateful
action types**) are different populations. **Multiplying them is artifact #17** —
the error that produced a fake erosion curve from a coverage statistic and a
chain-survival statistic. Any instantiation must measure both over one
population.

---

## 2. Track A — Verifiability (raises **p**)

| | question | tractability |
|---|---|---|
| **R-A1** | Can a claim vocabulary be *designed* so p → 1? Typed DSL + symbolic non-learned checker (AlphaProof/Lean, LLM+P, CaMeL are the existence proofs) | **now**, small compute |
| **R-A2** | What fraction of useful work admits a decidable checker *at all*? The counterweight to R-A1 | now, corpus work |
| **R-A3** | Do PROOF-carried chains survive depth? AR-1 measured provenance flat at 1.0000 through depth 8; correctness 0.0 at depth 1 | analytic |
| **R-A4** | Does the competence bound *shift* with frontier models? | needs credits |

**The measured starting point, recomputed from the registry rather than the
document: p = 10/18 = 0.556.** The documented 61.1% predates the FAIL_CLOSED
cutover, which moved `envelope_dag` to carrier NONE. Attesting it restores
+1/18 = 5.6 points — a pending user decision worth more than any code change on
this track.

## 3. Track B — Individual containment (raises **c**)

| | question | tractability |
|---|---|---|
| **R-B1** | Classify every quantity: TRANSFERS / EXTINGUISHES / ALREADY-REALIZED | **now**, analytic + testable |
| **R-B2** | H3 irreversibility — the one declared class never modelled | now |
| **R-B3** | Refuse-early: prevention instead of relocation | now |
| **R-B4** | Widen the reversible interior. 7 of 19 types are interior; **zero** have a per-action undo. Every action moved inside raises c *without needing verification* — the cheapest lever in the equation | now |

## 4. Track C — The collective (the vision's core)

| | question |
|---|---|
| **R-C1** | `aggregate = Σ local + flow across frame boundaries`. For conserved quantities the flow is **exactly** computable. This is the missing term §4.1 says nobody has |
| **R-C2** | For conserved quantities Σ flows = 0, so aggregate harm cannot be the level — it is **who bears it**. Distributional properties are what the box bounds locally at any scale. *Conjecture: bound the distribution, not the drain* |
| **R-C3** | Order parameters and tipping points. Concentration — already bounded by the box — is an order parameter. Descriptive theory exists (statistical-physics models of collective misalignment with adversarial tipping points); the **prescriptive half is ours** |
| **R-C4** | **Beneficial as option preservation.** Computable from state, not a sum of individual harms: does the collective preserve reachable futures? Connects to empowerment, to R-B2, to R-B4 |
| **R-C5** | What adversarial fraction tips the order parameter? BFT gives 1/3 for agreement; alignment tipping points suggest far less |

## 5. Track D — Scale and liveness · Track E — Deployment

**R-D1** the escalation budget (§1). **R-D2** liveness as a first-class metric —
every containment number carries its throughput counterfactual. **R-D3** measure
above M = 3; every planetary claim we hold is analytic.

**R-E1** DDIL under real partition · **R-E2** formal specs extended to the new
gates · **R-E3** supply chain and signed release · **R-E4** the escalation
interface, which at planetary scale is a research object rather than a feature.

---

## 6. POINT PREDICTIONS — fixed before R-D1 and R-B1 run

| | prediction | call |
|---|---|---|
| **P-D1a** | With H = 10⁴/day and A = 1, planetary N = 10⁹ requires `(1−p)(1−c) ≤ 10⁻⁵` | YES — arithmetic |
| **P-D1b** | At our current coverage, maximum safe N is **below 10⁶/day** — i.e. several orders short of planetary | YES |
| **P-D1c** | Amortization (A ≫ 1) is a **larger** lever than any plausible improvement in H | YES |
| **P-B1a** | **Credits and market capital are the ONLY conserved quantities in the vocabulary.** Everything else — content, authority, storage, permissiveness, emission counts — is non-conserved | YES |
| **P-B1b** | Therefore the harm-**transfer** problem is confined to the economic layer, and every other class, once modelled, genuinely EXTINGUISHES | YES |
| **P-B1c** | H4 is ALREADY-REALIZED, not extinguishing: the work ran before the refusal | YES |

**If P-B1a/b hold, the outlook for c improves substantially** — the transfer
result would bound one class rather than poisoning the whole model. That is a
strong claim and it is stated *before* the classification, deliberately.

---

## 7. What this program cannot reach

1. **Non-conserved collective harm has no distributional reduction.** R-C2 works
   precisely *because* conservation forces Σ flows to zero.
2. **Emission is terminal** (C15). Nothing after it is containable, and no
   detector helps.
3. **R-C4 tells you what to measure, not how to bound it locally.**
4. **The competence bound is not repealed by any of this.** Track A routes around
   it for designed vocabularies; the residue in R-A2 is permanent.
