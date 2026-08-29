# H3 — the sub-class the harm model mis-classified

**`research/HARM_MODEL_DRAFT.md` stands unedited**, per standing practice. This
document carries the correction and the design that replaces it;
`research/CORRECTIONS.md` indexes it.

Written 2026-08-15, while implementing H3 against the vision rather than against
a single node.

---

## 1. What the draft says, and why it is wrong

`HARM_MODEL_DRAFT` §H3 enumerates **"external network sends"** as an
irreversibility sub-class and cites four sites:

| cited site | what it actually does |
|---|---|
| `netd_client.send_message` | writes to a libp2p **`peer_id`** — another `gyza-netd` |
| `netd_client.publish_agent` | **DHT put** under `/gyza/agents/{bucket}` |
| `netd_client.publish_attestation` | **DHT put** |
| `netd_client.publish_delta` | **gossipsub** on a Gyza topic |

Its stated reason is that such a send *"leaves the modeled system entirely"*, so
no invariant and no detector can bound its consequence — the C15 boundary.

> **All four land on a node running this same software, keeping its own
> provenance chain and applying its own gate. They are FEDERATION, not exit.**

## 2. The reframe: C15 is topology, not law

A send leaves modelled state because there is nothing on the other side that
models anything. That is a property of **deployment topology**, and it changes as
the mesh grows: every new Gyza node converts a class of destinations from
unmodelled to modelled.

> **H3 is therefore the only declared quantity in this harm model that improves
> with scale.** Margin grows with M (R-M1), aggregates get harder, `A_system` is
> governed by the worst amortizer — all worsen. The set of destinations lacking a
> model shrinks.

It also supplies an incentive the planetary vision needs on its own terms:
exiting the mesh is budgeted and scarce, staying inside is cheap. That is a
structural reason to join a federation rather than a marketing one.

## 3. The classification is three-way, and the middle class is the point

```
ATTESTED_PEER      destination presented a verifiable attestation. Its gate
                   applies and its actions carry provenance — the effect stays
                   inside modelled state.
UNATTESTED_PEER    speaks the Gyza protocol, but nothing vouches for it.
                   Protocol-internal and NOT contained: a rogue node runs
                   whatever gate it likes.
OUTSIDE_PROTOCOL   leaves the protocol entirely (HTTP fetch, sandbox egress
                   under allowed_hosts). Genuinely irreversible.
```

**H3 measures `UNATTESTED_PEER + OUTSIDE_PROTOCOL`.** A two-way split would have
been wrong in the flattering direction: it would have counted every protocol
send as contained, when protocol membership vouches for nothing.

**The dependency this creates, stated rather than buried.** Excluding
`ATTESTED_PEER` moves H3's strength **onto the attestation tier**. If an agent
can get a rogue node attested, it exfiltrates through it and this bound is worth
nothing. H3 is exactly as strong as attestation is.

**Classification is frozen at send time.** `egress_class` is stored, not derived
at read time: a peer attested *later* does not retroactively contain a message
already sent to it.

## 4. Implementation

| piece | where |
|---|---|
| classification + recorder | `gyza/containment/egress.py` |
| append-only log | `blackboard.egress_log`, `record_egress` / `count_egress_since` |
| projection field | `GyzaState.mesh_exit_sends` |
| harm class + invariant | `H3_mesh_exit_sends`, `INV-H3-mesh-exit` |
| instrumentation | `netd_client.send_message`, `netd_client.publish_agent` |

**Durable, not in-process.** The log is a SQLite table for the same reason H6
counts envelopes from the append-only log: an in-process counter resets on
restart, and a cumulative bound whose origin can move is not a bound (artifact
#13).

**Recorded only on success.** A refused write did not leave the machine;
counting it would measure intent rather than egress.

**Measurement never breaks a send.** The recorder is wrapped: an exception there
would turn a successful transmission into a failure, and would put an error into
the same channel as a measurement — the species this program has now recorded
twice in one route.

## 5. NO BOUND IS DECLARED, and that is the decision

`guard_bounds.json` leaves `H3_mesh_exit_sends` unbounded on purpose.

`H1_credits` was retired because 100 was fixed without measuring the attainable
range and then refused **every real model's first action** (40,000 credits for
Sonnet, 120,000 for Opus). Standing rule #4 — check a threshold against its
feasibility ceiling *before* the run — has now failed four times, most recently
in R-M1's own decision rule. Declaring a level for H3 today would be the fifth.

