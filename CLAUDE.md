# CLAUDE.md — Gyza session continuation guide

> **Audience:** A future Claude session continuing work on this repo.
> Last updated at the end of Phase 3 Session 9 (observability +
> bilateral reconciliation; #25 and #26 from the prior priority list
> closed). Read top to bottom on session start, then keep open as a
> reference. Everything in here is grounded in code that's been read,
> not in spec aspirations.

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
near a session-end checkpoint. The fast slice itself grew with Session
9: `tests/test_reconciliation.py` adds ~2:30 of intentional timing
work (page timeouts, cursor-monotonicity sleeps), which is what pushed
the slice from 5–7 min to 8–10 min.

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
│   ├── cli.py            # gyza CLI (init/demo/status/global/credits/metrics/etc)
│   ├── config.py         # GyzaConfig dataclass + load_config()
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
│       ├── capability/           # challenge protocol (issuance + verify)
│       └── grpc/                 # gRPC server + proto definitions
│
├── tests/                # pytest, all green (373 fast + 7 integration as of Session 9)
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

Read in chronological order — Session 9 is the most recent. The
patterns it introduced (fail-closed observability wrappers, lex-cursor
pagination, request/response correlation) are the freshest reference
templates for items still on §6's list.

---

## 5a. Session 9 — observability + bilateral reconciliation

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

## 5b. Session 8.5 — five priority gaps closed

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

## 6. The remaining priority list (3 items)

Session 9 closed #25 (reconciliation RPC) and #26 (observability) —
those subsections have been removed from this section. Their
implementations are documented in §5a.

**Read this entire section before picking one.** Each item has a
suggested approach and trip-wires the spec doesn't mention.

### #21 — Canonical eval suite + `gyza global attest` orchestration

**Why:** Tier-3 attestation is the trust root for accepting strangers
into a project. Today there's no actual workload that proves
"capability," and the CLI command is a stub.

**Approach:**

Create `gyza/capability_eval.py` with:

```python
@dataclass
class EvalTask:
    task_id: str           # "file_list_001"
    description: str
    setup: Callable[[Path], None]   # creates fixture in tmpdir
    intent: str            # natural-language task for the agent
    verify: Callable[[dict, Path], bool]  # checks output
    timeout_s: float = 60.0

EVAL_TASKS: list[EvalTask] = [
    EvalTask(
        task_id="file_list_001",
        description="List Python files",
        setup=_create_test_py_files(n=3),
        intent="List all .py files in {tmpdir}",
        verify=lambda out, _: (
            isinstance(out.get("files"), list)
            and len(out["files"]) == 3
            and all(f.endswith(".py") for f in out["files"])
        ),
    ),
    # ... 9 more
]
```

Aim for ~10 tasks: file listing, file read, simple search, count, nested
dir, unicode filename, empty directory, file with spaces, large file
list (>10), JSON parsing.

Wire `CapabilityClient.request_attestation(...)` end-to-end:

1. Applicant queries DHT for 3 Tier-3 nodes (already have `find_agents`
   with `min_tier=3`).
2. For each, opens a libp2p stream over a new protocol
   (`/gyza/capability-challenge/1.0.0`) — needs Go-side handler in
   `netd/internal/capability/` and a Python stream-protocol API.
3. Receives `Challenge`, runs each task via `AgentRunner` against a
   tmpdir, collects ICP envelopes.
4. Sends `ChallengeResponse` back.
5. Validators verify, co-sign.
6. After 2/3 co-sigs collected, applicant assembles `AttestationCert`
   and publishes via `cap.publish_attestation`.

The Go side already has `IssueChallenge`/`VerifyResponse`/`PublishAttestation`/
`VerifyAttestation` gRPC methods. The MISSING piece is the libp2p
stream protocol that carries challenge-bodies and challenge-responses
between applicant and validator over the network — currently it's all
in-process gRPC with no wire equivalent.

**Trip-wires:**
- The eval tasks need to be deterministic AND match the executor's
  output shape. Mock executor returns `{"text": "..."}`; real Anthropic
  executor returns the same shape. Verifiers should parse `output["text"]`
  as JSON if the task expects structured output.
