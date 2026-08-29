# Respecification — two claim types moved out of NO_VERIFIER

**This is a design change to the shipped system, not a route.** The lever is
*what the agent is asked to claim*, not *how hard an unverifiable claim is
checked* — AR-2 closed the checking lever (a type-level envelope recovers 18.6%
of genuine failures at the only affordable granularity).

Both types **PASS rule 3d**: the restated claim still asks for something useful.
Both are registered PROOF-carried in V-1. 13 tests green.

---

## The binding criterion, met: each verifier rejects a REAL divergence

A verifier that has never rejected anything real has no demonstrated power, and
registering it would be relabeling. **Neither divergence below is a synthetic
mutant — both were found by reading `gyza/memory.py` and both are live in
shipped code.**

### D1 — the LanceDB over-fetch (caught)

`_LanceBackend.search` over-fetches `max(4k, 16)` candidates
(`gyza/memory.py:317`) and `retrieve_similar` applies the success/threshold
filter **afterwards** (`gyza/memory.py:438-446`). The SQLite path scans
everything (`gyza/memory.py:432-437`). So with `k=5` the Lance window is 20: if
the 20 nearest episodes are all unsuccessful, **the Lance backend returns
nothing while qualifying successful episodes exist**, and the SQLite backend
returns them. Same corpus, same query, different answers, no error raised.

Reproduced in `test_POWER_the_verifier_catches_the_real_lance_overfetch_divergence`
against the **real** `_LanceBackend` (lancedb 0.30.2, 384-dim vectors, 30 near
failures + 10 further successes). The verifier **rejects** the Lance-derived
claim and **accepts** the exhaustive one.

### D2 — un-normalized cosine (caught)

The Lance path scores `np.dot(query_vec, ep.task_embedding)` against the
**stored** vector (`gyza/memory.py:323`); the SQLite path normalizes first
(`gyza/memory.py:434`). For embeddings that are not unit-norm at write time the
two backends **rank differently** — magnitude, not direction, decides. A vector
with cosine ≈ 1.0 and norm 0.05 loses to one with lower cosine and norm 6.0.

The verifier rejects the un-normalized ranking and accepts the normalized one.

### D3 — sender hashing its INTENT (caught)

`test_POWER_a_sender_hashing_its_INTENT_rather_than_the_wire_is_caught`: a
claim whose `artifact_hash` is computed from what the sender *meant* to send
(a stale buffer: v2 intended, v1 emitted) **fails** against the emitted bytes.
This is S5 B3's circularity at the send boundary — a hash the sender computes
from its own intent is self-report at a finer grain.

---

## Part A — `memory_retrieval_relevance`

**A1. Before.** Produced by `EpisodicMemory.retrieve_similar`
(`gyza/memory.py:402-446`), consumed by `format_as_few_shot`
(`gyza/memory.py:447`). It asserted "these memories are relevant." **Nothing
checked it** — `NO_VERIFIER` in V-1.

**A2. The restatement.** `RetrievalClaim` (`gyza/verification/respec.py:86`):

> the returned set is exactly the first `k` items, in descending `metric` order,
> of the candidates in snapshot `corpus_snapshot` that satisfy
> `filter_predicate` and score ≥ `threshold`.

`metric`, `k`, `threshold`, `filter_predicate` and the **content-addressed**
`corpus_snapshot` are part of the **claim**, not the implementation. The old
code carried all of them implicitly, which is exactly why nothing could check
it. A claim missing any is **rejected at construction** (`IncompleteClaim`),
never defaulted.

**The corpus snapshot is the immutable frame** — artifact #13's species in this
domain. A claim whose reference set can move is not checkable: the verifier
cannot reproduce a neighbour set over a corpus that has since changed.
`corpus_snapshot_digest` content-addresses the exact candidate set, and a moved
corpus is **refused**, not silently re-ranked
(`test_a_moved_corpus_is_REFUSED_the_immutable_frame`).

