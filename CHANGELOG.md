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

## Session 30 — MVP-1: DNS-anchored bootstrap + VPS deploy script

First Linux-only MVP milestone (B1 from §6). Closes the
single-largest deployment trip-wire (`DefaultBootstrapPeers = []`)
and provides repeatable bootstrap node provisioning.

**Deliverables:**

- `netd/internal/bootstrap/` (new Go package, ~250 lines).
  - `Resolve(ctx, resolver, domain, logf)` → `[]peer.AddrInfo`.
    Looks up `_dnsaddr.<domain>` TXT records, parses each
    `dnsaddr=<multiaddr>` entry, merges with hardcoded
    `FallbackPeers`, dedups by `peer.ID`.
  - `ResolveWithExtras(...)` adds user-supplied `--bootstrap`
    entries to the merge.
  - `Resolver` interface for DNS injection (production uses
    `net.DefaultResolver`; tests use a fake).
  - 10 unit tests covering happy path, malformed multiaddrs,
    DNS failure → fallback, dedup, empty-domain, no-sources.
- `netd/cmd/gyza-netd/main.go`:
  - New `--bootstrap-domain` flag (default `gyza.network`).
  - New `--print-peer-id` mode: loads identity, prints peer ID
    to stdout, exits 0. Stdin-clean for deploy-script parsing.
  - `--bootstrap` semantically renamed: now "explicit extras
    merged with DNS set" instead of "the bootstrap list."
- `scripts/deploy-bootstrap.sh`. Idempotent provisioner for a
  fresh Ubuntu 22.04/24.04 VPS:
  - rsyncs source, installs Go 1.23.4, builds gyza-netd into
    /usr/local/bin/
  - Creates `gyza` system user with home `/var/lib/gyza`
  - Generates `compositor.key` if absent (preserves existing on
    re-run); writes 32 bytes from `/dev/urandom`, mode 0600
  - Computes peer ID via `--print-peer-id`
  - Installs systemd unit with `--dht-mode=server
    --enable-relay-service --bootstrap-domain=gyza.network`
  - Opens UDP 7749 in ufw (manual `ufw enable` left to operator)
  - Prints the multiaddr to add to DNS
- `scripts/verify-bootstrap.sh`. Post-deploy sanity check:
  - Queries `_dnsaddr.<domain>` TXT records via dig
  - Parses each `dnsaddr=` entry, extracts IP+port
  - UDP-probes each peer for routability

**Behavior change:** the daemon now does DNS resolution at startup
by default. With the default `--bootstrap-domain=gyza.network` and
no DNS records yet, the resolver logs an NXDOMAIN-style warning
and continues with empty `FallbackPeers`. Production behavior
unchanged when DNS records ARE published.

**Test status:** all 12 Go packages green. `bootstrap` package has
10 new unit tests; full Go suite runs in <10s.

**§6 progress:**
- B1: ✓ daemon-side code shipped. User-side: VPSes + DNS still
  required. Deploy script + verify script make this <30 min of
  operator work per VPS.
- B2 (packaging): NEXT.

---

## Session 29 — `Attestation.tla` sub-spec (§C1 #3) + scope revision

Third §C1 sub-spec. Core cert assembly + cosig verification from
`netd/internal/capability/capability.go`. Targets the
security-critical invariants of the cert format itself.

**Deliverables:**

- `spec/Attestation.tla` (~250 lines).
  - Actions: `HonestCosign`, `AssembleCert`, `AdversarialBadSig`,
    `AdversarialWrongBody`.
  - Six invariants: `INV_ATT_1_MinCoSignatures`,
    `INV_ATT_2_TierFixed`, `INV_ATT_3_LifetimeBound`,
    `INV_ATT_6_DistinctValidators`,
    `INV_ATT_7_AllCosignSameBody`, `INV_ATT_8_BodyPlausible`.
- `spec/Attestation.cfg` — honest model: 3 peers, 1 body,
  MinCoSignatures=2. TLC ~1s, 5 distinct states.
