# Sweep — invariants asserted in prose, and whether anything enforces them

Prompted by the divergence session's reframing finding: `gyza-icp` documented an
"ASCII-only invariant", every clause of it was true, and **nothing enforced it**.

> **AN UNENFORCED INVARIANT IS AN ASSUMPTION.**

**REPORT ONLY — nothing here was fixed.** A sweep that becomes a refactor stops
being a sweep.

---

## Method, and its honest limit

Scanned `gyza/`, `gyza-rs/*/src` and `netd/internal` — comments and docstrings
only, never identifiers or string data — for the linguistic markers of an
asserted invariant.

| stage | count |
|---|---|
| all marker lines (`must`, `never`, `always`, `assumes`, …) | **681** across 114 files |
| narrowed to **assertion-shaped** markers | **100** |
| **verified in depth against the code** | **14** |

**Two narrowings, both stated so the counts are not over-read.**

1. `must` / `do not` / `never` are overwhelmingly **imperatives to a
   maintainer** ("payload must be bytes", "DO NOT REORDER"). Those are enforced
   by review, correctly, and are a different thing from a claim about runtime
   state. Dropping them took 681 → 100.
2. **Only 14 of the 100 were verified against the code.** The remaining 86 are
   *candidates*, not classified findings. **A count of unverified candidates is
   not a count of unenforced invariants**, and is not reported as one.

---

## The classified 14

| # | claimed invariant | citation | class |
|---|---|---|---|
| 1 | envelope fields hold no non-ASCII, so the encoders agree | `gyza-rs/gyza-icp/src/lib.rs` (pre-fix) | **UNENFORCED-AND-REACHABLE** — *the case that prompted this; now fixed* |
| 2 | `verify_delegation` "assumes a cryptographically intact chain" | `gyza/economy/delegation.py:44` | **split — see below** |
| 3 | LSH bucket ids are 64-bit | `gyza/demand.py:38` | ENFORCED — `raise ValueError` two lines down |
| 4 | Go and Python agree on 64 LSH bits | `netd/internal/dht/dht.go:46` | ENFORCED — `const LSHBits = 64`, compile-time |
| 5 | Go↔Python ICP byte parity | `netd/internal/capability/capability.go:481` | **ENFORCED BY CONSTRUCTION — see below** |
| 6 | total market capital is conserved (zero-sum) | `gyza/economy/market.py:35` | ENFORCED — by test, `test_market_conserves_total_capital` |
| 7 | HLC `(l,c)` tuples are unique | `gyza/schema.py:17` | ENFORCED — internal lock; the comment is a *fixed bug's history* |
| 8 | the current task's eval marker is last in the prompt | `gyza/capability_eval.py:343` | ENFORCED — `rfind` scans from the end *because* of it |
| 9 | canonical-bytes encoding "shouldn't be reachable in practice" | `gyza-rs/gyza-icp/src/lib.rs:240` | ENFORCED — handled anyway, structured error not a panic |
| 10 | `cur >= stored`, so the reward diff is signed-positive | `gyza/reward.py:38` | UNENFORCED-AND-BENIGN — a violation yields a *missed refresh*, not a wrong value |
| 11 | uuid7 collisions are "safe in practice" | `gyza/_compat.py:40` | UNENFORCED-AND-UNENFORCEABLE — probabilistic; correctly stated as a probability |
| 12 | agent a0 "is never Byzantine" | `gyza/demo/collective_scale.py:168` | UNENFORCED-AND-UNREACHABLE — demo scenario setup, not a system property |
| 13 | staging state "is always a fold" | `gyza/containment/staging.py:16` | ENFORCED — no projected state is stored; structural |
| 14 | `_embed` loads SentenceTransformer independently of `default_embedder()` | CLAUDE.md §8 trip-wire | **STALE-IN-PART** — see below |

### Counts for the classified subset

