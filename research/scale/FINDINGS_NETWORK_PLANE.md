# The network plane at planetary scale — 2026-08-20

Analysis and one demonstrated defect, now fixed. Covers what the coordination
ceiling study explicitly excluded: libp2p, Kademlia DHT, and gossipsub.

---

## 1. The primitives are the right ones, and were not reinvented

| layer | implementation | scale evidence |
|---|---|---|
| Peer routing | Kademlia DHT (`go-libp2p-kad-dht`) | O(log n) lookup; proven at ~10M nodes in BitTorrent/IPFS |
| Pubsub | gossipsub | proven at ~10⁶ peers in Ethereum consensus |
| Transport | QUIC | — |

**Nothing here is homegrown, and that is the single most important fact about
the network plane's scalability.** The failure mode for a project like this is
writing a custom overlay; Gyza did not. The risk is therefore concentrated in
the thin layer written *on top*, which is where the rest of this file looks.

## 2. THE DEFECT: a restarted node was silently muted

**`sender_seq` was assigned from `publishSeq`, an in-memory map created fresh in
`NewManager` and persisted nowhere.** Receivers drop any delta whose seq is
`<=` the highest already seen from that sender (`checkAndUpdateSeq`).

So a daemon that restarted resumed at `seq = 1` while its peers still held its
old high-water mark, and **every message it published was silently dropped until
the counter climbed back past it.** No error, no log. The longer a node had run
before restarting, the longer it stayed mute.

At planetary scale restarts are routine — deploys, crashes, autoscaling — so
this is a steady-state property, not an edge case.

**Demonstrated, not inferred.** `TestRestartedSenderIsSilencedByStaleDedupState`
holds the harness constant and varies only the seq logic:

| sender_seq source | post-restart seq | receiver |
|---|---|---|
| original (in-memory counter) | `1` | **drops it** |
| `seqBase` + counter | `1787245…` | **accepts it** |

### Why the first attempt at this test was WRONG, and how it was caught

The first harness "restarted" A by building a second `Manager` on the **same
libp2p host**. It failed, and it would have been easy to report that as the
defect. It was not: a pubsub router registers stream handlers on its host, so a
second GossipSub on a live host does not behave like a fresh daemon — the test
was measuring the harness.

It was caught because the *fix* did not make it pass. A fix that leaves a test
red is either wrong or the test is; assuming the former and looking again is
what surfaced it. The corrected harness tears down the host too and rebuilds
from the same identity, which is what a real restart does.

**A wrong test that confirms your hypothesis is more dangerous than one that
fails,** and this one confirmed it twice before the A/B showed the harness was
inert to the fix.

### The fix

`Manager.seqBase`, seeded from `time.Now().UnixNano()` at construction. Time
advances across restarts, so the base always rises, and no node can publish
more messages in a run than there are nanoseconds in its uptime. No persistence,
no new I/O on the publish path, no signature change.

**Stated limit:** a backwards clock jump larger than a run's message count could
still regress. Persisting a high-water mark closes that and is the durable fix.

## 3. Unbounded state, both directions

Neither is fatal; both are unbounded, which matters at planetary scale.

- **Receiver:** `topicState.lastSeen map[string]int64` — one entry per sender
  ever seen, per topic, never evicted. At 10⁶ distinct senders this is
  per-topic growth with no ceiling.
- **Sender:** `publishSeq map[string]int64` grows per project and is **not**
  deleted on `LeaveProject`, though `topics` is. A slow leak, ~50 bytes per
  project ever published to.

## 4. Structural observations, not yet measured

- **Topic per project** (`TopicForProject` → `/gyza/project/<id>/blackboard`).
  A node in P projects maintains P gossipsub meshes, each with its own D peers
  and 1 s heartbeat. Cost scales with a node's project membership, **not** with
  network size — so it is bounded by deployment design rather than by scale.
  Unmeasured above 3 nodes.
- **All gossipsub parameters are defaults.** `NewGossipSub` sets only
  `WithMessageSigning` and `WithStrictSignatureVerification`. Defaults (D=6,
  heartbeat 1 s) are reasonable; Ethereum tunes them heavily at 10⁶ peers.
  Untuned is not wrong, but it is untested at scale.
- **Strict signature verification on every message** — correct for a provenance
  system, and a per-message CPU cost that has never been profiled.
- **DHT mode defaults to `auto`.** The flag's own help says promotion to Server
  "can take a while or never happen" without AutoNAT signalling. **If most nodes
  never promote, the network has too few DHT servers** — a free-rider failure
  that appears only at scale and is invisible on loopback.

## 5. Verdict

**Architecturally, yes.** Kademlia and gossipsub are the correct choices and are
proven at the scale in question. Nothing in the topology forecloses planetary
deployment.

**As implemented, not yet — but the gaps are shallow.** One demonstrated
correctness defect (now fixed), two unbounded maps, untuned pubsub parameters,
and a DHT-promotion default that could starve the routing layer. None requires
rearchitecting; all require work that has not been done.

**And nothing above has been run at more than three nodes.** Every claim in §4
is structural reasoning, not measurement. The honest summary is that the network
plane is *sound in design, under-measured in practice, and one restart bug
lighter than it was this morning.*
