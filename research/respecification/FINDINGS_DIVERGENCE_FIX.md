# Both Rust↔Python divergences, fixed

Closes the two divergences `FINDINGS_SURVEY.md` measured. Three commits on
`divergence-fix`, one per divergence plus the fixtures. **Every number here is
MEASURED on 2026-08-06.**

| commit | what |
|---|---|
| `d3f4646` | canonical JSON — Rust escapes non-ASCII |
| `c214038` | the amount guard — a positive predicate |
| `89541f9` | parity fixtures that can fail, negative control demonstrated |

---

## 1. Canonical JSON

**The rule was derived by sweep, and that changed the implementation.** A sweep
of `json.dumps(chr(cp))` over `0x00..=0x11F` gives:

```
escape iff  c < 0x20 || c == 0x22 || c == 0x5c || c >= 0x7f
```

serde_json already matches the first three, so the delta is `c >= 0x7f`.
**The bound is 0x7f, not 0x80** — Python escapes DEL (U+007F), which is ASCII.
An implementation written from *"escape non-ASCII"* would have emitted DEL raw
and still diverged. **The survey never probed DEL; only the sweep found it.**

**One implementation, not two.** `gyza-icp` and `gyza-capability` both need the
escaper and neither depends on the other. Copying it into both would reproduce
*exactly* the defect being fixed. Hence `gyza-canonjson` — a `serde_json`
`Formatter` overriding only `write_string_fragment`, so compact separators and
key order are inherited untouched.

### 1c — the capability pair, MEASURED (was an inference)

The survey labelled this pair *"same mechanism by construction, NOT separately
measured."* Now measured on the real `ChallengePayload` with BMP + astral + DEL
task ids: pre-fix Rust emitted raw UTF-8; post-fix both sides produce the same
**298 bytes, byte-identical** (compared with `gyza.canon.values_equal`). It did
diverge. It is fixed. **It was not a non-problem.**

### 1d — all 20 canonicalization sites

| site | Rust counterpart | status |
|---|---|---|
| `gyza/icp.py:60` | `gyza-icp:145` | **AGREES** (measured, 6 probes incl. DEL/astral) |
| `gyza/network/capability_protocol.py:249` | `gyza-capability:169,197,263` | **AGREES** (measured, 298 bytes) |
| the other **18** | none | **UNTESTABLE, not agreeing** |

The 18 are UNTESTABLE in the B4 sense: no Rust crate ports their module, so
there is nothing to disagree with. Specifically — **no crate canonicalizes a
manifest at all** (`capability_manifest_hash` appears only as an
already-computed hex field); `gyza-blackboard`'s `serde_json` calls are SQLite
storage that round-trips through one implementation, not signed bytes; and the
calls in `gyza-core`, `gyza-settlement` and `gyza-capability` past their
`#[cfg(test)]` boundaries are test-only.

---

## 2. The amount guard

**Two defects, and the guard is the one that mattered.**

`ledger.py:257` was `if amount < 0: raise`. Measured before the fix:

| amount | old guard | |
|---|---|---|
| `nan` | **ACCEPTED** | |
| `inf` | **ACCEPTED** | |
| `-inf` | REJECTED | |
| `-1.0` | REJECTED | |

**Root cause, stated exactly: NaN is not "not less than zero" — it is
INCOMPARABLE.** `partial_cmp` returns `None`. A guard phrased as an ordering
test cannot classify it. "Not negative" is a **proxy** that merely correlates
with "is a valid amount".

> **Fourth instance of the species.** R9's `G4′` pinned the frame; SR-5 floated
> the origin; `GuardConfigStore` checked the version integer; this checked an
> ordering. Each tested something that *correlates with* the protected quantity
> instead of the quantity.

**Where it goes.** The chokepoint is `canonical_sign_bytes` — both signing paths
(`:292`, `:318`) and the verification path (`:619`) funnel through it, and
`LedgerEntry.from_dict` builds **peer-relayed** entries straight off the network
(`settlement.py:672`) without touching `create_entry`. Guarding construction
alone would guard the *path*, not the *quantity*.

