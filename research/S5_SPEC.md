# S5 — reproducible builds + runner attestation (SPECIFICATION ONLY)

Not built. Specified so the asterisk it removes is legible and so the effort is
estimable rather than open-ended.

## The asterisk it removes

`gyza verify` returns "bounded (INDEPENDENTLY VERIFIED)". The bounds-proof rests
on an **enforcement record stamped by the runner** — and the runner **self-
reports its own build**. A verifier recomputes the signature, the hashes, and
`enforcement ⊆ manifest`, but it cannot check that the binary which produced the
record is the binary whose behaviour those checks assume. A modified runner can
stamp a record describing a sandbox it never entered.

So today the honest reading is: *given an honest runner*, a valid signature
implies bounded execution. S5 is what removes "given an honest runner".

## What it requires here

1. **A bit-reproducible build.** Same source → same binary bytes, on any
   machine. Needs: pinned toolchain and interpreter, `SOURCE_DATE_EPOCH`,
   deterministic archive ordering, stripped non-determinism from the onedir
   bundle. `gyza/release.py:compute_source_tree_hash` already hashes the source
   tree; that is the *input* side. The missing half is the *output* side —
   identical bytes.
2. **A build attestation.** A signed statement binding source-tree hash →
   binary hash, produced by a builder whose identity is independent of the
   runner's. Two or more independent rebuilders agreeing is what makes it worth
   anything; one signer is a trusted third party with extra steps.
3. **Runner self-identification bound to that attestation.** The enforcement
   record must carry the binary hash, and `gyza verify` must check that hash
   against the attested set. `gyza/trusted_releases.json` and
   `is_trusted_release` (`gyza/release.py:201`) are the existing shape; they
   currently pin a source-tree hash, not a binary hash.
4. **Hardware attestation (optional, and a different trust root).** A TEE quote
   would bind "this binary is what is actually executing". Without it, S5 proves
   the binary matches the source; it does not prove that binary is the one that
   ran.

## What it does NOT fix

- **Containment still ends at emission (C15).** A guard can refuse to emit;
  after emission there is no containment and no detector helps. S5 changes who
  you must trust about the sandbox, not what a sandbox can do.
- **Semantic correctness.** Untouched — the competence bound, terminal.
- **The fail-open enforcement gate.** That is a policy default (`S4`), not a
  build-integrity problem, and it is fixed separately.
- **Step 3 alone is circular without steps 1–2**: a runner that reports its own
  binary hash is self-reporting again, just at a finer grain.

## Effort estimate

| piece | estimate | note |
|---|---|---|
| bit-reproducible build | 1–2 weeks | mostly determinism whack-a-mole in the onedir bundle |
| build attestation format + signing | ~3 days | reuses the existing Ed25519 + canonical-JSON discipline |
| ≥2 independent rebuilders | **user-owned** | needs a second machine and a second operator; this is the part that makes it mean anything |
| verify-side binary-hash check | ~2 days | extends `is_trusted_release` from source hash to binary hash |
| TEE attestation | weeks–months | different trust root; out of scope for a first version |

**The critical-path item is not code.** It is the second independent rebuilder,
which is user-owned in the same way E1 and the external user are.
