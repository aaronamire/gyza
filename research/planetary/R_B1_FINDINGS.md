# R-B1 — the conservation taxonomy: **TRANSFER-IS-CONFINED**

All three predictions in `PROGRAM.md` §6 confirmed. The classification is
**derived** from two structural facts per quantity, never assigned — pinned by
test, and mutation-checked.

---

## The result

| outcome | count | quantities |
|---|---|---|
| **EXTINGUISHES** | **6/10** | content loss, key-rotation unreachability, outstanding delegated authority, storage growth, guard permissiveness, signed-envelope count |
| **TRANSFERS** | **2/10** | H1 credits, H2 market capital |
| **ALREADY_REALIZED** | 2/10 | H4 authority, emission volume |

> ### The conserved set is exactly `{H1_credits, H2_market_capital}` — and only H1 exists in production.

## Why this matters more than the count suggests

Two turns ago I told you consequence bounding *"transfers harm rather than
removing it"* and treated that as a general blocker on the vision. **That was
too strong, and this is the correction.**

The transfer property follows from **conservation**, definitionally: if what
leaves one frame enters another, then reducing the quantity inside your frame
*is* increasing it outside. Nothing about harm bounds in general produces that —
only conservation does.

Gyza's vocabulary contains exactly two conserved quantities, both economic, and
`BondedMarket` has zero production constructors. **So the harm-transfer problem
affects exactly one production quantity, and six of ten declarable quantities
genuinely remove harm when bounded.**

## The measured discriminant

The classification is not a table of opinions. Conservation is testable, and the
two signatures are opposite:

| | preventing the movement |
|---|---|
| **credits** (conserved) | total over all frames **UNCHANGED** — payer saves exactly 60.0, earner loses exactly 60.0. The harm went somewhere |
| **storage** (not conserved) | total over all frames **LOWER** — no counterparty gained an event. The harm did not happen |

Both measured against real objects (`Wallet` over `LedgerEntry`,
`AppendOnlyLog`). If the two behaved alike the taxonomy would separate nothing;
`test_the_taxonomy_is_not_degenerate` pins that all three outcomes stay
populated, and a mutant asserting storage is conserved fails the classification
test.

## ALREADY_REALIZED is the class nobody had named

H4 and emission volume are neither transferred nor extinguished: **the harm
occurs before the guard can act.** The runner refuses to sign an over-bound
execution, but the sandboxed work already ran; a guard can refuse to emit, but
after emission containment has no meaning (C15).

For this class a bound buys **non-repudiation, not containment** — which is
valuable and is a different product claim. Calling it containment would be the
overclaim this taxonomy exists to prevent.

## Consequences

1. **The outlook for `c` improves substantially.** Six of ten declarable
   quantities genuinely extinguish, so raising containment coverage is not
   poisoned by the transfer result — it is bounded away from one class.
2. **R-C2's conjecture is now well-scoped.** "Bound the distribution rather than
   the level" applies to conserved quantities, and there are exactly two.
3. **Prioritise the EXTINGUISHES six.** Every one of them, modelled, raises `c`
   with real removal rather than relocation. `H3_content_loss` and
   `storage_growth` are the two with computable state functions already
   identified in `HARM_MODEL_GAP`.
4. **Stop describing transfer as a general property of harm bounds.** It is a
   property of conserved substrates. Any document saying otherwise — including
   my own summaries from 2026-08-14 — overstates it.

## Limits

n = 10 quantities, from one vocabulary, classified by the person who proposed
most of them. The **conserved** half rests on a definitional argument and two
measured signatures; the **prevented** half is a judgement about where the guard
sits in each code path and is the weaker leg. A quantity I have misjudged as
preventable would move from ALREADY_REALIZED to EXTINGUISHES and flatter the
result.
