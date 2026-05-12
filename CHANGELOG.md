# Gyza — session changelog

> Per-session narratives, **newest first**. Was §5 of CLAUDE.md
> through Session 25; extracted to a standalone file in Session 26
> so CLAUDE.md stays focused on active reference. Operational
> trip-wires from each session live in CLAUDE.md §4; durable
> decisions live in `docs/adr/`.
>
> Session ordering: recent sessions (20+) keep full detail because
> they're operationally fresh. Older sessions (8.5 → 19) are
> compressed to one paragraph plus cross-references to the ADR /
> trip-wire / don't-do entries that capture the durable lessons.

---

## Session 26 — CLAUDE.md restructure + CHANGELOG split

**Strategic-decision session.** Restructured CLAUDE.md per the
12-suggestion audit raised at session start:

- Session narratives extracted to this `CHANGELOG.md` (§5 of
  CLAUDE.md becomes a one-line index + pointer here).
- New "Quick start for fresh Claude" section at the top of
  CLAUDE.md.
- §11 consolidated as the single "what only the user can do" view.
- §6 priority list updated to reflect Session 25 state (Rust Stream
  3 accelerating; TLA+ progressing slowly; B-bucket mostly stalled).
- Trip-wires (§4 in new numbering) split into three categories:
  lint/tooling false positives, real operational gotchas, resolved.
- Architecture map unified into a single tree with v1↔v2 interop
  matrix.
- §7 (critique) folded into §8 (vNext) as the "necessity argument"
  prefix.
- Old session narratives (8.5 → 19) compressed to one-paragraph
  summaries with cross-refs.
- Don't-do list recategorized into Never / Surface-to-user /
  Resolved.
- Section freshness indicators (`[updated SN]`) added.

Net CLAUDE.md size: ~3500 lines → ~1500 lines. Information
preserved in CHANGELOG.md, ADRs, and the operational sections.

No code changes. Engineering velocity unaffected; next session
resumes Rust Stream 3 work (`gyza-settlement` is the natural next
target).

---

## Sessions 23–25 — Rust Stream 3 sweep (verify_chain + gyza-core + gyza-blackboard)

Three consecutive Phase 0 Stream 3 sessions. Each committed
separately (`42ace1f`, `662452e`, `4a00284`) but narrated together
because they share a coherent target: complete the Rust substrate's
data + provenance + storage layer.

**Session 23 — `verify_chain` in gyza-icp.** Adds chain
verification walking parent_envelope_hash links. Per-hop checks:
(1) agent_pubkey decodes + signature verifies, (2) parent hash
matches BLAKE3 of prior envelope (None for root), (3) input_hashes
non-empty. `ChainVerificationError` carries the first failing
index — matches Python's `(False, first_bad_index)` semantics in a
structured form. 8 new tests including the §INV-ICP-5 "injection
breaks chain" proof.

**Session 24 — `gyza-core`.** Ports `gyza/schema.py`. Three types:
WorkItem (with `new_validated` constructor enforcing embedding
length / reward range / tier range), Artifact (serializable), and
Hlc (Kulkarni 2014 hybrid logical clock). The HLC is the notable
one — internal `Mutex<HlcState>` makes `now()` and `recv()`
atomic; a stress test with 8 threads × 1000 calls validates the
§INV-X-5 uniqueness invariant (8000 distinct HlcTuples produced
under shared-clock contention). 10 tests.

**Session 25 — `gyza-blackboard`.** Ports the core surface of
`gyza/blackboard.py`. SQLite via rusqlite (bundled feature — no
system sqlite dep). Three tables: `human_intents`, `work_items`,
`icp_envelopes`. Operations: `open[+in_memory]`, `post_intent`,
`post_work_item`, `claim_work_item` (atomic via `WHERE claimed_by
IS NULL`), `complete_work_item`, `get_unclaimed` (reward + tier +
TTL filter, reward DESC ordering), `store_envelope` (idempotent
`INSERT OR IGNORE`), `get_envelope`, `reconstruct_chain` (walks
parent links root-first). Embedding blob encoding matches Python's
`np.ndarray.tobytes()` for float32 LE. 12 tests including atomic
claim race semantics and embedding roundtrip preservation.