- `spec/Attestation_adversarial.cfg` — MalleableSigs=TRUE,
  2 bodies. TLC ~1s, 80 distinct states.

**Scope revision — §C1 from 6 → 9 sub-specs:**

The original plan listed 6 §C1 sub-specs (Settlement,
Reconciliation, Attestation, Blackboard, DHT, Gossip). During
this session the Attestation surface turned out to need 4 specs
because the protocol layers are genuinely separable and a single
spec covering all of them blew up TLC's state space (we hit
72M+ distinct states with no end in sight before tearing the
spec apart).

The Attestation portion splits into:
- `Attestation.tla` — cert assembly + cosig verification
  (this session, INV-ATT-1..3, 5, 6, 7, 8).
- `CapabilityStream.tla` — wire protocol: challenge/response/nonce
  + libp2p framing + gRPC bridge (INV-ATT-9..14, INV-CAPSTREAM-*,
  INV-CAPBRIDGE-*).
- `AttestationDHT.tla` — DHT publish/fetch + verifier cache
  (INV-ATT-15..22).
- `AttestationRecursive.tla` — TrustedBootstrap + recursive cert
  verification + cycle detection (INV-ATT-23..28).

New total: 9 sub-specs. 3 of 9 shipped.

**What `Attestation.tla` (this sub-spec) does NOT cover:**

- The wire protocol (challenge → response → verify → cosig).
  In real Python+Go, validators issue a Challenge with a nonce,
  the applicant signs a ChallengeResponse over the
  applicant-proposed body, the validator runs plausibility
  checks before emitting the cosig. This spec abstracts all of
  that away — `HonestCosign` produces a cosig directly under
  the assumption that the preceding wire steps succeeded. That
  abstraction is what makes the state space tractable; the
  wire-level guarantees live in `CapabilityStream.tla`.
- The clock. INV-ATT-3 / INV-ATT-8's expiry checks are
  structural in this spec (lifetime bounded); the dynamic
  "cert is fresh AT TIME T" check lives in `AttestationDHT.tla`
  / `AttestationRecursive.tla` where it matters operationally.
- Multiple applicants. We model a single canonical applicant;
  the cert format is symmetric across applicants.

**Lessons from the abandoned full-shape spec:**

The first draft tried to model challenge/response/nonce/clock all
in one spec. At Peers={p1,p2,p3} / Nonces={n1,n2} / MaxClock=3
TLC explored 72M+ distinct states with the queue still growing
at depth 11 after 25 min. Diagnosis: too many existentials in
`ProposeBody` (`iss`, `exp`, `task_set` all enumerated), plus
the wire-message SUBSETs (`challenges`, `responses`, `cosigs`)
growing combinatorially.

Resolution: split the spec along the natural protocol boundary
(cert format vs wire transport). The narrow spec is fast to
model-check and the invariants it does check are the
security-critical ones.

**§C1 progress:** 3 of 9 sub-specs done. Remaining:
CapabilityStream, AttestationDHT, AttestationRecursive,
Blackboard, DHT, Gossip.

---

## Session 28 — `Reconciliation.tla` sub-spec (§C1 #2 of 9)

Second §C1 sub-spec under the Session 17 vNext commitment.
Companion to `Settlement.tla` (S19) — together they cover
the full settlement protocol of `docs/invariants.md` §4.

**Scope.** Formalizes `gyza/economy/settlement.py::_handle_reconcile_*`
plus `request_reconciliation` as a paginated request/response RPC.
Targets INV-SETTLE-8..11 (lex cursor, cross-peer injection guard,
page cap, for_peer guard).

**Deliverables:**

