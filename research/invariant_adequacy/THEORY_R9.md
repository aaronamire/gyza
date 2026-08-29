# Theory — additive bounds vs inductive invariants

The formal content behind `FINDINGS_R9.md`. Three parts: why the additive framing
makes consequence composition look open, why an inductive invariant closes it,
and — the part the measurement forced — **what "inductive" does not buy you.**

---

## 1. The additive bound and why it is salami-vulnerable

Fix a per-action harm function `h(s, a)` and a trajectory `τ = a_1 … a_n`. The
additive metric is

```
H(τ) = Σ_{i=1..n} h(s_{i-1}, a_i)
```

A guard enforcing `h(s, a) ≤ β` at every step gives exactly one global statement:

```
H(τ) ≤ n · β
```

This is **linear in `n` and unbounded as `n → ∞`**. Nothing stronger follows,
because the bound carries no information from step to step: the guard's decision
at step `i` is independent of everything that happened before. That is the salami
attack, stated as a theorem rather than an exploit. Route 9's G1 is this guard,
and the measured diagnostic curve is the theorem's graph: `H_drain` = 10, 50, 100,
250, 500, 1000, **2000** at `n` = 1, 5, 10, 25, 50, 100, 200 — exactly `n · β` for
`β = 10`.

---

## 2. The inductive invariant

Let `S ⊆ States` be a predicate and `g` a guard. Say `S` is **inductive w.r.t.
`g`** if

```
(INIT)  S(s_0)
(STEP)  ∀ s, a :  S(s) ∧ g(s, a)  ⇒  S(δ(s, a))
```

**Proposition 1 (n-independence).** If `S` is inductive w.r.t. `g` and every
executed action is `g`-admitted, then `S(s_i)` for every `i` along the trajectory.

*Proof.* Induction on `i`. `S(s_0)` by (INIT). If `S(s_i)` and `a_{i+1}` is
admitted, then `S(s_{i+1})` by (STEP). ∎

The conclusion mentions no `n`. Nothing accumulates; there is no `n · β`. This is
the prefix-closure of safety properties (Alpern & Schneider 1987) used as a proof
rule: a safety property is exactly one that is violated at a finite prefix, which
is what lets a per-step check discharge a whole-trajectory obligation.

**Definition (adequacy).** `S` is *adequate* for a harm measure `harm` at level
`H_max` iff `∀ s : S(s) ⇒ harm(s) ≤ H_max`.

**Corollary.** Inductive + adequate ⇒ `harm(s_i) ≤ H_max` for all `i`, independent
of `n`, from a per-action check.

Bitcoin's conservation of value is the existence proof: inductive, checked per
transaction, adequate for "coins minted", hence salami-proof by construction.

**Proposition 2 (conjunction lemma).** If `S_1` is inductive w.r.t. `g_1` and
`S_2` w.r.t. `g_2`, then `S_1 ∧ S_2` is inductive w.r.t. `g_1 ∧ g_2`.

*Proof.* Assume `(S_1 ∧ S_2)(s)` and `(g_1 ∧ g_2)(s, a)`. Then `S_1(δ(s,a))` by
`S_1`'s step rule and `S_2(δ(s,a))` by `S_2`'s. ∎

That proof is two lines, and that is the point: **inductive invariants compose for
free; additive bounds do not.** Adequacy composes componentwise too — if `S_1`
bounds `harm_1` and `S_2` bounds `harm_2`, the conjunction bounds both — which is
why a *single* invariant is adequate only for the harm class it was written for.
Route 9 measures exactly this: G4 flattens drain and leaves irreversibility linear;
only a conjunction containing G3 flattens both.

**Proposition 3 (authority attenuation — the Gyza instance).** If a relation `⊑`
on capability specs is transitive and a chain check enforces
`spec(h_i) ⊑ spec(h_{i-1})` at every hop, then `spec(h_i) ⊑ spec(h_0)` for all `i`.
*Proof:* induction, transitivity at the step. ∎ Witness and the non-obvious clause
that makes `⊑` transitive: `FINDINGS_GYZA_INVARIANT_AUDIT.md` §(iii).

---

## 3. What inductiveness does NOT buy — three results the measurement forced

This section is the contribution. The theory above is standard; these three are
what red-teaming the invariant actually taught, and two of them contradicted the
preregistered expectation.

### 3.1 Inductiveness is cheap. Adequacy and checkability are where the difficulty lives.

**Observation.** *Any* predicate `S` becomes inductive if the guard is defined as
`g(s,a) := S(δ(s,a))`. (STEP) is then a tautology.