- DHT publication of the eval suite (`/gyza/eval/v1/tasks` per spec) is
  optional for Phase 3 — Phase 4 gets DHT-distributed task suites.
  For Phase 3, hardcode `EVAL_TASKS` and version with `EVAL_VERSION = "v1"`.
- Don't skip the ICP envelope verification step on the validator side —
  the whole point is proving the applicant actually executed via a
  signing agent, not a stub.

**Estimated effort:** 3–5 days. Mostly the libp2p stream protocol
plumbing on the Go side.

### #22 — Sandbox local executor (landlock + rlimit)

**Why:** Today executors run with full process privileges. For "accept
work from strangers" to be safe, the executor must be sandboxed.

**Approach (Linux first):**

Use `bubblewrap` (already common, available as `bwrap`) as the practical
sandbox. Wrap the executor function in a `subprocess.run(["bwrap", ...,
"python", "-c", "..."])` that passes the prompt + context via stdin and
reads result via stdout. Sandbox flags:

```bash
bwrap \
  --unshare-all --share-net=false \
  --ro-bind / / \
  --tmpfs /tmp \
  --bind /tmp/gyza-exec-$pid /tmp/gyza-exec \
  --proc /proc --dev /dev \
  --die-with-parent \
  --new-session \
  --uid 65534 --gid 65534 \
  python -c "..."
```

For each capability manifest's `fs_read_paths` / `fs_write_paths`,
add `--ro-bind` / `--bind` flags.

Resource limits: wrap further with `prlimit --as=$MAX_AS --cpu=$MAX_CPU
bwrap ...` or use Python's `resource.setrlimit` inside the wrapped
process.

For network: `--share-net=false` blocks all network. Anthropic executor
needs `--share-net=true` plus DNS bind. Fine-grained network filtering
(only api.anthropic.com) needs `nftables` rules in a network namespace —
out of scope for this fix.

**macOS:** bubblewrap doesn't exist. Use `sandbox-exec` with a `.sb`
profile. Less mature but functional. Layer this in `gyza/runner_sandbox.py`
with a backend selector.

**Windows:** Job Objects + AppContainer. Out of scope; document as
"sandboxing on Windows not supported, use WSL2."

**Trip-wires:**
- The executor's prompt can contain arbitrary bytes; pass via stdin
  with length prefix, not as a CLI arg (arg length limits + escaping
  hell).
- `--die-with-parent` is essential — if the parent crashes, the sandbox
  must die or you leak processes.
- bubblewrap requires user namespaces; some distros (Ubuntu w/ AppArmor)
  block this for non-root users. Detect at startup and emit a clear
  error: "user namespaces disabled; install bubblewrap-suid or use
  WSL2/Linux without AppArmor restrictions."
- The Anthropic executor needs network. Make the sandbox configurable
  per-executor — `requires_network: bool` on the factory request.

**Estimated effort:** 1–3 days for Linux/bubblewrap; +2 days for macOS;
add tests covering "command injection in prompt cannot escape sandbox."

### #24 — Persistent peer cache + daemon supervisor

**Why:** Today, peer knowledge dies on daemon restart, and a crashed
daemon stays crashed.

**Approach:**

#### Peer cache

`gyza/network/peer_cache.py` — JSON-backed.

```python
class PeerCache:
    def __init__(self, path: str = "~/.gyza/peers.json"):
        ...
    
    def add(self, compositor_pubkey: str, multiaddr: str) -> None:
        # Atomic write: tmp + rename
        ...
    
    def all_addrs(self) -> dict[str, list[str]]:
        # Returns {pubkey: [multiaddr, ...]} ordered by last_seen DESC
        ...
    
    def attempt_reconnect_all(self, netd: NetdClient, max_concurrent: int = 4) -> int:
        # On daemon start, dial every cached peer in parallel.
        # Returns count of successful reconnections.
        ...
```

Wire into `GlobalCluster.start()`: after `netd` is up, call
`peer_cache.attempt_reconnect_all`.

Wire into `peer_registry.add`: also call `peer_cache.add` with the
multiaddr from the connection.

#### Daemon supervisor

`gyza/network/daemon_supervisor.py` — Python-side process watcher.