- `spec/Reconciliation.tla` (~430 lines).
  - One state machine: `IssueRequest`, `HandleRequest`,
    `HandleResponse`, plus `Adversarial*` and `Drop*` actions.
  - Faithfully models Python's pop-after-wait pattern: pending
    is removed on every `HandleResponse`; per-pair `sess_cursor`
    + `sess_can_continue` carry session state between pages.
  - Four invariants: `INV_RECON_8_AcceptedFromTrueLedger` (honest
    mode), `INV_RECON_9_AcceptedOnlyFromAllocatedIDs`,
    `INV_RECON_10_PageCount`, `INV_RECON_10b_HonestResponsePageSize`.
  - Two adversarial actions (`AdversarialEmptyResponse` for DoS
    via empty + has_more=TRUE, `AdversarialContentResponse` for
    content forgery) plus `AdversarialRequest` for misroute.
- `spec/Reconciliation.cfg` — honest model: Peers={p1,p2},
  NumEntries=2, MaxPageSize=1, MaxPages=2, MaxReqIDs=4.
- `spec/Reconciliation_adversarial.cfg` — adversarial model with
  tighter bounds; INV-8 + INV-10b dropped.
- `spec/Settlement_invariants.md` — INV-SETTLE-8..11 entries
  promoted from DEFERRED to shipped with cross-ref table to
  `Reconciliation.tla` predicates.

**Bugs caught by TLC during spec development:**

1. **Empty-page cursor regression** (INV-12 in early draft): the
   honest responder allowed an empty page with `has_more=TRUE`,
   which let the initiator advance `page_idx` while the cursor
   stayed at (0, 0). Real Python returns at least one entry
   whenever `candidate` is non-empty. Fix: `candidate /= {} =>
   page /= {}` constraint in `HandleRequest`. Caught after 4
   states.
2. **Multi-response same-req_id acceptance**: an adversary could
   emit two responses with the same req_id and both got
   accepted, exceeding `MaxPages`. Real Python pops pending
   after each `event.wait()`, so a duplicate-req_id second
   response finds no match and is dropped. Fix: refactor
   `HandleResponse` to always pop pending; add
   `sess_cursor`/`sess_can_continue` to carry session state
   between pages. Caught after 6 states with 2.6M states
   explored.

**TLC validation:**

- Honest: 608k states, 256k distinct, 15s. No violation.
- Adversarial: bounds tightened to NumEntries=1, NumTimestamps=0,
  MaxPages=1, MaxPageSize=1, MaxReqIDs=2. Run details in this
  session.

**Why this matters strategically.** §C1 is "TLA+ formal spec of
v1 protocol" — the foundation of the vNext migration. Settlement
+ Reconciliation closes the settlement-protocol portion (4 of 6
sub-specs to go: Attestation, Blackboard, DHT, Gossip).
Reconciliation in particular was the most subtle of the four
because pagination + cross-peer injection are operationally
non-obvious; having a model-checked spec is more valuable than a
prose-only invariant table.

**What's NOT in the spec:**

- Reputation events on disputed/missing (INV-SETTLE-12): structural,
  downstream of the diff classification.
- The actual diff itself (`reconcile_with_peer` set difference):
  pure function tested in `tests/test_reconciliation.py`.
- Liveness: under fair delivery every session terminates within
  MaxPages, but TLC's safety mode doesn't check liveness; a
  separate temporal-logic property would.

---

## Session 27 — `gyza-settlement` Rust port (spec ↔ impl loop closed)

Phase 0 Stream 3 + §C1↔§C4 milestone: the first Rust crate
derived directly from a TLA+ formal spec. `spec/Settlement.tla`
(Session 19) is the ground truth; `gyza-rs/gyza-settlement/` is
the implementation.

**Deliverables:**

