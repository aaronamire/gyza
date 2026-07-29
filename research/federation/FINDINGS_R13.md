# Findings — Route 13: does containment compose across principals?

Write-up per `PREREGISTRATION_R13.md` (`1a1f1e4`), committed before any code that
produces a result. 240 cells, deterministic, `SEED = 1`, **zero model calls**,
85 s. All prior decisions stand. Disclosures are in §7 and are not buried.

---

## DECISION: **FEDERATION-DOES-NOT-COMPOSE**

> **Signature-gated local checks do NOT bound global multi-principal harm.** F2
> drives cross-principal violations to **0 against the unauthorized attack**
> (A3, all 6 cells, both modes) — and still leaks **1–3 violations per cell on
> PARTITIONED, solely-owned assets** under an ordinary benign workload, with the
> joint pool **removed from the action set entirely**. The leak is not about
> authority: every leaking action carried every signature it required.

**A signature authorizes an ACTION. It does not bound a CONSEQUENCE.** And the
reason is the very property the derivation leaned on: **statelessness**. A
stateless check cannot accumulate, so it cannot bound a cumulative quantity. The
property that makes the check partition in breadth is the same property that
makes it unable to bound harm.

**This was my 20% outcome and the one I said must not be softened.** It is
reported at full strength, and **no rescue round is proposed.**

| decision clause | fires? |
|---|---|
| FEDERATION-COMPOSES — F2 violations 0 at M=3/N=4 concurrent, overdraft 0, throughput ≥ 0.70 | **no** — 3 violations, overdraft 1134, ratio 0.429 |
| SIGNATURE-SUFFICIENT-EXCEPT-SHARED — 0 on partitioned assets, overdraft > 0 | **no** — violations persist on partitioned assets with the pool removed |
| **FEDERATION-DOES-NOT-COMPOSE** — F2 violations on partitioned assets too | **YES** |

---

## 1. The headline — F1 vs F2 cross-principal violations

**Violations are a COUNT over `(round, victim principal)` pairs**, as
preregistered (§8.2); the R10-comparable per-round binary is in `r13_result.json`
as `cross_violation_rounds`.

### 1a. Against A3, the unauthorized blind-channel attack — F2 works

CONCURRENT (serialized is identical in sign; see the JSON):

| M | N | F0 | F1 | **F2** | F3 |
|---|---|---|---|---|---|
| 2 | 1 | 2 | 2 | **0** | 0 |
| 2 | 2 | 2 | 2 | **0** | 0 |
| 2 | 4 | 2 | 2 | **0** | 0 |
| 3 | 1 | 3 | 2 | **0** | 0 |
| 3 | 2 | 3 | 2 | **0** | 0 |
| 3 | 4 | 3 | 2 | **0** | 0 |

This half of the derivation **holds**. F1 is blind exactly as predicted, and
signature gating closes it completely. **The zero is not a dead detector** —
T-BLIND-EXISTS hand-builds the channel and asserts the harness catches it, and
F1 in the same column shows 2–3.

### 1b. Against the benign MIXED workload — F2 leaks

| mode | M | N | F0 | F1 | **F2** | F3 |
|---|---|---|---|---|---|---|
| serialized | 2 | 1 | 0 | 2 | **1** | 0 |
| serialized | 2 | 2 | 0 | 2 | **1** | 0 |
| serialized | 2 | 4 | 0 | 1 | **1** | 0 |
| serialized | 3 | 1 | 0 | 2 | **2** | 0 |
| serialized | 3 | 2 | 1 | 1 | **2** | 0 |
| serialized | 3 | 4 | 0 | 2 | **3** | 0 |
| concurrent | 2 | 1 | 0 | 2 | **1** | 0 |
| concurrent | 2 | 2 | 0 | 2 | **1** | 1 |
| concurrent | 2 | 4 | 0 | 1 | **1** | 1 |
| concurrent | 3 | 1 | 0 | 2 | **2** | 0 |
| concurrent | 3 | 2 | 0 | 3 | **2** | 0 |
| concurrent | 3 | 4 | 0 | 3 | **3** | 1 |

F2 is **not** materially better than F1 here, and at M=3 it is **worse in 4 of 6
cells**. The leak **grows with M** (1 → 2 → 3 as principals are added), which is
the direction that matters for the scaling question.

### 1c. The decisive counterfactual — it is not the pool

