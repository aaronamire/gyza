# Findings — Route 12: mechanical channel discovery

Write-up per `PREREGISTRATION_R12.md` (committed `88a72b0`, before the analyzer
source and every result artifact). R9's central negative result was that an
unmodelled channel destroyed adequacy while the invariant held; R9 §7 called that
"a reason to distrust generalization, not to trust it." R12 asks whether blind
channels can be found **mechanically, before adversarial testing**.

Zero credits. Static analysis plus deterministic simulation, no model calls
anywhere on the path. All prior decisions stand; `research/invariant_adequacy/`
was imported read-only and never modified.

---

## DECISION: **UNSOUND**

The criterion **misses real blind channels**, on preregistered fresh data.

| | B1 retrodiction | **B2 prediction (the real test)** |
|---|---|---|
| witness-level recall, V1 | 0.25 (2/8) | **0.50 (4/8)** |
| witness-level recall, V2 | 0.50 (4/8) | **0.50 (4/8)** |
| precision | 1.00 | **1.00** |
| flagged fraction | 0.071 / 0.089 | 0.054 / 0.080 |
| vacuous? (>0.5 flagged) | **no** | **no** |

Recall < 1.0 on both parts ⇒ **UNSOUND** by the preregistered rule. The analyzer
is not vacuous — it flags 5–9% of triples, never produced a false positive, and
its flags were always correct. **It simply cannot see most real channels.**

**What this means, stated as the preregistration requires:** containment adequacy
**cannot** be certified mechanically by this criterion. Every containment claim
remains only as good as a **hand-enumerated harm model**, and must be labelled as
such. R9's result does **not** generalize beyond its simulator on the strength of
static analysis.

This is the more consequential outcome, and it was the recorded expectation: the
preregistration's derived structural section predicted UNSOUND with V1 ≈ 3/8 and
V2 ≈ 5/8 (actual 2/8 and 4/8 — the one-unit offset is a `G0`-inclusion bookkeeping
difference, disclosed in §6). The three miss mechanisms named there are exactly
the three observed.

---

## 1. B2 — prediction on the extended vocabulary (THE HEADLINE)

Seven new actions (`alias`, `set_principal`, `merge_accounts`, `snapshot`,
`restore`, `revoke_grant`, `escrow`) added to a **copy** of R9's environment. R9's
`guards.py` and `adversaries.py` executed **verbatim** — `run_r12` binds the module
name `environment` to the extended module before importing them, so `from
environment import ...` inside unmodified R9 source resolves to the extended
world. Analyzer flags were committed **before** the adversaries ran.

**Witness-level recall 0.50, precision 1.00, flagged fraction 0.054–0.080** (both
variants). The four false negatives:

| missed pair | actual witnessing action | why the analyzer said NOT-BLIND |
|---|---|---|
| G4′ · `h_drain` | `set_principal` | guard "sees" `principal` — **over-approximation** through the unresolved `if self.pinned` branch |
| G4 · `h_irrev` | `delete`, `external_send` | guard reads `objects` via `physically_valid` / `apply` |
| G4′ · `h_irrev` | `delete`, `external_send` | same |
| G2+G4 · `h_irrev` | `delete`, `external_send` | same |

The G4′ · drain miss is the sharpest single result in the route: **the analyzer
declared a guard sighted, on fresh preregistered data, and one `set_principal`
action then took 100% of holdings under that exact guard.** It is caused by
precisely the failure direction the preregistration flagged as dangerous —
over-approximating `READS(g)` makes guards look more sighted than they are.

### The new channel that worked

`set_principal` is a **one-action total-loss** channel for G0, G1, G2 and G4′:
`h_drain` = 175000 = 100% of holdings at `n = 1`. Every R9 guard tests the module
constant `PRINCIPAL`, while the harm measure reads the state field `s.principal`.

### Did any guard that was flat in R9 now grow? **No.**

| guard | drain @200 | irrev @200 | recoverable |
|---|---|---|---|
| G0 / G1 / G2 / G4′ | 175000 | 129–134 | no |
| G4 / G2+G4 | 50 | 129 | no |
| **G3 / G2+G3 / G3+G4′** | **0** | **0** | **yes** |

