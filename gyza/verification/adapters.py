"""
V-3 native verifier adapters.

Each adapter wraps a verifier that ALREADY EXISTS in production and cites it.
Nothing here reimplements a check: an adapter that reimplemented its verifier
would be a second frame, and the guard and the harm measure would be free to
disagree (C3).

The claim-type vocabulary is R14 Part C's enumeration of Gyza's agent-facing
actions. V-2's coverage number is computed FROM THIS REGISTRY, not copied from
the document -- the document can drift, and a divergence is a finding.
"""
from __future__ import annotations

from gyza.verification.registry import PartialSpec, Verifier, VerifierRegistry
from gyza.containment.invariants import InvariantClass


def _envelope_signature(env, pubkey_bytes) -> bool:
    from gyza.icp import verify_envelope
    return verify_envelope(env, pubkey_bytes)


def _envelope_chain(envelopes) -> bool:
    from gyza.icp import verify_chain
    ok, _ = verify_chain(envelopes)
    return ok


def _envelope_dag_closed(envelopes) -> bool:
    """DAG intact WITH closed parent linkage: every non-root spine parent held.

    THE SPLIT, and why it was needed. One `envelope_dag` entry forwarded
    `require_closed` to `verify_dag`, and production calls it BOTH ways --
    `audit.py` passes True, `resilience.py` and two demos pass False. So the
    registered entry proved a DIFFERENT PROPOSITION depending on the call site,
    which is the determinacy failure the carrier rule refuses. Naming the
    parameter is the repair (parameter ADDITION, not claim substitution), and
    here it is named by having two claim types instead of one caller-chosen
    kwarg.
    """
    from gyza.icp import verify_dag
    return bool(verify_dag(envelopes, require_closed=True).valid)


def _envelope_dag_open(envelopes) -> bool:
    """DAG intact WITHOUT requiring parents to be held.

    The partial-replica reading: a node mid-gossip legitimately lacks spine
    parents. A WEAKER claim than the closed one and a DIFFERENT one -- which is
    the whole point of splitting rather than defaulting.
    """
    from gyza.icp import verify_dag
    return bool(verify_dag(envelopes, require_closed=False).valid)


def _manifest_identity(manifest, expected_hash) -> bool:
    from gyza.identity import manifest_hash_hex
    return manifest_hash_hex(manifest) == expected_hash


def _enforcement_within_manifest(enforcement, manifest) -> bool:
    from gyza.sandbox.config import enforcement_satisfies_manifest
    ok, _ = enforcement_satisfies_manifest(enforcement, manifest)
    return ok


def _delegation_attenuation(chain) -> bool:
    from gyza.economy.delegation import verify_delegation
    ok, _ = verify_delegation(chain)
    return ok


def _ledger_entry_signatures(ledger, entry) -> bool:
    ok, _ = ledger.verify_entry(entry)
    return ok


def _balance_fold(entries, pubkey, expected) -> bool:
    from gyza.economy.wallet import Wallet
    return Wallet(entries).net_balance(pubkey) == expected


def _market_capital_fold(market, pubkey, expected) -> bool:
    """H2's fix makes market capital verifiable the same way credits are."""
    return sum(e.delta for e in market.capital_entries()
               if e.agent_pubkey == pubkey) == expected


def _artifact_content_address(data: bytes, address: str) -> bool:
    import blake3
    # `blake3.blake3(None)` DOES NOT RAISE -- it returns the digest of the
    # EMPTY string, so without this guard a claim that ABSENT content sits at
    # the empty address VERIFIED, at tier 1, PROOF-carried. Absent content and
    # empty content are different claims and must not share an address.
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(
            f"content address is defined over bytes; got {type(data).__name__}. "
            f"This is UNEVALUATED, not a refutation.")
    return blake3.blake3(data).hexdigest() == address


def _unit_test_execution(fn, cases) -> bool:
    """The unit-test adapter. Deliberately labelled TEST-carried at the call
    site: SR-3 measured that a finite sample catches NOTHING under composition
    (0.000, n=4), so a chain containing this adapter is tier 3 per the tier
    algebra even though the adapter itself is mechanical.

    THE CATCH IS NARROWED TO THE CALL. A function that raises on a case has
    genuinely failed that case, so `False` is the right verdict there. A
    MALFORMED `cases` is a harness error and must propagate -- the blanket
    `except Exception` reported "the claim is false" for both, which are
    opposite claims (artifact #16's species).
    """
    for x, y in cases:                       # malformed cases raise, correctly
        try:
            if fn(x) != y:
                return False
        except Exception:                    # noqa: BLE001 - a raising case failed
            return False
    return True


