# R-H3L — what quantity can carry an H3 level: preregistration (Gate 0)

**Written before any measurement code exists.** No result artifact in
`research/h3_level/` predates this file; the commit hash is printed in
`FINDINGS.md` §0 and must be an ancestor of every result commit.

**ZERO CREDITS.** Every measurement below runs against the in-process paths and
local daemons. No inference call is made. §4 states exactly how the one quantity
that would otherwise need credits is obtained without them, and §8 states what
that costs the result.

---

## 0. Why this route exists

`can_claim_containment` is **FALSE**, and it is false because `H3_mesh_exit_sends`
is registered as a harm class with **no declared level**
(`research/H3_MESH_EXIT.md` §5, §6). That document closes with a sequence:

> **instrument, measure the attainable range, then declare.**

Instrumentation is done. This route is the middle step. It is the only
remaining item that blocks the containment claim and is not a user decision —
the *level* is Aaron's call, the *attainable range* is a measurement.

**The failure this route exists to avoid is specific and has a name.**
`H1_credits` was retired because 100 was declared without measuring the
attainable range, and it then refused **every real model's first action**.
Standing rule #4 — check a threshold against its feasibility ceiling *before*
the run — has failed four times in this program. Declaring an H3 level from
intuition would be the fifth.

## 1. The question

`H3_mesh_exit_sends` is a **cumulative count of MESH_EXIT events since an
immutable genesis origin** (`gates.py:genesis_origin`, `origin_ns = 0`).

> **Q1. Can that quantity carry a level that bounds HARM rather than UPTIME?**
>
> **Q2. If it cannot, which candidate quantity can — and what is its attainable
> range?**

Q1 is asked first because measuring the attainable range of the **wrong
quantity** produces a defensible-looking number for an indefensible bound, and
nothing downstream would reveal it. This program has recorded that species three
times (R9's `G4′` pinned frame, SR-5's floating origin, `GuardConfigStore`
checking the version integer): **a check computed over something that
CORRELATES with the protected quantity rather than the quantity itself.**

A count of sends correlates with how long a node has been running. Harm is not
uptime. That is the hypothesis, and §3 states the ceiling that would confirm or
refute it before any data is collected.

## 2. The three candidate quantities

| id | quantity | shape |
|---|---|---|
| **Q-COUNT** | cumulative MESH_EXIT **events** since genesis | count, monotone, currently registered |
| **Q-BYTES** | cumulative MESH_EXIT **bytes** since genesis | measure, monotone |
| **Q-RATE** | MESH_EXIT events per signed envelope | ratio, non-monotone |

Q-BYTES is a candidate because R10 established that **harm must be a MEASURE,
not a boolean**, and `egress_log.byte_count` is already recorded at every
MESH_EXIT site. Q-RATE is a candidate because a cumulative bound on a flow is
exhausted by any long-running node regardless of behaviour.

Q-RATE carries a known prior against it: R-E found that **a ratio permits 97%
destruction by compliant principals**. It is retained so that the comparison is
made rather than assumed.

## 3. Feasibility ceilings, computed BEFORE the run — standing rule #4

Each ceiling is derived from the code, not from data, and is falsifiable by the
run. **Recording them here is what makes §6's rules checkable.**

**C1 — the inference floor.** `make_anthropic_executor._executor`
(`gyza/runner.py`) records exactly one `outside_send` per invocation, in a
`finally`, and the runner invokes the executor once per work item. Therefore

> **Q-COUNT increases by ≥ 1 per executed action, exactly, on the in-process
> path.**

**Consequence, stated before data:** a level `L` on Q-COUNT permits **at most
`L` actions in the node's lifetime**, because the origin is immutable and can
never be advanced. `L` is a lifetime action budget denominated in actions.
A node that behaves perfectly and one that exfiltrates on every send exhaust it
at the same rate.

**C2 — Q-BYTES has no comparable floor.** Bytes per send vary with prompt and
payload size, so the same action count spans a range of Q-BYTES. Whether that
range SEPARATES benign from exfiltrating traffic is exactly what §6 tests; it is
not assumed here.

**C3 — the attestable ceiling is already measured and is a minority.**
`egress.py` records that only `send_message` is peer-addressed, so attestation
can reclassify **one channel of five**, ~16% of egress under a delta-dominated
mix. Any claim that H3 shrinks with mesh growth is bounded by that share, and
this route inherits the bound rather than re-deriving it.