**Sequence: instrument, measure the attainable range, then declare.**

## 6. The consequence nobody would have chosen, and why it is right

Registering H3 **revoked Gyza's containment claim**. `can_claim_containment`
went from `True` to `False`, because a registered class with no declared level
leaves `readiness()["unbounded"]` non-empty — and it stays `False` even with a
**signed** guard configuration.

> **The real-world state did not change.** Gyza did not bound mesh-exit sends
> yesterday and does not bound them today. The only thing that changed is that
> the gap is now **named**. The previous `True` was available because the gap was
> unnamed, not because it was smaller.

This is the two-gate separation `KEY_PROVENANCE.md` recorded when H5 was the
unbounded class: C-8 (provenance) and D1 (every class bounded) are independent,
and **signing cannot paper over an undeclared level.** H3 re-exercises it, and
`test_SIGNED_bounds_lift_the_claim` now asserts the honest outcome.

## 7. What is NOT instrumented — the gap, stated

**`OUTSIDE_PROTOCOL` has a recorder API and no production caller yet.** The
genuine exit paths are:

1. **Sandbox egress under `allowed_hosts`** — an executor granted network may
   send anywhere. **Not instrumented.** This is the largest real hole.
2. **`network/artifact_client.py`** (`httpx`) — fetches artifacts from peer
   URLs. Arguably mesh-internal (the peers are Gyza nodes), but a fetch still
   discloses the requested hash. **Not instrumented; classification undecided.**

Recording this explicitly because "6 of 28 checking components had 0 production
callers" is a census this project has already run once. A class with a recorder
and no caller is that finding waiting to happen, and the way it stops being one
is a written gap plus a test that fails when the caller lands.

## 8. Two smaller repairs made alongside

**H5 had two sources for one bound.** `guard_bounds.json` declared
`H5_storage_growth = 1e10` while `ArtifactStore.max_bytes` was wired from
`GyzaConfig.max_artifact_store_gb` at three CLI sites. They agreed at 10 GB only
because H5's level had been *transcribed* from the config, and nothing kept them
in step. `gyza_model.storage_cap_bytes()` is now the single source and the
**declared bound wins** — a signed guard configuration the store then ignored
would be ceremony. No declared level now means unlimited, which is the honest
reading of "no bound declared" rather than a silent default.

**`kernel-enforced` swept from the remaining code sites.** The v0.1.2 release
removed all five occurrences from `README.md`; **eleven survived elsewhere** —
in `gyza/cli.py` (user-facing output), `demo/bounds_proof_demo.py`,
`gyza/network/demo_agent.py`, and one research document. Ten are corrected to
"OS-enforced".

**One was left alone deliberately:** `gyza/sandbox/config.py:382` says *RLIMIT_AS
is kernel-enforced*, and that is **true** — `RLIMIT_AS` is a genuine kernel
resource limit, unlike bubblewrap's unprivileged-userns + seccomp. A blanket
replace would have introduced an error while removing one.

## 9. Two test-discipline repairs the change forced

**`test_every_registered_invariant_predicate_executes` skipped unbounded
classes.** It `continue`d past any class with no declared level, so a
registered-but-unbounded class had its predicate **never executed** — an
unexercised registry entry, which is precisely the defect that file exists to
catch (artifact #16: 785 passing tests missed a quantity that raised on every
input). It now exercises every predicate against a probe level, and separately
asserts that any unbounded class is *declared* as such in
`gyza_model.MEASURED_NOT_BOUNDED` with a reason. **A forgotten level still
fails; a deliberate one passes.** That is strictly stronger than the assertion
it replaces, which only ever counted.

**A false failure I caused myself, recorded because the mechanism was right.**
`test_release.py::test_current_release_recomputes_to_same_value` failed in a full
run and passed in isolation. Cause: I edited `gyza/cli.py` and
`gyza/network/demo_agent.py` **while the suite was running**. `CURRENT_RELEASE`
is computed when `gyza.release` is imported and the test recomputes later, so the
source tree genuinely changed underneath it. The release-hash mechanism detected
a mid-run source mutation exactly as designed. **Do not edit the tree while a
test run is in flight** — the failure it produces looks like a code defect and is
not one.
