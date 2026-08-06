# Closing the engineering phase — the Rust survey, emission coverage, and the digest evaluation

Parts B, C and D of the closing pass. Part A (E1 ship) is recorded in
`CLAUDE.md` §7 and in the `v0.1.2` tag message, not here.

**Every number below is MEASURED on 2026-08-06 unless labelled DEFINITIONAL.**
Nothing in Parts B–D was fixed; B and D are report-only by instruction, and C
found nothing to fix — it found something to stop claiming.

---

## Part B — the Python ↔ Rust sibling survey

### B0. Why this ran now, and why the standing rule did not forbid it

A4's earlier survey left this pair unexamined, recording that testing it
"appeared to require concurrent language suites", which the standing rule
forbids.

> **The rule prohibits CONCURRENT EXECUTION, and its purpose is flake
> avoidance under resource contention. This survey runs the two sides
> SEQUENTIALLY and compares their OUTPUTS. That is not concurrent execution
> and does not engage the rule.** Recorded here so the survey is not skipped
> a third time for the same wrong reason.

Method: a Python probe and a Rust probe emit the same JSON shape over the
same inputs; a third step compares them with `gyza.canon.values_equal`, never
`repr` equality (#7, #15). The Rust probe is a scratch crate with path
dependencies on the real crates — the repo is untouched.

**The surveyed surface is byte-identical between `main` and `respecify`**
(`git diff --stat main respecify -- gyza-rs/ gyza/icp.py …` is empty), so this
result is branch-independent.

### B1. The pairs, with both citations verified against the tree

| # | operation | Python | Rust | paired? |
|---|---|---|---|---|
| P1 | BLAKE3 hash | `blake3` pkg | `gyza-crypto/src/lib.rs:48` | yes |
| P2 | keyed seed derivation | `identity.py:111` | `gyza-crypto/src/lib.rs:74` | yes |
| P3 | Ed25519 sign/verify | `icp.py:67,82` | `gyza-crypto/src/lib.rs:118,134` | yes |
| P4 | **envelope canonical JSON** | `icp.py:56` | `gyza-icp/src/lib.rs:116` | yes |
| P5 | envelope hash | `icp.py:63` | `gyza-icp/src/lib.rs:124` | yes |
| P6 | chain verification | `icp.py:105` | `gyza-icp/src/lib.rs:236` | yes |
| P7 | **amount canonicalization** | `ledger.py:138` | `gyza-settlement/src/lib.rs:188` | yes |
| P8 | **settlement sign digest** | `ledger.py:143` | `gyza-settlement/src/lib.rs:205` | yes |
| P9 | capability canonical JSON | `capability_protocol.py:249` | `gyza-capability/src/lib.rs:168` | yes |
| P10 | manifest canonical bytes | `identity.py:88` | — | **NO Rust side** |
| P11 | HLC | `schema.py` | `gyza-core/src/lib.rs:225` | yes, not probed |

### B2. Results — 71 probes

| verdict | n |
|---|---|
| AGREE | 60 |
| **DIVERGE** | **5** |
| UNTESTABLE | 6 |

The 6 UNTESTABLE are all P10 (manifest): **Rust has no counterpart at all.**
Reported as UNTESTABLE, *not* as agreement — "I could not distinguish them" and
"they agree" are different claims (B4).

---

### DIVERGENCE 1 — canonical JSON escapes non-ASCII in Python and does not in Rust

**This is the significant finding. It sits in the exact operation whose parity
is load-bearing for the signature.**

| case | Python `_payload_bytes` | Rust `canonical_bytes` |
|---|---|---|
| `café` | `"intent_id":"café"` (6 ASCII bytes) | `"intent_id":"caf\xc3\xa9"` (2 raw UTF-8 bytes) |
| `x🔐y` | `"x🔐y"` — a **surrogate pair** | `"x\xf0\x9f\x94\x90y"` — 4 raw bytes |

**Mechanism.** `json.dumps` defaults to `ensure_ascii=True`; `serde_json` emits
raw UTF-8. Different bytes → different BLAKE3 → different envelope hash →
**a signature produced by one side does not verify on the other.**

**Blast radius.** `gyza/` has **20** `json.dumps(…, sort_keys=True)`
canonicalization sites and **zero** of them pass `ensure_ascii` explicitly.
Every one inherits the escaping default. Two have Rust counterparts:

- `icp.py:60` ↔ `gyza-icp` — **MEASURED divergent** (above).
- `capability_protocol.py:249` ↔ `gyza-capability` — **NOT separately measured.**
  Same two library calls, so the same mechanism applies by construction; that is
  an inference, and it is labelled as one rather than reported as a result.

**Why four parity fixtures never caught it.** All four generators use
ASCII-only payloads — the ICP fixture is `intent_id="int-0001"`. The 18
non-ASCII bytes in the capability generator are **in comments**, not data. The
fixtures agree trivially, and trivial agreement is exactly what B2 warns
cannot distinguish two implementations. `ascii_plain` AGREES in this survey too;
the divergence is invisible until a probe carries a non-ASCII byte.

**Reachability.** No ASCII validation exists anywhere in `icp.py` or
`schema.py`. Envelope string fields are IDs, hex hashes and backend/model
names — ASCII on every default path — so this is **latent, not currently
firing**. The exposed surface is user-supplied: `gyza bundle <intent_id>`
(`cli.py:2493`) takes a free-form positional string with no charset constraint.

**A note for whoever fixes it (not fixed here, per B5).** The fix belongs on
the **Rust** side. Changing Python to `ensure_ascii=False` would alter the
canonical bytes of every envelope ever signed and invalidate the entire stored
history. Rust must be made to escape, not Python made to stop.

---

### DIVERGENCE 2 — `NaN` formats differently, and the amount guard lets it through

| | Python | Rust |
|---|---|---|
| `_amount_canonical(nan)` | `b"nan"` | `b"NaN"` |
| resulting sign digest | `541b9dbd…` | `63f7dd3f…` |

`inf` **agrees** (`"inf"` both sides) and is not a divergence. Only `NaN` is.

**Reachability is REAL, and the mechanism is a classic.**
`gyza/economy/ledger.py:257` guards with `if amount < 0`. Measured:

| amount | `amount < 0` | outcome |
|---|---|---|
| `-1.0` | True | REJECTED |
| `-inf` | True | REJECTED |
| **`nan`** | **False** | **ACCEPTED** |
| **`inf`** | **False** | **ACCEPTED** |

`NaN` compares False against every ordering operator, so a negative-amount
guard is exactly the wrong shape to exclude it. There is a finiteness check —
`wallet.py:83`, `not math.isfinite(amount)` — but it guards the **fold**, not
the **signing path**. So a NaN entry can be constructed, signed, and stored,
while contributing nothing to any balance.

The other 20 amount probes AGREE, including every half-even boundary
(`0.0000005`, `0.1234565`, `0.1234575`), `-0.0` → `"-0.000000"` on both sides,
`f64::MAX`'s full 309-digit expansion, and the smallest denormal.

---

### B3. Deliberate differences — not divergences

| pair | status | where the intent is recorded |
|---|---|---|
| Python JSON-canonical cosigs ↔ Go deterministic-protobuf cosigs | **DELIBERATE** | `netd/internal/capability/capability.go:24` — "just needs `Marshal{Deterministic:true}`". CLAUDE.md §9 forbids making them interop; the cross-network wire format is the Go one. |

This is Python↔**Go**, outside the Python↔Rust scope, and is listed so it is
not mistaken for an eighth finding.

### B4. What could NOT be distinguished

- **P11 (HLC)** — not probed. Rust `Hlc` is a stateful clock with injected
  time; the Python side is in `schema.py`. Comparing them needs a shared clock
  trace, which is a test campaign rather than a survey. **Reported as unprobed,
  not as agreement.**
- **P10 (manifest)** — has no Rust counterpart; the 6 UNTESTABLE rows.

### B5. Nothing was fixed

A divergence in canonical serialization or signature verification is
security-relevant and deserves its own commit and its own review.

---

## Part C — emission coverage

### C1. Measured, and the two respecified types are OPPOSITE

| claim type | production call sites | emitting | fraction |
|---|---|---|---|
| `memory_retrieval_relevance` | 1 (`memory.py:575`) | 0 | **0.0000** |
| `external_send_content` | 5 (`netd_client.py:369,527,552,982,1176`) | 5 | **1.0000** |

**Both extremes diagnosed before reporting, per the standing rule.**

- **The 0 is real, and it is one call site.** `build_enriched_prompt`
  (`memory.py:575`) is the only production consumer of `retrieve_similar`; it
  is reached from `runner.py:408` and does not pass `emit_claim`, which
  defaults False. Of 5 test call sites, exactly 1 opts in
  (`test_respecification.py:403`). The zero is not a harness artifact — it is
  the design decision working as recorded.
- **The 1 is DEFINITIONAL.** `_emit_send_claim` is called unconditionally on
  every send path; there is no flag and no branch that could fail to emit. The
  fraction is 1 by construction, not by measurement, and it is not evidence
  that anything works.

### C2. The honest pair

> **p(composable) = 0.8333 — what COULD be verified.**
> **Production emission = 0.0000 (retrieval) and 1.0000 (send) — what IS produced.**
> **Production CONSUMPTION = 0.0000 for both — what is ever CHECKED.**

Either number alone misleads. The registry figure is a property of the
*vocabulary*; the emission figure is a property of the *call sites*; and the
third row is the one that decides whether any of it does work.

### C3. The finding C3 asked for, and it is worse than near-zero emission

**Nothing in `gyza/` consumes either claim.** Exhaustive search over the whole
repository:

| symbol | writes | reads |
|---|---|---|
| `last_retrieval_claim` | 1 (`memory.py:509`) | **0 in `gyza/`**; 1 in tests |
| `last_send_claim` | 5 (`netd_client.py`) | **0 anywhere — including tests** |

`verify_send_claim` and `verify_retrieval_claim` are called only from
`adapters.py` (the registry wrapper) and from `test_respecification.py`.

So the send path is the sharper case, and it is **artifact #16's species one
level up**. Registering a checker is not evidence that it runs; here the
producer *does* run — on every send — and **writes to an attribute that no
code, in any file, ever reads.** Every send pays a full BLAKE3 over the wire
payload plus a `time.time_ns()` and an allocation, and the result is
unobservable.

**Paired with its counter-metric, as required:** that cost buys **zero**
verifications today. A guard's throughput cost is not evidence it is doing
anything. The machinery is real and was proven against three real divergences
(FINDINGS.md Parts A/B) — but between the producer and the verifier there is
currently no wire.

---

## Part D — incremental snapshot digest

### D1/D2. VERDICT: the write paths are NOT complete. **NOT BUILT.** The evaluation is the deliverable.

Three independent blockers, each verified:

**1. There is no transaction to update a digest inside.**
`memory.py:165` sets `isolation_level = None`, which is SQLite **autocommit**.
Measured directly: after an `INSERT`, `conn.in_transaction` is `False`, and a
second connection sees the row with no commit call. D3's first requirement —
"the digest updated in the same transaction as the write, never after" — is
**literally unsatisfiable on this backend as written**. The LanceDB path is
worse: `self._table.add(rows)` (`memory.py:307`) exposes no transaction at all.

**2. `EpisodicMemory.write()` is not a chokepoint, and the bypass is not
hypothetical.** `_backend.add()` is public-by-convention, and this repository's
own suite already calls it directly at `tests/test_respecification.py:145` and
`:293`. A digest maintained in `write()`/`flush()` would silently miss those
writes — attesting to a corpus state that never existed, which is the
blind-channel shape (R12) relocated into the digest itself. That is strictly
worse than no digest.

**3. Two backends, two mechanisms, one with no hook.** SQLite and LanceDB would
each need separate digest maintenance; the Lance path has nowhere to put it.

**One thing I checked and must NOT overclaim:** I expected the four
`EpisodicMemory(...)` sites to share `~/.gyza/memory.db` and make this a
multi-process problem. They do **not** — `cli.py:343`, `cli.py:1318`,
`attestation_adapter.py:194` and `demo_agent.py:585` each pass a distinct
`db_path`. Cross-process sharing is **not demonstrated in-tree** and is not
offered as a reason. (The store is nonetheless configured for concurrency —
WAL, `busy_timeout=10000`, thread-local connections — so single-writer is an
assumption a digest would be making, not a property it could rely on.)

### D3. Not implemented, per D2.

### D4. What mandatory emission would cost — MEASURED

Digest alone, by corpus size (384-dim float32 vectors):

| corpus | digest | bytes hashed |
|---|---|---|
| 100 | 1.67 ms | 0.2 MB |
| 1 000 | 5.78 ms | 1.5 MB |
| 10 000 | 41.99 ms | 15.4 MB |
| 50 000 | 210.29 ms | 76.8 MB |

Clean linearity — the digest is O(corpus), as designed.

End-to-end on the **real LanceDB backend**, n = 2000, median of 5:

| | latency |
|---|---|
| `retrieve_similar(emit_claim=False)` — today | **50.91 ms** |
| `retrieve_similar(emit_claim=True)` — mandatory | **612.36 ms** |
| overhead | **+561 ms, 12.0×** |

**The opt-in decision is confirmed by the number, not merely by the argument.**
Retrieval is O(log corpus) via the ANN index; the claim is O(corpus) because
`_build_retrieval_claim` calls `all_for_agent()` (`memory.py:525`) and
materializes every episode. Mandatory emission would reimpose exactly the full
scan that Part A1 of the prior session rejected as a fix for D1 — a 12× tax at
a corpus size that is small.

**And an incremental digest would not have rescued it.** Even at O(1)
amortized, the *verifier* still needs the full candidate set to recompute the
neighbour set, so verification stays O(corpus). The digest is the cheap half;
the expensive half is inherent to being checkable at all.

---

## What this closes, and the one thing it opens

Closed: the Rust pair is surveyed (B), emission is measured rather than implied
(C), and the digest question is answered with a verdict and a number (D).

Opened: **two real divergences in signed canonical bytes**, both latent today,
both invisible to the existing parity fixtures because those fixtures are
ASCII-only and finite-valued. Neither is fixed here. Neither should be fixed in
the same commit as anything else.
