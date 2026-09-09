# Gyza

**A substrate for multi-agent work, and a preregistered research program on
what a *population* of agents does to the safety properties that hold for
one.**

The open question in multi-agent AI is not whether a single agent behaves. It
is what happens when there are many: when they claim from a shared board,
decompose each other's work, run concurrently across a partition, and their
individual guards each say yes. Gyza is two things at once — a running system
where that happens, and the measurement of what it costs.

Every action an agent takes emits one signed envelope binding its key, its
capability manifest, its inputs, its output, and its parent action. Chains and
multi-parent DAGs verify offline with zero trust in the machine that produced
them. Authority is provably non-increasing down a delegation chain, and the
runner refuses to sign when observed enforcement is wider than the manifest it
was granted.

---

## Submitted to DARPA — DICE

**A full proposal was submitted to DARPA on 25 August 2026** under BAA
**HR001126S0010** — *Decentralized Artificial Intelligence through Controlled
Emergence* (DICE) — bidding Technical Areas 1 and 2, submission identifier
**HR001126S0010-DICE-FP-052**.

DICE asks how decentralized AI systems can be given controlled, verifiable
emergent behaviour. That is the question the rest of this README is about:
**this repository is the evidence that proposal cites**, and the multi-agent
results below are the measurements it was written on.

> **Submission is not selection.** No award has been made, no evaluation
> outcome is known, and nothing here is endorsed by DARPA or the U.S.
> Government. The submission is stated because this repository is the evidence
> cited in that proposal, and a reader should know what it was written for.

---

## The result that motivates the rest

Four preregistered routes, each with its decision rule committed before the
data existed, asked whether per-agent safety composes to a population. **It
does not**, and the four failures are structurally different:

| Route | Verdict | What it means |
|---|---|---|
| **R13** federation | `FEDERATION-DOES-NOT-COMPOSE` | Signature-gated local checks do not bound global multi-principal harm. Every leaking action carried every signature it required — **a signature authorizes an action, it does not bound a consequence**. A *stateless* check cannot accumulate, and statelessness is the same property that made it partition cleanly. |
| **AG-3** aggregate | `AGGREGATE-IS-HARDER` | An admission decision taken from a *stale read* of a quantity other principals can move is unsound — even when the read is perfectly consistent, and even when each guard reads only its own principal's state. The counterexample: four actions each admitted at concentration ≤ 0.40 jointly reach **0.625**, and the principal that breached its bound **took no action at all**. |
| **Arena** M > 3 | `BOX-SOUNDNESS-IS-SINGLE-THREADED` | The local box check is sound at **exactly 0.0000** violations for one thread per principal, at every M from 2 to 512 — and breached at every M the moment a principal runs two. n = 2, 4 and 8 are identical: the entire effect is the 1 → 2 transition. **Soundness was a property of single-threading, not of scale.** |
| **§4.2** red team | `HARM-IS-TRANSFERRED` | Run against the *shipped* guard, not a simulation. No declared bound was violated in any attack and the system was harmed anyway: the guard prevented 180 credits of drawdown and created 180 credits of unpaid delivered work. **A bound on a conserved quantity relocates harm onto counterparties the model does not measure.** |

The constructive half is as specific as the negative half:

- **Hierarchy helps decisively** (`R-H1`), and the benefit is the *leaf floor* — not the internal checks.
- **Review capacity federates if and only if it is attached to principals.** Per-principal reviewer load is flat in M (4.0 reviews/reviewer at M = 2 and at M = 512); a single federation-wide bound serializes onto one human and caps throughput regardless of M.
- **Topology bounds damage** (`R-B`): the defector count a federation survives rises with depth, and cluster size is a design parameter.
- **The invariant is total remaining value** (`R-T`) — and getting there cost this program two published headlines. `R-B`'s "≈1.6 defectors per cluster" and `R-T`'s own "coverage is the invariant" were both *correlates* of the protected quantity, not the quantity; running one cheap extra depth falsified the second within the hour. Breach is governed by the **denominator** alone, targeting the largest holder does nothing, and **every `k*` this program published against a randomly-placing adversary is an over-estimate — `R-B`'s 103 is loose by 1.87× against an honest tolerance of 55.**
- **Dispersal is self-defeating** (`R-D`) — the attack the churn route could not test is strictly worse than the one it did.

