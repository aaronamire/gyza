# Arena 1 — preregistration

**Committed BEFORE any WAN data exists.** Every prediction below is falsifiable
and stated as a point value or an ordering, so it cannot be rationalised after
the fact. This is the discipline Arena 2's value came from.

**Status at time of writing:** zero instances exist. The loopback CONTROL is
complete (`FINDINGS_PARTITION_CONTROL.md`, `HEAL_WINDOW.md`); the WAN
EXPERIMENT has not been run.

---

## 0. What is being measured, and why it needs hardware

`03_TECHNICAL_PLAN.md` §3.6 promises **time-to-recovery under degraded comms,
measured as a distribution**, and §3.7 concedes no DDIL claim beyond a clean
cut. Loopback RTT is ~0.05 ms; Amsterdam–Sydney is ~280 ms. **A factor of
~5,600 is the entire reason this cannot be answered on a laptop**, and it is
the only claim in the proposal for which that is true.

## 1. Environment

- **3 nodes**: New York (`gyza-us`), Amsterdam (`gyza-eu`), Sydney (`gyza-ap`).
  Vultr `vx1-g-2c-8g`, 2 vCPU / 8 GB, Ubuntu 24.04.
- **500 agents total, ~167 per node**, as `RunnerThreadRoster` threads.
- **Executor**: `make_command_executor` running `/usr/bin/uname -a` inside
  bubblewrap, so every action carries an enforcement record.
- Daemons: `--mdns=false`, `--dht-mode server`, explicit `--bootstrap`
  (`FallbackPeers` is empty; DNS still advertises three destroyed nodes).
- **Truth predicate for a partition is the PEER COUNT reaching 0 on every
  affected side** — never the absence of a connection event.
- **Posts are paced at >= 10 ms.** Measured: a tight loop loses 7% of gossip
  deltas on loopback and 5 ms takes it to 0. Unpaced, this harness would
  measure its own burst loss and call it partition behaviour.

## 2. Control values already measured (loopback, $0)

| quantity | control |
|---|---|
| duplicate execution under a symmetric cut | **100%** (worst case by design) |
| board agreement after heal | **0/20** — LWW converges the row, not the work |
| heal → first cross-node delivery | **2.08 s** |
| gossip burst-loss threshold | **5 ms** inter-post spacing |
| claim exclusion WITHIN a node | absolute — 0 double-claims up to 750 agents |

## 3. Predictions

> **P1 — RTT will have NO material effect on duplication during a FULL
> partition. Predicted 90–100%, i.e. statistically indistinguishable from the
> loopback control.**
> Rationale: once the link is cut there is no gossip in either direction, so
> latency cannot matter; both sides see the same mirrored backlog and claim it
> independently. **Falsified if WAN duplication is below 75%.**

> **P2 — An ASYMMETRIC (one-way) cut will duplicate at roughly HALF the
> symmetric rate. Predicted 40–60%.**
> Rationale: the side that still receives sees the other's claims and declines
> them; the side that does not, duplicates freely. **Falsified if asymmetric
> duplication is within 10 points of symmetric**, which would mean claim
> propagation is not what suppresses duplication.

> **P3 — Heal TTR will be HEARTBEAT-dominated, not RTT-dominated. Predicted
> 2–5 s at every RTT, including the 280 ms Amsterdam–Sydney leg.**
> Rationale: gossipsub's heartbeat is 1 s and re-meshing costs a small number
> of GRAFT/PRUNE rounds; 280 ms of RTT adds well under a second to that.
> **Falsified if TTR exceeds 10 s on any leg**, which would mean something
> other than the heartbeat governs re-meshing.
>
> **THIS PREDICTION CONTRADICTS OUR OWN DOCUMENTATION AND THE CONTRADICTION IS
> DELIBERATE.** `CLAUDE.md:624` states that mesh re-formation "needs 10–15 s on
> 2-node loopback". The control measured **2.08 s** for first successful
> delivery. Either the documented figure is stale, or it describes full mesh
> stabilisation while the control measures the operationally meaningful event.
> **Resolving that discrepancy is an outcome of this run**, and if TTR comes
> back at 10–15 s the control was measuring the wrong thing and P3 is wrong.

> **P4 — The post-heal silent-loss window will be WIDER in wall-clock on WAN,
> and will scale with re-meshing time rather than with RTT. Predicted 1–5 s.**
> Rationale: `HEAL_WINDOW.md` established that an item published after
> `connect_peer` reports success but before the mesh re-forms is permanently
> lost, because gossip does not retry and the CRDT converges over deltas
> RECEIVED. **Falsified if any item published at t+0 after reconnect arrives**,
> which would mean the window does not exist on WAN.

> **P5 — Availability is preserved throughout: per-node throughput during a
> partition will be within 20% of its unpartitioned value.**
> Rationale: the design is AP. Each node's agents work from local SQLite and
> never block on the network. **Falsified if throughput drops by more than 20%
> on any side**, which would mean a hidden network dependency in the work path.

> **P6 — The burst threshold will be HIGHER on WAN than the 5 ms control, but
> under 50 ms.** Weakest prediction here and flagged as such: the mechanism
> (publish-queue overflow) is understood only well enough to give a direction,
> not a value.

## 4. Feasibility ceilings — computed for BOTH sides of every comparison

Standing rule #4 has failed six times in this program, most recently by
checking the ceiling of the system under test and not of the apparatus.

- **C1 — Posting rate.** At 10 ms pacing, 500 items take 5 s. Non-binding.
- **C2 — Duplication needs a mirrored backlog.** Items must be posted AND
  mirrored before the cut, which at 10 ms pacing plus propagation is ~10 s.
  Non-binding.
- **C3 — TTR resolution is bounded by the probe interval.** The control probes
  every 2 s, so it cannot resolve a TTR below ~2 s — **and it reported 2.08 s,
  which is at the resolution floor.** The WAN harness must probe at 100 ms or
  the P3 range 2–5 s cannot be distinguished from the instrument.
- **C4 — Agent count.** 167/node is under the measured 750-agent single-board
  wall by 4.5x, so `database is locked` should not appear. If it does, the run
  is measuring SQLite and not the network.
- **C5 — Throughput.** ~1.95 actions/sec/core × 6 vCPU ≈ **11.7 actions/sec
  total**, shared by 500 agents. **This run cannot say anything about
  throughput at scale and will not try.**
- **C6 — Budget.** 3 × $0.060/hr = $0.18/hr; an 8-hour session is $1.44,
  inside $10 with room for one failed attempt.

## 5. What each outcome would change

- **P1 confirmed** → duplication is a property of the architecture, not of the
  network, and irreversible work needs either a fencing token or a CP path.
  This is a design finding, not a bug report.
- **P3 confirmed** → "recovery in seconds regardless of distance" becomes a
  measured DDIL claim, and §3.7's concession is replaced.
- **P4 confirmed** → anti-entropy moves from "scheduled Phase 1 work" to a
  prerequisite for any distributed deployment.
- **P5 falsified** → there is a hidden network dependency in the work path,
  which would be the most serious finding available here.

## 6. What this run will NOT claim

Throughput at scale (C5). Correctness of any output. That 500 agents is a
practical operating point rather than a demonstration — at 11.7 actions/sec
total, each agent gets ~0.023 actions/sec, and **"500 agents coordinating" and
"500 agents working at scale" are different sentences that must not be merged.**