**C4 — `attested_peers` has no production source.** `default_egress_recorder`
passes `None`, so `classify_peer` fails toward `UNATTESTED_PEER` and **every**
peer send counts toward H3. Measurements here are therefore an **over-count** of
true mesh exit. Over-counting is the safe direction for a bound and the unsafe
direction for a claim that H3 is small; §8 holds this against the result.

## 4. Environment

- Workload W1 — **local, no daemon**: the runner over a mock executor that
  invokes the same `outside_send` path as the real one. This isolates C1.
- Workload W2 — **two daemons on loopback** (`--dht-mode server`, `mdns=False`),
  driving `send_message`, `publish_delta`, `publish_agent`. This supplies the
  channel mix that C3's share is computed over.
- Workload W3 — **an exfiltrating variant of W1**: identical action count, each
  send carrying a large payload. This is the adversary Q-BYTES must separate and
  Q-COUNT (by C1) cannot.

**The inference send is measured without credits** by injecting an executor that
performs the same recorder call with the same byte accounting and returns a
canned response. What this does NOT measure is the real SDK's framing overhead;
`runner.py` already states the recorded count is a **lower bound**, and §8
carries that forward.

All three workloads write to a throwaway blackboard. Harm is computed by
`observe_now` from the append-only `egress_log`, never from a counter this
harness keeps — the harm-independence rule.

## 5. Measures

Reported for every workload: `Q-COUNT`, `Q-BYTES`, `Q-RATE`, the per-channel
split from `egress_by_channel_since`, and the `UNBOUNDED_GRANT` count **kept
separate** (a grant is a different unit from a send — `H3_BLIND_CHANNEL.md`).

Counter-metric, per standing rule #3: for every candidate level, the **actions
refused** alongside the **bytes withheld**. A quantity that refuses everything
bounds perfectly and is worth nothing.

## 6. Decision rules, feasibility checked

**SEPARATION** is the property a quantity must have to carry a level. Quantity
`Q` SEPARATES iff there exists a level `L` such that both hold:

- **(a) liveness** — a benign node completes **≥ 1000 actions** before `L`
  binds. 1000 is chosen against C1: at the 1-per-action floor, any Q-COUNT level
  below 1000 fails (a) by construction, and any level at or above it permits
  1000 exfiltrating sends too. The number is fixed here, before data.
- **(b) containment** — the W3 adversary is refused **before its 100th send**.

> **DECISION**
> - `Q-COUNT-DEAD` if Q-COUNT satisfies no `L` meeting both (a) and (b).
> - `Q-BYTES-CARRIES` if Q-BYTES admits such an `L`, with the range reported.
> - `NEITHER-CARRIES` if both fail — in which case H3 stays unbounded and the
>   containment claim stays FALSE, which is a legitimate outcome of this route
>   and **must not** be avoided by weakening (a) or (b) after seeing data.

**No tuning after results.** Implementation-bug fixes only, disclosed.

## 7. Point predictions, fixed before data

1. **Q-COUNT-DEAD.** By C1 the adversary and the benign node consume Q-COUNT at
   an identical rate, so no `L` satisfies (a) and (b) simultaneously. Predicted
   with high confidence because it follows from C1 by construction — if the run
   contradicts it, **C1 is wrong** and the inference site is not firing once per
   action, which is itself the finding.
2. **Q-BYTES separates, by at least 20×** between W1 and W3 per action.
3. **Q-RATE fails (b)**: an adversary that exfiltrates on every send has the
   same ratio as a benign node that sends on every action.
4. The W2 attestable share lands **within 10 points of the ~16%** already
   recorded, or the channel mix differs and the difference is reported.

## 8. What this route cannot establish

- It does not measure the real Anthropic SDK's on-wire bytes. Every Q-BYTES
  figure is a **lower bound** on true disclosure.
- C4 means peer sends are over-counted as exit. Q-BYTES levels derived here are
  therefore **conservative for the bound and pessimistic for the claim** that
  mesh growth shrinks H3.
- It cannot see sandboxed egress at all. That is `UNBOUNDED_GRANT`, a different
  unit, and no level in this route closes it (`H3_BLIND_CHANNEL.md`).
- **It does not declare a level.** It reports attainable ranges and which
  quantity can carry one. The level is a product decision, and choosing it is
  Aaron's (`CLAUDE.md` §10).