Entry points: `research/federation/FINDINGS_R13.md`,
`research/aggregate/FINDINGS_AG3.md`, `research/arena/FINDINGS.md`,
`research/harm_redteam/FINDINGS.md`, `research/PROGRAM_STATUS.md`.

---

## Status

Maturity: **alpha, Linux, source install.** A local fleet runs today — agents
claim from a shared board, execute sandboxed, and sign receipts that verify
offline on a machine that has never seen the project. The multi-node
coordination plane runs in a local testbed. Public bootstrap nodes are offline.

---

## Run a fleet, then verify it without trusting us

Nothing below asks you to believe a number in this file.

```bash
# Linux x86_64/aarch64, Python 3.10+, bubblewrap (bwrap) for sandboxing.
git clone https://github.com/aaronamire/gyza && cd gyza
pip install -e . && gyza init
```

**Five agents, a partition, and one auditable history** — zero config, offline,
runs in seconds:

```bash
gyza demo partition
```

Five nodes split into a control plane and a data plane, the link is cut, work
continues on both sides, an over-bound action is refused with no connectivity
available to ask anyone, and the histories merge. It ends by reconstructing the
full provenance DAG and re-verifying it:

```
envelopes after merge: 7 (expected 7) → 0 lost
causal-spine view: 2 branch(es) from the partition, each verify_chain-valid
full provenance DAG (verify_dag): VALID  [1 root, 1 leaf, 7 nodes]
audit_provenance(): 7 envelopes, 5 bounded execution(s); verdict=VALID
```

**A real supervised fleet on real sandboxed work:**

```bash
gyza serve --agents 3 -- /usr/bin/uname -a   # one OS process per agent, single-node
gyza status                                  # board, artifacts, harm bounds
gyza audit <intent_id>                       # one forensic verdict over the DAG
```

For a **multi-node** deployment, agents are threads attached to a gossip
project, so work posted on any node is claimable on every node:

```bash
gyza global start && gyza global status      # the daemon must be running AND meshed
gyza swarm --agents 3 --project my-project   # every node must pass the SAME project id
```

`gyza swarm` attaches to a daemon; it does not start one. Check the peer count
on every node first — a roster on an unmeshed node is a single-node fleet
wearing a distributed name, and nodes that mesh at the transport layer while
disagreeing on the project id look like a working cluster doing nothing.

Each agent gets **its own identity** — not N runners behind one key, which
would pool a per-principal rate cap and exhaust it N times faster. That is the
aggregate-bounding argument above, applied to our own process model.

**Then hand the evidence to someone who trusts nothing:**

```bash
gyza bundle <intent_id> -o run.tar.gz
gyza verify run.tar.gz     # no node, no daemon, no identity, no network
```

`gyza verify` re-derives every hash and signature from the bundle alone. If it
returns VALID on a machine that has never seen this project, the receipt is
sound; if a byte was altered, it fails. **Nobody outside this project has yet
run that check on a bundle they did not produce** — that is the largest open
credibility gap here and the cheapest one to close.

---

## The coordination layer

A **blackboard / stigmergic** model, implemented rather than described.

**A shared board with atomic claiming.** `try_claim` is atomic locally and only
then publishes. Mutual exclusion within a node is absolute — **zero
double-claims at every agent count measured, up to 750**, under genuine process
contention.

**Claims are leases, not deeds.** A runner that dies holding one no longer
leaks the work item; `reclaim_expired_claims` returns it, and completion
verifies ownership so a slow runner cannot overwrite whoever reclaimed its work.

**A work DAG with a join.** Work items carry `parent_id` and `lineage_root`. An
item whose `output_spec` declares `kind: "combine"` is **not servable while any
sibling is outstanding** (`pending_siblings`), so a combiner cannot sign a
partial result.

**Decomposition is bounded by the signed manifest, not by code.** An agent may
create work for other agents only if its compositor-signed manifest carries
`spawn.permitted` and a `max_children` budget — **default 0, least privilege**;
`gyza serve --spawn-children N` is the explicit grant. The runner refuses over
budget, refuses past `MAX_TASK_DEPTH = 3`, and clamps a child's `required_tier`
to its parent's so a low-tier decomposer cannot mint work only better-attested
agents may take. A refusal is a `RuntimeError` on the same path a bounds
violation takes: **no envelope is produced**, so a signed envelope still implies
the action stayed inside its grant.