**A3. The verifier.** `verify_retrieval_claim`
(`gyza/verification/respec.py:124`) **recomputes** the neighbour set — which is
what makes it PROOF-carried rather than sampled — and compares membership and
order, with a deterministic id tie-break so a tie cannot make a correct
implementation look divergent.

**A4. What the restatement loses, and the actual trade.**

> **Lost: whether nearness under M *is* relevance.**

The trade is not "we gave up relevance." It is: **that judgement moves from
per-query (unverifiable, every single time) to once, by a human, when M is
chosen.** One reviewable decision replaces an unbounded stream of unreviewable
ones.

**What would make it a BAD trade:** a domain where M is a poor proxy —
retrieval over negation ("cases where X did *not* apply"), over recency-
dominated relevance, or over any corpus where surface similarity and task
relevance diverge. In such a domain the claim would be perfectly verifiable and
would certify the wrong set every time, which is rule 3d's failure mode. Gyza's
use is few-shot retrieval of *similar past tasks*, where embedding similarity is
a defensible proxy — but that is a **judgement about this deployment**, not a
property of the mechanism.

**3d verdict: PASSES.** The restated claim still buys reproducibility,
auditability, and — demonstrated above — the ability to catch two live retrieval
bugs that would otherwise be silent.

---

## Part B — `external_send_content`

**B1. Before.** `gyza/network/netd_client.py`: `publish_agent:316`,
`send_message:461`, `publish_delta:928`, `publish_attestation:1122`. Claimed
"the right content was sent." **Nothing checked it** — `NO_VERIFIER`.

**B2. The restatement.** `SendClaim` (`gyza/verification/respec.py:164`):

> the bytes that left were artifact `artifact_hash`, under policy `policy_id`,
> to `destination`, at `timestamp_ns`, of length `n_bytes`.

**Content-addressing is reused, not reinvented** — `wire_digest` is the same
BLAKE3 discipline as the PROOF-carried `artifact_content_address`
(`gyza/network/artifact_store.py:47`).

**The hash binds to the bytes on the wire.** `verify_send_claim` is *given the
emitted bytes*, so the claim cannot stand in for them. A sender that computes
the hash from what it intended is caught (D3).

**B3. The verifier.** `verify_send_claim` (`gyza/verification/respec.py:196`):
hash comparison against emitted bytes, a length check, then a
policy-satisfaction predicate over `(claim, bytes)`. **The policy is
caller-supplied and deliberately not authored here** — a policy this module
wrote for the sends this module checks would be the tautology the whole design
guards against.

**B4. What it loses.** Whether sending was a good idea.

**Containment ends at emission regardless (C15)** — a guard can refuse to
*emit*; after emission containment has no meaning and no detector helps. So
non-repudiation of **what left** is close to the whole of what is obtainable at
that boundary. **This restatement loses less than it appears to**, because the
thing it gives up was never available.

**3d verdict: PASSES.**

---

## Part C — the two that should NOT be respecified (worked examples of 3d)

Recorded in `adapters.py` above `NO_VERIFIER` so a future reader meets them
before proposing a third respecification.

> **VERIFIABLE AND KNOWN NOT TO DELIVER IS NOT A WIN.** This is the discipline
> that keeps respecification from becoming relabeling.

**`routing_match_quality`.** Restatement: "routed to the argmax of declared-
capability overlap `F`". Mechanically checkable — recompute `F`, check the
argmax. **And R11 ROUTER-DEAD already measured that the restated property does
not deliver the value: difficulty routing failed even with an AUROC-1.000
oracle.** The check would pass while the system routed badly. Registering it
would add a green light to a known-broken mechanism.

**`execution_output_content`.** Restatement: "output hash = H, checkable by
re-execution". Verifies **reproducibility** and discards exactly the property
wanted — **a deterministic wrong program passes every time.** It would convert
"we cannot tell if this is right" into "this is reliably the same", which reads
like an improvement and is not one.

---

## Part D — what it bought, with the definitional labelling

**D1. Registry composition.**

| | PROOF | TEST | SPEC | NONE | p(composable) |
|---|---|---|---|---|---|
| before | 10 | 1 | 3 | 4 | 0.7222 |
| **after** | **12** | 1 | 3 | **2** | **0.8333** |

