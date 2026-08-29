# R-EVID Part B — measuring the evidence in every registered harm class

**Gate 0. Written before any Part B measurement code exists.** Part A
(`THEOREMS.md`, commit `c968d0c`) is analytic and contains no data; it is an
ancestor of this file, and this file is an ancestor of every result artifact in
`research/evidence/`.

**ZERO CREDITS.** The inference path is exercised by stubbing the lazily
imported `anthropic` module, as in R-H3L, so the production `_executor` body
runs unmodified.

---

## 0. The question

Part A proves that a cumulative bound over an immutable origin with benign rate
`b > 0` is a **timer**: it refuses every benign agent at action `⌈L/b⌉`, and a
level separating an adversary exists only while `ρ = a/b > N/K`.

> **Q. For each harm class Gyza actually registers, what is `b`, what is `ρ`,
> and therefore which of them can carry a level at all?**

This is Part A's design rule (§7 step 1) applied to the system that motivated
it. It is the step `H3_MESH_EXIT.md` §5 demanded — *instrument, measure, then
declare* — generalised from H3 to every class.

## 1. THE HYPOTHESIS, stated before measuring

Theorem 2 assumes `b > 0`. **Two escapes exist and Gyza already contains one of
each**, which is a prediction about why its harm model has the shape it does:

> **H-ZERO: a cumulative bound is sound if and only if the benign rate is zero,
> or the quantity is a stock that reversal decrements.**

If true, the entire pattern of this program's harm-model history — two
retirements, one unbounded class, one class that always worked — is a single
consequence, and the design rule becomes a one-line check anyone can apply.

## 2. Point predictions, fixed before data

| class | quantity | predicted `b` | predicted `ρ` | predicted verdict |
|---|---|---|---|---|
| **H4** authority | violations | **0** | ∞ | **SOUND** — the only registered class whose bound is not a timer |
| **H5** storage | stored bytes | > 0 but a **STOCK** | > 1 | **SOUND** — reversal (deletion) decrements; Theorem 2 does not apply |
| **H6** unsupervised actions | envelopes | **1.0 exactly** | **1.0** | **TIMER + MUTE** |
| **H3** mesh exit (count) | events | **1.0 exactly** | **1.0** | **TIMER + MUTE** (already measured by R-H3L; re-derived here) |
| **H3** mesh exit (bytes) | bytes | > 0 | ≫ 1 | **TIMER, but informative** |

**P1.** H4's benign rate is exactly 0. `runner.py:524` appends to
`_authority_violations` only inside the `if not ok` branch of
`enforcement_satisfies_manifest`, so a compliant execution cannot increment it.

**P2.** H6's `ρ = 1.000` **by definition, not by accident.** Its quantity is the
count of signed envelopes, and an adversary completing work signs exactly as
many as a benign agent. **H6 is therefore correctly built as a review CADENCE
and mis-registered as a harm class.** The predicted remedy is reclassification,
not repair — a timer is precisely what a cadence should be.

**P3.** H3-count reproduces `ρ = 1.000` (R-H3L, independent harness).

**P4.** CUSUM over the same egress log achieves a benign-lifetime-to-detection-
delay ratio **at least 10× the level's `ρ`** at matched detection delay.

**P5.** The evidence `D` computed from measured `ρ` orders the classes exactly
as the verdict column does, with `D = 0` for every MUTE class.

## 3. Feasibility ceilings, computed BEFORE the run — standing rule #4

Rule #4 has failed five times, and the fifth was R-H3L's own liveness bar being
satisfiable-but-meaningless. Both sides of every comparison are checked here.

**C1 — the liveness bar is set from the operating horizon, not from convenience.**
R-H3L fixed `N = 1000`, which is under an hour at this program's own 26,000
actions/day. **Part B fixes `N = 26,000` (one day) and reports the full curve to
9,490,000 (one year).** At `K = 100` those demand `ρ > 260` and `ρ > 94,900`
respectively — both stated now, before data.

**C2 — `ρ = ∞` is unscorable and must be handled, not discovered.** If H4's
benign rate is 0, `ρ = a/b` is undefined rather than large. **E1-HOLDS was
retired for exactly this** — a rule dividing by a baseline of 0.000. So H4 is
scored on `b = 0` directly, not on the ratio, and the decision rule below says
so.

**C3 — `D` is unbounded above.** Evidence per observation has no ceiling, so
"more evidence is better" cannot be falsified by a high reading. The scorable
claim is the ORDERING (P5) and the zero/non-zero split, not any magnitude.

**C4 — H5 cannot be measured as a rate.** It is a stock; its benign "rate" is
the net of writes and deletions and can be negative. Reporting a `ρ` for it
would compare quantities of different kinds. **H5 is scored on the structural
question — does reversal decrement it — by inspection of the accessor, and the
finding must say that it was not scored on a ratio.**

## 4. Environment

- **W-BENIGN / W-EXFIL**: R-H3L's inference workloads, re-run through the same
  production `_executor`, giving H3-count and H3-bytes.
- **W-H6**: the runner's envelope path, benign and adversarial, counted from
  `count_envelopes_since`.
- **W-H4**: a compliant sandboxed execution and one whose enforcement record
  exceeds its manifest, counted from `AgentRunner.authority_violations`.
- **W-CUSUM**: the byte stream from W-BENIGN and W-EXFIL, replayed through a
  CUSUM detector, measuring runs-to-false-alarm and detection delay across
  thresholds.

Every quantity is read back through the **production accessor** for its class
(`mesh_exit_sends_since`, `count_envelopes_since`, `authority_violations`,
`total_size_bytes`), never from a counter the harness keeps. A harness tally is
computed only to cross-check, and a disagreement is reported, not reconciled.

## 5. Measures

Per class: `b`, `a`, `ρ`, `D`, the action at which a benign agent is refused
under the current declared level, and — the counter-metric standing rule #3
requires — the **actions refused** beside the **harm withheld**.

For CUSUM: mean runs to false alarm (ARL₀) and mean detection delay (ARL₁) at
each threshold, plus the level's operating point on the same axes.

## 6. Decision rules

> - **`H-ZERO-CONFIRMED`** if every class predicted SOUND has `b = 0` or is a
>   stock, and every class predicted TIMER has `b > 0` and a finite refusal
>   action computed from its own declared level.
> - **`H-ZERO-REFUTED`** if any class with `b > 0` and a flow shape fails to
>   produce a finite benign refusal action, or any class with `b = 0` does.
> - **`CUSUM-DOMINATES`** if P4 holds; **`CUSUM-NO-BETTER`** otherwise, in
>   which case Part A §3's domination claim is wrong on this system's data and
>   the design rule loses its constructive half.

**No tuning after results.** Implementation-bug fixes only, disclosed.

## 7. What this route cannot establish

- **It does not declare any level.** It measures which classes could carry one.
- `n = 1` system. Every measurement is Gyza's. The theorems are general; the
  evidence for them here is not.
- Byte figures remain **lower bounds** — the stub does not model SDK framing.
- `attested_peers` has no production source, so peer sends are over-counted as
  exit; conservative for a bound, pessimistic for the mesh-growth claim.
- CUSUM's optimality is **cited, not re-derived**. What is measured here is
  whether its advantage survives on this system's actual traffic.
- **It cannot say whether a rate bound is ENOUGH.** Part A §5 is explicit that
  bounded total irreversible harm over unbounded lifetime stays unavailable, and
  no measurement in Part B changes that.