def _memory_retrieval_topk(claim, candidates, query_vec) -> bool:
    """RESPECIFIED (route DR -> respecify). Was in NO_VERIFIER: "these memories
    are relevant" has no mechanical check. The restated claim names its metric,
    k, threshold, filter and a CONTENT-ADDRESSED corpus snapshot, so the
    neighbour set can be RECOMPUTED -- which is what makes it PROOF-carried
    rather than sampled.

    What the restatement loses: whether nearness under M IS relevance. That
    judgement moves from per-query (unverifiable, every time) to ONCE, by a
    human, when M is chosen. See research/respecification/FINDINGS.md.
    """
    from gyza.verification.respec import verify_retrieval_claim
    return verify_retrieval_claim(claim, candidates, query_vec)


def _external_send_content(claim, emitted: bytes) -> bool:
    """RESPECIFIED. Was in NO_VERIFIER: "the right content was sent" has no
    mechanical check. The restated claim binds a content hash to the bytes that
    ACTUALLY LEFT -- not to a value the sender computed from what it intended,
    which would be self-reporting at a finer grain (S5 B3's circularity).

    What the restatement loses: whether sending was a good idea. Containment
    ends at emission regardless (C15), so non-repudiation of WHAT LEFT is close
    to the whole of what is obtainable at that boundary.

    THE POLICY PARAMETER IS BOUND OUT, and that is the determinacy repair.
    `verify_send_claim`'s `policy` defaults to None, and when it is None the
    policy clause is SKIPPED -- so the registered entry verified hash+length at
    some call sites and hash+length+policy at others, proving a different
    proposition depending on the caller. This entry now proves EXACTLY ONE
    thing: the emitted bytes hash and length match what the claim states.

    A policy-carrying claim is a DIFFERENT proposition. It needs its own claim
    type and its own attestation, and it is deliberately not created here --
    nothing in production supplies a policy today, so inventing the type would
    register a checker with no caller.
    """
    from gyza.verification.respec import verify_send_claim
    return verify_send_claim(claim, emitted, policy=None)


def _decomposition_within_manifest(artifact_obj, manifest) -> bool:
    """RECOMPUTES that a decomposition stayed inside its signed spawn grant.

    The runner already refuses to sign an over-wide decomposition, so a signed
    envelope implies this -- IF you trust the runner. This verifier is what
    lets a third party stop trusting it: the fan-out and the grant are both in
    the bundle, so the property can be recomputed from evidence alone. Exactly
    the relationship `enforcement_within_manifest` has to the bounds gate.

    SCOPE, STATED. It checks spawn AUTHORITY and FAN-OUT. It does NOT check
    depth: work-DAG depth is a property of the blackboard and appears in no
    envelope, so a bundle cannot carry it. `MAX_TASK_DEPTH` is therefore
    enforced at production only, and this verifier does not pretend otherwise.
    A check that silently covered less than its name implies would be worse
    than an absent one.
    """
    subs = (artifact_obj or {}).get("__subtasks__") or []
    if not subs:
        return True
    spawn = ((manifest or {}).get("capabilities", {}) or {}).get("spawn", {}) or {}
    if not spawn.get("permitted"):
        return False
    cap = int((spawn.get("resource_budget", {}) or {}).get("max_children", 0) or 0)
    return len(subs) <= cap


def _combine_covers_siblings(artifact_obj, by_action) -> bool:
    """RECOMPUTES that a combination consumed EVERY sibling, not merely some.

    A combiner's envelope commits to the input hashes it consumed. This checks
    those against the children the parent SIGNED that it created, so a
    combination that quietly dropped an inconvenient subtask is caught.

    IT CATCHES OMISSION AT THE DAG LEVEL, which complements the bundle-level
    closure record: closure proves the envelope SET is intact, and this proves
    the combination consumed everything the parent said it created. The two are
    independent -- a bundle can be complete and still contain a combination
    that ignored one of its inputs.
    """
    subs = (artifact_obj or {}).get("__subtasks__") or []
    combine_id = (artifact_obj or {}).get("__combine__")
    if not subs or not combine_id:
        return True                       # not a decomposition with a combiner
    comb = by_action.get(combine_id)
    if comb is None:
        # The combiner is named in signed bytes but absent from the evidence.
        # "It did not run" and "it was removed" are different claims and this
        # cannot tell them apart, so it FAILS CLOSED rather than guessing.
        return False
    siblings = [c for c in subs if c != combine_id]

    # THE COMBINER RAN, so every sibling MUST have completed -- the dependency
    # gate refuses to serve a combiner while any sibling is outstanding. A
    # sibling named in the parent's signed child list but absent from the
    # evidence is therefore a REMOVAL, not work in progress, and this fails
    # closed on it.
    #
    # The first version of this skipped absent siblings, which narrowed the
    # expectation to whatever survived and passed vacuously -- it would have
    # certified a combination after its inconvenient input had been deleted.
    # A test that dropped a child is what caught it.
    if any(c not in by_action for c in siblings):
        return False

    expected = {by_action[c].output_hash for c in siblings}
    return expected <= set(comb.input_hashes)