**Stream 3 cumulative status after Session 25:**

| Crate | Lines | Tests | Notable |
|---|---|---|---|
| gyza-crypto | ~280 | 6 | 4 Python-parity assertions |
| gyza-identity | ~210 | 7 | 4 parity tests |
| gyza-icp | ~650 | 16 | 3 parity + 8 chain tests |
| gyza-core | ~480 | 10 | concurrent-HLC uniqueness |
| gyza-blackboard | ~580 | 12 | real SQLite via rusqlite-bundled |

**Total: 51 tests across 5 crates, all green.** The Rust substrate
now has a complete data + provenance + storage layer that a vNext
runner can stand on. v1↔v2 schema compatibility achieved
(blackboard schema matches Python).

**Trip-wires surfaced:**
- `serde_json::Error` doesn't implement Eq/PartialEq; embed as
  String message in error enums.
- Clippy `doc-overindented-list-items` requires exact 4-space
  continuation indent for list items in doc comments.
- `use gyza_icp::{X, Y, Z};` where X is only used in tests
  triggers `unused_imports`; move to test-module imports.
- rusqlite without `bundled` requires system sqlite3; bundled
  takes ~15s longer to compile but produces portable binaries.

**What's NOT yet ported (remaining Stream 3):**
- `gyza-settlement` — implement directly from `Settlement.tla`.
  The §C1 spec↔Rust pairing.
- `gyza-blackboard` artifacts + artifact_files tables.
- `gyza-blackboard` idempotent variants (`post_intent_direct`, etc.).
- `gyza-capability` — Tier-3 challenge-response.
- gRPC layer to talk to a Rust-written daemon.

**Strategic significance.** First session series where the Rust
port could plausibly run end-to-end agent code without Python.

---

## Session 22 — gyza-icp port (canonical-JSON byte parity)

Continued Phase 0 Stream 3. Ported the ICP envelope module with
canonical-JSON serialization producing **byte-identical output to
Python's `json.dumps(d, sort_keys=True, separators=(",", ":"))`**.

**The byte-parity proof.** For a fixed envelope, Python and Rust
both produce the same canonical bytes, the same BLAKE3 hash
(`2b69bb3a...662d40`), and the same Ed25519 signature
(`6e7900cb...cc30e`). The Rust port can sign envelopes that Python
verifies; Python can sign envelopes Rust verifies.

**Deliverables:**
- `gyza-rs/gyza-icp/` crate. `EnvelopePayload` struct with
  **fields listed in alphabetical order** (load-bearing —
  serde_json emits in declaration order; alphabetizing gives
  sort_keys-equivalent canonical bytes).
- `SignedEnvelope = EnvelopePayload + signature` via `#[serde(flatten)]`.
- `canonical_bytes / envelope_hash / sign_envelope /
  verify_envelope / verify_envelope_self`.
- Sign-the-hash discipline: signature covers
  `BLAKE3(canonical_bytes)`, NOT canonical_bytes directly.
- `gyza-rs/scripts/regenerate_icp_fixtures.py` — fixture generator.

**Architectural choices:**
- Alphabetized struct field order is locked in. DO NOT REORDER.
- `Option<String>` for `parent_envelope_hash` serializes None as
  `null`, matching Python.
- `verify_envelope` takes explicit pubkey;
  `verify_envelope_self` derives from `agent_pubkey` field.
- ASCII-only invariant documented (Python `ensure_ascii=True` vs.
  Rust default UTF-8 are byte-identical only for ASCII content;
  all current ICP fields are ASCII).

**Trip-wires:**
- Don't paste parity fixtures from imagination. Always run the
  Python fixture script first.
- `derive_seed`'s pipe separator (`b"|"`) is between context and
  info, NOT around them.

---

## Session 21 — Phase 0 Stream 3 kickoff (Rust scaffold + first 2 crates)

The actual vNext code begins. After 5 sessions of strategic +
documentation + infrastructure work, this lands the first Rust
crates with byte-for-byte Python parity.