**D2. GENERAL's per-step log decay and silent-wrong rate** (DR's harness,
imported read-only and unmodified; f = 0; semantic reliability 0.3790 from 1000
executed MBPP samples, unchanged):

| | before | after |
|---|---|---|
| semantic fraction | 4/18 = 0.2222 | 2/18 = 0.1111 |
| **per-step log decay** | **−0.2156** | **−0.1078** |

| depth | silent-wrong before | after | reduction |
|---|---|---|---|
| 1 | 0.1275 | 0.0638 | **50.0%** |
| 2 | 0.2572 | 0.1388 | 46.1% |
| 4 | 0.4490 | 0.2512 | 44.0% |
| 8 | **0.7020** | **0.4298** | 38.8% |

**D3. The match to DR's projection is DEFINITIONAL, and so is most of this
table.**

DR projected −0.1078 for two respecifications. The recomputed value is
−0.1078 **exactly**. That is **arithmetic, not confirmation**: DR computed its
projection from the same registry composition this change edits, so landing on
it verifies that I moved two types and that both harnesses divide by 18. The
50.0% reduction at depth 1 is definitional for the same reason — halving the
semantic fraction halves the depth-1 silent-wrong rate by construction. The
sub-50% figures at greater depth are the only mildly non-obvious entries, and
they follow from compounding, not from evidence.

> **What is NOT definitional is whether the two verifiers actually work on real
> code.** That is Parts A5/B5, and it is the only load-bearing evidence here:
> three real divergences, all caught, none synthetic, with correct behaviour
> accepted in every case (no false rejection).

**D4. What remains in NONE, and why.**

| type | why it stays |
|---|---|
| `execution_output_content` | IRREDUCIBLY SEMANTIC — restatement verifies reproducibility and discards correctness |
| `routing_match_quality` | IRREDUCIBLY SEMANTIC by 3d — verifiable, and R11 measured that the restated property does not deliver |

---

## Honest limits

1. **The decay and silent-wrong numbers are arithmetic**, not new measurement
   (D3). The measured inputs are the registry composition and the 0.3790
   semantic reliability, both pre-existing.
2. **The two respecified verifiers check the CLAIM, not the deployment.**
   Nothing here rewires `retrieve_similar` or `netd_client` to *emit* these
   claims — the verifiers and the claim types exist and are registered; wiring
   the producers to populate them is the next change and is not done.
3. **D1 and D2 are real bugs that this work found and did not fix.** The
   respecification makes them *detectable*; `gyza/memory.py` still has both.
   Fixing them is a separate change and should not be folded into a
   verification commit.
4. **The retrieval trade depends on M being a decent proxy in this deployment**
   (A4), which is a judgement, not a measurement.

---

# Part 2 (2026-08-04) — the fix, the survey, and the wiring

## A1 — which behaviour is correct, and why

**D2 — settled by the claim, not by either implementation.** `RetrievalClaim`
declares `metric = "cosine_unit"`, defined in `gyza/verification/respec.py:54`
as *the dot product of L2-normalized vectors*. So **the metric definition is the
arbiter**. SQLite was computing that; Lance was computing
`dot(query, stored_vector)`, which is `‖stored‖ · cos` — a different quantity in
which magnitude outranks direction. Lance now normalizes both sides.

This is the payoff of respecification beyond bug-catching: **before the claim
named its metric, "which backend is right?" had no answer inside the system.**
Now it does.

**D1 — three alternatives, and making the backends agree is not the same as
making them right.**

| option | verdict |
|---|---|
| (i) **filter before rank** — push the predicate into the query as a LanceDB prefilter | **CHOSEN** |
| (ii) adaptive over-fetch, widening until *k* qualify | rejected |
| (iii) exhaustive scan | rejected |

(ii) degenerates to a full scan over an all-unsuccessful corpus **and pays
several round trips to get there** — strictly worse than one scan in the worst
case, and its cost depends on data the caller cannot see.
(iii) is sound and abandons the ANN index. **That trades a silent wrong answer
for a silent performance cliff, which is a different bug rather than a fix** —
so it is not shipped.

