# The M > 3 arena — **BOX-SOUNDNESS-IS-SINGLE-THREADED**

Preregistration `6a66012`, BLAKE3
`bf09419c3af4399c634727c91d678c1e070ba6fc655e68d518a71a1250f7a765`, committed as
the sole file in this directory before any arena code existed.

**Zero credits.** The committed environments were not modified; `box_bounds`,
`concentration` and `KAPPA` are imported from `env_aggregate` so the property
under test is byte-identical to the published one.

**One prediction refuted. Four apparatus defects found in my own arena before
any result was trustworthy — that section is the most instructive part of this
document.**

---

## 1. The arena expresses M > 3

| requested M | `env_federation` | arena |
|---|---|---|
| 3 | 3 | 3 |
| 10 | **3** | 10 |
| 512 | **3** | 512 |

The Gate 0 cap is gone. `principals(m)` generates rather than slicing a fixed
3-tuple, and a test asserts `len == m` at large m because the failure it
replaces was **silent**.

## 2. Part 1 — CALIBRATION: **P1 REFUTED**

Violation rate (concentration > κ while every local box check passed), averaged
over 20 seeds × 40 rounds, `n` = agents per principal:

| M | n=1 | n=2 | n=4 | n=8 |
|---|---|---|---|---|
| 2 | **0.0000** | 0.0638 | 0.0638 | 0.0638 |
| 8 | **0.0000** | 0.0262 | 0.0262 | 0.0262 |
| 64 | **0.0000** | 0.0250 | 0.0250 | 0.0250 |
| 512 | **0.0000** | 0.0250 | 0.0250 | 0.0250 |

### The finding

> ### The box's soundness is a property of SINGLE-THREADED principals, not of scale.

**n = 1: zero violations at every M** — diagnosed as **definitional** (P5), and
exactly what `FINDINGS_BOX_SCALING`'s 33,000 in-box configurations established.
**n ≥ 2: breached at every M**, and **n = 2, 4 and 8 are identical.** The entire
effect is the n=1 → n=2 transition; adding agents beyond the second changes
nothing.

### P1 was wrong, and so was §4b's optimism

**P1 predicted the violation rate falls monotonically in M.** It falls 2.4× from
M=2 to M=8 and then is **flat to M=512**.

`FINDINGS_BOX_SCALING` §4b argued the staleness attack *"gets harder with
scale"* because the required shed rises from 33.3% of endowment at M=2 to 99.3%
at M=100. That arithmetic is correct and **it does not protect the box**: the
floor `L` falls as 1/(m−1) by the same factor, so an agent shedding *to the
floor* scales its attack exactly with the defence. **The two cancel.**

**R-1 is technically met** (0.0250 < 0.0638/2) — but by the early M=2→M=8 drop,
not by the continued decay the rule assumed. Reporting it as "met" without that
qualification would be the wrong claim.

## 3. Part 2 — review capacity federates, conditionally

The original metric was wrong and hid the quantity: *actions per review* cannot
distinguish M reviewers from one. Corrected to **load per reviewer**:

| M | per-principal reviews/reviewer | shared-pool reviews/reviewer |
|---|---|---|
| 2 | 4.0 | 8.0 |
| 64 | **4.0** | 256.0 |
| 512 | **4.0** | **2048.0** |

> **`N ≤ M·h·A/ε` holds iff review capacity is ATTACHED TO PRINCIPALS.** Per
> principal, reviewer load is flat in M and throughput scales linearly. A single
> federation-wide bound serializes onto one human, whose load grows linearly, and
> caps throughput at `h·A/ε` regardless of M.

That is C7/R13 one layer up: a cumulative bound over a shared pool does not
compose, and here the shared pool is *human attention*.

## 4. FOUR APPARATUS DEFECTS, in my own arena

Each produced a plausible-looking number I could have published.

1. **Adversary too weak.** Proposed a fixed-fraction shed the local box trivially
   refused. Violation rate **0.0000 at every M** — an exact zero I nearly
   reported as a finding.
2. **Wrong mechanism.** One actor per principal, checking its own exact state.
   The box is *sound by construction* there; AG-3's unsoundness requires
   **multiple agents racing against a stale read of their own principal**. The
   arena could not reproduce the mechanism it was built to measure.
3. **Symmetric shedding.** Concentration is a **ratio** — when everyone sheds
   equally it does not move. The attack requires a **held-out target** while the
   others shed around it.
4. **Float boundary.** Shedding to exactly `L` lands an epsilon below it, so the
   check refused and M=32 alone reported 0.000. **I published a diagnosis of
   this as a "seed effect on timing" in the same output whose data refuted it**,
   then had to correct it. A margin of `L(1+1e-9)` fixed it.

The pattern: **building an adversary is harder than running the experiment**,
and every error failed in the *reassuring* direction — toward "no violations."

## 5. What this does not establish

1. **M = 512 is three orders below planetary.** This tests whether the trend
   matches the arithmetic, not the endpoint.
2. **I authored the arena.** Mitigated by fixing the adversary in the
   preregistration before the environment existed, and by testing a structural
   property rather than a behavioural one. Not eliminated — §4 is what that
   residual risk looks like in practice.
3. **Simulated principals.** No agents, no work, no humans; `h` is a parameter.
4. **Nothing about correctness.** Consequence only.

## 6. Consequences

1. **`FINDINGS_BOX_SCALING` §4b needs a correction of record.** Its
   scale-hardening argument is sound arithmetic that does not survive
   intra-principal concurrency. The box remains sound for single-threaded
   principals at any scale — which is a real and useful claim, just a much
   narrower one.
2. **Concurrency, not scale, is the box's control parameter.** Any deployment
   running more than one agent per principal is outside its guarantee, and that
   is the common case.
3. **Attach reviewers to principals.** The federation claim survives only under
   that structure; a single global bound reintroduces the serialization C7
   forbids.
