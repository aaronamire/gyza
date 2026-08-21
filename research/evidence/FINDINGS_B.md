# R-EVID Part B — one of Gyza's four registered harm classes is sound

**Verdict: `H-ZERO-CONFIRMED`. And `CUSUM-DOMINATES` is REFUTED at the low end —
the constructive half of Part A holds only where the measurand already carries
evidence, which is Theorem 4 applied to the fix rather than to the problem.**

---

## 0. Provenance

Part A `THEOREMS.md` — commit **`c968d0c`**, analytic, no data.
Part B preregistration — commit **`113e1c3`**, before any measurement code.
Both are ancestors of every result here. Results: `evidence.json`.
**Zero credits.** Production `_executor` with a stubbed `anthropic` module.

## 1. What was measured

Every quantity read through its production accessor, 200 actions per workload.

| class | shape | benign rate `b` | `ρ` | evidence `D` | benign refused at |
|---|---|---|---|---|---|
| **H4** authority | flow | **0.0000** | undefined | undefined | **never** |
| **H5** storage | stock-shaped | — (C4: not scored on a ratio) | — | — | see §3 |
| **H6** unsupervised actions | flow | 1.0000 | **1.000** | **0.0000** | action **10,000** |
| **H3** mesh exit (count) | flow | 1.0000 | **1.000** | **0.0000** | action 10,000\* |
| **H3** mesh exit (bytes) | flow | 1077.0 | 374.577 | 367.65 | action **1,003** |

\* no level is declared for H3; shown at a hypothetical 10,000 to make the timer visible.

## 2. H-ZERO confirmed, and the criterion is a one-line check

> **A cumulative bound is sound iff the benign rate is zero, or the quantity is
> a stock that reversal decrements.**

**P1 confirmed exactly.** H4's benign rate measured **0.0000** — a compliant
enforcement record never fails `enforcement_satisfies_manifest`, so
`runner.py:524` never appends. Theorem 2 requires `b > 0`; H4 escapes through
its hypothesis, not around its conclusion. **This is why H4 is the one class
that "was always real"** — not diligence, structure.

**P2 confirmed, and the remedy is reclassification.** H6's `ρ = 1.000` **by
definition**: its quantity is the count of signed envelopes, and an adversary
doing harmful work signs exactly as many as a benign agent doing useful work.
The difference is not in the count. So H6 is **correctly built as a review
cadence and mis-registered as a harm class** — a timer is precisely what a
cadence should be, and its 10,000 is an honest review interval and a
meaningless harm bound.

**P3 confirmed** on an independent harness: H3-count reproduces `ρ = 1.000`.

**P5 confirmed:** `D = 0` for exactly the MUTE classes, and the ordering matches
the verdicts.

## 3. H5 — stock in shape, flow in behaviour

The prediction was SOUND-because-stock. The measurement splits it:

| question | answer |
|---|---|
| does the quantity decrement when an artifact is removed? | **yes** (10,000 → 9,000 bytes) |
| does `ArtifactStore` expose any reversal? | **no** — `store`, `get`, `exists`, `size_bytes`, `list_hashes`, `total_size_bytes` |
| does any production path delete an artifact? | **no** — the sole `unlink()` in the tree (`artifact_store.py:92`) is corruption repair on a hash mismatch |
| is the quantity derived from append-only state? | **no** — `total_size_bytes` `rglob`s a mutable directory and sums `stat()` |

> **H5's decrementability is real and unreachable.** Nothing can trigger it, so
> in production `total_size_bytes` is monotone and its 10 GB level is a timer
> like the others. And the decrementability it does have comes from **breaking**
> the architectural principle — it stats mutable state instead of folding a log.

**So: of four registered classes, exactly one — H4 — carries a sound cumulative
bound.** H6 and H3 are mute timers; H5 is a timer with an unreachable escape.

This is the "declared but nothing supplies it" species in a new position. The
census asked *what supplies this quantity?* The question this adds is **what
supplies its REVERSAL?**

## 4. The tension with the architectural principle, and the way out

`ARCHITECTURAL_PRINCIPLE.md` says represent a safety-relevant quantity as a pure
fold over append-only partitioned state; R12 showed that makes blind channels
architecturally impossible. Its stated price is *"nothing is ever freed."*

> **That price is Theorem 2.** A fold over append-only state whose entries
> contribute non-negatively is monotone, hence a flow, hence a timer. **The
> principle that closes blind channels is the same principle that turns every
> cumulative bound into a clock.**

The escape is available *inside* append-only, and this codebase already
implements it: **let entries contribute negatively.** `Wallet.net_balance`
(`wallet.py:274`) is a fold over `LedgerEntry` that is settled-in minus
settled-out and *"may be negative; never clamped"*. It decrements — and every
decrement is an appended, attributable event.

