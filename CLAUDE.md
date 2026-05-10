# CLAUDE.md — Gyza session continuation guide

> **Audience:** A future Claude session continuing work on this repo.
> Last updated at the end of Phase 3 Session 12 (libp2p stream protocol
> for cross-network capability attestation —
> `/gyza/capability-challenge/1.0.0` — wired into the daemon). Session
> 11 shipped the algorithmic core of #21 (eval suite + Tier-1
> self-attest + in-process orchestration); Session 12 ships #21c (the
> wire layer). What remains in #21 is the Python applicant adapter
> (gRPC method that drives the libp2p initiator with a Python eval
> upcall), #21d (DHT-driven validator selection), and #21e (DHT cert
> publication + `gyza global attest --tier 3` CLI). Read top to bottom
> on session start, then keep open as a reference. Everything in here
> is grounded in code that's been read, not in spec aspirations.

---

## 1. What gyza is, in one paragraph

A peer-to-peer network where independent nodes (each running a
`LocalCompositor` identity, a `Blackboard`, and one or more `AgentRunner`s)
publish "work items" rooted in human-signed "intents," claim each
other's work, sign cryptographic provenance envelopes (ICP), and settle
compute credits bilaterally. Phase 1 was single-node. Phase 2 added
LAN clustering via Raft. Phase 3 added global federation: Kademlia DHT
for discovery, gossipsub for cross-cluster blackboard sync, NAT
traversal (DCUtR + circuit relay), bilateral compute-credit ledger,
proof-of-capability attestation, and a Go daemon (`gyza-netd`) that
owns all libp2p concerns. Python (`gyza/`) handles execution, identity,
ICP, and the ledger; the daemon and Python talk over a Unix socket via
gRPC. The integration test of record is `demo/single_machine_global.py`
which spawns two real daemons on loopback, runs a full coordinator-+-executor
project to settlement in ~5–25 seconds, and prints `BILATERAL ✓` if
everything works.

---

## 2. How to run things — the commands you'll use every session

### Python is at a non-standard path.

`pytest` is **not** on PATH. The codebase requires Python 3.14
(uses `uuid.uuid7`). The working interpreter is:

```bash
~/dev/marshal/.os/bin/python -m pytest …
```

Bare `python` resolves to `/usr/bin/python` which has no project deps
installed. Bare `pytest` doesn't exist. Always invoke through the
marshal venv.

### Fast iteration test slice (~8–10 minutes)

```bash
~/dev/marshal/.os/bin/python -m pytest tests/ -q --tb=line --timeout=90 \
  -k "not netd_client and not phase2_integration and not phase2_hardening and not blackboard_gossip"
```

That `-k` filter excludes the four heavy integration suites that spawn
real `gyza-netd` daemons. Run those when you're touching daemon code or
near a session-end checkpoint. The Python fast slice runs ~457 tests
in 8–10 min (Session 9 added timing-sensitive reconciliation tests;
Session 10 added 18 sandbox tests that each spawn a real bwrap
subprocess; Session 11 added 22 capability-eval tests + 15
attestation-protocol tests, each of which drives a real AgentRunner
through the eval suite). The Go test suite (~5s, ``go test ./...``)
grew by 5 in Session 12 with the capability_stream package — each
test spawns two real libp2p hosts on loopback.

### Heavy integration tests (~10–15 minutes total)

```bash
~/dev/marshal/.os/bin/python -m pytest tests/test_netd_client.py tests/test_network_blackboard_gossip.py \
  -q --tb=short --timeout=180
```

`tests/test_phase2_integration.py` and `tests/test_phase2_hardening.py`
are Phase 2 specific — usually only re-run if you touched
`gyza/network/cluster.py` or related.

### Go test suite (~5 seconds)

```bash
cd netd && go test ./... -count=1 -timeout=120s
```

### The integration test of record

```bash
~/dev/marshal/.os/bin/python demo/single_machine_global.py
```

Always confirms `Cross-cluster gossip: VALID ✓` and
`Bilateral settlement: BILATERAL ✓`. Elapsed time is dominated by
SentenceTransformer model load on first run (~25s); subsequent runs in
the same Python process cache the model. A clean two-run total of
~10s/run after warm cache means the integration is healthy.

### Build the daemon

```bash
make -C netd build
```

Required after any change to `netd/`. The binary lands at
`netd/bin/gyza-netd`.

### CLI smoke

```bash
~/dev/marshal/.os/bin/python -m gyza.cli --help
~/dev/marshal/.os/bin/python -m gyza.cli status
```

---

## 3. Things that look broken but aren't (trip-wires)

Read this section before reacting to any test/lint output.

### Pyright "Import could not be resolved"

You'll see warnings like:
```
✘ Import "blake3" could not be resolved [reportMissingImports]
✘ Import "gyza.network.peer_registry" could not be resolved
✘ Import "gyza.observability" could not be resolved
✘ Import "prometheus_client" could not be resolved
✘ Import "pytest" could not be resolved
```