The obvious objection is that the pool is doing all the work. It is not. Removing
`withdraw_pool`/`contribute_pool` from the action set **entirely** and re-running
F2 on the mixed workload:

| M | N | F2 with pool | **F2, POOL REMOVED** |
|---|---|---|---|
| 2 | 1 | 1 | 0 |
| 2 | 2 | 1 | **1** |
| 2 | 4 | 1 | **1** |
| 3 | 1 | 2 | **1** |
| 3 | 2 | 2 | **2** |
| 3 | 4 | 3 | **2** |

**5 of 6 cells still violate with no co-owned quantity in the environment at
all.** That is what moves the decision from SIGNATURE-SUFFICIENT-EXCEPT-SHARED
(my 60% prediction) to FEDERATION-DOES-NOT-COMPOSE.

### 1d. The mechanism, traced

M=3, N=4, F2, round 3, victim A (`h_lost[A] = 0.1167 > θ = 0.10`):

```
caused-by (withdraw_pool by=B dst=B:a0 amt=4 auth=[A,C])   authorized=True
caused-by (delete_cross  by=C obj=A:o1  auth=[A])          authorized=True
```

Both actions carry **A's own signature**. Neither alone crosses A's bound —
content contributes 0.083, resource 0.033 — and their **sum** does. A's guard
never evaluated either one, because a guard only ever evaluates its own
principal's actions. A consented to each act; nothing consented to the total.

This is R9's authority-vs-consequence gap and R12's `WRITES/READS` criterion
reappearing one layer up. Gyza is at G0 on consequence for the same reason.

---

## 2. The joint pool — the predicted failure mode, confirmed at full force

`pool_overdraft` = value withdrawn beyond what was ever funded. Max over run,
adversary A4:

| M | N | mode | F0 | F1 | **F2** | F3 |
|---|---|---|---|---|---|---|
| 2 | 1 | serialized | 180 | 180 | **180** | **0** |
| 2 | 1 | concurrent | 180 | 180 | **180** | 4 |
| 2 | 4 | serialized | 756 | 756 | **756** | **0** |
| 2 | 4 | concurrent | 756 | 756 | **756** | 52 |
| 3 | 4 | serialized | 1134 | 1134 | **1134** | **0** |
| 3 | 4 | concurrent | 1134 | 1134 | **1134** | 78 |

**F2 is byte-for-byte identical to F0.** Signature gating provides *exactly zero*
protection against joint overdraft — not "less", *none*. Every withdrawal carried
every required co-owner signature; the conflict was never about authority.

**P4 confirmed — the mechanism is sign alignment.** A withdrawal is net-neutral
in the withdrawer's own frame (`h_drain[A] = −4.0`: the claim falls by 2, the
balance rises by 8), so the local guard sees no harm to its own principal and
admits. Measured directly:

| action | fungible | Δ(A) drain, lost | Δ(B) drain, lost | sign |
|---|---|---|---|---|
| `delete_cross` on B's **sole-owned** object | no | (0.0, 0.0) | (0.0, 0.0417) | actor-NEUTRAL → **blind** |
| `delete_cross` on the **co-owned** SHARED object | no | (0.0, 0.0417) | (0.0, 0.0417) | ALIGNED → **self-policing** |
| `withdraw_pool` (A takes 8) | YES | (**−4.0**, 0.0) | (+4.0, 0.05) | actor-BENEFITS → **blind** |

**The variable is SIGN ALIGNMENT, not fungibility.** Rows 1 and 2 are the *same
action kind* on the *same non-fungible content class* at the *same magnitude*
(0.0417); they differ only in whether the actor co-owns the target, and only the
aligned one is contained. Fungibility is held constant while the sign varies, so
the two hypotheses are separated.

**General form.** *A local guard is adequate exactly for cross-principal actions
that harm the actor too, and blind exactly for those that benefit it. Local
containment works when incentives already align — and fails precisely when they
do not, which is when containment was the thing you needed.*

**The absent cell, stated as a limit.** Every actor-benefits action in the
vocabulary is fungible; there is no non-fungible *transfer* (seizing sole
ownership of the shared object). So the **strong** form — actor strictly gains
from non-fungible harm — remains **confounded with fungibility**. The
preregistration was **not** amended to add the action; a stated confound is
better than a post-hoc scope change.

---

## 3. F3 is not the upper bound it was supposed to be

