# A2 — the defector route: findings

**Preregistration:** `PREREGISTRATION.md`, committed `7444299` as the only file
in this directory, BLAKE3
`11380d79e3cb2b927bce2ccf6a0caaa9fb3afa6b433fb36adb95fe284a780840`. Re-verified
unchanged after the runs. **Zero credits**, exact rational arithmetic.

**Verdict: `COMPLIANCE-ASSUMPTION-NOT-SECURITY-PROPERTY`** — with one important
exception, and one prediction of mine that failed in the *un*comfortable
direction.

---

## 1. The answer

> **One principal that ignores its guard breaks the aggregate bound at every
> scale tested, up to M = 512.** R-M1's constructive result therefore describes a
> property of a *compliant* population. Without enforcement it is an assumption.

| mode | k\* at M=8 | M=64 | M=512 | verdict |
|---|---|---|---|---|
| **D-SHED** (ignores the floor) | **1** | **1** | **2** | **FRAGILE** |
| **D-SKEW** (old software: obeys `L(0)`, not `L(δ*)`) | 1 | 4 | **23** | **STATISTICAL** |
| **D-HOARD** (ignores the ceiling) | **1 hoarder, 0 shedders** | same | same | **FRAGILE, and it pays** |

Every k\* is **identical at 5 and 20 seeds**, and violations are monotone in k in
every cell.

**The exception matters practically.** `D-SKEW` — a node running last month's
software, with the box floor but no margin — is **not malicious and degrades
gracefully**: tolerance grows 23× from M=8 to M=512. Honest heterogeneity is
survivable. Malice is not.

## 2. The mechanism: it is the commons, not the defector's own term

My preregistration derived that shedding removes the defector's own holding from
the **denominator**, so impact should be **O(1/M)** and large M protective. That
is wrong, and instrumenting a single trajectory shows why.

Every non-target principal converges to **the same value** — 1.52 at k=0, 0.74 at
k=1 (M=8). Their `holdings` reach zero and what remains is purely their **pool
claim**, which never vanishes because `contrib` is not reduced by withdrawal (the
property the escrow route found at §2.6 and R-M1 reproduced independently).

So a defector "shedding to zero" cannot end below a compliant principal. What it
does instead is **withdraw every round forever**, draining the **shared pool** —
and since the non-target principals' entire remaining wealth *is* their pool
claim, the drain collapses all of them while the target keeps its account
balance.

> **The defector's damage does not travel through its own term in `max/sum`. It
> travels through the commons.** One principal over-drawing a shared resource
> harms all M, so the impact is **O(1), not O(1/M)** — and no amount of scale
> dilutes it.

`pool_remaining` at k\* makes this visible: 0.06 at M=8 against 12.18 in the
compliant control.

## 3. The incentive result, which is the one I got wrong

The preregistration predicted `defector_advantage` **negative** for shedding and
**positive** for hoarding, and named the hoped-for headline:
*"the attack that works is not rational, and the attack that is rational does not
work."*

| mode | defector advantage at k\* | M=8 | M=64 | M=512 |
|---|---|---|---|---|
| D-SHED / D-SKEW | **exactly 0.0000** | 0 | 0 | 0 |
| **D-HOARD** | **enormous, and growing with M** | **+62** | **+398** | **+3086** |

**The hoped-for headline is REFUTED.** The rational attack works perfectly and
pays 3086× the compliant outcome at M=512 — and the advantage *grows* with scale.
There is no incentive barrier protecting this bound; the profitable defection is
also the effective one.

**The exact 0.0000 is DEFINITIONAL** (diagnosed per rule #2, not reported as a
finding): a shedder and a compliant principal both bottom out at the same
irreducible pool claim, so shedding harder cannot make you poorer than your
neighbour. It costs the defector nothing and gains it nothing — it is pure
vandalism, and vandalism is exactly what it takes to break this bound by
shedding.

## 4. Predictions, scored — four of six refuted

| | prediction | outcome |
|---|---|---|
| **P-A2e** | k=0 ⇒ zero violations | **CONFIRMED, definitional as flagged.** The control holds at all three M |
| **P-A2a** | k\* grows linearly in M | **REFUTED** for D-SHED (1, 1, 2). **Holds for D-SKEW** (1, 4, 23) |
| **P-A2b** | φ\* rises with M; intervals disjoint | **REFUTED, in the opposite direction.** φ\* *falls*: 0.143 → 0.016 → 0.004 |
| **P-A2c** | D-HOARD cannot breach at any M — *derivable* | **REFUTED.** §1b held the denominator at `U·M` while the compliant population is simultaneously *shedding*, shrinking it. A "derivable" ceiling computed against the wrong denominator |
| **P-A2d** | D-SKEW needs more defectors than D-SHED | **CONFIRMED** (23 vs 2 at M=512) |
| **P-A2f** | advantage negative for SHED, positive for HOARD | **HALF CONFIRMED.** Positive for HOARD as predicted, and vastly so; **exactly 0** rather than negative for SHED, definitionally. The *headline* it was meant to support is refuted |

**The closed form in §1a is refuted along with P-A2b.** It predicted φ\* ∈
[0.409, 0.586] at M=8; measured 0.1429. Both of this program's closed forms have
now failed — R-M1's was conservative by ≈2× and sign-flipped at the feasibility
boundary; this one had the wrong denominator. **Recorded rather than patched.**

## 5. What this means for the substrate

**R-M1's constructive result stands, with its precondition made explicit.**
Bounded activity does make a planetary aggregate unreachable — *among principals
that run the check*. A2 shows the check must be **enforced**, not assumed.

That is precisely what Gyza already has for authority: a signed manifest, a
runner that **refuses to sign** when enforcement exceeds it, and an attenuation
theorem down the delegation chain. A2 says the same machinery is required for
aggregate participation, and it says **which side is urgent**:

> **Enforce the ceiling before the floor.** Shedding defection is vandalism —
> effective but unprofitable, so only an attacker willing to burn its own
> position does it. Hoarding defection is effective *and* pays 3086×, so it is
> what a rational participant does. The box is two-sided and only one side has an
> incentive behind it.

This also connects to H3: a defector here is simply a principal not running the
check, and **attestation is the only thing that distinguishes it from a compliant
one**. H3's containment claim already rests on the attestation tier; A2 shows the
aggregate bound rests on it too. One dependency, two harm classes.

**B6 — the action-rate `CapabilitySpec` dimension — is justified by this**, and
its specification changes: it must bound accumulation, not only rate.

## 6. What this route cannot establish

1. **No detection or ejection.** A real mesh would identify and evict a principal
   draining the commons. Every k\* here is a **lower bound** on real tolerance,
   and the D-HOARD result in particular assumes nobody notices 3086× enrichment.
2. **The hoarder is the target** — the max holder by construction, which is the
   worst case for a concentration bound. A hoarder starting from an ordinary
   position was not tested.
3. **Non-adaptive, non-colluding defectors**, one aggregate, one conserved total,
   uniform staleness, simulated principals. R-M1's limits carry over.
4. **The commons is this environment's design.** The mechanism in §2 depends on a
   shared pool whose claims are pro-rata and irreducible. A federation without a
   commons would not exhibit it — but a federation without a commons also has no
   cross-principal aggregate to bound.
5. **Nothing about correctness.** Consequence only; the competence bound remains
   terminal.