(i) keeps the index and removes the *systematic* under-retrieval: the over-fetch
window now contains only rows that can survive the filter, so a qualifying
result can no longer be structurally unreachable. Verified available in
lancedb 0.30.2 (`where(..., prefilter=True)`) before being relied on.

**What is NOT claimed: exactness.** This is an approximate-nearest-neighbour
index and remains one. Recall is still approximate; what is fixed is the case
where a qualifying result could *never* be returned regardless of recall.

A deterministic id tie-break was added on **both** paths, matching the
verifier's ordering, so a score tie cannot make a correct implementation look
divergent.

## A2/A3 — the fix, proven on the real backend

| test | what it pins |
|---|---|
| `test_D1_FIXED_lance_and_sqlite_agree_on_the_divergence_case` | lancedb 0.30.2, 384-dim, the same 30-failure/10-success corpus: Lance returns **all 5** qualifying results and agrees with SQLite exactly. Pre-fix it returned **0**. |
| `test_D2_FIXED_ranking_follows_the_declared_metric_not_magnitude` | `near` (cos ≈ 1.0, norm 0.05) now outranks `far` (lower cos, norm 6.0) |
| `test_D1_the_prefix_behaviour_is_STILL_rejected_regression_fixture` | the original failure remains reproducible and still rejected |

**A regression test that cannot reproduce the original failure is not a
regression test**, so both pre-fix behaviours are kept as explicit fixtures and
asserted to still fail.

## A4 — sibling survey (REPORT ONLY; nothing here was changed)

Both bugs are one family: *a claim's parameters were implicit, so two
implementations of the same operation silently diverged.* Searching `gyza/` for
that shape:

| # | sibling pair | agree on a nontrivial input? |
|---|---|---|
| S1 | `uuid.uuid7` (native) vs `gyza/_compat.py:30 _uuid7_fallback` | **YES, tested** — both give version 7, variant 2, 36 chars; the fallback is monotone in its ms field across 5 draws |
| S2 | `gyza/memory.py:_embed` vs `gyza/embeddings.default_embedder()` | **NOT A PAIR ANY MORE** — `_embed` routes through `default_embedder()` (`memory.py:80-81`). See the correction below. |
| S3 | `wallet.net_balance` (`wallet.py:274`) vs `ReservationBook.available` (`subcontract.py:184`) | **NOT DUPLICATION** — `available()` *calls* `net_balance()`. This is the architectural principle holding: the gate reads the same fold rather than a second one. |
| S4 | Python ↔ Rust (`gyza-rs`, 7 crates) | **COULD NOT TEST HERE.** Genuine dual implementation and the largest such surface. It has a fixture-based parity discipline (`gyza-rs/scripts/regenerate_*_fixtures.py`, 4 generators). Exercising it means running the Rust suite, which the standing rule forbids running beside the Python suite, and a survey that turns into a test campaign stops being a survey. **`gyza-rs/` is also untracked on this branch.** |
| S5 | Python JSON-canonical cosigs vs Go deterministic-protobuf cosigs | **DELIBERATELY DIFFERENT BYTES**, documented as such. Not a divergence bug; making them agree is explicitly forbidden. |

> **A documentation correction, found by the survey.** CLAIMED trip-wire:
> *"`gyza.memory._embed` loads SentenceTransformer independently of
> `gyza.embeddings.default_embedder()`, so `GYZA_EMBEDDER=stub` leaks."*
> **That is STALE** — `_embed` now routes through `default_embedder()`
> (`memory.py:80-81`) and source inspection confirms it. The trip-wire describes
> a divergence that no longer exists.

**No sibling was fixed in the fix commit**, per the instruction.

## B — the wiring

**B1 — `retrieve_similar` emits a `RetrievalClaim`** carrying metric, k,
threshold, filter and the content-addressed corpus snapshot. It is built through
`RetrievalClaim`, which rejects an incomplete claim at construction, so **a
producer cannot default one into existence**.