**Deliverables:**
- `gyza-rs/Cargo.toml` — workspace root, Rust 2024 edition,
  resolver 3, Rust 1.93+.
- `gyza-rs/MIGRATION.md` — porting strategy: bottom-up order,
  parity-test discipline, deprecation workflow.
- `gyza-rs/scripts/regenerate_crypto_fixtures.py` — Python
  fixture generator.
- `gyza-rs/gyza-crypto/` — Ed25519 + BLAKE3 + key derivation.
  Public surface: `hash`, `derive_seed`, `Signer`, `verify`. 6
  tests including 4 Python-parity asserts.
- `gyza-rs/gyza-identity/` — `LocalCompositor` + `AgentIdentity`.
  `CTX_COMPOSITOR_SEED` / `CTX_AGENT_SEED` protocol constants. 7
  tests including 4 parity asserts.
- `.github/workflows/ci.yml` — added `rust` job (cargo fmt /
  clippy / build / test).
- `.gitignore` — `gyza-rs/target/`.

**Parity proof:** For a fixed test master seed, Rust produces
byte-identical output to Python for `blake3('')`, `blake3([0])`,
compositor seed, agent seed, compositor pubkey, compositor
signature of `"hello gyza"`, agent pubkey, agent signature. All
asserted in the test module.

**Trip-wires surfaced:**
- Always generate parity fixtures from Python BEFORE pasting into
  Rust tests. First draft had placeholder hex values that didn't
  match.
- `derive_seed`'s pipe separator is between context and info, NOT
  around them.
- `ed25519-dalek::Signer` trait clashes with the local `Signer`
  struct name; use `use ed25519_dalek::Signer as _` for trait-only
  imports.
- Workspace `description` field doesn't inherit via
  `description.workspace = true` in Rust 1.93; declare per-crate.

---

## Session 20 — Phase 0 mixed-stream (ADR log + CI)

Mixed-stream Phase 0 session per the Session 19 strategic decision
("Phase 0 has four streams; TLA+ alone was leaving three stalled").
Lands two of the unaddressed streams: ADR log (Stream 4) and CI
(B-bucket B3).

**Deliverables:**
- `docs/adr/` directory with 15 retroactive ADRs documenting
  Phase 1 → Session 17 decisions (ADR-0001 through ADR-0015).
- `docs/adr/README.md` — ADR format, index, maintenance rules.
- `.github/workflows/ci.yml` — fast CI on push/PR. Three parallel
  jobs: Go test suite (~5s), Python fast slice (~10min), TLC
  Settlement.tla validation (~30s). Concurrency block cancels
  stale runs. Caches pip + HF models.
- `.github/workflows/integration.yml` — nightly + on-touch heavy
  integration: real-daemon multi-host tests + demo-of-record.
  Schedule: 04:00 UTC daily.

**ADR conventions:** 4-digit zero-padded IDs starting at ADR-0001.
Sections: Status, Context, Decision, Consequences, Alternatives
considered, References. Required for cross-module / wire-format /
crypto / strategic-commitment decisions.

**CI design choices:** Two-tier (fast every push, heavy nightly).
Caching for pip + HuggingFace models. `concurrency` block cancels
in-progress runs on new pushes. TLC step model-checks
`Settlement.tla` in ~25s.

**Trip-wires:**
- CI uses bare `python` (from `actions/setup-python`); local dev
  uses `~/dev/marshal/.os/bin/python`. `requirements.txt` is the
  bridge.
- First CI run on fresh checkout is ~15min due to HF model
  download; cached runs ~10min.
- Heavy integration requires the daemon binary, so `make -C netd
  build` is gating.
- ADR IDs are stable; don't renumber.

---

## Session 19 — first §C1 sub-spec (Settlement.tla)

First TLA+ behavioral spec under the vNext commitment. Formalizes
the bilateral settlement protocol from `gyza/economy/settlement.py`
and validates six safety invariants via the TLC model checker.