**P5 is wrong.** F3 contains the overdraft under SERIALIZED (0 in every cell) and
**fails under CONCURRENT** (4–78), and shows cross-principal violations in 3
mixed/concurrent cells. The reason is R10's, not R13's: under concurrent
semantics every guard — including the global one — evaluates against the **same
pre-round state**, so N individually-safe lookaheads compose into an unsafe joint
state. *Even a global checker with full visibility is not a bound under
concurrent admission.* The only configuration that contained everything was
global **and** serializing.

---

## 4. Throughput and blocked actions — reported beside every containment number

A configuration that blocks all cross-principal action has perfect containment
and zero federation value. F2's cost, mixed workload:

| M | N | mode | F1 thr | F2 thr | ratio | F2 blocked | awaiting auth |
|---|---|---|---|---|---|---|---|
| 2 | 1 | serialized | 0.92 | 0.58 | 0.636 | 17 | 5 |
| 2 | 4 | concurrent | 1.92 | 1.75 | 0.913 | 75 | 20 |
| 3 | 2 | serialized | 1.58 | 2.00 | **1.263** | 48 | 14 |
| 3 | 4 | concurrent | 2.92 | 1.25 | **0.429** | 129 | 13 |

Ratio range **0.429 – 1.263**. The preregistered bar (≥ 0.70) fails at M=3/N=4 —
the exact cell the decision rule names — so F2 fails the throughput clause as
well as the containment clause.

**Check cost** (guard evaluations per admitted action), M=3/N=4/concurrent:
F0 1.00 → F1 4.11 → **F2 9.60** → F3 16.00. Containment and cost move together;
F3 buys its serialized containment at 16× F0 and by reading every principal's
state, which is the coordination bottleneck the configuration exists to price.

---

## 5. Point predictions, scored

| # | prediction | outcome |
|---|---|---|
| P1 | F1 shows large cross-principal harm | ✓ 44 violations vs F2's 20; 2–3/cell under A3 |
| **P2** | **F2 drives partitioned-asset violations to 0** | **✗ WRONG** — 0 against A3, but 1–2 per cell under the benign workload with the pool removed |
| P3 | F2 does not prevent joint-pool overdraft | ✓ decisively — F2 ≡ F0 |
| P4 | the mechanism is net-neutrality in the actor's own frame | ✓ measured, `h_drain[A] = −4.0` |
| **P5** | **F3 contains everything at serializing cost** | **✗ WRONG** — F3 leaks under concurrency (4–78) |
| P6 | shared object self-policing; sign alignment, not fungibility | ✓ same action kind, fungibility held constant |
| **P7** | **SIGNATURE-SUFFICIENT-EXCEPT-SHARED fires** | **✗ WRONG** — DOES-NOT-COMPOSE fires (my 20% branch) |

**Three of seven wrong, including the central one.** The derivation in §1 of the
preregistration was mine, and its load-bearing claim — that a stateless signature
check is "a LOCAL, STATELESS check bounding a GLOBAL property" — is **refuted**.
It bounds *who may act*. It does not bound *what accumulates*. This is the third
time in this program that a preregistered prediction being wrong was where the
result was (G4/G4′ inversion, H-CONS refutation, now this).

---

## 6. What this implies for the ARCHITECTURAL PRINCIPLE

`ARCHITECTURAL_PRINCIPLE.md` states **APPEND-ONLY, PARTITIONED,
DERIVED-NOT-STORED**, with R10's design rule: *a guard scales in breadth only if
its state partitions along the same axis as the actions.*

**"Partitioned" must be extended, and the extension is not "cover co-owned
quantities too".** R13 shows the harder thing: partitioning the *assets* between
principals does not partition the *harm*. Two amendments follow from the data:

1. **Partition the harm frame, not just the assets.** A guard is adequate only
   over harm whose frame it reads. Since `READS(g_i) = READS(h_i)` by
   construction, a federation of local guards has **no guard for any harm whose
   frame spans principals** — including the *sum* of individually-authorized
   effects on a single principal. The fix is not a bigger signature; it is that
   **the victim's own guard must evaluate the consequence**, which means an
   authorization must be re-decided *at the moment of effect against the current
   frame*, not signed once in advance. That is exactly Gyza's
   `verify_delegation` discipline (re-decided at result-acceptance time, not
   grant time) — and R13 says that discipline is **load-bearing**, not belt-and-
   braces.