> **Reversal must be an appended fact, not an absence.** A tombstone is
> append-only. A deleted file is not. That is the difference between H5 and the
> ledger, and it is the whole of the constructive rule.

Gyza contains the pattern and the anti-pattern in the same tree, again.

## 5. `CUSUM-DOMINATES` is REFUTED at the low end

P4 predicted CUSUM would beat the level's ceiling by **≥10×** at matched
detection delay (`K = 100` actions). Measured:

| `ρ` | CUSUM benign lifetime | LEVEL ceiling (`Kρ`) | advantage |
|---|---|---|---|
| **1.05** | 45.8 | 105.0 | **0.4× — WORSE than the level** |
| **1.20** | 223.7 | 120.0 | **1.9× — below the 10× bar** |
| 1.50 | 21,204.8 | 150.0 | 141× |
| 2.00 | ≥60,000 | 200.0 | ≥300× |
| 4.00 | ≥60,000 | 400.0 | ≥150× |
| 10.00 | ≥60,000 | 1,000.0 | ≥60× |

**P4 fails at ρ ≤ 1.2 and holds from ρ ≈ 1.5.**

**The ≥ signs are load-bearing.** At ρ ≥ 2 every benign run hit the simulation
cap (40/40 censored), so those lifetimes are lower bounds and the apparent
*decline* from 300× to 60× is **not** a real trend — it is the denominator `Kρ`
growing while the numerator is pinned at the cap. Reporting them as point values
would be artifact #17 exactly: a trend line through numbers that are not
measuring the same thing.

**Why the failure is the right answer.** As `ρ → 1`, `D → 0`; by Theorem 4 the
observations needed diverge, so no threshold meets a 100-action delay budget
without collapsing the false-alarm rate. **The optimal test is bounded by the
same evidence that bounds the naive one.** Part A §3 says the level "is
dominated"; the honest statement is:

> **CUSUM dominates the cumulative level exactly where the measurand carries
> evidence, and nowhere else. Against a sufficiently stealthy adversary no
> statistic over that quantity helps — including the optimal one.**

That strengthens the unified thesis rather than weakening it: **the measurand,
not the test, is the binding constraint.** Part A §3's flat "dominated" is
corrected in `CORRECTIONS.md` #31.

## 6. Apparatus defects, disclosed

1. **The first H4 measurement returned `b = 1.0` and would have refuted P1.** It
   used invented field names (`ro_binds`, `read_paths`) and omitted `backend`,
   so every record failed as *incomplete* and benign and adversarial were
   indistinguishable **because both were malformed**. The harness now asserts
   the compliant record is accepted before counting anything — a measurement
   whose control fails is not a measurement.
2. **The first CUSUM run was worthless.** It used only the loudest adversary
   (ρ = 374) with `k = (b+a)/2`, putting the reference 188× above the benign
   mean; ARL0 pinned at the cap in all four cells, censored 60/60 — an exactly
   saturated metric, caught by standing rule #2. A detector handed a 374× shift
   is trivially perfect and measures nothing. **The regime that decides anything
   is the stealthy adversary**, and sweeping into it is what produced §5's
   refutation.

## 7. What this cannot establish

- **`n = 1` system.** The theorems are general; the evidence here is Gyza's.
- **H6's rate is structural, not sampled.** `runner._complete` signs exactly one
  envelope per completed item, so both behaviours are 1.0/action by
  construction. Labelled in `evidence.json` rather than dressed as a sample.
- **Byte figures are lower bounds** — the stub omits SDK framing.
- `attested_peers` has no production source, so peer sends are over-counted as
  exit. Conservative for a bound, pessimistic for the mesh-growth claim.
- **CUSUM's optimality is cited, not re-derived** (Lorden 1971; Moustakides
  1986). What is measured is whether its advantage survives on this traffic.
- **No level is declared, and no rate bound is implemented.** This route says
  which classes could carry one.
- **It does not escape §5 of Part A.** Bounded total irreversible harm over
  unbounded lifetime remains unavailable.

## 8. What it means for Gyza

1. **H6 should be reclassified** from harm class to review cadence. It is not
   broken; it is mislabelled, and the label costs the containment claim.
2. **H3 must not be bounded on the count.** `D = 0` — R-H3L said it, and this
   derives it from the verification arm's own statistic.
3. **H5 needs a reversal that is an appended fact** — a tombstone folded into
   the quantity — or its bound is a timer. Route it through the pattern
   `Wallet.net_balance` already uses.
4. **H4 is the template.** Bound quantities whose benign rate is zero.
5. `can_claim_containment` stays **FALSE**, on both of its independent grounds.