**Deliverables:**
- `spec/Settlement.tla` (~600 lines) — TLA+ behavioral spec:
  state machine, 4 dispute paths, adversarial submit action,
  6 safety invariants (INV-SETTLE-1..6 from `docs/invariants.md`).
- `spec/Settlement.cfg` — honest-only TLC config. Passes in 25s,
  1.2M states / 495K distinct, depth 9.
- `spec/Settlement_adversarial.cfg` — tight-bounds adversarial
  config (`MalleableSigs=TRUE`, 2 peers / 1 envelope / 1 entry).
  Passes in 40s, 5M states / 828K distinct, depth 22.
- `spec/Settlement_invariants.md` — TLA+-predicate-to-INV-SETTLE-N
  mapping with per-invariant soundness arguments.
- `spec/README.md` — how-to-run, scope, maintenance workflow.
- `spec/tools/tla2tools.jar` (2.2 MB) — official TLA+ release.

**Real bug TLC caught:** Original INV-SETTLE-5 was too strong
("if either side applied, both must be applied"). TLC found the
transient-gap counterexample in <5 seconds. Weakened to "when
BOTH sides applied, fields agree"; the stronger property is
liveness, not safety.

**Trip-wires:**
- `EXTENDS Integers` required for negative-int reputation.
- TypeOK can't enumerate partial-function types; assert structural
  well-formedness per-element.
- Adversarial state space explodes; tight bounds for fast checks,
  larger bounds need hours of compute.
- Bracket-counting in nested TLA+ record literals is fragile.

---

## Session 18 — pre-spec artifacts for §C1

Three documentation artifacts in service of §C1 (TLA+ formal
protocol specification). No code changes; pure documentation.

**Deliverables:**
- `docs/invariants.md` (~120 invariants by stable `INV-X-N` ID
  across 16 sections + 2 appendices).
- `docs/state-machines.md` (10 state machines: WorkItem,
  Settlement entry, Attestation cert, Agent runner, DHT records,
  Capability challenge, RequestAttestation bridge, Verifier cache,
  RecursiveVerifier in-call state, HLC ratchet).
- `docs/wire-protocol.md` — consolidated wire-format reference:
  identity, three canonical-bytes routines (canonical JSON,
  deterministic protobuf, BLAKE3), 7 gRPC services, 2 libp2p
  stream protocols, gossipsub topics, message-bus types, 3 DHT
  namespaces, LSH params, cross-language compat matrix.

Estimated §C1 cycle saving: ~12 weeks → ~6 weeks via
translate-not-discover from the structured docs.

**Trip-wires:**
- Three distinct canonical-bytes routines (canonical JSON /
  deterministic protobuf / BLAKE3) — not interchangeable.
- Stable invariant ID convention — never renumber.
- Some invariants are protocol-level not runtime-checked
  (load-bearing for §C2 proofs).

---

## Session 17 — vNext architectural commitment + CLAUDE.md restructure

Strategic-decision session. No new code. The architectural target
for every future session is now binding: the vNext architecture
(CLAUDE.md §8) is committed, not sketched.

**What this means concretely for sessions going forward:**
1. §C1 (TLA+ spec) is the immediate top priority.
2. Phase 3 hardening continues; Phase 4–9 feature work pauses.
3. Wire formats from this point forward are forward-compatible.
4. "Retrofit" reframed as "migration milestone."
5. Strategic decisions in §13 are partially settled by §8
   (multi-token, encrypted-by-default privacy, formal-spec
   discipline, Rust core).

CLAUDE.md restructured: top-of-file commitment header, §1 vNext
commitment paragraph, §6 reordered as binding roadmap, §7 reframed
from neutral critique to diagnosis-justifying-commitment, §8 fully
rewritten as committed substrate with necessity-argument table +
14-layer architecture + Design surface remaining + Costs accepted
+ Binding execution plan + Migration mechanics +
Parallel-vs-sequential decision, §10 reframed as built-on-vNext,
§13 partial settlement noted, §16 commitment-protection don't-dos
added.

Captured as ADR-0015.

---

## Session 16 — #21f follow-ups (A1 + A2)

