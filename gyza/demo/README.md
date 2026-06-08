# DDIL partition demo — control plane vs. data plane

```
python -m gyza.demo.ddil_partition            # auto: real bubblewrap if present
python -m gyza.demo.ddil_partition --construct # force the no-bwrap path
```

Five in-process nodes form a network, delegate a *bounded* subtask,
split 3/2, keep working on both sides of the split, refuse an
out-of-bounds action on the isolated side **with no connectivity**,
heal, and deterministically reconcile into an intact,
independently-verifiable provenance chain. The value is the printed
transcript: it is readable end-to-end without reading the code.

## Why there are two planes

A naive design runs everything through one consensus layer (Raft).
That is fatal for a DDIL ("Denied, Degraded, Intermittent, Limited")
deployment, because **Raft deliberately stops accepting writes when it
can't reach a majority.** The whole network would go dark exactly when
connectivity is worst — which is when it is needed most.

The fix is to split the system into two planes that make *opposite*
trade-offs, each one correct for the kind of state it carries:

| | **Control plane** | **Data plane** |
|---|---|---|
| Carries | Who is trusted; who may grant authority | Already-authorized work and its results |
| Behavior under partition | **Pauses** (safe) | **Stays available** (keeps working) |
| Consistency model | Strong / linearizable (Raft quorum) | Eventually consistent (CRDT + gossip) |
| In this demo | `control_plane.py` | `coordination_plane.py` + `gossip.py` |

**Control plane (Raft).** Issuing new authority requires a majority.
When the network splits, the minority side *cannot* mint new grants —
and that is the correct, safe behavior. Authority you can't replicate
to a majority is how "split-brain" authority leaks; refusing to issue
it is the feature, not a bug. In the transcript you see the minority
side report *"NO QUORUM, grant authority paused"* while the majority
side keeps its authority.

**Data plane (CRDT + gossip).** Work that was *already authorized
before* the split continues on both sides. Each side records its
actions as cryptographically signed ICP envelopes and spreads them by
gossip to whoever it can still reach. When the partition heals, the two
sides merge. The merge is **conflict-free**: every event is identified
by the BLAKE3 hash of its signed envelope, so two replicas that hold
the same event are guaranteed to hold byte-identical content — there is
never a "which copy wins" question, and nothing signed is ever thrown
away.

A partition makes the history **fork** — both sides legitimately build
on the last shared envelope. That is inherent to an available data
plane, not a defect. Reconciliation keeps *both* branches, each
independently verifiable, ordered by the ICP parent-hash chain (never
by wall-clock). The branches share their common prefix exactly.

## Provenance is a DAG, not a chain

Real agent work isn't linear. It fans out (one task spawns many),
forks (a partition), and **fans in** (a synthesis step consumes several
results). The provenance model reflects this: an envelope has two kinds
of dependency edge — its **causal spine** (`parent_envelope_hash`, an
agent's own prior action) and its **data dependencies** (each
`input_hashes` entry that resolves to another envelope's `output_hash`).
Together they form a directed acyclic graph.

`gyza.icp.verify_dag` validates that whole graph as a unit: every
signature, acyclicity (a data-dependency cycle between two agents is a
mutual-farm corruption, and is rejected), and a deterministic
topological order so every replica reconstructs it identically. This is
the multi-parent generalization of `verify_chain`; a linear chain is
just the special case with one root and one leaf. No envelope schema
change was needed — `input_hashes` was already a list.

The demo shows both views after the heal: the **causal-spine view**
still shows two forked branches, while the coordinator then performs a
**fan-in synthesis** consuming both branch tips, and `verify_dag`
re-joins the fork into a single auditable result (one root, one leaf) —
a shape the linear chain could never express.

## The trust root is government-controlled — on purpose

The control plane's grant authority is anchored in a trust root that a
sovereign operator holds. This is a deliberate **sovereignty feature**,
not a centralization compromise. A government, a coalition, or a
regulated institution can be the root of trust for *who is allowed to
do what* on its own network, while the data plane remains decentralized
and partition-tolerant. You get a chain of custody that a sovereign can
stand behind, without giving up the resilience that makes the system
usable in contested or disconnected environments. Authority is
centralized where accountability demands it; availability is
decentralized where operations demand it.

## The honest claim

This demo proves three things, each with a **real** production function
(no stubs on the safety path):

1. **DDIL-native coordination** — the data plane stays available on both
   sides of the partition; the control plane pauses correctly on the
   minority side.
2. **Forensic auditability** — `gyza.icp.verify_chain` validates each
   forked branch and `gyza.icp.verify_dag` validates the full multi-parent
   provenance graph (including the fan-in synthesis) end to end; the
   envelope count proves zero loss.
3. **Capability-bounds enforcement** — `enforcement_satisfies_manifest`
   (the brick-3 signing gate) refuses an over-budget action *locally,
   with no quorum and no peers*, and
   `gyza.economy.delegation.verify_delegation` proves the bounds
   composed across the whole delegation chain.

It does **not** prove the *outputs were correct*. Gyza proves
**accountability** (every action is signed and attributable),
**containment** (every action provably stayed within its granted
bounds), and **bounds-compliance** (authority composes downward and
cannot be laundered). Whether a result is actually *right* — useful,
true, well-judged — is a **human-on-the-loop** decision. The protocol
guarantees you can *trust the frame*; a person still has to *check the
picture*.

## What's real vs. modeled

* **Real, unmodified:** the ICP envelope schema and `verify_chain`; the
  brick-3 gate `enforcement_satisfies_manifest`; the compositional
  verifier `verify_delegation`; `DelegationGrant` signing/verification;
  agent issuance and manifest signing. None of these were touched.
  `verify_dag` was *added* to `icp.py` — purely additive, leaving the
  signing path (`_payload_bytes` / `sign_envelope` /
  `compute_envelope_hash`) and its Rust byte-parity fixtures untouched.
* **Real bubblewrap, when present:** in the default (`auto`) mode each
  bounded execution runs in an actual `bwrap` sandbox and the host
  stamps the enforcement record. With `--construct`, the record is
  built from the sandbox config (a verbatim mirror of
  `gyza/sandbox/executor.py`) and judged by the same real gate — so the
  demo runs unchanged on any machine. **Enforcement *soundness*** (that
  bwrap actually pins the bounds) is demonstrated separately in
  `demo/bounds_proof_demo.py`; *this* demo proves
  **bounds-*verification* under partition.**
* **Modeled (deliberately):** the control plane is an in-process
  component that implements the genuine quorum-intersection rule Raft's
  safety derives from (a write commits iff the proposer reaches a strict
  majority), shaped like `gyza.network.raft.GyzaRaftNode` so the
  production Raft node can be swapped in later. Bounds are exercised on
  the **memory dimension** (RLIMIT_AS) — the asymmetric dimension that
  makes boundedness *compose*, and the one that needs no real host
  filesystem paths.

## Files

| File | Role |
|---|---|
| `coordination_plane.py` | Content-addressed CRDT (G-Set of ICP envelopes); merge + deterministic ICP-ordered reconstruction |
| `gossip.py` | `Network` (partition state) + pull-based anti-entropy |
| `control_plane.py` | Quorum-gated grant authority (the CP half) |
| `ddil_partition.py` | The five-node scenario + narrated transcript |

Tests: `tests/test_ddil_coordination_plane.py` (CRDT laws),
`tests/test_ddil_control_plane.py` (quorum + gossip),
`tests/test_ddil_partition.py` (the full scenario).