- `gyza-rs/gyza-settlement/` (~600 lines).
  - `LedgerEntry` struct — bilateral ledger entry mirroring
    `gyza.economy.ledger.LedgerEntry` (preserves the
    `from_compositor` = payer / `to_compositor` = earner naming
    for Python parity).
  - `canonical_sign_bytes(entry, role)` — produces a 32-byte
    BLAKE3 digest. `role` is `"earner"` or `"payer"`. **Python
    parity validated** by fixture test.
  - `sign_as_earner(entry, earner_signer)` /
    `sign_as_payer(entry, payer_signer)` — set `to_signature` /
    `from_signature` respectively. Verify signer's pubkey matches
    the entry's claimed role.
  - `verify_earner_signature` / `verify_payer_signature` /
    `verify_entry`.
  - `apply_cosigned_entry(entry)` — verify both sigs, flip
    `settled = true`.
  - `payer_validate(entry, recipient_pubkey, resolved_envelope,
    our_amount, tolerance_ratio)` — the Settlement.tla
    `HandleEarnerSigned` guard chain as a pure function. Checks
    misroute → earner sig → envelope hash → amount tolerance, in
    that order, matching the TLA+ action's branch structure.
  - `within_tolerance(claimed, truth, ratio)` — ±tolerance check.
- `gyza-rs/scripts/regenerate_settlement_fixtures.py` — Python
  fixture generator.

**20 unit tests:**
- Amount canonicalization (`{:.6}` formatting matches Python `:.6f`).
- Role distinctness (earner vs payer digests differ).
- Earner sign + verify roundtrip.
- Earner sign rejects wrong signer pubkey.
- Payer cosign requires earner signature first.
- Payer cosign verifies earner sig BEFORE signing (Settlement.tla
  INV-SETTLE-2).
- Payer cosign rejects wrong signer pubkey.
- Full bilateral roundtrip → applied + verifiable.
- Apply rejects unsettled (no payer sig) entry.
- Apply rejects tampered amount (re-verify catches it).
- `within_tolerance` basic + zero-truth edge case.
- `payer_validate` happy path + 4 dispute paths (misroute,
  envelope mismatch, amount outside tolerance, invalid earner sig).
- Serde JSON roundtrip preserves verifiability.
- **Canonical sign bytes parity with Python** (load-bearing):
  - `canonical_sign_bytes(entry, "earner")` =
    `6e9d9ae550d0c36b40038dd5e2f0c8f1bfb84bd392c845d3cdda1254fc67b440`
  - `canonical_sign_bytes(entry, "payer")` =
    `4f521f5c5b7461181de4c914a2d23753e5628c8649af263f1c4cd73a82412b1a`

**Strategic significance.** Closes the §C1 ↔ §C4 loop: TLA+ spec
(Session 19) → Rust implementation derived from spec (Session 27).
The Settlement.tla state machine's branch structure (4 dispute
paths + happy path) maps 1:1 onto `payer_validate`'s match arms
and `SettlementError` variants. Future spec changes propagate to
Rust via the parity tests + structured error types.

**Workspace total after Session 27:** 71 tests across 6 crates
(gyza-crypto 6, gyza-identity 7, gyza-icp 16, gyza-core 10,
gyza-blackboard 12, **gyza-settlement 20**). All passing under
`cargo fmt --check + clippy -D warnings + test --workspace`.

**What this DOESN'T port (deferred to follow-ups):**

- SQLite-backed `ComputeLedger` storage. Will mirror
  `gyza-blackboard` pattern. ~1 session.
- `LedgerSettlementService` (the network/messaging layer that
  orchestrates the state machine over libp2p). Depends on Rust
  gRPC + libp2p layers which don't exist yet. Multi-session work.
- Reconciliation RPC. Separate Settlement.tla sub-spec needed
  first (acknowledged in CLAUDE.md §6 C1 progress table).
- Reputation hooks (`gyza-reputation` crate, future).
- Settlement-latency observability (`gyza-observability` crate,
  future).

**Trip-wires this session surfaced:**

- **`format!("{:.6}", f64)` rounds half-to-even by default**, same
  as Python's `f"{:.6f}"`. Parity test passes for the values the
  protocol uses. Don't rely on this for adversarial-edge floats;
  Python's float repr has corner cases.
- **`SettlementError::InvalidRole` returns early before any
  other check.** Important: tests that construct entries with
  invalid roles should expect this error, not the downstream
  checks.
- **Don't reuse the same Rust `Signer` for earner and payer.**
  They have different compositor identities; tests use
  `TEST_MASTER` for earner and `PAYER_MASTER` for payer.

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
