# Is the carrier rule ENFORCED or DOCUMENTED? — and how far it mechanizes

**Branch `carrier-enforcement`.** Zero credits. No attestation authored.

---

## 0. GATE 0 — the current state, cited

### 0a/0b. **SOMETHING BETWEEN**, and the boundary is exact

> **The carrier VALUE is caller-supplied. What the refusal inspects is the
> verifier's SIGNATURE — never its body.**

| what | where | what it does |
|---|---|---|
| `SpecRecord.carrier` | `authority.py:227` | a plain `str` field, supplied by whoever registers |
| membership check | `authority.py:244-248` | the declared value must be in `("PROOF","SPEC","TEST")` — a check of a declaration against a constant |
| `check_carrier_claim` | `authority.py:316-332` | **INSPECTS `fn`** — refuses PROOF if the signature carries a parameter in `SAMPLING_PARAMS` |
| `check_claim_determinacy` | `authority.py:335-374` | **INSPECTS `fn`** — refuses PROOF/SPEC if the signature is variadic or has defaults |

So the second and third of the prompt's options are both partly true: the
refusal **does** derive something about the verifier, but only from its
**signature**. Nothing reads the body. **The rule "a verifier of an
underdetermined claim can only sample" is enforced exactly to the extent that
underdetermination is visible in the parameter list**, and no further.

### 0c. Does the read-set analysis add anything? **Yes — it is a different property**

Signature screens see *what the caller may pass*. They cannot see *what the
verifier reaches for on its own* — a closed-over threshold, a module constant, a
mutable global. That is a distinct question, so this is not duplication, and
Part A attempts it.

### 0d. **Zero credits.** Static analysis of code objects; no generation.

### 0e. The prompt's premises, checked

**Sixth and seventh premise failures, and they are load-bearing here:**

| asserted | tree |
|---|---|
| `credits_conserved` "caught by the rule" | **0 hits** across every `.py` and `.md` |
| `memory_bound`, `capability_check`, `session_dag` | **1 hit each — my own `FINDINGS_CARRIER_RULE.md` recording that they do not exist** |
| "all 21 entries" | **18** |
| "the four PROOF→TEST corrections" | **never happened** — committed finding: *"No mislabelled PROOF entries. Zero."* |

**A3 cannot be run as written**, because the cases it names to retrodict against
do not exist. It was run against the **real** registry and against **synthetic
positive controls of the shape described**, which is the closest honest
substitute and is reported as such.

---

## 1. PART A — WHAT IS MECHANICALLY DECIDABLE

### 1a. A2 — the approximation direction, stated first because it is load-bearing

`gyza/verification/reads.py` reads a function's code object and partitions what
it touches into **CODE** (functions, classes, modules — calling a pure function
is not reading ambient state) and **DATA** (a constant, a global, a closed-over
value — these parameterise the verdict without appearing in the claim).

> **unresolvable → treated as UNNAMED DATA → flagged as sampling.**

That is the **conservative** direction: over-approximating refuses too much
(noisy but safe); under-approximating admits a mislabelled PROOF, which SR-3
measured composing at **0.000** and which stays invisible until depth.

**Constructs that could not be resolved, enumerated, and how each was handled:**

| construct | handling |
|---|---|
| `getattr` / `globals` / `vars` / `eval` / `exec` / `__import__` | **conservative** — counted as unnamed state, counted in `n_conservative_defaults` |
| a name absent from `__globals__` and from builtins | **conservative** |
| a callable with no `__code__` (C builtin, partial, `__call__` object) | **conservative** — the whole verifier is flagged |
| indirection through a dict or registry | **conservative** (the container is the read) |
| calls beyond `depth` | **NOT conservative — the one under-approximation**, disclosed by `truncated_at_depth`, which names every call not followed |
| attribute reads on **passed-in** objects | **not ambient** — the object is named by the claim, so `market.capital_entries()` is a read of a named parameter |

**Conservative defaults fired: 1 across all 16 verifiers** (`getattr` in
`_envelope_dag`). **MEASURED.**

### 1b. A defect in my own first version, found and fixed

The first implementation scanned only `LOAD_GLOBAL`. **Every adapter in this
codebase imports inside the function body** (`from gyza.icp import
verify_envelope`), which binds a *local* — so the scan saw the adapter shell and
**none of the verifier**, reporting `defaults=0` and `truncated=0` for all 16.

> **That is the DANGEROUS direction — an under-approximation that made every
> verifier look clean.** It was caught by the tell that no real analysis reports
> zero unresolved reads on sixteen functions. Fixed by following `IMPORT_NAME` /
> `IMPORT_FROM`; a test now asserts the delegate resolves.

### 1c. A3 — retrodiction against the hand classification

**Positive controls (the shape the rule was derived from) — the mechanism has
demonstrated power:**

| control | result |
|---|---|
| closed-over threshold (`make(100)` → `value <= threshold`) | **CAUGHT** — `closure_data = {threshold}` |
| module-level mutable config | **CAUGHT** — `global_data = {MODULE_CONFIG}` |
| pure recomputation `a == b` | not flagged ✅ |
| calls an imported pure function | not flagged ✅ — *code is not state* |
| dynamic `getattr` | flagged, `n_conservative_defaults ≥ 1` ✅ |

**On the live registry (depth 2):**