> **What is granted and what is exercised are different questions.** The grant
> reaches the manifest and the gate enforces it, both covered by tests. But of
> the three executors selectable from the CLI — `mock`, `command`, `anthropic`
> — **none requests a decomposition**. The reference planning executor
> (`make_planning_executor`) is exercised in tests and is not CLI-reachable, so
> from `gyza serve` today no child work item is ever created. This is stated
> because "ask what supplies the quantity, not whether the checker exists" is
> the failure this project keeps finding in itself.

**Selection decorrelates agents.** `get_unclaimed` is deterministically ordered,
so a strict argmax made every agent want the same row and the claim win rate
fell as 1/N — 100%, 50.4%, 27.9%, 19.9%, **11.4%** at 1..16 agents. Ties are
now broken at random within an epsilon, and the fetch is bounded. A negative
control pins that a *unique* best item is still returned, so the change
decorrelates without weakening selection.

**Humans are in the loop, and the loop is append-only.** `gyza review` lists
escalations and resolves them. A RESUME requires a named reviewer and a reason,
because it advances the accounting origin — and an origin advance nobody is
accountable for is how a cumulative bound is defeated silently. Every resume is
an appended record, never a reset.

---

## Measured, not asserted

Every figure comes from a preregistered run whose decision rule was committed
before the data existed, with a hash predating every result artifact.

### Coordination

| Quantity | Value |
|---|---|
| Claim exclusion within one board | **0 double-claims** at every count to 750, before and after the contention fix |
| Contention fix, homogeneous work | **44×** at 16 agents (4 → 175 claims/s); win rate 11.4% → **91.1%** |
| Single-board wall | **~750 agents**; first failures at 1,000, all `database is locked`; wall at 1,500 |
| Partition scaling (cores available) | **1.73×** at 2 partitions against a ceiling of 2.00× |
| Sandboxed agent actions | **1.95 / sec / physical core** |
| Resident cost per running agent | **2.24 MB** running (0.27 MB constructed) |

### Under partition

| Quantity | Value |
|---|---|
| Duplicate execution across a partition | **100%** — worst case by construction |
| Board agreement after heal | **0 / 20** — last-writer-wins converges the row, not the work |
| Post-heal silent-loss window | **0.400 s + 3.098 × RTT**, R² = 0.907, 17 runs, **0 inversions** |
| Compromised-agent arena | **11 attacks, 11 preregistered outcomes, 0 failed positive controls** |

### Verification

| Quantity | Value |
|---|---|
| Cheap structural checking, inside competence | J = 0.777, LR = 19.8, n = 433 |
| Provenance across chain depth | **flat at 1.0000 through depth 8** |
| Correctness across chain depth | **0.0 at every depth, including depth 1** |

Three of these deserve a sentence.

**100% duplicate execution.** Two real daemons, gossip-attached boards, four
agents each. The design forces the worst case deliberately — mirror all work,
cut, start both rosters from an identical view — so 100% is an upper bound, not
an average. What it establishes is that **nothing in the architecture prevents
it**. For idempotent work this is waste; for an irreversible action it is a
correctness failure, and **convergence is not compensation**: after heal both
envelopes exist and both verify.

**The silent-loss window.** An item published between the moment the transport
reports success and the moment the gossip mesh re-forms is lost permanently —
gossip does not retry, and the CRDT converges over deltas *received*. Sweeping
RTT with `tc netem` gives a ~400 ms floor plus roughly three round trips, which
is what a mesh handshake costs. Zero non-monotone runs out of 17 makes this a
window with a sharp edge rather than a decaying probability, which is what makes
a readiness predicate a viable remedy rather than only anti-entropy.

**The competence bound.** A preregistered program across six structurally
independent mechanism families found that cheap black-box verification of
natural-language reasoning is bounded by the verifier's competence: *you cannot
cheaply verify what you cannot understand*. Each family was preregistered with
a decision rule before data and each failed for the same reason from a
different direction. The durable positive — cheap structural checks do work
**inside** the checker's competence — is the only regime a bonded market is
viable over.