The extended vocabulary made the attack **faster** (1 action instead of 3) but
opened no new successful channel against the adequate guards. G3 blocked
`set_principal`, `escrow`, `merge_accounts`, `restore` and `alias` alike; A2 found
no unrecoverable state within depth 12. R9's positive result survives a vocabulary
it was never tested against — a genuine, if narrow, piece of external validity.

### Hand vs analyzer: 3 disagreements, all **hand error**

| action | guard | hand | analyzer | diagnosis |
|---|---|---|---|---|
| `set_principal` | G3, G4, G4′ | BLIND | NOT-BLIND (`sees=['principal']`) | **hand was wrong** |

My hand table said no R9 guard reads `principal` because they all use the module
constant. Wrong: G3 and G4 call the *environment's own* `principal_total` /
`recoverable`, and so inherit the harm measure's frame transitively. **Guards that
reuse the environment's accounting are automatically frame-aligned** — a design
insight that falls out of the disagreement, and the analyzer beat me to it.

Preregistration predicted `escrow` would be the likeliest disagreement. It was
not; `set_principal` was. Disclosed.

---

## 2. B1 — retrodiction (weak evidence by construction)

**Read this section as weak.** It is retrodiction on n = 9 configurations against
a result that already exists, and it could in principle have been reverse-engineered.
B2 above is the real test. B1's value is diagnostic, not evidential.

Witness-level **recall 0.25 (V1) / 0.50 (V2)**, precision 1.00, flagged fraction
0.071 / 0.089. Ground truth and witnessing actions were derived from R9's
committed `r9_result.json` and `_scripted.json` — read by the **evaluator**, never
by the analyzer (GATE 0b, §5).

### Pair-level recall (0.50) OVERSTATES the analyzer, and this is an artifact-class trap

Scoring "did the analyzer flag this (guard, harm) pair at all" gives V1 recall
0.50. Scoring "did it flag via the action that actually caused the leak" gives
**0.25**. The gap is entirely G1 · `h_drain` and G2 · `h_drain`, which were
"hit" via `external_send` and `transfer` while R9's demonstrated witness was
`reassign`. **Right pair, wrong channel.** Reporting only the pair-level number
would have doubled the apparent recall on a coincidence. Witness-level is the
honest metric and is used everywhere above.

### The three miss mechanisms (all predicted in §5 of the preregistration)

1. **Incidental reads.** `estimated_drain`'s first line is `own = s.own`
   (`guards.py:35`), so G1 and G2 *syntactically* read the very field they are
   blind to — they read `owner` at keys named by the action (`a.src`, `a.dst`), and
   `reassign` names none. **The task's stated retrodiction target asserts "G2's
   predicate reads only action kinds"; the code does not do that.** V2's dead-read
   elimination recovers these two (V1 0.25 → V2 0.50).
2. **Feasibility reads.** `physically_valid` reads `balances`, `owner`, `objects`
   unconditionally as a precondition check, so every guard calling it looks
   sighted regardless of whether its harm arithmetic depends on those fields. Live
   on the relevant path, so V2 does not help.
3. **Successor simulation.** G3 and G4 compute `apply(s, a)` and evaluate a
   predicate on the successor; simulating a transition touches essentially every
   field. **These guards can never be flagged.**

### The structural result: discriminating power is anti-correlated with guard quality

Mechanism 3 is the general statement. The criterion can only speak about guards
written as **syntactic action filters** — G1 and G2, exactly the guards R9 showed
to be *inadequate* — and is uninformative about guards written as
**successor-state predicates** — G3 and G4, exactly the *adequate* ones. A static
audit is most confident precisely where it matters least.

**Why the criterion cannot be repaired by refinement:** blindness is a question
about whether the guard's *decision* depends on a field the way the *harm* does.
That is semantic dependence, not syntactic mention. V2 (path-sensitivity + dead-read
elimination) recovers exactly the cases where the read is syntactically dead, and
nothing more. Deciding the general case means deciding whether the guard handles
the field correctly — **which is the adequacy question the check was supposed to
replace.** The cheap mechanical check re-imports the hard question, the same shape
as R5's extraction stage and R8's test-writing stage. Per the preregistration, **no
third variant was built after seeing results.**

---

## 3. The analyzer's approximation direction (A4, load-bearing)

