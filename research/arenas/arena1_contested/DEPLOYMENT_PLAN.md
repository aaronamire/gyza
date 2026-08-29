# Arena 1 — 500 agents, three continents, one measured DDIL result

**Target: the single thing DICE asks for that Gyza currently concedes.**
`03_TECHNICAL_PLAN.md` §3.6 promises *"time-to-recovery under degraded comms,
measured as a distribution"*, and §3.7 concedes *"we do not claim DDIL
resilience beyond a clean cut."* This run replaces that concession with a
number, and it is the only claim on the list that a laptop physically cannot
produce — loopback RTT is ~0.05 ms; New York to Sydney is ~200 ms, a factor of
4,000.

## What the run produces

1. **A time-to-recovery distribution**, not a single clean cut: symmetric
   splits, asymmetric (one-way) loss, and repeated flapping, across three real
   WAN legs with genuinely different latencies.
2. **The heal-window measurement.** `HEAL_WINDOW.md` established, on loopback,
   that an item published after `connect_peer` reports success but before the
   gossip mesh re-forms is **permanently lost** — and that `wait_for_sync`
   returns "synced" without checking on exactly that plane. Its WIDTH across
   real WAN is unknown and is the most valuable number this deployment can
   return.
3. **One signed evidence bundle for the whole run**, verifiable offline by a
   reviewer who trusts none of the three machines.

## Why 500 agents and not more

Measured, not chosen: the single-blackboard wall is **~750 agents**, where
`database is locked` failures overtake successes. 500 across three nodes is
**167 per board** — under the wall by 4.5x, so the experiment measures the
NETWORK rather than SQLite contention. Raising agent count would degrade the
thing being measured.

## Topology

| node | region | role |
|---|---|---|
| `gyza-us` | **New York, US** | Americas |
| `gyza-eu` | **Amsterdam, NL** | EMEA |
| `gyza-ap` | **Sydney, AU** | APAC |

Chosen for **RTT diversity**, which is what makes a *distribution* rather than
three copies of one number: NY↔AMS ~80 ms, NY↔SYD ~200 ms, AMS↔SYD ~280 ms.
Three nodes is also the minimum that supports a **2-1 majority/minority split**,
which is the interesting partition shape.

Plan: **`vx1-g-2c-8g`** — 2 vCPU, 8 GB — at **$0.060/hr** each.
- 8 GB is large headroom: 167 agents cost ~200 MB, and 500 on one box measured
  487 MB.
- 2 vCPU gives ~3.9 actions/sec/node at the measured 1.95/core. Throughput is
  not what this run measures; partition behaviour is.

**Cost: 3 x $0.060 = $0.18/hr.** An 8-hour session is **$1.44**; a full day is
**$4.32**. Both inside the $10 budget with room for a failed attempt.

---

# PREREQUISITE — two engineering gaps, and neither is optional

**Do not create instances before these land.** They are free to build on a
laptop and the hardware is useless without them.

### Gap 1 — the fleet entry point is one OS PROCESS per agent

`gyza serve` uses `RunnerProcessSupervisor`. At the measured 138 MB per-process
baseline, 500 agents is **~69 GB**. As threads it is **~0.5 GB**, and threads
are the correct topology for this workload: subprocess-bound work scales
**29.89x at 32 threads** (CPU-bound scales 0.66x) because the GIL is released
across the bwrap call.

`AgentSupervisor` already runs runners as threads but is `NON_ADOPTED`, and its
stated reason is still live: *"threads share a fate — one unhandled exception in
one runner takes the whole roster."* Adopting it needs per-thread fault
isolation, which is the work.

### Gap 2 — `gyza serve` has no networking at all

Verified: no `NetworkBlackboard`, no `attach_gossip`, no `GossipClient`.
`RunnerSpec` carries a blackboard *path*, so every process opens a local SQLite
file. **Three nodes running `gyza serve` today are three isolated islands.**
Without cross-node gossip there is no distributed coordination, so there is
nothing for a partition to partition — and the entire deployment measures
nothing.

This is the larger gap and it is the whole point of the run.

### Also required before instances exist

- **A preregistration with predictions committed to a hash BEFORE any data**,
  per the discipline every route in this program follows. Arena 2's value came
  from predictions that could not be rationalised afterwards.
- **The partition harness**: the three cut shapes, with the *peer count reaching
  zero on both sides* as the truth predicate — not the absence of a connection
  event, and not an application-level symptom.
- **`--bootstrap` wiring.** `FallbackPeers` is now empty (the old nodes were
  destroyed and their IPs reallocated), and `_dnsaddr.gyza.network` still
  advertises three dead addresses. The new nodes must be bootstrapped by
  **explicit multiaddr**, not by DNS.

---

# DEPLOYMENT GUIDE

Run these once the prerequisite lands. Every step is yours; none of it can be
done from a session.

## Step 0 — SSH key (once)

```bash
cat ~/.ssh/id_ed25519.pub
```
Vultr console -> **Orchestration -> SSH Keys -> Add SSH Key** -> paste.
Without this the instance emails a root password and the deploy script cannot
run unattended.

## Step 1 — create three instances

For each of New York, Amsterdam, Sydney:

- **Type**: Dedicated CPU -> **VX1** -> `vx1-g-2c-8g` (2 vCPU / 8 GB)
- **OS**: Ubuntu 24.04 LTS x64
- **SSH Key**: select the key from Step 0
- **Hostname/Label**: `gyza-us`, `gyza-eu`, `gyza-ap`
- Leave backups/DDOS/IPv6 off — they cost money and this is a bounded run