---

## What this proves, and what it does not

Being precise about the boundary is the point of the design, not a caveat
appended to it.

**Proven, with the code as witness:**

| Property | Where |
|---|---|
| Actions are attributable and tamper-evident; chains and DAGs verify offline | `verify_chain`, `verify_dag` in `gyza/icp.py` |
| Authority is monotone non-increasing down a delegation chain | `verify_delegation` in `gyza/economy/delegation.py` |
| A valid signed envelope implies bounded execution — the runner refuses to sign otherwise | `require_enforcement` in `gyza/runner.py` |
| Mutual exclusion on a shared board; a dead agent's claim returns | `try_claim`, `reclaim_expired_claims` in `gyza/blackboard.py` |
| Decomposition is capped by the signed manifest and by depth | `_spawn_subtasks` in `gyza/runner.py` |
| Balances are a fold over append-only entries; no field an unmodelled path can write behind a guard's back | `gyza/economy/ledger.py`, `wallet.py` |
| One forensic surface composing the real verifiers, failing closed | `audit_provenance` in `gyza/audit.py` |

**Not proven, and not claimed:**

- **Correctness of any output.** Gyza establishes *accountability* and
  *containment*. Whether a result is *right* is a human decision — a measured
  limit, not an omission.
- **That local containment aggregates.** This is the headline above, and it is
  our own result against our own design. Four consequence classes are declared
  under a signed configuration and are **measured, not yet enforced**.
- **Containment as a whole.** `can_claim_containment` is currently **false**,
  for one reason: the authority signing key lives on the same host that runs
  agents, so anything able to read that file could re-sign the policy it is
  constrained by. Every other gate is closed and verified — `readiness()` with
  the key absent returns true.
- **Effects that leave modelled state.** A guard can refuse to *emit*. After
  emission, containment has no meaning and no detector would help.
- **Scale.** The largest measured configuration is 750 agents on one board and
  500 across a partitioned pair. Scaling above ~4 concurrent agents is **not
  merely untested but untestable on the development host** — the apparatus
  saturates below the interesting region, and a thousand-agent claim needs
  hardware before it needs code.
- **Anti-entropy.** Implemented in the demo coordination plane and **not** in
  the production gossip path.

---

## How it works

**Identity.** A local compositor derives per-agent Ed25519 keys from a master
seed via HKDF. No certificate authority. An agent's identity is its key, and a
compositor certificate binds a key to a capability manifest.

**Provenance.** Canonical JSON → BLAKE3 → sign-the-hash with Ed25519. Each
envelope carries the agent pubkey, the manifest hash, input hashes, the output
hash, and parent-envelope hashes. Multi-parent DAGs reconstruct and verify.

**Attenuation.** A `CapabilitySpec` covers five dimensions — read paths, write
paths, a network boolean, a memory cap, and an action rate cap — plus a
separate signed spawn budget. Delegation is proven monotone non-increasing,
with bounded depth and cycle detection, so a subcontractor honestly inside its
*own* over-wide manifest is still caught at the `manifest ⊆ delegated` step.

**Execution.** Bubblewrap — unprivileged user namespaces plus seccomp. This is
an **OS-enforced** boundary, not a kernel security boundary, and the distinction
is deliberate. The sandbox is derived from the signed manifest, and the
enforcement record is folded into the artifact so the envelope hash commits to
it.

**Networking.** libp2p host, Kademlia DHT, gossipsub, QUIC. None of it is
homegrown — the failure mode for a project like this is writing a custom
overlay, and the risk is concentrated in the thin layer written on top, which is
where the partition results above come from.

**Formal methods.** TLA+ specifications for settlement, reconciliation and
attestation, each with an honest and an adversarial model, and a Rust reference
implementation with byte-parity fixtures against the Python. *The TLA+ sources
and the invariant catalogue are not in the public tree.*

---

## Research discipline

The unusual thing about this repository is not a feature; it is the record of
being wrong in public.

- **Preregistration before data.** 50 preregistration documents, each
  committing environment, configurations, decision rules and point predictions
  with a hash that predates every result.