| class | n |
|---|---|
| ENFORCED (runtime, test, or by construction) | **9** |
| UNENFORCED-AND-REACHABLE | **1** (the ASCII case, now fixed) + **1 partial** (#2) |
| UNENFORCED-AND-BENIGN / UNENFORCEABLE / UNREACHABLE | **3** |
| STALE | **1 partial** |

---

## #5 — the contrast worth keeping

`capability.go:481` claims *"Cross-language match is guaranteed because both
sides use the canonical JSON Python already emitted (we never re-encode here)."*

**It is true, and it is enforced by construction.** The code hashes
`r.IcpPayloadBytes` — the bytes it *received*. There is no second encoder, so
there is nothing to diverge.

> **Go avoided, by not re-encoding, exactly the bug Rust had from re-encoding.**
> The same invariant was stated in both places; Go made it structural and Rust
> made it an assumption. That is the whole lesson in one comparison.

## #2 — the split, and why it is not alarming

`verify_delegation` checks bounds composition and **no signature**. Its
precondition is documented, not self-enforced. Two production callers:

- **`gyza/economy/coordinator.py` — ENFORCED.** `chain_ok` is checked in code at
  `:223`, before `verify_delegation` at `:257`. The documented conjunction
  `chain_ok ∧ manifest_hash_ok ∧ verify_grant ∧ grant_binds_to ∧
  verify_delegation` is implemented, not merely written down. The module
  deliberately does not re-derive the crypto and takes it injected.
- **`gyza/verification/adapters.py:47-50` — UNENFORCED.** The registered
  `delegation_attenuation` verifier calls `verify_delegation(chain)` with no
  precondition at all, while the registry marks it **PROOF-carried**.

**Reachability, which is what decides the severity:** `build_registries()` has
**zero production callers** — every one of its 14 call sites is a test. So the
unenforced path is **UNREACHABLE IN PRODUCTION TODAY**, and is a latent hazard
for whenever the coordination layer is wired to a real entry point.

## #14 — a CLAUDE.md trip-wire that is half stale

CLAUDE.md §8 says `_embed` loads SentenceTransformer independently of
`default_embedder()`, "so `GYZA_EMBEDDER=stub` leaks". Measured:

- the **stub leak is FIXED** (`memory.py:80-81` special-cases it);
- the **independent load is NOT** — two singletons, two model loads in one
  process, for every non-stub configuration.

They agree in value today **only because `all-MiniLM-L6-v2`'s pipeline ends in a
`Normalize` layer**, which neither module documents or depends on deliberately.
Point either at a model without it and they diverge silently. *That* is an
unenforced invariant, and it is the same shape as #5's counterexample.

---

## B5 — outlier or pattern?

**On frequency, the ASCII case is closer to an OUTLIER than a pattern.** Of 14
verified, 9 are enforced by a real mechanism — a `raise`, a `const`, a lock, a
structural choice, or a test. This codebase generally does back its assertions.
What made the ASCII case unusual is that it **named the gap and deferred it**
("if a future field needs non-ASCII, this needs explicit reconciliation") — the
check was not forgotten, it was *scheduled and never done*.

**But a different pattern IS present, and it is the more useful finding:**

> **The mechanisms backing these assertions are drifting from RUNTIME to
> TEST-ONLY, and the largest instance is that the entire V-1 verifier registry
> has no production caller at all.**

That is Part A's consumption gap generalized. `build_registries()` — the tier
router's whole verifier surface — is invoked from 14 test sites and **zero**
production sites. An invariant enforced only by a test holds for the code the
test exercises, not for the system.

**Not recorded as a ledger artifact.** `ARTIFACT_LEDGER.md` is for *clean numbers
that turned out false*; this produced no number and was found by reading. Same
call the `GuardConfigStore` finding got, and for the same reason — recording it
here keeps the ledger's definition intact.

## B4 — anything security-relevant?

**Nothing in the UNENFORCED-AND-REACHABLE class is live.** The one true instance
(#1) is fixed on `divergence-fix`. #2's unenforced path is real but unreachable
in production because its only caller is the test-only registry. **If the
coordination layer is ever wired to a production entry point, #2 becomes live
and should be fixed in that same change** — the registered `delegation_attenuation`
verifier must not report PROOF over a chain whose signatures nobody checked.
