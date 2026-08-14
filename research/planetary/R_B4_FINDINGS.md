# R-B4 — H5 storage growth: **THE SYSTEM IS GOVERNED BY ITS WORST AMORTIZER**

The first EXTINGUISHES quantity built, registered, and measured. Two results:
one that says we picked the wrong class to enforce by nine orders of magnitude,
and one that says fixing it by *adding* classes will not work.

---

## 1. What was built

`H5_storage_growth` — bytes retained by the content-addressed store since the
accounting origin. **The architectural principle's own stated price**
(*"nothing is ever freed"*) had no function computing it anywhere; per
`HARM_MODEL_GAP` it was "declarable, existing code: **none**." This is the code.

It reads `ArtifactStore.total_size_bytes` through the projection — the store's
own fold, never a reimplementation, the same frame-alignment discipline H1 gets
from `Wallet` and H2 from `fold_capital`.

**Registered with NO declared bound, deliberately.** How many bytes an operator
will retain is a user decision (BUILD_PLAN D1); inventing a level would make the
containment claim unfalsifiable. So `readiness()` now reports
`unbounded: ["H5_storage_growth"]` and `gyza status` prints it. **The gap moved
from invisible to reported** — the same move C-8 made for unsigned bounds.

A finding that fell out: **`ArtifactStore.max_bytes` is never set in
production.** All three constructions default to `None` = unlimited. A capacity
mechanism exists, is tested, and is switched off everywhere.

## 2. h̄, measured on a real store with real signed envelopes

| agent output | bytes retained per action |
|---|---|
| short (200 B) | 1,043 |
| typical (2 KB) | 2,844 |
| large (20 KB) | 20,845 |

## 3. A = B/h̄ — and it clears the planetary bar easily

R-D1 established that 10⁹ actions/day at H = 10⁴ needs **A ≈ 38,500**.

| bound | short | typical | large |
|---|---|---|---|
| **1 GB** | 958,773 | **351,617** | 47,973 |
| 10 GB | 9,587,728 | 3,516,174 | 479,731 |
| 100 GB | 95,877,277 | 35,161,744 | 4,797,314 |

> **Even a 1 GB retention bound with typical outputs amortizes 351,617 actions —
> nine times what planetary scale requires.** The same figure for H1, the only
> bound we enforce, is **under 1**.

The ratio between the two, at a 10 GB bound: **1.4 × 10⁹**.

## 4. THE COROLLARY, and it is the more important half

Escalations from different classes **add** — you escalate when *any* bound is
hit — so actions-per-escalation is their harmonic combination:

> ### A_system = 1 / Σᵢ (1/Aᵢ)

which is dominated by the **worst** amortizer. Measured:

| | A_system |
|---|---|
| H5 alone | 3,516,174 |
| **H1 + H5** | **0.0025** |

**Adding a bound that amortizes three and a half million actions moves the
system total by nothing.** One miscalibrated class caps everything.

This changes the shape of the roadmap. I had been treating "enforce more
EXTINGUISHES quantities" as the way to buy scale. **It is not, while H1 stands
as it is.** Coverage is additive in safety and harmonic in scale, and those pull
in opposite directions.

## 5. Consequences

1. **Fixing H1's calibration is a prerequisite, not a parallel task.** No amount
   of good bounds compensates for one bad one. This raises the priority of memo
   M2 from "decide when convenient" to "blocks the scale story."
2. **H5 is the right class and should be bounded** — it removes harm rather than
   relocating it, and its amortization is effectively free. But bound it for
   *safety*, not expecting a scale gain until (1).
3. **`ArtifactStore.max_bytes` should be set from the declared bound** once one
   exists, so the capacity mechanism and the harm model stop being two unrelated
   things that both mean "too many bytes."
4. **Report A per class in `gyza status`.** An operator cannot see which class is
   capping their throughput, and after this result that is the number that
   matters most.

## 6. Limits

`h̄` is measured over three synthetic output sizes on one machine, with one
artifact schema; a real workload's distribution is unmeasured and could differ by
an order of magnitude — though the conclusion survives that comfortably, since
even the 20 KB case clears the planetary bar at 1 GB.

The harmonic formula assumes escalations from different classes are independent
and that any bound hit costs one human decision. Batching several breached
classes into one review would relax it, and that is R-D1's assumption 2, still
untested.