Record the three public IPv4 addresses.

## Step 2 — firewall (Network -> Firewall Groups)

Create one group, attach it to all three instances:

| purpose | protocol | port | source |
|---|---|---|---|
| SSH | TCP | 22 | **your IP only** |
| libp2p QUIC | **UDP** | **7749** | the other two node IPs |

**UDP, not TCP.** The daemon listens on QUIC; a TCP-only rule silently produces
a mesh that never forms, and the failure looks like a Gyza bug.

## Step 3 — deploy

From the repo root, one node at a time:

```bash
./scripts/deploy-bootstrap.sh root@<NY_IP>  gyza-us
./scripts/deploy-bootstrap.sh root@<AMS_IP> gyza-eu
./scripts/deploy-bootstrap.sh root@<SYD_IP> gyza-ap
```

**Do not pass `--demo-agent`.** It installs the hosted demo agent that claims
public work and spends the Anthropic key; this run needs neither.

## Step 4 — mesh them explicitly

DNS discovery is dead, so wire the bootstrap set by hand. On each node, get its
peer id:

```bash
ssh root@<IP> '/usr/local/bin/gyza-netd --key-path /etc/gyza/node.key --print-peer-id'
```

Then start each daemon pointing at the other two:

```
--bootstrap /ip4/<OTHER1_IP>/udp/7749/quic-v1/p2p/<OTHER1_PEERID>,\
/ip4/<OTHER2_IP>/udp/7749/quic-v1/p2p/<OTHER2_PEERID>
--dht-mode server
```

`--dht-mode server` matters: `auto` starts as Client and, without AutoNAT
signalling on a small mesh, may never promote — **and the failure is silent.**

## Step 5 — verify the mesh BEFORE running agents

```bash
ssh root@<IP> 'gyza global peers'
```
Every node must show **2 peers**. Anything less and the partition experiment is
measuring a mesh that never formed. Do not proceed on a partial mesh.

## Step 6 — the run

Driven from the repo once the prerequisite lands; the harness handles roster
start, the three cut shapes, heal timing and bundle export.

## Step 7 — TEARDOWN, and this is not optional

```
Vultr console -> Instances -> ... -> Destroy
```

**Destroy, not power off.** A stopped instance still bills, and the previous
three bootstrap nodes are gone in a way that suggests exactly this. Confirm the
console reads **No Instances** afterwards.

Then: those IPs return to Vultr's pool and are reallocated to strangers within
days. **Do not commit them to `FallbackPeers` or DNS** unless the nodes are
permanent — that is precisely how the shipped daemon came to be dialing three
machines belonging to other people.

---

## What this run may and may not claim

**May:** 500 agents coordinating across three continents with signed provenance;
a time-to-recovery distribution over three partition shapes at real WAN
latency; the heal-window width, measured; an evidence bundle a reviewer
verifies offline while trusting none of the machines.

**May NOT:** anything about sustained throughput. At ~1.95 actions/sec/core,
six vCPUs give ~11.7 actions/sec total, and 500 agents share it. **This is a
COORDINATION and RESILIENCE experiment, not a throughput one**, and the two
must not be quoted as one number.

---

# Gap 2 closed (2026-08-25) — and it was hiding a data-loss bug

Two real daemons on loopback, gossip-attached `NetworkBlackboard` on each, a
`RunnerThreadRoster` on each. Work posted on node A only.

**Result: 12/12 items mirrored A->B in 0.20 s; 11 signed on BOTH nodes; ZERO
cross-node duplicate executions.**

## The bug this exposed, which nothing else would have

`NetworkBlackboard.complete_work_item` **dropped `expected_owner`**, a
parameter its base class accepts and the runner always passes by keyword. The
resulting `TypeError` landed in `_complete`'s best-effort
`except Exception: pass`.

**So on ANY networked deployment, every completion silently failed to record.**
Envelopes were signed and stored — 6 of them in the first run — while the board
showed `completed_at_ns = NULL` for every item. Work stayed
claimed-but-incomplete until the lease expired, then was redone. Forever.

Two fixes, and the second is the more important:

1. The override now passes `expected_owner` through. An AST-style signature
   sweep confirmed this was the **only** such override, and
   `tests/test_override_signatures.py` now enforces it with a negative control
   proving the detector can fail.
2. **`_complete` no longer swallows programming errors.** `TypeError` and
   `AttributeError` re-raise; everything else still degrades best-effort but
   now **logs**. A signature mismatch is not a storage failure, and treating it
   as one made a permanent bug look exactly like a transient disk hiccup.

This is the **third dropped-parameter bug in one day** (`get_unclaimed`'s
`limit`, `try_claim`'s `claimant_tier`, then this) — and `try_claim`, two
methods above, already carries a comment warning that an override dropping a
parameter "would silently reintroduce the gap". A correct comment two methods
away did not prevent it. The mechanised check is what does.

## A prediction of mine, refuted

I expected cross-node **duplicate execution**: `try_claim` wins locally via
SQLite and only then publishes, so two nodes can both claim the same item with
HLC last-writer-wins settling it afterwards. **Measured zero on loopback**,
because the claim gossips in 0.20 s — faster than the other node's poll
interval.

**That result is a CONTROL, not a conclusion.** Loopback RTT is ~0.05 ms;
Amsterdam-Sydney is ~280 ms, so the window in which two nodes can both believe
an item is unclaimed is roughly **5,000x wider** on the real deployment.
Whether duplicate execution appears there — and at what rate, under which
partition shapes — is exactly the question Arena 1 exists to answer, and it now
has a measured zero-latency baseline to be compared against.
