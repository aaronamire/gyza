# H3 was a measurement surface with no measurement pipeline

**Found 2026-08-19 by reading, while preparing to measure H3's attainable range
so a bound level could be declared.** No test failed. No number was wrong. The
class was registered, `readiness()` reported it, and it was the single blocker
on `can_claim_containment`.

**It was disconnected at FIVE independent points at once.** Any one of them
alone makes H3 measure exactly 0.

---

## The five defects

| # | defect | consequence |
|---|---|---|
| 1 | **`EgressRecorder` had zero production constructors.** The parameter was threaded through `NetdClient`, `GossipClient`, `CapabilityClient`, `ArtifactClient` and the sandbox runner, and supplied at **none** of the 12+ construction sites | every call site short-circuited on `if recorder is None: return` |
| 2 | **`publish_delta` and `publish_attestation` never called the recorder** — 2 of the 4 sites `HARM_MODEL_DRAFT` §H3 cites. They live on `GossipClient` and `CapabilityClient`, which had no recorder parameter at all | half the documented producers silent even once wired |
| 3 | **`outside_send` has no caller anywhere** | `OUTSIDE_PROTOCOL` — half of H3's definition — is unreachable in-process |
| 4 | **No attested-peer source exists in `gyza/`** | `classify_peer` always receives `None` and correctly fails toward `UNATTESTED_PEER`, so *every* peer send counts as exit |
| 5 | **`GyzaState.mesh_exit_sends` is supplied by nothing.** Zero references outside `projection.py` and `gyza_model.py` | H3 computes `0 − 0 = 0` **even if 1–4 were all fixed** |

Defect 5 is decisive and is **H2's retirement condition verbatim**, one layer
deeper. H2 was retired because "the one production projection that feeds the
harm model hardcodes `capital_entries=[]`, so it measured exactly 0.0 in every
production evaluation while being reported as a bounded class." H3's equivalent
parameter simply defaults to 0 and no caller ever sets it.

**And nothing evaluates H3 in an adopted path.** The only `engine.evaluate`
callers are `gates.py` (H1-only, and H1 is retired) and `staging.py`, which is
explicitly labelled a reference implementation of a **non-adopted** execution
model.

## Why no test caught it

Every producer had unit coverage that built its own fixtures. None asserted that
a *production* construction site supplies a recorder, and none followed the
quantity from producer to projection.

This is the second occurrence of the species. Artifact #16 was a harm quantity
that raised on every input behind 785 passing tests. The rule written then —
**REGISTERING A CHECKER IS NOT EVIDENCE THAT IT RUNS** — is what this document
records the second instance of, and the rule's own remedy ("assert that every
registry entry is executed against a real input") is what
`tests/test_h3_producers_fire.py` now does.

## Fixed

- **Defect 1** — `default_egress_recorder()` (`containment/egress.py`), the
  first production constructor. Wired at `global_cluster.py`, which builds one
  recorder and shares it across `NetdClient`, `GossipClient` and
  `CapabilityClient`. Returns `None` on failure: a measurement surface must
  never be why a node fails to start.
- **Defect 2** — `_safe_peer_send()` shared by all three clients;
  `publish_delta` and `publish_attestation` now record. Both are fan-out sends
  (a gossip topic, a DHT put to the k closest nodes), so **one log row stands
  for an unknown number of receiving nodes** — H3 therefore *understates* peer
  count on those two channels, and that is stated rather than implied.
- **The near-miss on defect 5** — `mesh_exit_sends_since()` is now the single
  correctly-filtered accessor. `count_egress_since` defaults to `classes=None`
  meaning *every* class, so any caller that forgot the filter would fold
  `UNBOUNDED_GRANT` into a send count — reporting "1" for a capability
  permitting arbitrarily many unobservable sends. That accessor had **zero**
  production callers, so no code had yet got it right or wrong.

## NOT fixed, and each blocks a truthful bound

1. **`OUTSIDE_PROTOCOL` is unreachable in-process** (defect 3). All external
   network from agents leaves through a bubblewrap sandbox whose grant is
   all-or-nothing, and that is recorded as `UNBOUNDED_GRANT` — a *different
   unit*, deliberately excluded from H3. So H3 currently measures
   `UNATTESTED_PEER` alone, and its stated definition
   (`UNATTESTED + OUTSIDE_PROTOCOL`) overstates what it counts.
2. **No attestation source** (defect 4), so H3's headline property — *the only
   declared quantity that shrinks as the mesh grows* — is **unrealised**. Every
   send counts. This errs toward reporting more exit than exists, which is the
   safe direction for a bound, but it means the number is a **total peer-send
   count**, not a mesh-exit count.
3. **No adopted evaluation path** (defect 5). The quantity can now be *counted*;
   nothing *checks* it.

## The warning that matters most

**`can_claim_containment` is one JSON line and one signature away, and taking
that step now would be a lie of exactly the kind this program keeps catching.**

`readiness()` computes the flag as `not unbounded and not uncovered and
bounds_signed`. Adding `H3_mesh_exit_sends` to the signed bounds file would
empty `unbounded` and flip the claim to **True** — while nothing evaluates H3,
`OUTSIDE_PROTOCOL` cannot fire, and the count means something other than its
name.

That is H2's error precisely: *a class reported as bounded while measuring 0 in
every production evaluation.* H2 was retired for it after two months. The
remedy is not to declare faster; it is to finish the pipeline, measure a real
distribution, and then declare against it — standing rule #4, which has now
failed five times in this program.