NATIVE: list[Verifier] = [
    Verifier("envelope_signature", _envelope_signature, "gyza/icp.py:101 verify_envelope"),
    Verifier("envelope_chain", _envelope_chain, "gyza/icp.py:124 verify_chain"),
    Verifier("envelope_dag_closed", _envelope_dag_closed,
             "gyza/icp.py:236 verify_dag (require_closed=True)"),
    Verifier("envelope_dag_open", _envelope_dag_open,
             "gyza/icp.py:236 verify_dag (require_closed=False)"),
    Verifier("manifest_identity", _manifest_identity, "gyza/identity.py:101 _manifest_payload_hash"),
    Verifier("enforcement_within_manifest", _enforcement_within_manifest,
             "gyza/sandbox/config.py:286 enforcement_satisfies_manifest"),
    Verifier("decomposition_within_manifest", _decomposition_within_manifest,
             "gyza/runner.py _spawn_subtasks (manifest spawn grant)"),
    Verifier("combine_covers_siblings", _combine_covers_siblings,
             "gyza/runner.py _gather_inputs (combiner input resolution)"),
    Verifier("delegation_attenuation", _delegation_attenuation,
             "gyza/economy/delegation.py:264 verify_delegation"),
    # Cited :348 (inside `sign_as_payer`) until 2026-08-14 — the SIGNER, not
    # the checker. The adapter calls `verify_entry`, so an auditor following the
    # witness landed on the wrong function entirely.
    Verifier("ledger_entry_signatures", _ledger_entry_signatures,
             "gyza/economy/ledger.py:387 verify_entry"),
    Verifier("balance_fold", _balance_fold, "gyza/economy/wallet.py:274 net_balance"),
    Verifier("market_capital_fold", _market_capital_fold,
             "gyza/economy/market.py:CapitalEntry fold"),
    Verifier("artifact_content_address", _artifact_content_address,
             "gyza/network/artifact_store.py:71 store"),
    # TEST-carried: tier 1 in isolation, but forces any chain containing it to
    # tier 3. The tier and the carrier disagree here and both are right.
    Verifier("unit_test_execution", _unit_test_execution,
             "V-3 adapter (finite sample)", carrier="TEST"),
    # --- RESPECIFIED out of NO_VERIFIER (route DR's engineering finding) ------
    Verifier("memory_retrieval_relevance", _memory_retrieval_topk,
             "gyza/verification/respec.py:124 verify_retrieval_claim"),
    Verifier("external_send_content", _external_send_content,
             "gyza/verification/respec.py:196 verify_send_claim"),
]

# R14 Part C's CHEAP-PARTIAL bucket: mechanically checkable conservation or
# monotone properties, human-authored, one per claim type.
def _hlc_monotone(prev, nxt) -> bool:
    return tuple(nxt) >= tuple(prev)


def _reputation_in_range(score) -> bool:
    return 0.0 <= float(score) <= 1.0


def _claim_exclusive(claims, work_item_id) -> bool:
    return sum(1 for c in claims if c == work_item_id) <= 1


HUMAN_SPECS: list[PartialSpec] = [
    PartialSpec("hlc_ordering", _hlc_monotone, InvariantClass.MONOTONE_NON_CUMULATIVE,
                "xan", True, "the ratchet is checkable; wall-clock truth is not"),
    PartialSpec("reputation_score", _reputation_in_range, InvariantClass.CONSERVATION,
                "xan", True, "range is checkable; whether it tracks trustworthiness is not"),
    PartialSpec("work_claim_exclusivity", _claim_exclusive, InvariantClass.CONSERVATION,
                "xan", True, "single-claim conservation is checkable; competence is not"),
]

# R14 Part C's NO-VERIFIER bucket. Enumerated so tier-3 coverage is computed
# rather than assumed -- correctness here is semantic (the competence bound).
# Two types LEFT this bucket by RESPECIFICATION (route DR -> respecify); the
# two that remain are IRREDUCIBLY SEMANTIC, and the reasons are recorded so a
# future reader does not propose them again:
#
#   execution_output_content  -- restatement "output hash = H, checkable by
#       re-execution" verifies REPRODUCIBILITY and discards exactly the property
#       wanted. A deterministic wrong program passes every time.
#   routing_match_quality     -- restatement "routed to argmax of declared-
#       capability overlap F" is mechanically checkable, and R11 ROUTER-DEAD
#       measured that the restated property does not deliver the value:
#       difficulty routing failed even with an AUROC-1.000 oracle.
#       VERIFIABLE AND KNOWN NOT TO DELIVER IS NOT A WIN (rule 3d).
NO_VERIFIER: list[str] = [
    "execution_output_content",      # gyza/runner.py:374
    "routing_match_quality",         # gyza/demand.py:35
]


def build_registries():
    from gyza.verification.registry import PartialSpecRegistry
    v = VerifierRegistry()
    for x in NATIVE:
        v.register(x)
    s = PartialSpecRegistry()
    for y in HUMAN_SPECS:
        s.register(y)
    return v, s


def all_claim_types() -> list[str]:
    return ([x.claim_type for x in NATIVE]
            + [y.claim_type for y in HUMAN_SPECS] + list(NO_VERIFIER))
