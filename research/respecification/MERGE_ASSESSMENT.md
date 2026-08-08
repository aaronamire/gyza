# Merge assessment — `divergence-fix` into `main`

**NOT MERGED. This is a release decision about signed bytes and it is the user's
to make.** Prepared, not executed.

| | |
|---|---|
| branch | `divergence-fix` (4 commits: `d3f4646`, `c214038`, `89541f9`, `7436160`) |
| merged to `origin/main`? | **NO** — verified with `git merge-base --is-ancestor` |
| `origin/main` | `f67c917`, tagged **`v0.1.2`**, `pyproject` version `0.1.2` |

---

## 1. What changes about the bytes — answered from the code

Two changes, and **they affect opposite sides**:

### 1a. Rust non-ASCII escaping — **RUST bytes change; PYTHON bytes do not**

`gyza-icp::canonical_bytes` and `gyza-capability`'s three canonical-bytes
functions moved from bare `serde_json` (raw UTF-8) to `gyza_canonjson` (escapes
`c >= 0x7f`, surrogate pairs above the BMP).

- **Python is untouched.** Its `json.dumps(..., ensure_ascii=True)` behaviour is
  unchanged, so **every Python-signed envelope verifies exactly as before.**
- **Rust output changes** — but *only for payloads containing a byte `>= 0x7f`.*
  For pure-ASCII payloads the two encoders are byte-identical, which is why the
  four pre-existing parity fixtures passed throughout.

### Is any Rust-signed history affected? **No, and the reason is structural**

`gyza-rs` exposes `sign_envelope` (`gyza-icp:164`), `sign_as_earner` and
`sign_as_payer` (`gyza-settlement:268,296`) — **but the workspace has no binary
target at all:**

| check | result |
|---|---|
| `[[bin]]` sections across all 8 crates | **0** |
| `main.rs` files | **0** |

> **`gyza-rs` is library-only. It has never run as a program, so it has never
> produced a persisted signed artifact.** There is no Rust-signed history to
> invalidate — not "we found none", but **there is no execution path that could
> have created any.**

**Net: zero stored signatures change meaning.** Python-signed history is
untouched by construction; Rust-signed history does not exist.

### 1b. The NaN guard — **refuses input that previously passed; changes no byte**

`_require_signable_amount` is added at `canonical_sign_bytes`
(`gyza/economy/ledger.py`), replacing `if amount < 0` at `create_entry`. For every
amount that was **already signable** the digest is **bit-identical** — the guard
only *rejects*, never re-encodes. Rust gains the mirror predicate
(`SettlementError::UnsignableAmount`).

**Behaviour change:** `NaN` and `+inf`, which previously passed the ordering test,
are now refused at signing, and verification returns `(False, "unsignable
entry")` instead of raising.

---

## 2. Stored data — rechecked, and labelled honestly

`/home/xan/.gyza/ledger.db`, the only ledger database on this machine:

| | |
|---|---|
| entries | **9** |
| **non-finite amounts** | **0** |
| negative amounts | 0 |
| range | 4.0 – 200.0 |

> **This is "NO KNOWN INSTANCE", not "the old guard was adequate."** At n = 9 demo
> entries the absence is unsurprising whatever the guard did. It is a
> weakly-powered null and no migration is indicated by it.

**No entry becomes unverifiable after the merge**, because all 9 amounts are
finite and their digests are unchanged (§1b).

---

## 3. What the parity fixtures now cover — and the negative control

Three hostile fixtures, present and confirmed in the tree:

| fixture | location |
|---|---|
| `fixture_payload_hostile` | `gyza-rs/gyza-icp/src/lib.rs:349` |
| `fixture_challenge_hostile` | `gyza-rs/gyza-capability/src/lib.rs:644` |
| `numeric_edge_digests_match_python` | `gyza-rs/gyza-settlement/src/lib.rs:545` |

They carry what the four originals did not: BMP non-ASCII, a combining mark, an
**astral codepoint** (surrogate pair), **DEL (U+007F)** — the boundary a
spec-derived *"escape non-ASCII"* implementation misses — plus `-0.0`, the
smallest denormal, `f64::MAX` and both half-even boundaries.

**The negative control was demonstrated when built** (`89541f9`): reverting
`canonical_bytes` to bare `serde_json` made the three hostile fixtures **FAIL**
while the four ASCII-only originals still **passed** — a direct measurement that
the old fixtures had no power. That demonstration is recorded in the commit; it
was **not** re-run here, since it requires mutating the branch.

---

## 4. Release implication

`origin/main` is `f67c917`, tagged `v0.1.2`. **Merging changes signing behaviour
after a tag.**

**Recommended: `v0.1.3`, a PATCH bump. Reasoning:**

- **No public API changes.** Signatures of `canonical_bytes`, `sign_envelope`,
  `canonical_sign_bytes` are unchanged.
- **No stored artifact changes meaning** (§1, §2).
- The behaviour changes are **a correctness fix** (Rust now matches the Python
  reference it was always specified against) and **a refusal that was always
  intended** (non-finite amounts were never meant to be signable).

**Two things that argue for treating it as more than a patch, stated so the call
is informed rather than nudged:**

1. **It changes bytes covered by signatures.** Even with no affected history
   *today*, anyone who has built on `gyza-rs` as a library and persisted its
   output independently would be affected. `gyza-rs` is `0.1.0-vnext.0` and
   unpublished, which is why I still land on patch — **but that reasoning
   depends on it being unpublished, and that is worth confirming before
   tagging.**
2. **The tag convention is `v<pyproject version>` and must match** — all four
   existing tags do. A `v0.1.3` tag requires bumping `pyproject.toml:7` **and**
   `gyza/__init__.py:14` together; `tests/test_release.py:85` asserts they agree.

**Release blockers unchanged from `v0.1.2`:** `MINISIGN_SECRET_KEY` is still
unset and the arm64 onedir build is still broken at
`packaging/Dockerfile.build:20` (x86_64 base image on an arm64 runner). The
fail-closed signing gate added in `f67c917` means a tag push produces a **loud
refusal**, not an unsigned release — so tagging is safe but will not publish
assets.

---

## 5. Recommendation

**Merge is low-risk and I recommend it — as a deliberate release action, not
housekeeping.** The suggested sequence:

1. Confirm `gyza-rs` has never been published as a library to any registry (§4.1).
2. Merge `divergence-fix` → `main`.
3. Bump `pyproject.toml` **and** `gyza/__init__.py` to `0.1.3`.
4. Run the three suites sequentially; expect Python 876+, Rust 108, Go 10.
5. Tag `v0.1.3` only if the signing key exists — otherwise the release job
   refuses by design.

**Not done here**, per C3. This changes what a signature means, and that should
be chosen rather than inherited from a session's momentum.