> **Claim emission is OPT-IN (`emit_claim=False`) and that is a considered
> decision, not laziness.** Content-addressing the snapshot requires enumerating
> every candidate — the same O(corpus) full scan rejected in A1 as a fix for D1.
> Making the claim mandatory would reintroduce on the hot path exactly the
> performance cliff refused three sections earlier. **Verification is O(corpus);
> retrieval stays O(log corpus).** An auditor pays deliberately; every query
> does not.
>
> The honest cost: a claim is only available where someone asked for one. A
> retrieval with no claim is `last_retrieval_claim is None` — **no claim
> produced, never "the claim was empty"**.

`_LanceBackend.all_for_agent` was added for this and is documented as never
being on the retrieval path.

**B2 — the four send paths emit a `SendClaim`** over the bytes handed to the
transport: `send_message:461`, `broadcast:493`, `publish_agent:316`,
`publish_delta:928`, `publish_attestation:1122` (five, counting `broadcast`,
which the prompt did not list but which emits bytes the same way).

**A scope difference between them, stated rather than smoothed over:**

- `send_message` / `broadcast`: `emitted` **IS** the wire payload — the same
  `bytes` object passed to the stub.
- the three protobuf paths: `emitted` is **this process's serialization of the
  message the transport will itself serialize**. That is the closest faithful
  capture available without a transport interceptor, and it is **not** a claim
  about gRPC's own output bytes.

`test_POWER_a_wired_sender_reporting_INTENT_is_caught` pins the one way this
wiring could be silently useless: a claim built from `intended` fails against
`actually_emitted`.

**B3 — no default policy is authored.** All five paths currently record
`policy_id = "no-policy-declared"`; **none has a caller-supplied policy today.**
The absence is *recorded in the claim* rather than passing vacuously, and a test
asserts no policy predicate is defined in `netd_client`. A policy this module
wrote for the sends this module makes is the oracle-embedding species (R14).

**B4 — the registry-execution test now uses a real produced claim.**
`_send_case` calls `_emit_send_claim`, the same function the send paths call;
`test_retrieve_similar_emits_a_claim_the_REGISTERED_VERIFIER_ACCEPTS` runs the
**registered** verifier over a producer-emitted claim and the real corpus, then
asserts a tampered ordering over the same corpus is rejected.

## C — what is MEASURED now, and what was DEFINITIONAL then

**C1. Registry, recomputed from code** (not restated from the prior session):

| PROOF | TEST | SPEC | NONE | n | p(composable) |
|---|---|---|---|---|---|
| 12 | 1 | 3 | 2 | 18 | **0.8333** |

**C2. The separation.**

**DEFINITIONAL (prior session, and still definitional — not re-reported as a
result):**
- the −0.1078 per-step log decay matching DR's projection. DR computed that
  projection *from the same registry composition this change edits*; landing on
  it verifies arithmetic, not the world.
- the 50.0% depth-1 silent-wrong reduction, which follows by construction from
  halving the semantic fraction.

**MEASURED (and this is what the two sessions actually bought):**
- the verifiers reject **three real divergences** in shipped code (D1, D2, D3),
  none synthetic;
- **D1 and D2 are now fixed**, proven against the real LanceDB backend, with the
  pre-fix behaviour retained and still rejected;
- **producers now emit claims the registered verifiers accept on correct
  behaviour and reject on divergence** — production and verification are
  connected, where before the verifiers existed and nothing produced what they
  check.

**C3.** The decay projection is **not** re-reported as a result of this work. It
was arithmetic then and it is arithmetic now. What is new is that the machinery
exists end to end.

## Still not done

- **Only `memory` and `netd_client` are wired.** No other producer emits either
  claim type.
- **No caller supplies a policy** for any send path (B3), so
  `verify_send_claim`'s policy argument is exercised only in tests.
- **The protobuf paths' digest is over our serialization**, not the transport's
  (B2). Closing that needs a gRPC interceptor.
- **S4 (Python ↔ Rust) is unexamined** by this survey.