**These are not real.** There is no `pyproject.toml` or `pyrightconfig.json`
configuring the marshal venv as the analysis target, so Pyright resolves
imports against the system Python which has none of the project deps.
At runtime everything works. Do **not** "fix" these by adding fallback
imports or guarding with `try` — except where Session 9 already does
so deliberately for `gyza.observability` (see §9 "fail-closed import
wrapper" pattern).

### Pyright unused-variable warnings on lambdas

```
✘ "_pk" is not accessed
```

Lambda parameters prefixed `_` are intentional unused-by-convention. Pyright
doesn't recognize this for callable arguments. Ignore.

### Pyright `"row" is possibly unbound`

In `_wait_until` patterns the variable is guaranteed bound after the
predicate succeeds, but Pyright can't infer that across the lambda. The
pattern is:
```python
deadline = time.monotonic() + 5.0
while time.monotonic() < deadline:
    row = bb._conn().execute(...).fetchone()
    if row["completed_at_ns"] is not None:
        break
    time.sleep(0.1)
assert row["completed_at_ns"] is not None  # pyright complains; runtime is fine
```
If you genuinely care: initialize `row = None` before the loop. Most of
the test code skips this for brevity. Don't refactor purely to silence.

### Demo elapsed time variance (~5s vs ~25s)

If the SentenceTransformer model isn't cached on the running Python
process, the first `embed()` call loads ~80 MB of weights. The demo
prints elapsed times but the variance is dominated by this. A single
run on a freshly-started Python interpreter takes ~25s; the cache lives
in `~/.cache/huggingface/`.

### `gyza global attest` returns "not yet implemented"

Intentional placeholder. Wired in CLI but the cross-network
attestation orchestration hasn't been built (it's task #21 in this doc).

### `DefaultBootstrapPeers = []string{}` in `netd/internal/host/host.go`

Intentional. The original spec said "fall back to IPFS bootstrap" but
gyza-netd uses the `/gyza/1.0` DHT protocol prefix, so IPFS nodes
won't respond to its queries anyway. There's no free public DHT to
ride. Cross-internet operation requires either explicit `--bootstrap`
or one peer with a public IP playing bootstrap.

### Long-running test suite: 8–10 minutes is normal (Session 9+)

Mostly the heavy integration tests (sentence-transformers loads,
real daemon startup at ~2s each, gossipsub mesh formation 2s waits).
Session 9 added `tests/test_reconciliation.py` which contributes
~2:30 of intentional timing work — pagination cursor monotonicity
sleeps, page-timeout / send-failure paths. If you see >12 minutes
consistently, something's wrong; otherwise this is the cost of
integration coverage.

---

## 4. Architecture map

```
~/dev/gyza/
├── gyza/                 # Python — execution, identity, ICP, ledger
│   ├── schema.py         # WorkItem, Artifact, HLC (thread-safe)
│   ├── blackboard.py     # SQLite WAL store + envelope log + reconstruct_chain
│   ├── runner.py         # AgentRunner (claim/execute/sign loop, chain-verify gate)
│   ├── icp.py            # ICPEnvelope + sign/verify, single-key + multi-compositor
│   ├── identity.py       # LocalCompositor (master seed → agent issuance), AgentIdentity
│   ├── memory.py         # EpisodicMemory (LanceDB + SQLite fallback), uses ST
│   ├── drift.py          # SpecializationTracker (per-agent embedding state)
│   ├── demand.py         # LSHIndex + DemandOracle (bucket signals, deficit math)
│   ├── reward.py         # exponential reward inflation
│   ├── embeddings.py     # Embedder Protocol + ST + Stub backends — single source of truth for "embed text"
│   ├── supervisor.py     # AgentSupervisor (poll oracle → spawn via factory)
│   ├── observability.py  # Prometheus counters/histograms/gauges + structlog config (Session 9)
│   ├── capability_eval.py # Session 11 — canonical eval suite + run_eval_locally + verify_eval_results
│   ├── cli.py            # gyza CLI (init/demo/status/global/credits/metrics/etc)
│   ├── config.py         # GyzaConfig dataclass + load_config()
│   ├── sandbox/          # Session 10 — executor sandboxing
│   │   ├── config.py         # SandboxConfig + _system_mounts()
│   │   ├── runner.py         # run_sandboxed() — bwrap argv builder + framing
│   │   ├── _entrypoint.py    # in-sandbox bootstrap (length-prefixed JSON)
│   │   ├── executor.py       # make_sandboxed_executor + presets
│   │   └── _probes.py        # importable probe executors for tests
│   ├── economy/
│   │   ├── ledger.py     # bilateral compute-credit ledger + reconcile_with_peer
│   │   ├── settlement.py # earner_signed ⇄ payer_cosigned + reconcile.{request,response} protocol
│   │   └── reputation.py # EWMA reputation store, wired to runner + settlement
│   └── network/
│       ├── cluster.py            # Phase 2 LAN cluster (Raft formation)
│       ├── transport.py          # Phase 2 QUIC + Noise
│       ├── discovery.py          # Phase 2 mDNS (Phase 3 daemon also has it)
│       ├── raft.py               # pysyncobj wrapper
│       ├── network_blackboard.py # Raft + gossip-attached blackboard
│       ├── netd_client.py        # Python NetdClient + GossipClient + CapabilityClient
│       ├── peer_registry.py      # compositor↔peer_id cache w/ rate-limited refresh
│       ├── peer_cache.py         # Session 10 — JSON-persisted (pubkey, multiaddr) for redial after restart
│       ├── daemon_supervisor.py  # Session 10 — heartbeat/respawn watcher around gyza-netd
│       ├── capability_protocol.py # Session 11 — Validator/Applicant roles + run_attestation orchestrator + verify_attestation_cert
│       ├── global_cluster.py     # Phase 3 orchestrator (publish_agents, find_and_collaborate, settle, hooks)
│       ├── artifact_*.py         # content-addressed file store, server, client
│       └── trust_registry.py     # pinned compositors + cached manifests (Phase 2)
│
├── netd/                 # Go — gyza-netd daemon (libp2p, DHT, NAT, gossip)
│   ├── cmd/gyza-netd/main.go     # entry point (flags, signals)
│   └── internal/
│       ├── identity/             # Ed25519 seed → libp2p crypto.PrivKey
│       ├── host/                 # libp2p host config (QUIC + Noise + yamux)
│       ├── dht/                  # Kademlia DHT + Python-compatible LSH
│       ├── discovery/            # mDNS service
│       ├── nat/                  # DCUtR + AutoRelay
│       ├── gossip/               # gossipsub + signed deltas
│       ├── message/              # /gyza/message/1.0.0 stream (varint frames)
│       ├── capability/           # challenge protocol (issuance + verify, in-process)
│       ├── capability_stream/    # Session 12 — libp2p `/gyza/capability-challenge/1.0.0` (3-frame proto exchange)
│       └── grpc/                 # gRPC server + proto definitions
│
├── tests/                # pytest, all green (457 fast + 7 integration as of Session 12)
├── demo/
│   ├── single_machine_global.py  # Phase 3 integration sim — RUN THIS to verify
│   ├── single_machine_phase2.py  # Phase 2 sim
│   ├── two_machine_demo.py       # Phase 2 cross-machine (subprocess)
│   ├── two_agent_pipeline.py     # Phase 1 local
│   └── injection_demo.py         # Phase 1 tampering demo
└── scripts/
    └── generate_lsh_planes.py    # generates Go-side LSH planes
```

### Layered dependencies (skim before designing changes)

```
runner ─┬── blackboard ── (sqlite, ICP envelope log)
        ├── memory     ── (LanceDB or SQLite, ST embeddings)
        ├── drift      ── (per-agent SpecializationTracker)
        ├── icp        ── (ICPEnvelope dataclass + sign/verify)
        └── reputation ── (optional EWMA store)

global_cluster ─┬── netd_client (gRPC stubs over Unix socket)
                ├── gossip_client
                ├── peer_registry
                ├── settlement ── ledger
                └── supervisor   ── demand oracle, factory-pattern spawning

netd_client ── netd (Go subprocess; libp2p, DHT, NAT, gossipsub)
```

### Critical data flow: a complete cross-cluster claim

```
A (coordinator)                                 B (executor)
─────────────────                               ─────────────
post_intent(spec) ─────► gossip ────────────────► _apply_delta
post_work_item(w) ─────► gossip ────────────────► _apply_delta
                                                      │
                                                      ▼
                                                  runner.try_claim
                                                  (verify chain)
                                                  ─► execute
                                                  ─► sign envelope
                                                  ─► store_envelope (log)
                                                  ─► on_envelope_signed
                                                       │
                                                       ▼
                                              settlement.submit_earned
                                                       │
                                                       ▼
                                       ledger.entry.earner_signed (libp2p stream)
                                                       ▼
settlement._handle_earner_signed
─► verify earner sig
─► resolve envelope_hash (poll local bb up to 3s)
─► verify amount within ±20%
─► sign_as_payer
─► reputation.record_success(earner)                                                       
─► ledger.entry.payer_cosigned (libp2p stream)
                                                       ▼
                                       settlement._handle_payer_cosigned
                                       ─► verify payer sig
                                       ─► apply_cosigned_entry
                                       ─► reputation.record_success(payer)

complete_work_item ────► gossip ─► merge_completion_direct
                                                       
Both ledgers now hold byte-identical settled entries.
Both reputation stores now reflect the successful interaction.
```

---

## 5. What was done in recent sessions

Sections newest-first. Session 12 is the most recent. The patterns
introduced in Sessions 9–12 (fail-closed observability wrappers,
lex-cursor pagination, request/response correlation, length-prefixed
JSON over subprocess pipes, atomic JSON persistence, applicant-proposed
canonical-bytes-for-quorum-cosignatures, libp2p stream protocols
mirroring `/gyza/message/1.0.0`'s varint-frame pattern) are the
freshest reference templates for items still on §6's list.

---

## 5a. Session 12 — libp2p stream protocol for cross-network attestation

Closed §6 #21c — the wire layer that lets two daemons run the
proof-of-capability flow over libp2p. New package:
``netd/internal/capability_stream/`` with the protocol handler at
``/gyza/capability-challenge/1.0.0``. 5 Go tests. Daemon registers
the protocol on startup. Cumulative tests after Session 12: 457
Python (unchanged from Session 11) + 5 new Go.

### Architecture-level decision settled

Session 11 built a Python ``capability_protocol.py`` with
JSON-canonicalized signatures. Session 12 found that the existing Go
``netd/internal/capability/`` package was already complete (with
ChallengeManager.IssueChallenge / VerifyResponse / AssembleAttestation
/ VerifyAttestation, and full proto types in netd.proto) AND used
``proto.MarshalOptions{Deterministic: true}`` for canonicalization.
**The two canonicalizations produce different bytes** — a Go validator
cosigning a body and a Python validator cosigning the same body do not
produce signatures that aggregate into a single quorum.

**Decision: Go protobuf + deterministic marshal is the canonical wire
format for cross-network.** Python's ``capability_protocol.py`` from
Session 11 stays as-is for IN-PROCESS Tier-1 self-attestation (its
unit tests still pass and the `gyza global attest` CLI still works
against it), but it is NOT the cross-network wire. A future Python
applicant adapter consumes Go protobuf via Python's protobuf
library, which produces byte-identical output to Go's deterministic
marshal.

### Wire protocol — 3 frames over `/gyza/capability-challenge/1.0.0`

```
→  Validator → Applicant : Challenge          (deterministic marshal of pb.Challenge)
←  Applicant → Validator : ChallengeResponse  (deterministic marshal)
→  Validator → Applicant : VerifyResponseResult
```

Each frame is ``[uvarint_len][marshaled_proto]``. Mirror of
``/gyza/message/1.0.0``'s pattern in
``netd/internal/message/message.go``.

**No kickoff frame from the applicant.** The validator initiates by
extracting the applicant's compositor pubkey from the libp2p
``RemotePeer`` (Noise-authenticated, so the binding is load-bearing).
Saves a round trip and avoids a redundant "applicant says hello"
frame.

**3-frame exchange, not 4.** Validator picks task_ids from its own
canonical list (currently hardcoded to match
``gyza/capability_eval.py``'s EVAL_TASKS); the applicant doesn't
propose them. A future v2 protocol could let the applicant negotiate
a subset, but for v1 the validator decides.

**Per-stream deadline.** ``StreamTimeout = 120s``. Long enough for
real-LLM eval execution (mock-eval ~50ms × 6 tasks ≈ 0.3s, but
Anthropic-shaped 3-10s × 6 ≈ 18-60s) plus margin. ``StreamTimeout``
applies to the WHOLE exchange — open + 3 frames + close — so a slow
or malicious peer can't pin the host's goroutines.

### Public API

```go
// Validator side: register handler on startup.
mgr, err := capability_stream.NewManager(host, capability_stream.Config{
    CapabilityManager: capMgr,            // *capability.ChallengeManager
    TaskIDs:           canonicalTaskIDs,  // matches gyza/capability_eval.py
    VerifyOut:         nil,                // permissive for now; Python upcall later
    Logf:              logger.Info,
})

// Applicant side: drive the protocol against a peer.
cosig, err := mgr.RequestAttestation(ctx, validatorPeerID, runEval)
//   runEval is an EvalRunner callback that turns a Challenge into a
//   ChallengeResponse. In Go tests it synthesizes ICP envelopes
//   directly; in production the daemon wires it to a Python gRPC
//   stream that runs the actual eval.
```

### Validator-side handler (handleIncoming)

  1. Set 120s stream deadline.
  2. Extract applicant pubkey from libp2p PeerID.
  3. ``capMgr.IssueChallenge(applicantPubkey, taskIDs, ttl)``.
  4. Write Challenge frame.
  5. Read ChallengeResponse frame.
  6. ``capMgr.VerifyResponse(challenge, response, verifyOut)``.
  7. Write VerifyResponseResult — ``Success=true`` with cosig OR
     ``Success=false`` with ``Error=<reason string>``.
  8. Stream closes.

Errors at steps 1, 2, 4, 5, or 7 close the stream silently (logged at
INFO). Errors at step 6 are RECOVERABLE — they get wire-encoded as a
structured ``VerifyResponseResult{Success=false}`` so the applicant
can diagnose without needing a second protocol layer for error
reporting.

### Applicant-side initiator (RequestAttestation)

  1. Open stream to ``target`` peer ID.
  2. Read Challenge frame.
  3. ``capMgr.VerifyChallenge(challenge)`` — sanity-verify BEFORE
     running the eval. **Trip-wire:** the eval is the slow step;
     don't burn applicant CPU on a malformed challenge.
  4. Call ``runEval(challenge)`` callback. Returns
     ChallengeResponse with ICP envelopes + applicant signature
     already populated. The libp2p layer doesn't sign anything;
     signing is the callback's job (typically a Python upcall).
  5. Write ChallengeResponse frame.
  6. Read VerifyResponseResult frame.
  7. Return cosig on Success, error on rejection.

### Tests (5)

  * ``TestSuccessfulAttestationRoundTrip`` — happy path with two
    real libp2p hosts on loopback.
  * ``TestValidatorRejectsBadResponse`` — corrupted ICP signature
    on a TaskResult; validator rejects via
    ``VerifyResponseResult{Success=false}``; applicant surfaces as
    ``"validator rejected: task X: ICP envelope signature mismatch"``.
  * ``TestApplicantRejectsForgedChallenge`` — validator overrides
    its own stream handler to emit a challenge with corrupted
    ChallengerSignature; applicant rejects BEFORE running the eval
    (assertion: eval callback was never invoked).
  * ``TestEvalRunnerError`` — eval callback returns an error;
    applicant returns the error and validator sees a clean
    ``read length: EOF`` (no half-written frame, no protocol
    pollution).
  * ``TestSelfRequestRejected`` — ``RequestAttestation`` against
    own peer ID is refused at the API level.

### Daemon wiring

``netd/cmd/gyza-netd/main.go`` constructs the Manager right after
``capability.NewChallengeManager``. The hardcoded ``TaskIDs`` list
matches ``gyza/capability_eval.py``'s ``EVAL_TASKS`` — drift between
the two is silently a "missing task result" rejection at the
validator. Keep them in sync; a future config-driven approach can
read this from a shared source.

### What §6 #21 still needs after this session

Python side has zero awareness of the new protocol. The next session's
work is the **Python applicant adapter**:

  1. New gRPC method on the daemon: ``RequestAttestation(peer_id) →
     AttestationCert``.
  2. Python-side server-streaming or callback-style upcall mechanism
     so the daemon can ask Python to run the eval (the daemon owns the
     libp2p stream; Python owns the AgentRunner). The
     ``EvalRunner`` callback shape is the contract.
  3. Bridge ``run_attestation`` orchestrator from
     ``gyza/network/capability_protocol.py`` to call the new gRPC
     method instead of the in-process Validator role.

After that: #21d (DHT-driven validator selection) and #21e (DHT
publication + ``gyza global attest --tier 3`` CLI). Both are mechanical
once the Python adapter exists.

---

## 5b. Session 11 — capability eval + cross-network attestation orchestration

Closed the algorithmic core of §6 #21. Two distinct deliverables in
sequence: the local eval primitive (Tier-1 self-attestation), then the
cross-network protocol orchestration (in-process; libp2p layer
deferred). Cumulative tests after Session 11: ~457 (was 420 at start of
Session 11; +22 capability_eval + +15 capability_protocol).

### #21a — Canonical eval suite + Tier-1 self-attestation — `gyza/capability_eval.py` + 22 tests

**What "capability" actually means here.** The eval suite tests the
machinery (LocalCompositor → AgentIdentity → AgentRunner → Blackboard →
ICP signing → executor returning structured output), not LLM quality.
Tasks are **structurally verifiable** — verifier parses output by
shape, not by LLM-judging it. Each task carries a `setup`,
`prompt_body`, `expected_output(workdir, nonce)`, `output_keys`
(schema), and `timeout_s`. Six tasks ship in `EVAL_TASKS`:
count_py_files, list_extensions, first_line_of_data, filename_lengths,
sum_numbers, echo_nonce.

**Replay + forgery defenses (eval level):**

  * Each task's prompt embeds `[GYZA_EVAL_TASK={id} NONCE={nonce}]`.
    The mock-eval executor uses `prompt.rfind("[GYZA_EVAL_TASK=")` —
    NOT `find` — because `build_enriched_prompt` prepends few-shot
    context from prior episodes, which contains earlier tasks'
    markers verbatim. Scanning from the start would silently solve
    the wrong task. **Trip-wire: episodes-as-few-shot leak earlier
    task markers into the current prompt.**
  * Each output is backed by an ICP envelope signed by the agent
    identity. Verifier checks `envelope.agent_pubkey == applicant`
    AND `BLAKE3({"text": canonical_text}) == envelope.output_hash`
    AND output passes structural shape AND output equals
    `task.expected_output(workdir, nonce)`. Forgery-protected at
    every layer.

**`run_eval_locally` driver.** Posts intent + work item per task,
waits for runner to sign envelopes, captures outputs via a
`make_recording_executor` wrapper. Per-task `workdir/<task_id>/` keeps
fixtures isolated. **Trip-wire: WorkItem's `ttl_ns=0` makes
`Blackboard.get_unclaimed`'s TTL filter immediately expire the item;
set `ttl_ns = (timeout_s + 30) * 1e9`.**

**`make_recording_executor` stores both `parsed` and `text`.** The
runner hashes `{"text": result["text"]}` (see `runner.py::_execute`),
so the verifier must reproduce that exact form to validate
`output_hash`. But the verifier ALSO needs the parsed dict for shape
+ semantic checks. Capturing only one breaks the chain-of-evidence;
capturing both keeps the independence between "this output hashes
correctly" and "this output means what it claims."

**`gyza global attest` CLI** went from stub → working Tier-1
self-attestation. Builds an ephemeral runner under the user's
compositor key, runs the suite, verifies, emits a JSON artifact at
`~/.gyza/attestations/self-<nonce>.json` with the signed report.
Tier-3 cross-network attestation still requires the libp2p layer.

### #21b — Cross-network attestation protocol orchestration — `gyza/network/capability_protocol.py` + 15 tests

**In-process for now.** Wire types are designed JSON-serializable so
the future libp2p stream layer is a mechanical frame-and-ship. What
this session builds: `Validator`, `Applicant`, `run_attestation`
orchestrator, consumer-side `verify_attestation_cert`. The
`/gyza/capability-challenge/1.0.0` libp2p protocol on the Go side is
explicitly deferred.

**Wire types:** `Challenge`, `ChallengeResponse`, `ChallengeOutcome`,
`ValidatorCosig`, `AttestationCertPayload`, `AttestationCert`. All
hex-string / int / list-of-those for clean JSON canonicalization.

**Validator-chosen nonce — load-bearing.** Each validator picks its
own nonce in the Challenge; the applicant runs the eval suite ONCE
per validator (each with a different nonce). This blocks replay
across validators — a malicious applicant who got one good response
can't reuse it against a second validator. With mock executor at
~1-10ms per task × 6 tasks × 3 validators ≈ 180ms, the cost is
trivially affordable.

**Applicant-proposed cert payload, validator-constrained — also
load-bearing.** Every cosig must be over IDENTICAL canonical bytes
or the quorum can't aggregate. The applicant proposes one
`AttestationCertPayload` (timestamps, identity, eval version) and
sends it inside every ChallengeResponse; each validator
independently verifies (a) the eval results, (b) timestamps are
within ±1h clock-skew window, (c) lifetime ≤ 90 days, (d) applicant
pubkey matches, (e) schema string matches — and signs that exact
payload. Orchestrator collects k-of-n cosigs.

**`sign_fn` callable, NOT raw seed bytes — caught a real bug.**
`LocalCompositor` HKDF-derives its compositor signing key from the
master seed. Reading the master-seed file and using it directly to
sign produces signatures under the WRONG key. The protocol layer
accepts a `sign_fn: Callable[[bytes], str]` — production passes
`LocalCompositor.sign`, tests pass `make_seed_signer(seed)` for
synthetic identities without writing key files. **Trip-wire: never
assume a key file's bytes ARE the signing seed; LocalCompositor's
file is the master seed and the actual compositor key is HKDF-derived
from it.**

**Two pubkeys in the response — compositor binds the cert; agent
verifies the envelopes.** ICP envelopes are signed by the AGENT
identity (ephemeral, runner-bound). The cert binds at the
COMPOSITOR (durable, DHT-indexed). So `ChallengeResponse` carries
both `applicant_compositor_pubkey` and `applicant_agent_pubkey`;
the eval verifier checks envelopes against the agent pubkey, the
cert payload uses the compositor pubkey. The bridge "agent issued
by compositor" is via the capability manifest — forwarding the
manifest in the response and verifying that link is a documented
follow-up.

**Threat model defended:**

  * Replay across validators       — validator-chosen nonce
  * Eval result tampering          — eval verifier (gyza.capability_eval)
  * Cosignature transplant         — each cosig binds to validator_pubkey
                                     and is over canonical(payload)
  * Applicant signature forgery    — verified at every Validator
  * Stale cert acceptance          — payload carries expires_at_ns;
                                     verify_attestation_cert checks
  * Duplicate-cosig padding        — verifier dedups by validator_pubkey
                                     (prevents single validator
                                     forging pseudo-quorum)
  * 1 malicious validator          — 2-of-3 quorum tolerates

**Threat model NOT defended at this layer:**

  * Sybil applicant + Sybil validators — needs DHT-driven random
    selection of Tier-3 validators (orchestrator-layer concern,
    out of scope here).
  * >k/n malicious Tier-3 validators — fundamental quorum limit.
  * Validator that's not actually Tier-3 — consumer-side
    `verify_attestation_cert` should be paired with a DHT lookup
    that confirms each `validator_pubkey` is itself Tier-3 attested.
    That lookup is outside the pure verifier (requires IO).

### What §6 #21 still needs

  * **libp2p stream protocol** at `/gyza/capability-challenge/1.0.0`
    on the Go side. The dataclasses are JSON-serializable, so this
    is a mechanical varint-frame + protocol-handler addition. Mirror
    the existing `/gyza/message/1.0.0` pattern.
  * **DHT-driven validator selection.** `CapabilityClient` calls
    `find_agents(min_tier=3, k=N)` and feeds the result into
    `run_attestation` as the `validators` list.
  * **DHT publication of the cert.** `cap.publish_attestation` already
    exists on the daemon; just needs the cert proto-shape mapped from
    our Python dataclass.
  * **`gyza global attest --tier 3` CLI mode** that ties it together.

These are all mechanical now that the algorithmic protocol is settled.

---

## 5c. Session 10 — peer cache, daemon supervisor, executor sandbox

Two §6 priorities closed: #24 (peer cache + supervisor) and
#22 (sandbox). Cumulative tests after Session 10: ~420 (was 373 at
Session 10 start; +30 peer-cache/supervisor/integration; +18 sandbox).

### #24 — Persistent peer cache + daemon supervisor — `gyza/network/peer_cache.py` + `daemon_supervisor.py` + 30 tests

**PeerCache.** JSON-backed at `~/.gyza/peers.json` by default, atomic
write via `tempfile + os.replace` in the same directory (rename atomicity
requires same filesystem). Stores `(pubkey, multiaddr, last_seen_ns)`
tuples; multiple multiaddrs per peer are supported. `all_addrs()` returns
addresses ordered by `last_seen DESC` per pubkey, and
`attempt_reconnect_all` tries each peer's newest address first, falling
through on failure. **Counts are per-peer not per-multiaddr** — a peer
reachable at two addresses counts once. A schema version mismatch on
load preserves the old file untouched and starts empty.

**DaemonSupervisor.** Heartbeat-driven watcher around gyza-netd. Polls
`netd.is_running()` every 5s; after 3 consecutive failures, kills the
zombie and respawns with backoff `1, 2, 4, 8, 16, 32, 60` seconds capped
at the tail. The single `NetdClient` instance is reused across respawns
(gRPC autoreconnects to the same Unix socket — callers don't need to
care). Exposes `set_on_respawn(cb)` for the GlobalCluster to wire its
recovery hooks. **Callback exceptions are caught and logged**, never
trigger another respawn (would mask the underlying bug + cause storms).

**GlobalCluster wiring.** Optional `peer_cache` + `supervisor` kwargs;
mutually exclusive with `netd_client` (raises ValueError on misuse).
`start()` calls `peer_cache.attempt_reconnect_all` BEFORE flipping
`is_started=True` — settlement.send_message would otherwise race past
the redial. `find_and_collaborate` writes back the verified pubkey
(not the originally-advertised one) so DCUtR re-routes don't poison
the redial set. `_on_daemon_respawn(netd)` callback redials the cache,
re-publishes DHT ads, and rejoins active project gossip topics.

**CLI.** `gyza global start --supervised` runs as a long-lived
foreground supervisor (blocks until SIGINT). One-shot mode without the
flag is preserved — the CLAUDE.md trip-wire about "don't auto-supervise
inside fire-and-forget CLI" stands.

**Trip-wires fixed in passing:**

  * `_lib_` and `/lib64` are symlinks on merged-/usr distros (Arch,
    modern Fedora/Debian). The Sandbox runner originally treated them
    as duplicate dirs and deduped — that broke the dynamic linker
    (`/lib64/ld-linux-x86-64.so.2` failed to resolve). Fixed by
    `_HostMount(kind="symlink"|"bind")` distinguishing the two and
    emitting `--symlink` instead of `--ro-bind` for symlinks. (Lives
    in #22's code, but discovered while writing the sandbox tests.)

### #22 — Executor sandbox — `gyza/sandbox/` + 18 tests

**Threat model.** Phase 3 accepts work claims from strangers; the
executor surface is therefore a security boundary. Sandboxing today
mainly matters forward-looking: the existing Anthropic executor is
HTTP-bound (no local code execution beyond the SDK), but Phase 4+
introduces tool-using and code-running executors where the boundary is
load-bearing. Building it now makes those additions safe by default.

**Architecture.** Four modules:

  * `config.py` — `SandboxConfig` dataclass (FS allowlist, network flag,
    RLIMIT_AS, RLIMIT_CPU, wall-clock timeout, env passthrough).
    `_system_mounts()` introspects `sys.prefix` / `sys.base_prefix` /
    `sysconfig.get_paths()` and builds the bind/symlink list a fresh
    Python interpreter needs to boot. Distinguishes bind from symlink
    (see merged-/usr trip-wire above).
  * `_entrypoint.py` — runs INSIDE the sandbox via
    `python -m gyza.sandbox._entrypoint`. Reads length-prefixed
    (8-byte big-endian) JSON from stdin, applies `resource.setrlimit`,
    imports the inner factory by `module:func` qualname, calls it,
    writes a length-prefixed JSON response. Length-framing is essential
    because tokenizer/SDK `print()` calls would corrupt a stream-of-JSON
    channel (sentence-transformers writes a load report to stdout on
    first import).
  * `runner.py` — `run_sandboxed()` builds the bwrap argv. Flag ordering
    is load-bearing: system mounts → `/proc /dev` → **/tmp tmpfs** →
    user `ro_paths` → workspace. The tmpfs-before-ro_paths order means a
    user `ro_path` rooted under `/tmp` (e.g., a pytest tmp dir) lands
    ON TOP of the tmpfs and stays visible. Reverse the order and the
    tmpfs shadows everything.
  * `executor.py` — `make_sandboxed_executor(qualname, init_kwargs,
    config)` returns a `Callable[[str, dict], dict]`; the runner
    consumes it identically to a non-sandboxed executor. Presets:
    `sandboxed_mock_executor()`, `sandboxed_anthropic_executor()`.

**Defended against:**

  * Path traversal in `context` — bind allowlist denies arbitrary host
    file reads. `~/.ssh`, `~/.gyza/compositor.key` are NOT visible.
  * FS persistence — only `rw_paths` and `workspace` accept writes;
    everything else fails with EROFS.
  * Network exfiltration — fresh net namespace by default
    (`requires_network=False`); only loopback. `True` enables
    host-shared net (used by Anthropic executor).
  * Resource exhaustion — RLIMIT_AS (default 2GB), RLIMIT_CPU (default
    300s), wall-clock timeout (default 120s).
  * Env leakage — `--clearenv` by default; explicit `env_set` and
    `env_passthrough` control what crosses the boundary. API keys go
    via `env_set`, never argv (no `ps`-visible secrets).

**NOT defended against:** kernel CVEs in user namespaces, side-channels,
malicious code in the trusted tree (anything in `ro_paths` is implicitly
trusted — don't put attacker-controlled code there).

**Backend selection.** `detect_backend()` probes for `bwrap` AND user
namespaces (smoke-spawns `bwrap ... /usr/bin/true`). Returns
`SandboxBackend.BUBBLEWRAP` or `SandboxBackend.NONE`. NONE means
direct in-process execution — used as an explicit fallback in trusted
environments; logs a warning at every call.

**Production wiring NOT yet done.** This session built the primitive
and proved the boundary; existing Anthropic and mock executors used in
the demo and tests are still NOT sandboxed by default. Switching the
runner's default executor to `sandboxed_anthropic_executor` would
break the integration demo (subprocess startup time + bwrap flag
interaction with the test harness needs validation). Deferred until a
follow-up that intentionally rolls out sandboxing across
`demo/single_machine_global.py` and the docs.

---

## 5d. Session 9 — observability + bilateral reconciliation

Two §6 priority items closed. Cumulative tests after Session 9: **373**
(was 349 at Session 9 start; +10 observability + +14 reconciliation).

### #26 — Prometheus metrics + structlog — `gyza/observability.py` + 10 tests

New module exposes 5 counters, 2 histograms, 4 gauges via the
default `prometheus_client` registry, plus an idempotent
`start_metrics_server(port=9100, addr="127.0.0.1")` and a one-shot
`configure_structlog(json=True)`. Default bind is loopback — operators
who want external scraping pass `addr="0.0.0.0"` explicitly.

**Wire points (every counter / histogram is incremented at exactly
one site so dashboards align cleanly with code):**

| Module | Metric | Where |
|---|---|---|
| `runner.py` | `gyza_agent_completions_total{outcome}` + `gyza_claim_to_complete_latency_seconds` | `_run_loop` success/release edge |
| `economy/settlement.py` | `gyza_settlements_total{role}` | on successful payer cosign / earner apply |
| `economy/settlement.py` | `gyza_disputes_total{reason}` | every protocol-rejection path (6 reasons) |
| `economy/settlement.py` | `gyza_settlement_latency_seconds` | keyed by entry_id, paired across submit/apply |
| `network/network_blackboard.py` | `gyza_gossip_deltas_total{direction}` | `_apply_delta` (in) / `_publish_delta_if_attached` (out) |
| `supervisor.py` | `gyza_supervisor_spawns_total` + `gyza_roster_size` | `_spawn` and `stop` |
| `network/global_cluster.py` | `gyza_dht_peer_count` + `gyza_connected_peers` + `gyza_ledger_net_credits` | refreshed on each `publish_agents` (TTL/2 cadence — no extra timer) |

**Settlement latency carrier.** `record_settlement_start(entry_id, t)`
stamps `time.monotonic()` when `submit_earned` ships; the apply
handler in `_handle_payer_cosigned` calls
`observe_settlement_latency(entry_id, time.monotonic())` which pops
the start and observes the diff. The map purges on observation; an
entry that never round-trips (peer goes dark) leaks until process
exit. Acceptable at Phase 3 scale.

**CLI.** `gyza metrics start [--addr --port]` (foreground, blocks
until SIGINT) and `gyza global start --metrics
[--metrics-addr --metrics-port]` (boot daemon AND scrape together).

### #25 — Bilateral ledger reconciliation RPC — `gyza/economy/settlement.py` + 14 tests

Two new MessageBus types `ledger.reconcile.request` /
`ledger.reconcile.response` plus the outbound
`LedgerSettlementService.request_reconciliation(...)` returning a
`ReconcileResult` dataclass. Wire schema in the docstring of
`_handle_reconcile_request`.

**Lex-cursor pagination.** Request carries `since_timestamp_ns` AND
`since_entry_id`. Server filter:
`(created_at_ns, entry_id) > (since_t, since_id)` ordered by the
same lex tuple. The lex tiebreaker is **essential, not optional** —
single-ns cursor would silently skip entries that share a
`created_at_ns` (rare on slow clocks, but the spec is correct, not
"usually fine"). Server fetches `max_entries+1` rows to detect
`has_more` without a separate COUNT query.

**Threat-model defenses worth knowing:**

  * **For-peer guard.** Request carries explicit `for_peer` field.
    Server drops requests where `for_peer != self_pubkey`. Prevents
    a hostile peer from probing our pairwise-ledger with strangers.
    Replies (which would leak existence-of-key) are NOT sent on
    misroute — cheap defense in depth on top of bus-level peer auth.
  * **Cross-peer injection guard.** `_handle_reconcile_response`
    verifies BOTH that `request_id` is in `_pending_reconciles` AND
    that `response.from_compositor` matches the peer the pending
    entry was registered against. Without the second check, any peer
    could inject a response into a known-pending request_id —
    UUIDv7 is not unguessable to a wire-traffic observer.
  * **Page cap** (`max_pages=50` default) bounds adversarial peers
    from looping us with permanent `has_more=true`. On cap hit,
    return `error="page_cap_exceeded"` with whatever was accumulated
    — partial diagnostic over silent truncation.
  * **Server-side max page size.** Client's `max_entries` is capped
    at `_MAX_RECONCILE_PAGE_SIZE = 2000` regardless of what the
    request asks for. Bounds adversarial response sizes.

**Reputation policy (CLAUDE.md original §6 #25 trip-wire):**

  * `disputed` → `record_dispute(peer)` PER disputed entry (each one
    is a separate protocol-violation signal — same canonical bytes
    must produce same signatures, divergence is unambiguous).
  * `missing_theirs` and `missing_ours` → **NO** reputation change.
    Could be benign pruning, gossip lag, or unsettled entries.
    Penalizing for these would manufacture disputes.

**Pagination loop sketch (in `request_reconciliation`):** `while
pages < max_pages: register pending; send; event.wait(timeout); break
on error/no-has-more; advance cursor`. The `while-else` clause
catches the cap-exceeded path — the while-else block fires only if
the loop exhausts `max_pages` without a `break`, which is exactly
what we want to label as `error="page_cap_exceeded"`.

**CLI.** `gyza credits reconcile <peer_pubkey>
[--peer-id --page-size --page-timeout]`. Requires running daemon;
peer_id auto-resolves via `PeerRegistry` when `--peer-id` is omitted.

### Trip-wire fixed in passing

`tests/test_chain_verification.py::test_runner_verify_lineage_non_strict_proceeds_when_missing`
had a 20s deadline that was tight under cold SentenceTransformer load
(test runs in ~33s in isolation due to one-time model load). Bumped
to 60s with a comment explaining the cold-cache cost. Don't tighten
it back without first warming ST in conftest.

---

## 5e. Session 8.5 — five priority gaps closed

### #19 — Real semantic embeddings — `gyza/embeddings.py` + 18 tests
Replaced seeded-random vectors with a real `Embedder` Protocol +
`SentenceTransformerEmbedder` (sentence-transformers/all-MiniLM-L6-v2,
384-dim, lazy load) + `StubEmbedder` (BLAKE3-seeded random for tests/CI)
+ `default_embedder()` singleton + `embed_intent` / `embed_work_description`
helpers. Wired into `gyza global find` and the demo.
**Convention:** every node in a project must use the same `model_id`;
Phase 3 hardcodes the default ST model. Phase 4 will negotiate.

### #20 — Runtime ICP chain verification — `gyza/blackboard.py` + `gyza/runner.py` + 11 tests
Added `icp_envelopes` table + `store_envelope` / `get_envelope` /
`get_envelope_for_action` / `reconstruct_chain` to `Blackboard`.
Runner persists every signed envelope automatically (`_complete()`)
and verifies a candidate work item's ancestor chain via `verify_chain`
before claiming (`_run_loop()`). Two flags govern policy:
`verify_chain_before_claim: bool = True` and
`strict_chain_verification: bool = False` (missing envelopes → reject
when True, warn-and-proceed when False).
**Tests use the pattern:** `_mark_completed_externally(bb, w, env_hash)`
to set up scenarios where the runner sees only the leaf item, not the
parent — otherwise the runner trivially completes the parent itself
and the test races to a false pass.

### #23 — Self-organization spawn loop — `gyza/supervisor.py` + 9 tests
`AgentSupervisor` polls `DemandOracle.all_signals()`, spawns via a
user-provided factory when a hot bucket has no serving agent, enforces
`max_agents`, fails soft on factory exceptions. Closes the
`should_spawn_replica → issue_agent` loop the spec called for.
**Pattern:** factory takes a `SpawnRequest(identity, specialization_seed,
bucket, spawn_reason)` and returns an unstarted `AgentRunner`. The
supervisor starts and tracks it.

### #27 — HLC thread-safety + cross-cluster ratchet — `gyza/schema.py` + `gyza/runner.py` + 9 tests
Two distinct fixes:
- HLC `now()`/`recv()` are now mutex-guarded. Pre-fix, two concurrent
  `now()` calls could produce the same `(l, c)` tuple — uniqueness
  violation.
- AgentRunner accepts `hlc=` kwarg. When in cluster mode, callers pass
  `gc.shared_hlc()` (which is `bb.gossip_hlc()`) so local claims and
  remote-claim merges share one ratcheting clock.
**Demo wires:** `runner = AgentRunner(..., hlc=side.cluster.shared_hlc())`.
**Future code that constructs runners in cluster mode MUST pass this**, or
risk silent total-order violation.

### #28 — Reputation feedback loop — `gyza/economy/reputation.py` + 16 tests
EWMA-based, SQLite-persisted, lock-guarded. Outcome model: success +1,
failure -0.5, dispute -1. Wired into:
- `AgentRunner._complete` / `_release` (local agent's score)
- `LedgerSettlementService` at every protocol-level rejection point
  (forged sig, envelope mismatch, amount tolerance, misroute) AND at
  successful settlement (counterparty's score)
**Deliberate non-dispute:** `_handle_earner_signed` does NOT bump dispute
on "unknown work_item_id" — could be gossip lag, not malice.

### Cumulative tests after Session 8.5: 349 (was 286 at session start)

---

## 6. The remaining priority list (#21 — Python adapter + DHT)

Session 9 closed #25 / #26; Session 10 closed #22 / #24; Session 11
closed the algorithmic core of #21 (eval suite + Tier-1 self-attestation
+ in-process cross-network attestation orchestration); Session 12
closed #21c (the libp2p stream protocol). Previous priority items are
documented in §5a–§5e.

**What's left of #21 is the Python ↔ Go bridge plus DHT.** The wire
protocol exists in Go and is tested with two real libp2p hosts on
loopback; what's missing is the Python applicant adapter that drives
the protocol from outside the daemon, plus DHT discovery and
publication.

### #21-bridge — Python applicant adapter

**Why:** Today the Go libp2p stream handler exists but has no Python
caller. The applicant-side ``RequestAttestation`` in
``netd/internal/capability_stream`` takes an ``EvalRunner`` callback
that produces a ``ChallengeResponse`` from a ``Challenge``. In
production that callback is Python (the AgentRunner lives there). The
daemon owns the libp2p stream; Python owns the eval execution. They
need to talk.

**Approach (recommended):** server-streaming gRPC with role inversion.

Add to ``CapabilityService`` in ``netd/internal/grpc/proto/netd.proto``:

```proto
service CapabilityService {
  // ... existing methods ...

  // Cross-network Tier-3 attestation, applicant side. The daemon
  // opens a libp2p stream to ``target_peer_id``, reads the
  // Challenge, sends it to the Python client over the response
  // stream, awaits the ChallengeResponse frame from the client,
  // forwards it on the libp2p stream, and finally yields the
  // CoSignature (or rejection).
  rpc RequestAttestation(stream AttestationApplicantFrame)
      returns (stream AttestationDaemonFrame);
}

message AttestationApplicantFrame {
  oneof body {
    AttestationStartRequest start    = 1;  // first frame: target_peer_id
    ChallengeResponse       response = 2;  // applicant's filled-in proto
  }
}

message AttestationDaemonFrame {
  oneof body {
    Challenge          challenge = 1;
    VerifyResponseResult outcome  = 2;
  }
}

message AttestationStartRequest {
  string target_peer_id = 1;
}
```

Python flow:
  1. Open the bidirectional stream.
  2. Send AttestationStartRequest{target_peer_id}.
  3. Daemon opens libp2p stream to validator, reads Challenge,
     forwards Challenge over the gRPC stream.
  4. Python receives Challenge → runs eval (via existing
     ``run_eval_locally`` against the local AgentRunner) → sends
     ChallengeResponse over the gRPC stream.
  5. Daemon forwards over libp2p, reads outcome, forwards to Python.
  6. Stream closes.

This keeps the daemon as the libp2p owner (matches the §1
architecture rule) and Python as the AgentRunner owner. The daemon
NEVER directly invokes Python code; the gRPC stream is the
choke point, with each side polling its own end.

**Alternative (rejected):** "daemon calls Python" via a callback gRPC
where Python registers as a server. Inverts the usual gRPC client →
server direction; introduces an extra goroutine and harder error
semantics. Not worth it for this flow.

**Trip-wires:**

  * The applicant's libp2p PeerID — and therefore its
    Noise-authenticated identity — is the daemon's compositor key,
    not the agent's. Make sure the applicant signature on the
    ChallengeResponse uses the COMPOSITOR signing key, not the agent
    key. (The TaskResult inner ICP envelopes ARE signed with the
    agent key; that's a different signature.)
  * Eval workdirs MUST be per-validator (validator-chosen nonces
    differ across validators, so each validator's eval lives in its
    own subdirectory). The Python orchestrator pattern from
    ``run_attestation`` already does this with
    ``workdir / f"v_{v.pubkey[:16]}"``.
  * The gRPC stream's backpressure is per-direction. A slow Python
    eval doesn't block the daemon's libp2p reads (Go side has its
    own goroutine reading the libp2p stream into a buffer). But if
    Python crashes mid-eval, the daemon's libp2p stream times out at
    ``capability_stream.StreamTimeout`` (120s) — surface that to the
    Python caller as a structured error.

**Estimated effort:** 1–2 days. Most of the work is gRPC plumbing
plus the Python orchestrator that wraps existing primitives.

### #21d — DHT-driven validator selection

**Why:** Today `run_attestation` takes a caller-supplied list of
Validators. In production the applicant must DISCOVER Tier-3
validators via the DHT.

**Approach:**

```python
# In CapabilityClient or a new Tier3AttestationClient:
def request_tier3_attestation(self, applicant: Applicant) -> AttestationCert | None:
    ads = self._netd.find_agents(
        query_embedding=ATTESTATION_QUERY_EMBEDDING,  # generic query
        k=3, min_tier=3,
    )
    if len(ads) < 3:
        return None  # not enough Tier-3 validators online
    validators = [self._stream_validator_for(ad) for ad in ads]
    outcome = run_attestation(
        applicant=applicant, validators=validators,
        workdir=..., output_recorder=..., quorum_k=2,
    )
    return outcome.cert
```

`_stream_validator_for(ad)` wraps the libp2p stream protocol in a
Validator-shaped façade (issues challenges by sending the
ChallengeRequest frame, returns Outcome by reading ChallengeOutcome).

**Trip-wires:**

  * Don't pick validators the applicant has prior credit history
    with — collusion-prone. Random selection from `find_agents`
    results, dedup by compositor pubkey.
  * Three validators yielding fewer than 2 cosigs (quorum failure)
    should NOT auto-retry against three different validators; that
    leaks the failure to more peers. Surface to the operator, let
    them re-issue manually.

### #21e — DHT publication of the cert + `gyza global attest --tier 3` CLI

**Why:** A cert that no one can find is useless. Publish to DHT keyed
by applicant compositor pubkey so peers can fetch + verify.

**Approach:**

  * Define the protobuf shape of `AttestationCert` mirroring the
    Python dataclass. Map dataclass → proto via field-by-field
    population.
  * Call existing `cap.publish_attestation(cert_proto)` after a
    successful `run_attestation` returns a non-None cert.
  * Wire `gyza global attest --tier 3` CLI (extend the existing
    `gyza global attest` from Session 11): if `--tier 3`, run the
    full DHT-discovery + cross-network attestation flow.

**Trip-wires:**

  * The cert is signed by N validators; the DHT record itself doesn't
    need an additional signature wrapper — go-libp2p-kad-dht already
    signs records. But peers fetching the cert must verify each cosig
    via `verify_attestation_cert`; trusting the DHT record's
    well-formedness is NOT trusting the cert's content.
  * Cert TTL on the DHT record should be ≤ `expires_at_ns - now`
    so consumers can't fetch an already-expired cert.

**Estimated effort for #21c–e:** 2–3 days, mostly Go protocol handler
+ Python stream client. The algorithmic work is done.

<!-- #22 (sandbox) and #24 (peer cache + supervisor) closed in Session 10;
#21a (eval suite + Tier-1 self-attest) and #21b (cross-network protocol
orchestration in-process) closed in Session 11. Implementations live in
gyza/sandbox/, gyza/network/peer_cache.py + daemon_supervisor.py,
gyza/capability_eval.py, and gyza/network/capability_protocol.py. -->

---

## 7. Future prospects — Phase 4 through 9

This section is the long-horizon roadmap past the §6 priority list.
Each phase has a thesis, real technical mechanisms, hard problems
that aren't waved away, gating conditions (when it's safe to start),
and what the phase actually unlocks. Phases 4 and 5 are
near-implementable; Phase 6+ are increasingly ambitious.

The general principle: **don't start phase N until phase N-1 has real
users generating real data.** The algorithms in later phases need
empirical inputs from earlier phases to be worth implementing. Building
Phase 5 against synthetic Phase 3 demand teaches you nothing about
real Phase 5 dynamics.

---

### Phase 4 — The learning phase (next after priority list)

**Thesis.** Today's network coordinates static agents. Phase 4 makes
agents adapt — fine-tune their weights to the demand they observe.

**Gating condition:** 20+ live nodes producing organic completion data.
Below that, the training data is too sparse to make fine-tuning
meaningful.

**Mechanisms:**

- **Fine-tuned child agents.** When the supervisor spawns a replica
  for a hot bucket, it should fine-tune the child's executor (LoRA
  adapter or full fine-tune) on the parent's recent successful
  completions in that bucket. Requires an LM training loop per node —
  heavy infra. Probably tied to a base model class (Qwen2.5-3B is the
  spec's reference baseline). LoRA registry per node: `(bucket_hash,
  base_model, lora_path, training_data_hash)`.
- **DHT-distributed LoRA payloads.** New nodes can download attested
  LoRAs for hot buckets from existing specialists via content-addressed
  DHT keys (`/gyza/loras/{hash}`). Joiners arrive pre-loaded with the
  network's accumulated expertise.
- **Versioned identity / manifest rotation.** Today, losing
  `~/.gyza/compositor.key` loses your reputation history forever.
  Phase 4 rotates the keypair while preserving reputation by chaining
  manifests: the new manifest signs over the old one, and the
  reputation store carries the chain forward through linkable lineage.
- **Scoped revocation lists via gossip.** Phase 2 has a local
  `TrustRegistry`. Phase 4 gossips revocation events ("compositor X
  was revoked by compositor Y at timestamp T") under a topic like
  `/gyza/revocations`, weighted by revoker reputation × tier × age
  decay so a swarm of low-tier revocations gets ignored.
- **Encrypted work items.** Today, intents and work item descriptions
  are plaintext-gossiped to all project members. Phase 4 adds
  per-recipient ECIES (`encrypted_payload: bytes` +
  `recipient_pubkeys: list[str]`) so an intent is visible only to the
  chosen recipient compositors. Plaintext metadata (LSH bucket, tier,
  reward) stays in the clear for routing.
- **Cross-cluster intent provenance.** Today, remote intents are
  attributed to `delta.sender_compositor_pubkey` (the publisher).
  Phase 4 adds an explicit `creator_compositor_pubkey` field so a
  forwarded intent (e.g. via a relay node on behalf of an offline
  originator) keeps correct attribution.

**Hard problems:**

- **Catastrophic forgetting.** A LoRA fine-tuned on bucket X may
  regress on the base model's general capability. Eval suite (#21)
  must gate publishing a new LoRA — the new weights only get
  attested-and-shared if they pass capability checks.
- **Training data quality.** "Successful completions" includes
  everything that didn't error. Reward signal is weak — was the output
  *good* or just non-failing? Probably needs RLHF-style reward
  modeling, which is another order of magnitude of complexity.
- **LoRA verification.** How does a downloader know a LoRA was
  actually trained on the data its manifest claims? Verifiable
  training (zk-ML) is a research frontier; for Phase 4, the practical
  answer is "the publisher signs the LoRA + their training data
  hash, and you trust them up to their attestation tier."
- **Rotation under compromise.** If `OLD_KEY` is leaked, the attacker
  publishes their own rotation cert pointing at THEIR new key.
  Defense: time-locked rotations (publish at T, takes effect at T+24h;
  legitimate holder can publish a counter-statement during the
  window). Or M-of-N trustee co-signatures (social recovery).
- **Metadata leak under encrypted intents.** Even with body encrypted,
  the LSH bucket leaks rough topic. For high-privacy use cases need
  randomized bucket assignment per recipient — breaks routing. Tradeoff.

**What it unlocks:** specialists actually specialize. The network's
collective expertise compounds. Sybil attacks get harder (Sybils have
no track record AND no specialized capability).

---

### Phase 5 — Capability composition (workflows)

**Thesis.** Today's `WorkItem` is atomic — one prompt, one output.
Real-world goals decompose into DAGs. Phase 5 makes plan-execute-recombine
first-class.

**Gating condition:** Phase 4's eval suite + reputation are working.
Without them, plans can't be costed or trusted.

**Mechanisms:**

- **Goal-decomposition agents.** New agent class whose output is a
  `Plan` — a typed dependency DAG of sub-WorkItems with declared
  input/output shapes. Lives in `gyza/planning/`. Reuses existing
  settlement and ICP infrastructure for sub-tasks.
- **Capability advertisement extensions.** `AgentDescriptor` gains
  `capability_signature` — a typed schema description (input/output
  modalities, side-effects, latency profile, cost envelope).
  Discovery becomes typed: "find agents whose capability_signature
  satisfies this constraint."
- **Plan execution engine.** Walks the DAG, dispatches each node as a
  WorkItem, monitors progress, handles failures via retry / fallback
  agent / replan. Carries a credit budget per Plan; sub-tasks can't
  collectively exceed it without re-asking the user.
- **Speculative execution.** A Plan with two alternative branches both
  meeting demand could execute both speculatively and commit the
  winner. Loser of the race gets partial credit (mechanism design
  choice — keeps participation incentive alive).

**Hard problems:**

- **Cost prediction is its own ML problem.** Today's `compute_task_cost`
  is a simple model-tokens product. Phase 5 needs *ex-ante* prediction:
  "this Plan will probably cost between 30 and 80 credits." Without
  this, users can't approve plans rationally. Probably regression
  trained on historical settlements with bootstrapped confidence
  intervals.
- **Compositionality of trust.** Per-Plan reputation requires
  aggregating over the chain. If agent X has 0.95 reputation and agent
  Y has 0.6, the Plan's success probability isn't `0.95 × 0.6` —
  failure modes correlate, retries change the math. Bayesian network
  reliability analysis territory.
- **Cycle detection.** LLM-generated DAGs have cycles all the time
  ("step 3 depends on step 5 which depends on step 3"). Need static
  analysis at plan validation time, max-depth limits, cycle-breaking
  heuristics. Tarjan's SCC algorithm; mechanical.

**What it unlocks:** real workflows. Today Gyza does atomic tasks;
Phase 5 does multi-step jobs with cost bounds, retries, and replanning.

---

### Phase 6 — Embodied + multimodal

**Thesis.** Today everything is text. Phase 6 adds vision, audio,
real-time streams, physical actuators.

**Gating condition:** Phase 5 plans are working; you have customers
asking for non-text capabilities.

**Mechanisms:**

- **Multimodal artifact schema.** `Artifact` gains `mime_type` and
  chunked storage. Use [bao](https://github.com/oconnor663/bao) (BLAKE3
  tree mode) for verifiable random access to blob slices.
- **Streaming work items.** Today's WorkItem is request/response.
  Streaming requires subscription semantics: producer agent writes to
  an artifact-stream, consumers subscribe and pull frames. Blackboard
  gains `WorkItemStream` records with chunk pointers.
- **Real-time scheduling discipline.** Robot control needs deterministic
  sub-100ms response. Current poll-based runner with second-scale ticks
  is wrong for this regime. Add an event-driven runner mode + per-agent
  scheduling SLAs (`max_latency_ms: 50`).
- **Hardware attestation.** A node claims it has a Franka Panda. Three
  layers: (a) self-reported via capability manifest, (b) attested by
  Tier-3 validators who've physically inspected (off-chain trust
  transfer), (c) cryptographic attestation via TPM-backed device
  certificates from manufacturer. (a) trivial, (b) sociological,
  (c) real and exists for some hardware.
- **Capability gating for actuators.** Compositor manifest already
  supports filesystem capabilities; extend to actuator capabilities
  ("agent can move arm in volume `[x:0..0.5, y:-0.3..0.3, z:0..0.4]`
  at `<=0.5 m/s`").

**Hard problems:**

- **Bandwidth.** Gossipsub wasn't designed for video. Need a split:
  control-plane gossip (capability changes, work item posts) stays on
  gossipsub; data-plane streams open dedicated libp2p streams between
  subscriber and producer. Lot of new code.
- **Physical actuator safety.** A buggy agent commanding a robot is a
  physical hazard. Need deterministic kill-switches at the hardware
  level — "no command exceeding velocity X reaches the motor controller,
  ever." Industry-standard in industrial automation; the protocol just
  wires it.
- **Latency-bounded routing.** Today's discovery picks by specialization
  match. Phase 6 routing also satisfies `max_latency_ms` constraints —
  geographic awareness in the DHT. Existing libp2p `dnsaddr` + IP geo
  gets ~80%; rest is active research (latency-aware Kademlia).
- **Hardware diversity.** ROS2 for robotics, OpenCV/V4L for video,
  ALSA for audio. Phase 6 effectively becomes a federation broker
  between Gyza and these standards. Per-platform shims, no shortcut.

**What it unlocks:** Gyza stops being a "remote LLM coordination
protocol" and becomes a substrate for real-world automation. Coordinator
posts "monitor my warehouse for safety incidents" → network composes
vision + alert-routing + physical-actuator agents into a working system.

---

### Phase 7 — Self-modifying protocol (governance)

**Thesis.** Today the protocol is whatever the latest `gyza-netd`
binary implements. Phase 7 makes the network vote on its own evolution.

**Gating condition:** Network has 1000+ nodes with diverse stake
distribution. Below that, governance is theater — small holder
collusion can pass any vote.

**Mechanisms:**

- **Protocol upgrade proposals as a special intent type.** A
  `ProtocolProposal` carries a formal change description (probably TLA+
  for invariant-checked specs, plus a Go/Python implementation patch).
  Reviewed by special "protocol reviewer" agents.
- **Stake-weighted voting with quadratic dampening.** Voting power is
  a function of compute credits earned over last N days × attestation
  tier × node uptime. **Quadratic voting** (`vote_weight = sqrt(stake)`)
  bounds the influence of capital concentration — a node with 100x
  stake gets 10x voting power, not 100x. Glen Weyl mechanism.
- **Activation cooldown.** Passing vote takes effect 30 days after
  consensus. During cooldown, supporting nodes download the binary;
  others either upgrade or accept backward-compat path. Time to
  discover bugs before commitment.
- **Forward-compatible wire formats.** Protobuf with strict reserved
  field discipline. Old daemons preserve unknown fields on round-trip;
  new daemons treat absent new fields as defaults. Additive changes
  free; breaking changes need coordinated rollout.
- **Constitutional invariant fences.** Some properties are unvotable:
  the 384-dim embedding bound, Ed25519 identity scheme, BLAKE3 hash
  function, bilateral settlement requirement. Changing them requires a
  hard fork, not a soft upgrade. Document the constitutional layer
  explicitly so a 51% attacker can't slowly erode it.

**Hard problems:**

- **Sybil resistance under voting.** Reputation alone isn't enough — a
  capital-rich adversary can buy stake. Quadratic voting helps;
  reputation-weighting helps more; tier-gated participation helps most.
  No defense is perfect against state-level adversaries with patience.
- **Schism.** A 50/50 vote forks the network. Need Schelling-point
  mechanisms to make one side dominant — probably a `SchismResolver`
  agent class computing which side has more economic activity, signaling
  that as canonical. Compare Bitcoin's "longest chain" rule.
- **Spec language for safe upgrades.** TLA+ is mature but human-written.
  Will need LLM-assisted spec writing AND an LLM-assisted reviewer
  that checks proposals against constitutional invariants before they
  go to vote. Itself a research problem (formal-verification-aware LLM
  agents) but tractable for restricted spec languages.
- **Capability creep.** "The network can change itself" includes "the
  network can vote to remove its own safety properties." The
  constitutional fence handles known invariants; emergent ones can be
  eroded. Mitigation: slow-zone period where new features are
  constrained until they prove safe.

**What it unlocks:** the network outlives any specific human maintainer.
It evolves. The protocol becomes a common-pool resource governed by
participants. Whether that's good or bad depends on how well the
governance mechanism resists capture.

---

### Phase 8 — Cross-substrate heterogeneity

**Thesis.** Today everyone runs an LLM. Phase 8 makes radically different
compute substrates collaborate as peers.

**Gating condition:** Multiple substrate vendors actually exist in the
ecosystem. As of writing, this includes LLMs (OpenAI/Anthropic/llama),
neuromorphic (Loihi, NorthPole, Akida), and specialized inference
silicon (Groq, Cerebras). Quantum is ~10 years out for fault-tolerance.

**Mechanisms:**

- **Substrate-abstracted capability descriptors.** Today
  `model_identifier: "anthropic:claude-sonnet-4-5"` couples capability
  to a specific model. Decouple: `output_class: "natural_language" |
  "code_python" | "image_2d" | "policy_robotics"`. Discovery routes by
  `output_class`, not model name.
- **Embedding alignment.** Two substrates produce 384-dim vectors but
  in different spaces — incomparable for cosine similarity. Options:
  (a) universal projection learned from cross-substrate parallel data,
  (b) per-pair Procrustes alignment computed on shared vocabulary,
  (c) canonical reference embedding model that every substrate's
  outputs are projected through. **(c) is the practical answer** — it
  bottlenecks everything through one model but is the only path that
  scales.
- **Substrate-specific cost models.** Cerebras WSE-3 outputs 1500 tok/s
  at $X per inference; llama.cpp on Raspberry Pi does 0.5 tok/s at
  near-zero marginal cost. Extend `CREDIT_RATES` into a substrate
  registry with per-substrate calibration.
- **Substrate-typed attestation tiers.** `Tier3-x86`, `Tier3-loihi`,
  `Tier3-quantum`. Trust is partitioned by substrate class until
  cross-substrate eval suites mature.
- **Cross-substrate format brokers.** Image-modality agent calls
  text-modality agent: somebody has to OCR or caption-then-transcribe.
  These brokers are themselves agents (multimodal ones) that emerge
  as a market function.

**Hard problems:**

- **Embedding alignment is unsolved at scale.** Procrustes-based methods
  work for related models on shared vocabulary; degrade dramatically
  on out-of-distribution data. Reference-model-projection sidesteps
  alignment at the cost of bottlenecking through one model. Real
  tradeoff with no clean answer.
- **Throughput rate-limiting.** Current protocol assumes peers within
  ~100x of each other in throughput. Cerebras-class node and Raspberry
  Pi differ by ~10,000x. Need explicit rate-limiting at the discovery
  layer — Cerebras-class nodes only serve Cerebras-class demand, not
  get DDOSed by Pi nodes.
- **Neuromorphic substrates** (Intel Loihi 2, IBM NorthPole, BrainChip
  Akida) are event-driven, sparse, low-power. Current request/response
  with millisecond-scale prompt exchange doesn't match their natural
  mode (continuous-time spike processing). Need a streaming-first
  agent class as a separate first-class citizen.

**What it unlocks:** the network becomes substrate-agnostic. Survives
any single hardware paradigm becoming obsolete. Resilience by diversity.
Composes capabilities no single substrate has — quantum optimizer
feeds classical ML, whose outputs control robotics, all settled in
real-time.

---

### Phase 9 — Economic singularity (network self-funding)

**Thesis.** The credit economy starts paying for its own infrastructure.
The network becomes a DAO-like entity that funds its own operations.

**Gating condition:** Real settlement volume. ~$100K/year of credit-flow
makes a 2% treasury fee meaningful ($2K/year — enough for a small
bootstrap node). At $10M/year ($200K treasury) the network can self-fund
non-trivial development. Below those thresholds, treasury is symbolic.

**Mechanisms:**

- **Treasury contracts.** A small percentage of every settlement
  (say 2%) flows to a network treasury — collectively owned, governed
  via Phase 7's voting mechanism. Funds bootstrap nodes, relay nodes,
  eval-suite maintenance, security audits, embedding model hosting.
- **Funded R&D bounties.** Protocol improvements as `WorkItem`s with
  treasury-backed rewards. Future protocol changes become jobs the
  network posts to itself; specialist developer agents (or human
  developers wrapped as agents) claim and execute.
- **Stablecoin / fiat on-ramps.** Credits become exchangeable for real
  money via DEXs or bilateral OTC. **This is the regulatory cliff** —
  money transmitter rules in US, PSD2 in EU, etc. Has to be navigated
  jurisdiction by jurisdiction.
- **Network-funded hardware.** Treasury pays for dedicated bootstrap
  / relay infrastructure. Eventually could fund agent-running hardware
  itself: GPU clusters as commons, output credits flowing back to
  treasury minus operational costs. Recursive.

**Hard problems:**

- **Regulatory exposure.** Once credits are exchangeable for fiat, the
  project is subject to financial regulations everywhere it operates.
  Mitigation: keep credits internal to compute-for-compute exchange;
  explicit "no fiat conversion" commitment. Tradeoff: limits the
  economic bootstrap mechanism.
- **Public goods funding mechanism design.** "How do we collectively
  decide what to fund?" is the classic public goods problem at scale.
  Quadratic funding (Gitcoin-style) is plausible — small donations
  amplified, capture is harder.
- **Bootstrap dilemma.** Who pays for the first bootstrap nodes before
  there's enough income to fund them? Founders subsidize for ~12 months,
  then transition. Treasury starts at zero and grows. Chicken-and-egg
  phase requires patient capital.
- **Capture risk.** If a single corporation (or state) accumulates
  enough stake, they control the treasury. Quadratic voting helps but
  no mechanism is perfectly capture-resistant. Documented limitation.

**What it unlocks:** the network self-perpetuates without external
patron. It becomes an economic entity in its own right — an organism
that pays for its own metabolism.

---

---

## 8. Production infrastructure — what only humans can do

The last session enumerated this in detail. Summary for context:

- **Bootstrap nodes** (3+ VPSes, ~$30/mo total) — without these,
  cross-internet discovery doesn't work at all.
- **DNS** for `dnsaddr`-based bootstrap rotation (~$15/yr).
- **Apple Developer ID** ($99/yr) for unsigned macOS binary problem.
- **Windows code-signing certificate** ($200–400/yr).
- **5–10 beta testers** willing to run nodes for a week. Without them,
  NAT diversity is unmeasured.
- **Security audit** ($2k–40k depending on scope).
- **Inference budget** — Anthropic API or self-hosted GPU.

None of these are coding tasks. The user owns them.

---

## 9. Conventions you must follow

### Don't break the test suite

Run the fast slice (`-k "not netd_client and not phase2_integration ..."`)
before declaring any change "done." When you touch daemon code, also
run `tests/test_netd_client.py` and `tests/test_network_blackboard_gossip.py`.

### Pyright noise is not a green light to refactor

If Pyright complains about an import that runs fine, **leave it alone.**
The lack of a pyrightconfig.json is intentional (the project doesn't
have a stable target Python install layout yet).

### Test patterns to copy

- For integration tests that need a running daemon:
  see `tests/test_netd_client.py::test_message_send_subscribe_two_daemons`
  (uses `NetdClient.start_daemon` + `_kill` lifecycle).
- For settlement protocol logic without a daemon:
  see `tests/test_settlement.py` (`_FakeBus` + `_make_pair`).
- For runner tests that need a chain in the envelope log:
  see `tests/test_chain_verification.py::_mark_completed_externally`
  pattern.
- For HLC concurrency tests: see `test_hlc_now_unique_under_concurrent_calls`.
- For wait-until polling: copy the `_wait_until(predicate, timeout_s)`
  helper used in many test files. **Don't** use bare `time.sleep` for
  "wait for an async event to happen" — flaky.
- For metrics assertions (Session 9+): use
  `prometheus_client.REGISTRY.get_sample_value(name, labels)` (or the
  `gyza.observability.get_counter_value` wrapper) and compare DELTAS
  (after − before). The default registry is process-global; earlier
  tests in the run will already have incremented things.
- For reconciliation tests (Session 9+): see
  `tests/test_reconciliation.py::_make_pair` — same `_FakeBus` pattern
  as settlement, plus `_StubReputation` for asserting on dispute
  counts and `_direct_insert` for forging divergent ledger states
  that the legitimate cosign flow can't produce (apply_cosigned_entry
  is symmetric, so both ledgers stay byte-identical otherwise).

### Fail-closed observability import wrappers (Session 9 pattern)

The instrumented modules (`runner.py`, `settlement.py`,
`network_blackboard.py`, `supervisor.py`, `global_cluster.py`) all
guard their `from gyza.observability import ...` behind a `try/except`
that installs no-op stubs on import failure. This keeps the runtime
working on a stripped-down install missing `prometheus_client`. When
adding a new wire-point:

```python
try:
    from gyza.observability import SOME_METRIC as _SOME_METRIC

    def _obs_thing(label: str) -> None:
        _SOME_METRIC.labels(kind=label).inc()
except Exception:  # noqa: BLE001
    def _obs_thing(label: str) -> None:  # type: ignore[misc]
        pass
```

Don't skip the wrapper — Pyright noise is a known false positive (§3),
but a real ImportError taking down the runner because someone forgot
to install `prometheus_client` is not.

### Concurrency invariants

- Every shared HLC instance MUST have a lock (it does now).
- The `LedgerSettlementService._lock` guards the read-modify-write of
  cosigning. Never sign outside it.
- `LedgerSettlementService._pending_lock` (Session 9) guards the
  reconciliation pending-request map. It is **separate** from
  `_lock` on purpose — settlement signing must not block on a slow
  `request_reconciliation` caller, and vice versa. Don't merge them.
- `ReputationStore._lock` guards EWMA updates similarly.
- The `Blackboard` is thread-local-connection but writes serialize via
  SQLite's WAL writer lock. Don't add long transactions.
- The runner's `_run_loop` is single-threaded. Don't introduce
  parallelism inside it without locking the runner state.

### Python style

- `from __future__ import annotations` at the top of every Python file.
- Comments explain the WHY, not the WHAT. Look at recent files
  (`embeddings.py`, `supervisor.py`, `reputation.py`) for the prose
  style — paragraphs with rationale, not docstring fillers.
- Type hints on public APIs; not required on internal helpers.
- No emojis in code or comments.
- No `print()` in library code — use `logging`. CLI code can `print`.

### Don't add files when editing existing ones works

If you need to add a method, add it to the existing class. Don't create
`gyza/economy/reputation_helpers.py` to host one function.

### Don't write Markdown documents unless asked

This file (CLAUDE.md) is an exception. Don't generate `DESIGN.md`,
`PLAN.md`, `ARCHITECTURE.md` etc. without an explicit request.

---

## 10. The session-start ritual

Every time you (a future Claude session) open this repo:

1. Read this file top to bottom. ~10 minutes.
2. Run the fast test slice (8–10 min as of Session 9; was 5–7 min
   pre-#25). Verifies you have a working environment AND nothing has
   rotted since the last session.
3. Run `python demo/single_machine_global.py` (~18–25s warm,
   ~25–40s cold ST cache). Verifies the integration path is intact —
   look for `Cross-cluster gossip: VALID ✓` and
   `Bilateral settlement: BILATERAL ✓`.
4. Check `git log --oneline -20` to see what changed since you last
   touched it.
5. The remaining work in §6 is the Python applicant adapter
   (#21-bridge) + #21d (DHT discovery) + #21e (DHT publish + CLI
   Tier-3 mode). The natural next step is the Python adapter — once
   it exists, #21d/e are mechanical. Pick one or ask the user.

If any of steps 2/3 fail, **stop and diagnose before doing new work.**
A failing baseline is more important than any new feature.

A note on flaky-deadline failures: Session 9 ran into one (the
`test_runner_verify_lineage_non_strict_proceeds_when_missing` test
had a 20s deadline that's tight on cold ST load). If you hit a
similar timing flake in the fast slice, run the test in isolation —
if it passes there in 30s+ but fails in the suite at 20s, the
deadline is the bug, not the code under test. Bump and document.

---

## 11. Don't-do list

Things a session might be tempted to do that would be wrong:

- **Don't add daemon auto-restart inside `gyza global start`.** That CLI
  returns immediately; supervisor inside it dies with the Python
  process. Wire supervision at the `GlobalCluster` lifecycle layer
  for long-running Python processes; keep the CLI a one-shot launcher.
- **Don't normalize embeddings client-side again.** SentenceTransformer
  with `normalize_embeddings=True` already returns L2-normalized
  vectors; double-normalizing wastes cycles and is a footgun.
- **Don't change `EMBEDDING_DIM` from 384.** Every advertisement on the
  DHT is keyed by an LSH bucket computed against 384 planes. Changing
  the dim invalidates the entire global state.
- **Don't use `verify_chain_multi_compositor` in the runner.** It
  requires `trust_registry` + `artifact_store` plumbing that doesn't
  exist there. Use `verify_chain` (single-key) for pre-claim checks;
  the multi-compositor version is for offline audit and Phase 2 demos.
- **Don't replace SQLite with anything fancier without a strong reason.**
  The blackboard, ledger, reputation, drift, and memory backends are
  all SQLite. WAL gives concurrent reads; the writes serialize but
  workload doesn't push that limit. Switching costs orders of
  magnitude more time than the throughput is worth at Phase 3 scale.
- **Don't add a "background reward refresh" inside the runner.**
  That's roadmapped under Phase 1.5 polish. The runner's job is
  claim/execute/sign; reward inflation is the blackboard's job.
- **Don't bypass `verify_chain_before_claim` in tests "for speed."**
  Use the `verify_chain_before_claim=False` flag explicitly. Hiding
  the verification under the rug means a real bug there could slip
  through.
- **Don't skip writing tests for the remaining priority items.** The
  pattern of test-then-ship in Sessions 8.5 + 9 caught real bugs
  (HLC thread-safety, chain-verify race condition with self-completed
  parents, settlement disputes on misroute, reconciliation
  cross-peer injection vector caught only because the test injected
  a forged response). Don't break that pattern.
- **Don't merge `LedgerSettlementService._lock` and `_pending_lock`.**
  They guard different concerns — settlement signing vs. pending
  reconciliation requests. Combining them would let a slow reconcile
  caller block payer cosignature decisions, which is the opposite
  of how each operation's latency budget should compose.
- **Don't add new dispute reason labels without updating the metric
  comment.** `gyza_disputes_total{reason}` has a documented label
  enumeration in `gyza/observability.py`; dashboards that pre-define
  panels per-reason will go blank for an unknown label until somebody
  refreshes them. Keep the comment in sync.
- **Don't replace lex-cursor reconciliation pagination with a single
  ns cursor.** Two entries that share `created_at_ns` (rare but
  possible at fast clocks) would silently fall off page boundaries.
  The `since_entry_id` tiebreak is load-bearing.
- **Don't reorder bwrap argv flags in `_build_bwrap_argv`** without
  understanding the layering. `--tmpfs /tmp` MUST come before user
  `ro_paths` so a tmp-rooted ro_path lands on top; reversing that
  silently shadows pytest's tmp_path-based test fixtures and any
  caller that mounts a tmp-rooted dir read-only.
- **Don't bind `/lib64` (or any other host symlink) as `--ro-bind`**
  on merged-/usr distros. Use `--symlink` to reproduce the link
  faithfully — `_HostMount` already handles this. A directory bind
  at `/lib64` makes `/lib64/ld-linux-x86-64.so.2` unreachable and
  every dynamically-linked binary inside the sandbox fails with
  `execvp: No such file or directory`.
- **Don't pass API keys as bwrap argv.** Use `env_set` so the value
  reaches the sandbox via `--setenv KEY VALUE`, not `--exec ... KEY=VALUE`
  on the command line. Argv is visible to `ps` for any user on the
  host; env via `--setenv` is namespace-private to the sandboxee.
- **Don't auto-supervise inside one-shot `gyza global start`.** Already
  honored — the `--supervised` flag is the foreground-blocking variant.
  Adding the supervisor to the no-flag path silently breaks the CLI's
  fire-and-forget contract because the Python process exits before the
  heartbeat thread can do anything useful.
- **Don't merge `_lock` and `_proc_lock` in `DaemonSupervisor`.** They
  guard different concerns: heartbeat-thread state vs. subprocess
  rotation. Combining them would deadlock the heartbeat against a
  concurrent stop().
- **Don't use `prompt.find("[GYZA_EVAL_TASK=")` in eval-related code
  — use `rfind`.** The runner's `build_enriched_prompt` prepends
  few-shot context from past episodes, which contains earlier
  tasks' markers verbatim. Scanning from the start silently solves
  the WRONG task. The current task's marker is always last.
- **Don't set `WorkItem.ttl_ns=0` in eval-driven flows.** The
  blackboard's `get_unclaimed` filter is `(created_at_ns + ttl_ns) >
  now_ns`, so `ttl_ns=0` immediately expires the item and the runner
  never claims it. Use `(timeout_s + 30) * 1_000_000_000`.
- **Don't try to read `LocalCompositor`'s key file expecting it to be
  the compositor signing seed.** The file holds the master seed; the
  compositor signing key is HKDF-derived (`_derive_seed(master,
  _CTX_COMPOSITOR_SEED, b"")`). Pass `LocalCompositor.sign` as a
  callable instead. For tests, use
  `gyza.network.capability_protocol.make_seed_signer(seed)` against a
  freshly-generated 32-byte seed.
- **Don't have validators sign DIFFERENT cert payload bytes.** Every
  cosig in a Tier-3 cert is over the SAME canonical bytes — that's
  the load-bearing invariant for quorum aggregation. The applicant
  proposes one `AttestationCertPayload` (timestamps + identity +
  schema), and `run_attestation` passes it to every validator
  unmodified. A validator that mutates the payload before signing
  produces a cosig that won't aggregate.
- **Don't verify ICP envelopes against the applicant's COMPOSITOR
  pubkey.** Envelopes are signed by the AGENT identity. The cert
  binds at the compositor; the eval verifier checks against the
  agent. `ChallengeResponse` carries both pubkeys for this reason.
  The bridge "agent issued by compositor" is via the capability
  manifest — verifying that link is a documented follow-up; for now
  the validator confirms the agent passed the eval and the cert
  binds at the compositor.
- **Don't skip the validator's clock-skew check** when accepting a
  ChallengeResponse. A malicious applicant could propose a cert with
  `issued_at_ns` 6 months in the past, so the cert appears already
  near-expired even though it's "fresh." The validator rejects
  payloads whose `issued_at_ns` is more than ±1h from its local
  clock; consumers separately enforce `expires_at_ns > now`.
- **Don't have the consumer-side `verify_attestation_cert` accept a
  cert whose validators are NOT themselves Tier-3.** That check
  requires DHT IO and lives outside the pure verifier. Pair the pure
  verifier with a separate "this validator's pubkey was attested
  Tier-3" lookup before trusting any cert.
- **Don't try to make Python's JSON-canonicalized cosignatures
  interoperate with Go's deterministic-protobuf cosignatures.** They
  produce different bytes; a Go validator and a Python validator
  cosigning the "same" body won't aggregate into a single quorum. For
  cross-network attestation the wire format is Go protobuf with
  `proto.MarshalOptions{Deterministic: true}`; Python applicant
  adapters (when they're built) should use the Python protobuf
  library against the same proto definitions in
  `netd/internal/grpc/proto/netd.proto`. The Python
  `gyza/network/capability_protocol.py` from Session 11 stays as-is
  for IN-PROCESS Tier-1 self-attestation only.
- **Don't add a kickoff frame to `/gyza/capability-challenge/1.0.0`.**
  The validator extracts the applicant pubkey from the libp2p
  RemotePeer (Noise-authenticated). The protocol is 3 frames, not
  4. Adding a kickoff "applicant says hello" frame is redundant
  AND introduces a new failure mode (applicant can claim a different
  pubkey than its libp2p identity).
- **Don't run the eval before verifying the challenge signature.**
  `RequestAttestation` calls `capMgr.VerifyChallenge` BEFORE
  invoking the eval callback. The eval is the slow step (10s+ for
  real LLMs); a malformed challenge from a spoofing peer must be
  rejected without burning applicant CPU.
- **Don't drift the validator's task list from the applicant's eval
  suite.** The daemon's `capability_stream.Manager.TaskIDs` is
  hardcoded to match `gyza/capability_eval.py`'s `EVAL_TASKS`. A
  task in one but not the other surfaces silently as "missing task
  result" rejection on every cosig attempt. Until task-set
  negotiation lands (a future v2 protocol), keep them in sync
  manually.
- **Don't remove the per-stream deadline.** `StreamTimeout = 120s`
  bounds the WHOLE applicant↔validator exchange. A peer that opens
  a stream then sleeps forever would otherwise pin a goroutine.
  120s is generous (real-LLM eval suite at ~60s plus margin); making
  it longer admits DoS, making it shorter starves slow honest peers.
- **Don't write unstructured errors to the libp2p stream.** Validator
  rejections go on the wire as
  `VerifyResponseResult{Success=false, Error=<reason>}` so the
  applicant can diagnose without out-of-band logging. Network/IO
  errors close the stream silently — the applicant's read times out
  cleanly. Keep these two paths separate; mixing them makes
  applicant-side error handling ambiguous.

---

## 12. If something is unclear

Ask the user. The user is the architect, makes scoping calls, and owns
the strategic decisions (what counts as Tier 3, who runs bootstrap
nodes, what credits redeem to). When in doubt about scope or priority,
ask.

When the user says "think really hard like a CS PhD" — that's the
quality bar. Don't ship hand-wavy code. Audit before fixing. Test the
fix. Verify nothing else regressed.