So "our invariant is inductive" is close to content-free as a safety claim — G3 is
constructed exactly this way and is trivially inductive. The three substantive
questions are:

1. **Adequacy** — does `S` actually imply a harm bound?
2. **Checkability** — can `g` be decided cheaply per action?
3. **Permissiveness** — does `g` still admit useful work?

Route 9 measured all three because inductiveness alone predicts nothing. The
measured spread is stark: G1 costs 0.64 µs/check and bounds nothing; G3 costs
76.5 µs (≈120×) and bounds everything — at 0.625 permissiveness.

### 3.2 Inductive ⇏ adequate: the counter must track the harm, not the action shape

**The result.** G2's invariant `S(s) := c(s) ≤ B` is inductive and was **never
violated** — after three admitted actions the counter reads `c = 0.0` against
`B = 500`. The environment simultaneously measures `H_drain = 175000`, **100% of
the principal's holdings.**

The mechanism: `c` accumulates `estimated_drain`, which enumerates the *value-moving
action kinds* (`transfer`, funded `external_send`). The `reassign` action moves no
value; it moves the **ownership frame** over which "the principal's resource" is
defined. The counter is blind to it, so `S` is preserved while adequacy fails
completely.

**Generalization.** An invariant expressed over **actions** is not an invariant; it
is a filter. Only an invariant expressed over **state** can be adequate, because
harm is a function of state. G2 and G1 reason about action shapes and both leak;
G3 and G4 evaluate a predicate on the successor *state* and both hold. This
single distinction separates the adequate guards from the inadequate ones in
every cell of the experiment.

### 3.3 The frame must match: pin the invariant's frame and you unpin it from the harm

**The result, and it inverted the preregistered prediction.** The preregistration
predicted G4 (frame read from the current state) would leak through frame mutation
and G4′ (frame pinned at `s_0`) would hold. **The opposite is true.**

- **G4′ (pinned):** `H_drain = 175000`. Its predicate sums balances over the
  accounts that were principal-owned *at `s_0`*. `reassign` changes ownership
  without moving a balance, so the pinned sum is unchanged, the invariant holds,
  and 100% of the resource is gone.
- **G4 (current frame):** `H_drain = 50` — exactly the total authorized egress,
  flat in `n`. Its predicate reads the *current* owner map, which is the same frame
  the harm measure uses, so `reassign` registers as the loss it is and is rejected.

**The lemma this yields.** Let `harm` be evaluated over a frame `F(s)` (here: which
accounts count as the principal's). An invariant `S` is adequate only if it is
evaluated over the *same* frame. Pinning `S`'s frame to `F(s_0)` while `harm`
floats with `F(s)` creates a gap of exactly the mass the adversary can move
between frames — and moving mass between frames is generally a *cheaper* action
than moving mass within one.

The intuition that "pinning the frame is the conservative choice" is wrong, and it
is wrong in the dangerous direction. Pinning is conservative for the *predicate's*
stability and catastrophic for its *adequacy*.

---

## 4. What is NOT capturable this way — the competence bound

Everything above concerns harm that is a **function of state**: resource moved,
objects destroyed, information emitted. For those, a cheap state predicate can be
adequate, and Route 9 measures the price.

It says **nothing** about harm that depends on the **semantic content** of an
output. No state predicate distinguishes a correct answer from a confidently wrong
one, a sound plan from a subtly unsound one, or faithful code from code that
compiles and does the wrong thing. Deciding *that* requires understanding the
claim — which is precisely the **competence bound**
(`research/COMPETENCE_BOUND.md`), closed across six mechanism families and
**terminal**.

The two results are complements, and the division is clean:

| | mechanism | status |
|---|---|---|
| **Is the claim right?** | cheap black-box verification | **CLOSED — bounded by verifier competence.** Works inside competence (LR 19.8), collapses outside (LR 1.25). |
| **How bad can it be if it is wrong?** | inductive state invariant | **Bounded — at a measured permissiveness cost.** Route 9. |

Route 9 does not reopen the first question and does not depend on its answer. It
is the `v`-lever in `p · q · B ≥ g`: given that `q` is capped by competence, bound
`v` instead. The honest joint statement is that **an agent's actions can be made
provably containable while its judgment remains unverifiable** — and that the
containment is bought with permissiveness, not with cleverness.

---

## 5. Scope

The propositions are general. Every *number* is scoped to a simulated environment
with a hand-designed 7-action vocabulary and two hand-chosen harm measures; the
closed-form recoverability check that makes G3 cheap exists only because that
environment is small and fully observable. Limits are enumerated in
`FINDINGS_R9.md` §"What this cannot establish".