- **A corrections log — 34 entries.** Claims this project made and then had to
  retract, with the mechanism that produced each error. Superseded text stands
  unedited by design, so the index is the only way to find what moved.
- **An artifact ledger.** Clean numbers that turned out false, kept with the
  reason each was believed. An exact 0 or 1 is treated as a suspected artifact
  until shown to be definitional.
- **Report the cost beside the catch.** A guard that blocks everything has
  perfect containment and zero value. Every containment number is paired with
  its counterfactual — which is how `HARM-IS-TRANSFERRED` was found, in our own
  shipped guard.
- **Feasibility ceilings computed for both sides** of every comparison,
  including the apparatus. Checking only the system under test has produced a
  meaningless verdict here more than once — most recently a 4-core laptop
  reported as an architectural ceiling.
- **Negative results published.** `ROUTER-DEAD` (difficulty-based routing fails
  even with an AUROC-1.000 oracle), `R12 UNSOUND`, `RESERVATION-DEAD-ABOVE-M=3`,
  and the competence bound itself. Each closed a line of work this project
  wanted to keep.

Entry points: `research/PROGRAM_STATUS.md`, `research/FRONTIER_LEDGER.md`,
`research/CORRECTIONS.md`.

---

## Known gaps

Stated because a gap you can read is worth more than one you find.

1. **Aggregate bounds are unsound under concurrency.** `AGGREGATE-IS-HARDER`
   is a property of the design, not only of a simulation: an admission decision
   that is a function of joint state must be linearized against joint-state
   updates, and nothing in the current path does that.
2. **No production anti-entropy.** A gossip delta lost into a not-yet-formed
   mesh is never reconciled. Work-item deltas now carry their lineage intent so
   that specific failure self-heals, but a lost *claim* or *completion* does
   not. This is the largest correctness gap in the distributed layer.
3. **The attestation tier is a scheduling filter that reads like an
   authorization boundary.** `required_tier` is consulted in one place — the
   polling query. A tier-0 agent that learns an item id by any other means can
   claim it, execute it, and sign a valid envelope. The tier is not one of
   `CapabilitySpec`'s five dimensions, so the attenuation proof says nothing
   about it. A gap in coverage, not a hole in the proof.
4. **Decomposition is granted but never requested.** See the note above: no
   CLI-selectable executor emits a subtask request.
5. **Authority key colocation.** The single reason `can_claim_containment` is
   false.
6. **Compositor key rotation is deferred**, and a naive implementation would
   pin history to the old key while the live gate reads the new one.
7. **No external verification.** Nobody outside this project has verified a
   bundle.
8. **n = 1.** Every measurement here is of this system. The theorems are
   general; the evidence for them is not.

---

## Tests

```bash
python -m pytest tests/ -q --tb=line --timeout=90     # Python, 115 files
cd netd    && go test ./... -count=1                  # Go daemon
cd gyza-rs && cargo test --workspace                  # Rust reference, 111 tests
```

The Rust crates carry parity tests against fixtures generated from the Python,
so a divergence in canonical encoding fails the build rather than producing two
implementations that quietly disagree.

---

## Layout

```
gyza/        Python — the product
  blackboard.py  shared board: atomic claims, leases, the work DAG + combine gate
  runner.py      claim / execute / sign; the bounds gate and the spawn gate
  roster.py      RunnerThreadRoster — agents as threads, for multi-node swarms
  supervisor.py  RunnerProcessSupervisor — one OS process per agent, restart on stall
  icp.py         signed envelopes; chain and DAG verification
  audit.py       the unified forensic verdict; fails closed
  containment/   harm model, signed guard config, review queue, readiness
  economy/       delegation attenuation, append-only ledger, settlement
  network/       libp2p client, DHT, gossip, artifact store
  sandbox/       bubblewrap executor and enforcement records
  demo/          5-node DDIL control-plane / data-plane demo
netd/        Go — the libp2p daemon
gyza-rs/     Rust — reference implementation, byte-parity with Python
research/    preregistrations, findings, corrections, artifact ledger
tests/       pytest
```

---

## License

See `LICENSE`. Issues and independent verification attempts are welcome; a
failed `gyza verify` on a bundle this project produced is the most useful bug
report possible.