| | |
|---|---|
| **flagged fraction** | **2/16 = 0.1250** |
| **true positives** | **0** |
| **false positives** | **2** |
| **false flags on the recomputing five** | **0** ✅ |
| conservative defaults fired | **1** |

| entry | flag | diagnosis |
|---|---|---|
| `memory_retrieval_relevance` | `verify_retrieval_claim.FILTER_SUCCESS_ONLY` | **FALSE POSITIVE.** A module-level **vocabulary token** compared against `claim.filter_predicate` — a field the claim **does** name and validates. Genuinely PROOF-carried |
| `envelope_dag` | `getattr` | **FALSE POSITIVE / conservative default.** Fires on `getattr(res, "valid", res)` over a *returned* object, not ambient state. Separately and correctly refused by the determinacy screen for a different reason (`**kw`) |

**Precision = 0/2 = 0.0000. Recall against genuine unnamed-state reads in this
registry = undefined — there are none to find.**

**Diagnosing both clean numbers:**
- **Zero true positives is MEASURED and is a fact about this codebase, not
  about the analysis** — the positive controls show it fires when there is
  something to find. Gyza's verifiers are hash/signature recomputation and
  folds over passed-in arguments; none closes over a policy value.
- **Zero false flags on the recomputing five is the result that matters**, and
  it is the one thing that would have made the mechanism unusable outright.

**The counter-metric beside recall:** a checker that flagged everything would
have perfect recall and no value. This one flags **12.5%** — but **100% of its
flags are false**, so its precision, not its recall, is what disqualifies it.

### 1d. A4 — **THE VERDICT: SCREENING-ONLY**

> **Not ENFORCEABLE, and the decisive fact is not the flag rate — it is that
> wiring it would REFUSE A CORRECT ENTRY.**
>
> `memory_retrieval_relevance` is a genuinely PROOF-carried verifier that
> recomputes the whole neighbour set. A gate built on this analysis would refuse
> it. A guard that refuses correct entries is not conservative; it is wrong, and
> it would push authors to launder the code until the screen shuts up.

**What SCREENING-ONLY licenses:** the analysis is a **triage tool**. On this
registry the triage burden is **2 entries requiring human diagnosis, of 16** —
low in absolute terms, but every one of them a false alarm, so the tool
currently costs review time and returns nothing.

**Per B3, no partial gate was built.** `test_the_analysis_is_not_wired_into_the_
refusal_path` asserts `SpecAuthority.register` does not reference it, so a
future session cannot quietly "finish the job."

> **Therefore: the carrier remains DECLARED UNDER ATTESTATION. The registry
> provides NON-REPUDIATION for carrier claims, not prevention — the same weaker
> property the attestation itself has.**

---

## 2. PART B — the status is now explicit at the point of registration

**B1.** Every registration records `carrier_assurance`, and `audit()` reports it:

> *"DECLARED-UNDER-ATTESTATION — screened one-directionally against the
> verifier's SIGNATURE (sampling parameters, variadic/defaulted policy). NOT
> verified to recompute; the attester takes responsibility for the carrier
> claim."*

A reader of the registry can now tell **PROOF was declared, not verified**,
without finding this document. **B2 does not apply** (the verdict is not
ENFORCEABLE). **B3 applies and was followed.**

The consequence is stated as an executable fact rather than prose:
`test_a_verifier_that_reads_unnamed_state_STILL_REGISTERS` constructs the
closed-over-threshold defect, confirms the analysis detects it, and then
**registers it successfully**. The registry does not prevent this. It records
who answered for it.

---

## 3. What was built

- `gyza/verification/reads.py` — read-set analysis, conservative on every
  unresolvable construct, with `n_conservative_defaults` and
  `truncated_at_depth` reported rather than hidden.
- `gyza/verification/authority.py` — `CARRIER_ASSURANCE` recorded on every
  registration and in `audit()`. **The refusal path is unchanged.**
- `tests/test_reads.py` — **15 tests**: 5 positive controls, 3 approximation-
  direction tests, 5 measurement tests, and 2 that pin SCREENING-ONLY.
- **156/156 pass** across eight suites, run sequentially.

## 4. Honest limits

1. **`truncated_at_depth` is the one under-approximating axis.** Beyond the
   depth bound, reads are invisible. At depth 2 truncation is empty for 14 of
   16 entries, but "empty at this depth" is not "there is nothing deeper."
2. **The CODE/DATA partition is authored judgement.** Treating a module-level
   *constant* as unnamed state and a module-level *function* as not is the call
   that makes the analysis usable — and it is exactly the call that produced the
   `FILTER_SUCCESS_ONLY` false positive. A constant used as a vocabulary token
   is indistinguishable, to this analysis, from a constant used as a threshold.
3. **Precision 0.0000 is measured on n = 2 flags.** It is enough to disqualify
   the analysis as a gate (one false refusal of a correct entry is sufficient)
   but it is not a well-powered precision estimate.
4. **The analysis reads Python code objects.** It says nothing about the Rust or
   Go implementations of the same properties.
5. **The rule itself remains DOCUMENTED, not enforced**, for the read-set half.
   The signature half — sampling parameters and variadic/defaulted policy — *is*
   enforced, and that is the honest division: **the registry mechanically
   refuses verifiers whose SIGNATURE announces the defect, and takes an
   attester's word for everything else.**