`wallet.py:83` already refuses non-finite amounts — but it guards the **fold**,
deciding what a balance projection counts. **Guarding the fold is not guarding
the signature:** a NaN entry dropped by the projection could still be signed,
stored and relayed, carrying a valid signature over bytes the two languages
disagree about.

**Verification rejects rather than raises.** A hostile amount from a peer is
adversarial input, not a programming error; a network-facing verifier that
raises on it is a denial-of-service.

### 2c — the format fix is LATENT, not live

With the guard in place a non-finite amount can no longer **reach** either
formatter. So harmonizing `"nan"`/`"NaN"` **removes a latent divergence; it does
not repair a live path**, and is not presented as one. Harmonizing the
*formatters* was rejected outright: it would have made both sides agree on an
encoding of a value neither should ever sign. Both sides now refuse instead.
`+inf` formats `"inf"` identically on both sides and **never diverged**; it is
refused anyway, because the property is *finite*, not *formats the same*.

### 2d — the stored-data answer

`/home/xan/.gyza/ledger.db`, the only ledger database on this machine:

| | |
|---|---|
| entries | 9 |
| **non-finite amounts** | **0** |
| negative amounts | 0 |
| range | 4.0 .. 200.0 |

No stored entry exploits the defect; no migration is needed.

> **Diagnosing that zero.** With n = 9 demo entries the absence is unsurprising
> whatever the guard did. This is **"no known instance," not evidence the old
> guard was adequate** — a weakly-powered null, and it is labelled one.

---

## 3. Fixtures that can fail

The four existing fixtures are ASCII-only and finite-valued, so they agreed
under **both** encoders and had no power. The new ones carry BMP non-ASCII, a
combining mark, an astral codepoint (surrogate pair), DEL, CJK, NBSP, an RTL
mark, a solidus and a quote that must *not* gain an escape — plus seven numeric
digests (`-0.0`, smallest denormal, `f64::MAX`, both half-even boundaries,
`0.1+0.2`, `1e17`).

### The negative control was DEMONSTRATED, not asserted

The fix was reverted in the working tree and the suites re-run:

| test | pre-fix |
|---|---|
| `hostile_canonical_bytes_parity_with_python` | **FAILED** |
| `hostile_envelope_hash_parity_with_python` | **FAILED** |
| `hostile_challenge_canonical_bytes_parity_with_python` | **FAILED** |
| `canonical_bytes_parity_with_python` (old, ASCII) | ok |
| `envelope_hash_parity_with_python` (old, ASCII) | ok |
| challenge / attestation / response parity (old, ASCII) | ok |

**The second half is the finding.** The new fixtures fail without the fix; the
old ones pass without it. That is a *direct measurement* of the old fixtures
having no power — not an inference about them. Fix restored, all green.

---

## The documentation finding, and it reframes everything

`gyza-icp`'s module docs carried an **"ASCII-only invariant"**: no envelope field
holds non-ASCII, the encoders therefore agree, and *"if a future field needs
non-ASCII, this needs explicit reconciliation."*

> **The divergence was not unknown. It was known, written down, and ASSUMED
> AWAY.**

Every clause of that note was true and it was still the wrong call, because
**nothing enforced the invariant**. No validation restricts any field to ASCII,
and `gyza bundle <intent_id>` (`cli.py:2493`) takes a free-form positional
string — so the "future field" was reachable from the command line the entire
time. **An unenforced invariant is an assumption**, and this one sat under every
cross-language signature. The paragraph is replaced with what is now true.

---

## Gate

| | |
|---|---|
| Python | **872 passed**, 1 skipped (861 + 11 new) |
| Rust | **108 passed** (94 + 14 new), fmt clean, clippy `-D warnings` clean |
| Go | **10 packages ok** |

Suites run **sequentially**. Sequential comparison is not concurrent execution.

## Not touched, deliberately

The send/retrieval **consumption gap** (0.8333 composable / 1.0000 emitted /
**0.0000 consumed**, `last_send_claim` read at zero sites anywhere including
tests) is real and is the next item. Mixing an unused-machinery question into a
signed-bytes fix would make both harder to review.