| quantity | direction | consequence |
|---|---|---|
| `WRITES(a)` | **over**-approximate (every field named as a `_with`/`replace` keyword on any path of the branch, changed or not) | mixed: enlarges both intersections |
| `READS(h)` | **over**-approximate | safe — more actions qualify as channels |
| `READS(g)` | **over**-approximate wherever a branch cannot be resolved | **DANGEROUS** — guards look more sighted, blind channels are missed |

The `READS(g)` row is not hypothetical: it caused the G4′ · drain false negative
in B2. The `if self.pinned:` branch of `_Conservation._total` is unresolvable
statically, so the analyzer unions both arms and inherits `principal_total`'s
read of `principal` — attributing to the pinned guard a sightedness only the
unpinned one has.

**Constructs that could not be resolved, and how each was handled:**

| construct | handling |
|---|---|
| `if self.pinned:` (instance-attribute branch) | both arms unioned — **over-approximates `READS(g)`**, the dangerous direction; the sole cause of the G4′ miss |
| dynamic attribute access / dict-key indirection | root expression unresolvable ⇒ **excluded** from `READS(g)` and counted in `unresolved` (conservative, errs toward flagging BLIND) |
| `events` read via `apply`'s `events = s.events` | recorded as `events:*`, which does **not** set-match any concrete `events:<kind>` — an **under**-approximation of `READS(g)`, i.e. the safe direction, retained deliberately per the preregistration's conservative default |
| reads through `apply(s, a)` | attributed to the root state parameter — a read of the successor's field counts as observing that field |

**The conservative default fired 0 times** on both R9 and the extended
environment (`unresolved = 0` on every guard). So the analyzer's misses are **not**
caused by unresolvable syntax; they are caused by the criterion itself. That is
the cleanest available evidence that this is a conceptual limit rather than an
engineering one.

---

## 4. BFS validation — the preregistered disagreement fired

`snapshot` + `delete` of a last-copy content: **closed form says unrecoverable,
brute-force BFS says recoverable** (the principal can `restore`). Reported, **not
patched**, per the preregistration.

| case | closed form | BFS | agree |
|---|---|---|---|
| **snapshot, then delete last copy** | **False** | **True** | ✗ |
| alias, then delete original | True | True | ✓ |
| delete last copy (no snapshot) | False | False | ✓ |
| escrow | False | False | ✓ |
| merge principal accounts | False | False | ✓ |
| set_principal | False | False | ✓ |

The disagreement is in the **conservative** direction: G3 refuses an action that
is in fact reversible, costing permissiveness rather than safety. R9 already had
to strengthen this predicate once (its disclosed correction #1, also caught by BFS
validation). **Two independent breakages of the same closed form, from two
different vocabulary extensions, is the finding**: closed-form reachability is
fragile under vocabulary change, and R9's own warning that "real systems require
an approximation, and the guarantee degrades with it" is now demonstrated rather
than asserted.

My preregistration attributed the predicted break to `alias`. `alias` agreed;
`snapshot`/`restore` broke it — a candidate the preregistration did name. Half
right, disclosed.

---

## 5. Part C — Gyza's credit ledger

Full detail with `file:line` witnesses in `FINDINGS_GYZA_CREDIT_CHANNELS.md`.

- **No blind channel exists in the bilateral ledger**, and the reason is
  architectural: a balance is a **pure fold over signed entries**
  (`wallet.py:171`), not a mutable pot, so every path that changes a balance must
  write a `LedgerEntry` and the gate reads exactly those fields. In R9's terms
  this is the **G4 pattern** (guard reads the frame the harm reads), not the G2
  pattern. A clean result, stated plainly.
- **The `reassign` / `set_principal` analogue does not exist**: no compositor
  rotation, no ownership transfer, `_owner` set once (`subcontract.py:172`).
- **F1 LATENT** — `BondedMarket._capital` (`market.py:287/325/332/345`) is a second
  credit-like pool the gate never reads. Not a leak today (no bridge to
  `LedgerEntry` exists), but `market.py:21-23` states the roadmap is to make it the
  multilateral settlement layer. **When that bridge is built it becomes exactly
  R9's G2 failure.**
- **F2 LATENT** — `settlement.py:71-72` defers "rotation of the compositor key (a
  settled entry references the key valid at the moment of signing)." That sentence
  *is* R9's frame lemma. Implemented naively it reproduces **G4′**: history pinned
  to the old key, gate reading the new one.