Closes two acknowledged trip-wires from Session 15's #21f closeout.

**A1 — DHT TTL bounding on PublishAttestation.**
- `MinPublishAttestationLifetime = 24h` floor in
  `PublishAttestation` rejects near-expired certs.
- `gyzaValidator.Validate` rejects expired AttestationCert records
  past `expires_at_ns + 5min grace` at both PutValue/GetValue.
- Three-layer defense: publish floor + validator-side rejection +
  Session 15's 1h consumer-side slack.

**A2 — Recursive Tier-3 verification (library only).**
- New `netd/internal/capability/recursive.go::RecursiveVerifier`:
  trusted-bootstrap base case, cycle detection, depth bound (5),
  positive-only cache, substitution defense (fetched cert's
  `ApplicantPubkey` MUST equal queried pubkey).
- 11 unit tests covering all guard mechanisms.
- Integration into `DHTAttestationVerifier` deferred; blocked on
  configured bootstrap set (deployment-side).

Captured as ADR-0014. Test count: +14 Go (3 dht A1 + 11
capability A2). Two existing tests bumped from 24h to 48h cert
lifetime.

---

## Session 15 — verify-on-fetch in `find_agents` (#21f)

Closes #21f end-to-end. Sessions 11–14 made it possible to *earn*
and *publish* a Tier-3 cert; until this session, consumers still
trusted the self-reported `attestation_tier` field. Now the
daemon enforces verification at routing time.

**Deliverables:**
- `netd/internal/dht/verifier.go` — `AttestationVerifier` interface
  + `DHTAttestationVerifier` (TTL-cached positive/negative,
  single-flight per pubkey, 16-slot semaphore, 250ms per-fetch
  timeout, 1h near-expiry slack window).
- Wired into `GyzaDHT.FindAgents` for `min_tier >= IssuedTier`.
- New `--dht-mode auto|server|client` daemon flag (required
  for multi-daemon integration tests on loopback — ModeAuto never
  promotes without AutoNAT).
- `start_daemon(dht_mode=...)` kwarg in Python `NetdClient`.
- 13 new Go tests (10 verifier unit + 3 FindAgents integration) +
  1 Python integration test (`test_verify_on_fetch.py`).

Captured as ADR-0013.

**Trip-wires:**
- `kaddht.ModeAuto` stays Client mode on loopback meshes — tests
  must set `dht_mode="server"`.
- Verifier keys by `compositor_pubkey`, NOT `agent_pubkey`.
- Transient failures NOT cached; only positive + definitive
  negative are.

---

## Sessions 8.5 → 14 — compressed summaries

Each session below closed specific priority items. Durable lessons
captured in ADRs (`docs/adr/`), trip-wires (CLAUDE.md §4), and
don't-do entries (CLAUDE.md §16). Compressed here.

