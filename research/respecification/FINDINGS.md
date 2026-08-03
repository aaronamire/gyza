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