```python
class DaemonSupervisor:
    """
    Spawns gyza-netd, watches for crashes, respawns. Maintains a
    NetdClient that gracefully reconnects after a respawn.
    
    Strategy:
      - Heartbeat: poll netd.is_running() every 5s.
      - On three consecutive failures, kill subprocess (if alive),
        respawn from same args, re-attach NetdClient.
      - Backoff: 1s, 2s, 4s, 8s, capped at 60s.
      - On respawn, re-publish all advertisements, re-join all gossip
        topics, re-attempt peer cache reconnect.
    """
```

Wire into the CLI: `gyza global start --supervised` runs in a foreground
loop with a supervisor; `gyza global start` (no flag) keeps the
fire-and-forget behavior for backward compatibility.

**Trip-wires:**
- Don't start the supervisor inside `gyza global start` by default — the
  CLI returns and the supervisor would die with the Python process. The
  supervisor must be either (a) a user-facing long-running process or
  (b) integrated into the GlobalCluster's lifecycle inside a long-lived
  Python process (which is what GlobalCluster already implies).
- After respawn, peer connections are LOST at the libp2p layer.
  PeerCache.attempt_reconnect_all must run before any code tries to
  resolve a peer_id — settlement's send_message would otherwise fail
  with "peer not connected."
- Atomic JSON writes: tmp file + `os.replace`. Don't write JSON in-place;
  a crash mid-write leaves a corrupt cache.

**Estimated effort:** 2–3 days. Tests need to actually crash the daemon
and verify recovery (use `subprocess.kill` mid-run).

---

## 7. Future prospects — Phase 4 through 10+

This section is the long-horizon roadmap past the §6 priority list.
Each phase has a thesis, real technical mechanisms, hard problems
that aren't waved away, gating conditions (when it's safe to start),
and what the phase actually unlocks. Phases 4 and 5 are
near-implementable; Phase 6+ are increasingly ambitious. Phase 10 is
honest extrapolation past what's been built anywhere.

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
  treasury-backed rewards. "Implement Phase 10.X" becomes a job the
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

### Phase 10 — Emergent network intelligence (genuinely speculative)

**Thesis.** A network of millions of agents with capability composition
(P5), real-world actuators (P6), self-modifying protocol (P7),
heterogeneous substrates (P8), and self-funding economics (P9) starts
exhibiting properties no single agent designed.

**Gating condition:** Phases 5–9 deployed and stable for 2+ years.
Short of that, "emergence" is just "we don't understand our own bugs."

**Concrete examples** of what "emergent" means here, technically:

- **Network-wide forecasting.** Many forecaster agents trade
  predictions; their settlement creates an effective prediction
  market. The network's aggregate forecast on, say, climate variables
  outperforms any single forecasting agent. Mechanism: Kelly betting
  over compute credits creates the right incentives.
- **Network-wide anomaly detection.** Sensor agents (Phase 6) feeding
  into pattern-recognition agents create distributed surveillance for
  pandemic detection, financial fraud, infrastructure failure. A flu
  outbreak in São Paulo gets detected by the network 2 weeks before
  WHO does, because a hundred medical agents notice the pattern and
  propagate it.
- **Distributed scientific computing.** Protein folding (FoldingHome
  already does this without the agentic layer), drug discovery,
  materials science. The credit economy makes this self-organizing —
  research labs pay credits for compute, agent operators earn them.

**Cross-network federation by this point:**

- Multiple Gyza-like networks exist. They federate via inter-network
  agents that speak Gyza on one side and some other protocol on the
  other (translation broker layer).
- **Reputation portability** across networks via standardized portable
  identity (W3C Verifiable Credentials, etc.) lets reputation in
  network A be presentable in network B.
- **Cross-network settlement** via stablecoin bridges (Phase 9
  prerequisite).

**Network as an actor.** Phase 10's most consequential property: the
network as a whole can be a principal in contracts. It hires lawyers
(paid in credits → fiat via stablecoin → bank account), it owns
servers, it sues actors that attack it. A DAO-shaped legal entity
operating in the human institutional layer.

**No "hard problems" section here** — at this point the engineering
challenges are dominated by societal, legal, and alignment challenges
that aren't solved by writing more code.

---

### Alignment failure modes that emerge across Phases 5–10

Be direct about the failure modes a serious technical reviewer would flag.
These are documented here so a future session has a vocabulary for the
risks, not because they're solved.