**Session 14 — Tier-3 quorum attestation + DHT publication
(#21d + #21e).** Closed the algorithmic core of the #21 cluster.
**Load-bearing fix:** Go validator's `VerifyResponse` had been
authoring its own `AttestationBody` per call, producing
non-aggregatable cosigs across validators. Fixed by adding
`proposed_attestation_body` field to `ChallengeResponse` —
applicant proposes one body; every validator signs the same
bytes. 6 plausibility checks on the proposed body
(`verifyProposedAttestationBody`). `request_tier3_attestation`
orchestrator in `attestation_adapter.py`. `gyza global attest
--tier 3` CLI. Captured as ADR-0012.

**Session 13 — Python applicant adapter (#21-bridge).**
Python-initiated bidirectional streaming gRPC on
`CapabilityService.RequestAttestation`. Three frames each
direction, mirroring the libp2p protocol. Validator-side
relaxation: `verifyTaskResult` no longer requires `agent_pubkey
== applicant_pubkey` (ICP envelopes signed by AGENT keys; response
body signed by COMPOSITOR; agent↔compositor binding via
capability manifest is a future follow-up). Captured as ADR-0011.

**Session 12 — libp2p stream protocol (#21c).** New package
`netd/internal/capability_stream/`. Protocol
`/gyza/capability-challenge/1.0.0`. Three frames per stream,
each `[uvarint_len][marshaled_proto]`. Validator extracts
applicant pubkey from libp2p `RemotePeer` (Noise-authenticated).
StreamTimeout = 120s. **Architectural decision:** Go protobuf +
deterministic marshal IS the canonical wire format for
cross-network; Python's JSON path stays for in-process Tier-1
only. Captured as ADR-0010.

**Session 11 — capability eval suite + cross-network
orchestration (#21a + #21b).** Six structurally-verifiable eval
tasks in `gyza/capability_eval.py`. Replay defense: each prompt
embeds `[GYZA_EVAL_TASK={id} NONCE={nonce}]`; mock executor uses
`prompt.rfind` (not `find`) because `build_enriched_prompt`
prepends few-shot context with prior tasks' markers verbatim.
`gyza/network/capability_protocol.py` for in-process Tier-1
orchestration. `gyza global attest --tier 1` CLI. Threat model
defended in-protocol (replay across validators,
cosig-transplant, stale cert, duplicate-cosig padding, 1
malicious validator); NOT defended (sybil applicant + sybil
validators, validator-not-actually-Tier-3, >k/n malicious).
Captured as ADR-0009.

**Session 10 — peer cache, daemon supervisor, executor
sandbox (#22 + #24).** `PeerCache` with JSON-persisted
`~/.gyza/peers.json` (atomic write via tempfile + os.replace).
`DaemonSupervisor` with 5s heartbeat + exponential backoff
respawn. `gyza/sandbox/` with bwrap-based executor isolation
(fresh net namespace default, RLIMIT_AS/CPU, --clearenv).
**Critical trip-wire:** `/lib64` is a symlink on merged-/usr
distros; binding as `--ro-bind` breaks the dynamic linker — use
`--symlink`. **Production wiring NOT done**: demo/tests still use
unsandboxed executors. Captured as ADR-0008.

**Session 9 — observability + reconciliation (#25 + #26).**
Prometheus + structlog. 5 counters / 2 histograms / 4 gauges via
default registry. Settlement latency carrier with map-purge on
observation. Bilateral ledger reconciliation RPC. Lex-cursor
pagination `(since_timestamp_ns, since_entry_id)` — single-ns
cursor would skip entries sharing `created_at_ns`. Threat-model
defenses: for-peer guard, cross-peer injection guard, page cap
(max_pages=50), server-side max page size (2000). Reputation
policy: `disputed → record_dispute` per entry; `missing_theirs /
missing_ours → NO reputation change` (could be benign).

**Session 8.5 — five priority gaps closed (#19, #20, #23, #27, #28).**
Real semantic embeddings (sentence-transformers
all-MiniLM-L6-v2). Runtime ICP chain verification (icp_envelopes
table; runner persists every signed envelope; chain verified
pre-claim). Self-organization spawn loop (`AgentSupervisor` polls
`DemandOracle`; spawn via user-provided factory). HLC
thread-safety (mutex-guarded now/recv); cross-cluster ratchet
(runner accepts `hlc=` kwarg). Reputation feedback loop (EWMA,
SQLite-persisted; wired into runner + settlement).

---

## Earlier sessions (pre-8.5)

Phase 1 (single-node) and Phase 2 (LAN cluster via Raft) work.
Foundational: `gyza/blackboard.py`, `gyza/icp.py`,
`gyza/runner.py`, `gyza/identity.py`, `gyza/economy/ledger.py`.
Captured as ADR-0001 through ADR-0007.

For the precise per-session detail of these earlier phases,
consult `git log --oneline -30` and the relevant ADRs:

- ADR-0001 (Python+Go split via gRPC)
- ADR-0002 (Ed25519 + BLAKE3 primitives)
- ADR-0003 (384-dim embeddings + LSH)
- ADR-0004 (Bilateral compute-credit settlement)
- ADR-0005 (Linear ICP envelope chains)
- ADR-0006 (Blackboard coordination pattern)
- ADR-0007 (Kademlia DHT under `/gyza/1.0`)
