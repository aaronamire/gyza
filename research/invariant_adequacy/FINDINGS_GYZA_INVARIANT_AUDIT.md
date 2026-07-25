# Gyza self-audit against the inductive-invariant criterion

Code-only, zero credits, **no security logic changed**. Every claim below cites a
code path and was checked by executing the real predicates against the real
manifest shape (read-only probes; no files in `gyza/` modified).

Reference frame: Route 9 (`FINDINGS_R9.md`) measured that an inductive invariant
bounds global harm **only if** (a) it is enforced at every state transition and
(b) its predicate covers every channel the harm measure counts. This audit asks
those two questions of Gyza's own bounds.

---

## (iv) first, because it reframes everything else: AUTHORITY, not CONSEQUENCE

**Gyza bounds AUTHORITY. It does not bound CONSEQUENCE.** Stated plainly, as the
task requires.

`CapabilitySpec` (`gyza/economy/delegation.py:70`) has exactly four dimensions:
read paths, write paths, a network boolean, and a memory cap. The bounds
predicate decides *what an agent may touch*. Nothing in the codebase bounds *how
much damage it may do inside what it may touch*: given `rw = {/out}`, no
predicate limits how many files under `/out` are destroyed; given
`network.allowed_hosts = [api.x]`, no predicate limits how many bytes are
exfiltrated to that host.

In Route 9's terms, **Gyza is at G0 on both harm classes, conditional on
authority containment.** This matches the literature exactly: authority
composition is solved (CaMeL); consequence composition is not.

Two partial exceptions, both real and both narrow:

1. **`memory_limit_mb`** (`spawn.resource_budget.memory_limit_mb`) is a genuine
   *consequence* bound — a resource cap, not an access grant. It is the only
   dimension of its kind, and §(iii) shows it is also the dimension that carries
   the whole attenuation theorem.
2. **Economic consequence** is bounded separately, in the settlement layer: the
   coordinator's `reserve`/budget gate plus audit-before-cosign
   (`gyza/economy/coordinator.py` steps 2 and 6) cap credits at risk. That is
   structurally a **G2-class monotone budget** over one channel — and Route 9's
   result applies directly: a G2-class bound is adequate only if its counter
   tracks *every* channel that moves the quantity it claims to bound.

---

## (i) Is the bound evaluated on every action, or only at delegation time?

**Two layers, two different answers. Neither is grant-time-only, so Gyza passes
the ScopeGate test — but one of them fails open.**

### Layer 1 — the execution bounds gate: per work item, and fail-OPEN by trigger

`gyza/runner.py:406-416`:

```python
enforcement = raw.get("__enforcement__")
if enforcement is not None:
    ok, why = enforcement_satisfies_manifest(enforcement, self._identity.manifest)
    if not ok:
        raise RuntimeError("refusing to sign — ...")
```

- The check fires **once per work item**, at signing time — not per syscall.
  That is the correct granularity, not a defect: the work item *is* Gyza's state
  transition, and per-syscall containment is the kernel's job (bubblewrap), not
  the predicate's. At the granularity of Gyza's own ledger, the check is
  per-transition and therefore inductive.
- **But the gate is conditional on the record being present.** An executor that
  stamps no `__enforcement__` skips the check entirely. This is documented
  back-compat (the comment at `runner.py:402-405`), and it means the signing path
  **fails open**, not closed.
- It is not, however, silently laundered as bounded. `gyza verify`
  (`gyza/cli.py:2136-2196`) emits a distinct verdict, `• no bounds-proof — this
  envelope makes no claim about sandbox enforcement`, and `all_ok` requires
  `bounds_independently_verified` whenever bounds *are* claimed. **Disclosure at
  verification substitutes for fail-closed at signing.** That is a defensible
  design, but it should be stated as what it is: the guarantee is
  non-repudiation of a claim, not refusal to proceed without one.

### Layer 2 — the delegation bound: checked twice, including at the transition that matters

`gyza/economy/coordinator.py`:

- **Step 1 (grant time, proactive)** — `capability_subset(subtask.required,
  self._p.manifest_spec)` at line 175: a parent may never delegate wider than its
  own manifest, refused before anything is posted.
- **Step 6 (result acceptance, before payment)** — `verify_delegation(chain)` at
  line 257, inside the pay-iff gate.

This is the ScopeGate property done right: authority is re-decided at the state
transition that actually confers value (payment), not merely stamped at grant.
A grant-time-only implementation would have been the `G_BROKEN` control in
`guards.py` — and Route 9's negative-control test shows such a guard is detectable.

---

## (ii) Is the predicate decidable, or does it depend on unverifiable inputs?

**The predicate is decidable. Its inputs are not independently verifiable.** These
are two separate facts and conflating them would overstate the guarantee.

**Decidable, total, cheap.** `capability_subset`
(`gyza/economy/delegation.py:157-194`) is a pure function: set inclusion on two
path sets, a boolean implication on network, and an integer comparison plus a
"must declare" rule on memory. `O(|paths|)`, no I/O, no recursion, always
terminates, no unverifiable oracle.

**Path comparison is exact-string set inclusion, and that is conservative.**
Probed directly:

| enforcement `ro_path` | vs manifest grant `/data` | result |
|---|---|---|
| `/data` | identical | admitted |
| `/data/` | trailing slash | **rejected** |
| `/data/../etc` | traversal | **rejected** |
| `/data/./sub` | subpath | **rejected** |

It is *not* prefix-containment, so a subtree grant must be written out exactly;
every non-identical string fails closed. This is the safe direction and is a
strength, not a bug — but it means the grant vocabulary is literal, and `/data`
does **not** imply `/data/sub`.