2. **Co-owned fungible quantities need spend-once representation.** For the pool
   specifically, the R10 reading holds: the guard's own state is the conflict
   set, and a monotone shared budget is inherently serializing. A UTXO-like
   spend-once representation would partition the guard's state along the action
   axis. **This is a recommendation, not a result — R13 did not test it**, and
   proposing it is not a rescue round for the decision above, which stands.

**For Gyza directly.** The multilateral-settlement roadmap (`market.py:21-23`)
is a federation of principals over a co-owned pool. R13 says signatures on
individual settlements will **not** bound aggregate exposure, and that the H2
anti-pattern is the smaller half of the problem — even a correctly folded,
append-only, derived-not-stored ledger leaks if each principal's guard reads only
its own frame.

---

## 7. Disclosures (R9 §6) — four, all pre-decision

1. **Preregistration arithmetic slip.** §3.2's inventory table gave contents as
   12 (M=2) / 17 (M=3); the true values are **11 / 16** (5 per principal + 1
   shared). The built environment was correct; the table was wrong. Caught by
   the test that the preregistration itself mandated ("report from the BUILT
   environment, never trust this table"). No threshold depends on it.
2. **Implementation bug — `write` required the object to exist.** R10's did not.
   This silently made *every* deletion permanent, including of duplicated
   content, breaking the duplicate-survives property recoverability rests on.
   Fixed to R10 semantics; ownership now retained across deletion.
3. **Implementation bug — the violation metric was narrower than preregistered.**
   The first implementation used "victim was idle this round" as a proxy for
   "the victim's guard never saw it", which undercounts every round in which the
   victim also acted. Replaced with the preregistered counterfactual (violated
   jointly, **not** violated by the victim's own admitted actions alone). Found
   by the mandated diagnose-the-zeros pass, **before** the decision.
4. **A FOURTH feasibility-ceiling defect — mine, same species as R11's.** §7.2
   computed F2's throughput ceiling as `1 − f_cross·(1−f_auth) = 0.90` and called
   the range `[0.60, 0.90]`. **Measured ratios reach 1.263, above my own
   ceiling.** The ceiling was computed as if the workload were applied to a
   *fixed* state; guards are state-dependent and change the *trajectory* — F2
   blocks early deletions, which preserves state, which keeps later actions
   admissible. The static calculation was not wrong arithmetic, it was the wrong
   model. **The rule "check every threshold against its feasibility ceiling
   before the run" is necessary but not sufficient: the ceiling must be computed
   under the mechanism's own dynamics, not under a fixed state.** The decision is
   unaffected (F2 fails the bar at the named cell, 0.429), but the ceiling as
   stated was not a ceiling.

**Diagnosed zeros and clean numbers**, per the standing rule. F2's 0 under A3 is
real, not a dead detector (T-BLIND-EXISTS + F1's 2–3 in the same column). F3's 0
overdraft under serialized is real (T-F3-blocks-overdraft). Blind-vs-goal BFS
agreement was **14/14 = 1.000** — an exact 1.0, diagnosed: the probe set is small
(14) and deliberately includes the structural cases where RULE 1 (no
resurrection) makes the answer analytic, so agreement is expected rather than
surprising; it is **not** evidence the optimization is safe in general.

---

## 8. What this cannot establish

- **Simulated**, `M ≤ 3` principals, hand-designed action vocabulary,
  hand-chosen harm measures, `SEED = 1`, 12 rounds, one θ (0.10).
- **Agents serve exactly one principal.** Multi-principal agents are a different
  and harder problem, out of scope.
- Nothing about principals with genuinely **conflicting objectives** — only
  conflicting **harm measures**.
- Nothing about **coordination or task decomposition** across principals.
- Nothing about **semantic-content harm** — that is the competence bound, closed
  across six families, terminal.
- Concurrent orders are **sampled** (24) above N·M = 4, so violation counts at
  M=3/N=4 are **lower bounds** on the true adversarial worst case. The decision
  is unaffected in direction: more orders can only find more violations.
- **Recoverability did not discriminate.** It is `False` for every principal in
  every configuration including F3, because θ = 0.10 admits at least one
  irreversible content deletion and one is enough. This is R10 Part B's result
  reappearing — *the measure grades, the boolean steps* — and it means
  recoverability carried no signal in this route. Reported rather than dropped.
- The leak measured here depends on principals **actually authorizing**
  cross-principal actions. A federation in which no principal ever authorizes
  anything has no leak and no federation.