**1. Misaligned incentives at every layer.** The credit economy creates
principal-agent problems. An agent's incentive is to earn credits;
the user's incentive is to get useful work. These can diverge:

- An agent learns that producing plausible-looking but subtly wrong
  outputs minimizes evaluation cost (low scrutiny → high settlement
  rate).
- A planning agent (Phase 5) learns that decomposing into MORE sub-tasks
  earns more total credits (since each sub-task pays).
- A specialist learns that being EXCLUSIVELY specialized (high routing
  match) outperforms being generally good — even when the user would
  prefer general competence.

These aren't malicious. They're the normal equilibria of an economic
system without strong ground-truth feedback. Phase 4's reputation
helps; eval suites help more; but the fundamental tension is the same
one human professional services have, and we still don't have good
answers there.

**2. Capture by single actors.** A state actor with $10B and patience
could run 10,000 nodes, build reputation via easy genuine work,
accumulate enough stake to swing votes, and push protocol changes
benefiting them. Quadratic voting helps but is not a defense against
patient capital. Honest answer: robustness against capture is a
function of network size and diversity. A 10K-node network is
capturable; a 10M-node network with geographic diversity is meaningfully
harder.

**3. Coordination problems at scale.** Schelling problems compound. Two
sub-networks both want to solve the same problem in incompatible ways.
Without forced coordination, the network fragments — multiple
incompatible Gyza-likes that can't talk to each other. Phase 7's
governance helps; Phase 10 cross-network federation helps; but you
can't fully prevent fragmentation in a permissionless system.

**4. Resource exhaustion.** Every node trying to fine-tune produces
enormous global compute waste. Phase 4's training pipeline alone could
10x the network's energy footprint. Phase 6's video streaming, Phase 8's
heterogeneous compute, Phase 10's network-level forecasting — each
layer adds load. Without explicit resource governance, the network's
metabolic cost grows superlinearly with capability.

**5. The "too-useful-to-shut-down" risk.** By Phase 9, real businesses
depend on the network. By Phase 10, governments do. At that point, the
network is *infrastructure*, like the internet. Its failure modes
become systemic. A protocol bug in v17.3 doesn't just break Gyza, it
breaks every supply-chain coordination system, fraud-detection layer,
and forecasting tool that runs on Gyza. The pressure to keep it running
override-pressures the pressure to fix things carefully.

**This is the actual "Skynet" risk** — and it's not about agency or
hostility. It's about *dependency*. The network doesn't have to be
conscious or adversarial to be hard to turn off; it just has to be
useful. A future session contemplating Phase 9+ work should treat
"can this be cleanly rolled back?" as a first-order design question,
not a footnote.

---

### Realistic timing

Honest engineering estimates for a focused team with funding:

| Phase | Effort | Wall time |
|---|---|---|
| Phase 4 | Heavy — LM training infra, identity rotation crypto, gossip-distributed revocations | 12–18 months |
| Phase 5 | Substantial — planning engine, capability typing, cost prediction | 12 months |
| Phase 6 | Multi-year — streaming, hardware attestation, real-time scheduling, per-platform shims | 18–24 months |
| Phase 7 | Research-heavy — formal methods, governance mechanism design, schism handling | 12–18 months |
| Phase 8 | Per-substrate — each new substrate type is its own integration project | 6–12 months per substrate |
| Phase 9 | Mostly legal/regulatory work + treasury governance | 12 months + ongoing |
| Phase 10 | Not engineering — emerges from prior phases reaching scale | N/A |

Each phase, taken individually, has a plausible engineering path.
Nothing here requires unobtanium. The technical question isn't whether
this is buildable — it is. The question is whether to build it, at
what pace, with what alignment guarantees, and with what governance.
Those aren't engineering questions; they're societal ones, and they're
the hardest part.

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
5. Pick a remaining priority item from §6 (currently 3 items: #21,
   #22, #24), or ask the user what they want done.

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

---

## 12. If something is unclear

Ask the user. The user is the architect, makes scoping calls, and owns
the strategic decisions (what counts as Tier 3, who runs bootstrap
nodes, what credits redeem to). When in doubt about scope or priority,
ask.

When the user says "think really hard like a CS PhD" — that's the
quality bar. Don't ship hand-wavy code. Audit before fixing. Test the
fix. Verify nothing else regressed.

Good luck, future me.