**The unverifiable part is upstream.** The `__enforcement__` record is stamped by
the host-side runner, which self-reports its own build
(`runner_trusted` / `gyza/trusted_releases.json`). `gyza verify` says so out loud:
`⚠ runner build is NOT a verified release — a malicious build could have stamped
a fictitious enforcement record.` So the predicate decides correctly over its
inputs; **soundness of the inputs rests on reproducible builds plus hardware
attestation, which Gyza does not yet have** — exactly as `README.md`'s honest-limits
section states.

### One precise gap worth recording

An empty (or non-dict) enforcement record is caught **iff the manifest declares a
memory cap**, because the "if outer declares a cap, inner MUST declare one" rule
is the only dimension with a *must-declare* asymmetry. Probed:

| manifest | `enforcement = {}` ⊆ manifest? |
|---|---|
| declares `memory_limit_mb: 512` | **False** — "grant caps memory at 512 MB but the inner spec declares no cap" ✓ caught |
| declares **no** memory cap | **True** — passes trivially |

The reason is structural: empty path sets are a subset of anything, and
`network=False` is never a violation, so with no memory cap there is nothing left
to trip. A manifest without a memory cap therefore accepts a content-free
enforcement record as compliant.

**Reported, not fixed** (this audit changes no security logic). The shape of a fix
would be either a presence/completeness check on the record at the call site, or
extending the must-declare asymmetry beyond memory. Note the practical exposure is
limited: `runner.py` already skips the gate entirely when the record is absent, so
this corner concerns a record that is present but empty, and `gyza verify`'s
manifest re-hash is a second, independent check on the same object.

---

## (iii) Does delegation-chain conjunction provably attenuate? — YES, with a theorem

**Theorem (authority attenuation).** Let `h_0 … h_k` be a chain accepted by
`verify_delegation`. Then `manifest(h_i) ⊆ manifest(h_0)` for every `i`, and
`enforcement(h_i) ⊆ manifest(h_0)`. Authority is **monotone non-increasing** down
the chain.

**Witness:** `gyza/economy/delegation.py:213-289`. At each non-root hop the
function requires all three of

```
1.  enforcement(h) ⊆ manifest(h)          (line 261)
2.  manifest(h)    ⊆ delegated(h)         (line 274)   -- blocks capability laundering
3.  delegated(h)   ⊆ manifest(parent)     (line 282)   -- parent can only pass what it holds
```

**Proof.** Induction on `i`. Base: `i = 0` is bounded by its own manifest by (1).
Step: assume `manifest(h_{i-1}) ⊆ manifest(h_0)`. By (2) and (3),
`manifest(h_i) ⊆ delegated(h_i) ⊆ manifest(h_{i-1})`, and `capability_subset` is
transitive, so `manifest(h_i) ⊆ manifest(h_0)`. Apply (1) for the enforcement
claim. ∎

This is a genuine **inductive authority invariant**, and it is the same shape as
Route 9's adequate guards: a predicate over state, enforced at every hop, whose
conjunction along the chain is free (the conjunction lemma).

**The load-bearing detail — transitivity is not free, and one rule buys it.**
`capability_subset`'s memory rule ("if `outer` declares a cap, `inner` MUST declare
one, and it must be ≤") is exactly what preserves transitivity. Verified by
counterfactual probe:

```
A(cap 64) ⊆ B(cap 128) ⊆ C(cap 256)   =>  A ⊆ C            ✓ transitive
A(cap 64) ⊆ B'(NO cap)  but  B' ⊄ C(cap 256)                <- the fold breaks
```

Without the must-declare clause, a single uncapped intermediate hop would absorb
the ancestor's cap and every descendant would be unbounded on memory. The
docstring at line 165 already claims this; the probe confirms it. **It should be
stated as a theorem with the code as witness, and the memory asymmetry named as
the reason the induction closes** — it is not a stylistic choice and must not be
"simplified" away.

`verify_delegation` additionally enforces **cycle detection** (no pubkey twice —
the mutual-farm attack) and a **depth bound** (`MAX_DELEGATION_DEPTH`), both of
which the R9 environment's `grant` channel makes concrete.

---

## Summary

| Question | Answer |
|---|---|
| (i) Per-action or grant-time-only? | **Neither layer is grant-time-only.** Execution bounds: once per work item (the right granularity), but **fail-open** when no record is stamped, disclosed at `gyza verify`. Delegation bounds: checked at grant time **and** again before payment. |
| (ii) Decidable? | **Yes** — total, pure, `O(\|paths\|)`, exact-string path inclusion that fails closed. **Inputs are not independently verifiable**: the enforcement record is self-reported by the runner, pending reproducible builds + TEE. One gap: an empty record passes when the manifest declares no memory cap. |
| (iii) Attenuation? | **Yes, provably** — theorem above, `verify_delegation` as witness, with the memory must-declare rule as the clause that makes `capability_subset` transitive. Plus cycle detection and a depth bound. |
| (iv) Consequence or authority? | **Authority only.** `memory_limit_mb` is the single true consequence bound; economic consequence is bounded separately by a G2-class monotone budget in settlement. No recoverability or drain invariant of the Route 9 kind exists anywhere in the codebase. |

**The one sentence that matters for Gyza's roadmap.** Gyza has a *sound and
provably attenuating authority invariant* and essentially *no consequence
invariant* — so Route 9's finding applies to it directly: adding a G4-class
conservation invariant over the credit ledger, or a G3-class recoverability
invariant over agent-visible state, is the missing lever, and Route 9's
permissiveness numbers say what such a guard would cost.
