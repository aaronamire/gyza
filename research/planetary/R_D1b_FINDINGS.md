# R-D1b — measuring `h̄`: **THE DECLARED BOUND REFUSES EVERY REAL MODEL'S FIRST ACTION**

R-D1 identified `A = B/h̄` as the binding term for planetary scale and noted
nobody had measured it. This measures it. **The prediction was wrong and the
result is operationally urgent.**

---

## 1. THE PREDICTION WAS WRONG

**P-A1 said `A` would be order 1–100 — "the amortization lever is near-unused."**
Measured `A` is **0.0008 to 1.0**. The lever is not near-unused; it is
**inverted**. For every real model, a *single action* exceeds the declared bound.

**P-A2 held:** `A` is set entirely by the pricing function `compute_task_cost`,
with nothing safety-related entering.

## 2. The measurement

`h̄` = credits consumed per action = `compute_task_cost(model, tokens_out,
duration_ms)`. Against the declared `B = 100.0`, at 1000 output tokens:

| model | credits/token | cost of one action | **A = B/h̄** |
|---|---|---|---|
| `mock` | 0.1 | 100.0 | **1.00** |
| `qwen2.5-3b` | 0.125 | 125.0 | **0.80** |
| `qwen2.5-7b` | 0.333 | 333.3 | **0.30** |
| `gpt-4o` | 50 | 50,000 | **0.0020** |
| `claude-sonnet-4-5` | 40 | 40,000 | **0.0025** |
| `claude-opus-4-5` | 120 | 120,000 | **0.00083** |

## 3. Confirmed against the real guard, not just arithmetic

`SettlementGuard.check_payment` on an **empty ledger** — the node's very first
action, entire budget available:

| model | verdict |
|---|---|
| `mock` | ADMITTED (costs exactly the bound) |
| `qwen2.5-3b` | **REFUSED** |
| `claude-sonnet-4-5` | **REFUSED** |
| `claude-opus-4-5` | **REFUSED** |

> ### A node running any real model — including a local 3B — cannot settle its first task.

## 4. What this means operationally, stated plainly

**I enabled this gate in `GlobalCluster` yesterday, by default. As shipped, it
would refuse all real settlement traffic.**

The full suite passed because **nothing in it settles at realistic rates**: the
settlement tests use `mock` at token counts that land at or under 100 credits.
This is the fixture problem again — a suite that builds its own inputs never
exercises the ones production sends.

The bound itself is not new; it was declared 2026-07-31 and enforced nowhere.
**Enforcement is what revealed it was never calibrated against the cost model.**
That is enforcement doing its job, and it is also a defect in the state I left
the tree in.

## 5. What B would have to be

| model | A = 1 | A = 10 | A = 100 |
|---|---|---|---|
| `qwen2.5-3b` | 125 | 1,250 | 12,500 |
| `claude-sonnet-4-5` | 40,000 | 400,000 | 4,000,000 |
| `claude-opus-4-5` | 120,000 | 1,200,000 | 12,000,000 |

Reaching even `A = 100` on a frontier model needs `B` four to five orders of
magnitude above the declared 100 — which empties the *"deliberately TIGHT"*
rationale in `guard_bounds.json` entirely. **The bound and the pricing function
cannot both stand as they are.**

## 6. A candidate cause, flagged as a candidate

`CREDIT_RATES` is applied **per token** (`tokens_out * rate`). On one
2-second / 1000-token task the token term exceeds the time term by **100×** for
`mock` and **40,000×** for Sonnet, so the documented time-based floor — *"catches
local backends where token counts are noisy"* — is **inert for any realistic
workload**. It can never bind.

That is consistent with `CREDIT_RATES` being intended as credits per *thousand*
tokens rather than per token; at that reading Sonnet's 1000-token action costs 40
credits and sits inside the declared bound. **I am not asserting a units bug** —
pricing is a policy choice and the intent is not mine to infer. But the two
mechanisms disagree by orders of magnitude and only one of them can be right.

## 7. The interaction with R-B1, which is the sharper point

R-B1 classified H1 as **TRANSFERS**: bounding it relocates harm rather than
removing it. H1 is also the **only enforced bound in the system**.

> **So the only bound we enforce is on the one class where enforcement does not
> remove harm — and it is the bound consuming the entire escalation budget.**

Six of ten declarable quantities EXTINGUISH when bounded. None of them is
enforced. **On the escalation arithmetic, we are spending our scarcest resource
on the class where it buys the least.**

## 8. Actions

1. **Decide B against the cost model, or the cost model against B** (user; folds
   into memo M2). Until then the enforced gate is miscalibrated.
2. **Consider defaulting the gate off in `GlobalCluster`** until (1) lands — or
   accept that a real deployment refuses everything. This is a live decision, not
   a cleanup.
3. **Add a settlement test at realistic model rates.** The absence of one is why
   this survived a 1068-test suite.
4. **Enforce an EXTINGUISHES quantity next** — `storage_growth` and
   `H3_content_loss` both have computable state functions already identified —
   so that some enforced bound actually removes harm.