- **C5, the most important finding: Gyza has no written-down harm model.** A search
  of `gyza/` and `docs/` for a declared harm measure returns nothing. The harm
  measure used in the C3 analysis had to be **reconstructed from the gate**, which
  is circular in exactly the way R9's GATE 0b forbids — disclosed there rather than
  hidden. Irreversibility, R9's second harm class, is unmodelled anywhere in the
  economic layer.

---

## 6. Corrections and disclosures

- **Preregistration hand-prediction offset.** My §5 derived table gave V1 3/8 and
  V2 5/8; measured witness-level values are 2/8 and 4/8. The difference is that my
  hand count included `G0` in the denominator while the reported figures exclude
  the unguarded baseline (reported both ways in `r12_result.json`). The direction,
  the mechanisms, and the UNSOUND verdict were as predicted.
- **Two preregistered point predictions were wrong, both disclosed above:**
  `escrow` was predicted the likeliest hand/analyzer disagreement (it was
  `set_principal`); `alias` was predicted to break the closed-form recoverability
  predicate (it was `snapshot`/`restore`, also a named candidate).
- **`PREREGISTRATION_R12.md` was not edited.** No criterion, variant, vocabulary,
  or threshold changed after data. No third analyzer variant was added.
- **One implementation fix**, before results: `classify` was called with a `dict`
  rather than a `set` in one test, raising `TypeError`. Test-side only.
- **Suspicious-number check.** Precision is exactly 1.00 in every cell. Diagnosed:
  the analyzer flagged 8 triples in B1 and 6 in B2, and every flag corresponded to
  a demonstrated leak. With flagged fractions of 5–9% this is a small-numbers
  result, not evidence of a well-calibrated detector — it is reported as
  `n_flagged` beside the ratio for exactly that reason. Precision 1.0 on 6 flags is
  not a strong claim and is not presented as one.

---

## 7. What this cannot establish

- One small hand-written Python environment plus one real codebase. The AST rules
  (`_with`/`replace` keyword sinks, literal event tags, `a.kind` branch tests) are
  tuned to this coding style; a differently-written environment would need
  different extraction and might fail for reasons unrelated to the criterion.
- It cannot find harm channels in effects that **leave the modeled state entirely**
  — network side effects, out-of-band coordination, anything the environment does
  not represent. R9's whole lesson was about unmodelled channels, and a static
  analysis over the model is definitionally blind to what the model omits. **A
  clean R12 report is not evidence of containment.**
- It says nothing about **semantic-content harm** — that is the competence bound
  (`research/COMPETENCE_BOUND.md`), closed across six families, terminal, and
  untouched here.
- **The criterion is one-sided.** Every NOT-BLIND result above — including Part C's
  clean bilateral-ledger finding — means only "not provably blind." It never means
  adequate. `test_criterion_is_one_sided_guard_reads_but_ignores` pins a guard that
  reads a field, ignores it entirely, and is correctly classified NOT-BLIND.

---

## 8. What this does establish

**Blind channels are not mechanically discoverable by field-intersection static
analysis.** The criterion is sound in the direction it claims (precision 1.00, no
false positive in 14 flags across both parts) and **misses half the real channels**,
including one that took 100% of holdings in a single action on fresh preregistered
data.

The failure is conceptual, not an engineering shortfall — the conservative
unresolvable-syntax default never fired. **Blindness is semantic dependence; the
criterion tests syntactic mention.** Closing that gap means deciding whether a
guard handles a field correctly, which is the adequacy question the check was meant
to replace.

Three consequences that stand:

1. **R9's scoping holds.** "Adequacy here does not transfer to real deployments
   with unmodelled effect channels" cannot be repaired by static analysis. Every
   containment claim must name its hand-enumerated harm model.
2. **Static screening is most confident where it matters least.** It can only
   analyze action-filter guards — the inadequate ones — and is silent on
   successor-simulation guards — the adequate ones.
3. **For Gyza specifically, the binding constraint is upstream of any analyzer:
   there is no written harm model to check against.** Writing one down — the
   quantities, their frames, and the bound claimed for each — is the prerequisite
   for any mechanical audit, and it does not exist today.
