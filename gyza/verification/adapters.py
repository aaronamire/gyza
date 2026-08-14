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


def _envelope_dag(envelopes, **kw) -> bool:
    from gyza.icp import verify_dag
    res = verify_dag(envelopes, **kw)
    return bool(getattr(res, "valid", res))


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


def _external_send_content(claim, emitted: bytes, policy=None) -> bool:
    """RESPECIFIED. Was in NO_VERIFIER: "the right content was sent" has no
    mechanical check. The restated claim binds a content hash to the bytes that
    ACTUALLY LEFT -- not to a value the sender computed from what it intended,
    which would be self-reporting at a finer grain (S5 B3's circularity).

    What the restatement loses: whether sending was a good idea. Containment
    ends at emission regardless (C15), so non-repudiation of WHAT LEFT is close
    to the whole of what is obtainable at that boundary.
    """
    from gyza.verification.respec import verify_send_claim
    return verify_send_claim(claim, emitted, policy)


NATIVE: list[Verifier] = [
    Verifier("envelope_signature", _envelope_signature, "gyza/icp.py:82"),
    Verifier("envelope_chain", _envelope_chain, "gyza/icp.py:105"),
    Verifier("envelope_dag", _envelope_dag, "gyza/icp.py:217"),
    Verifier("manifest_identity", _manifest_identity, "gyza/identity.py:101"),
    Verifier("enforcement_within_manifest", _enforcement_within_manifest,
             "gyza/sandbox/config.py:286"),
    Verifier("delegation_attenuation", _delegation_attenuation,
             "gyza/economy/delegation.py:229 verify_delegation"),
    # Cited :348 (inside `sign_as_payer`) until 2026-08-14 — the SIGNER, not
    # the checker. The adapter calls `verify_entry`, so an auditor following the
    # witness landed on the wrong function entirely.
    Verifier("ledger_entry_signatures", _ledger_entry_signatures,
             "gyza/economy/ledger.py:387 verify_entry"),
    Verifier("balance_fold", _balance_fold, "gyza/economy/wallet.py:274"),
    Verifier("market_capital_fold", _market_capital_fold,
             "gyza/economy/market.py:CapitalEntry fold"),
    Verifier("artifact_content_address", _artifact_content_address,
             "gyza/network/artifact_store.py:47"),
    # TEST-carried: tier 1 in isolation, but forces any chain containing it to
    # tier 3. The tier and the carrier disagree here and both are right.
    Verifier("unit_test_execution", _unit_test_execution,
             "V-3 adapter (finite sample)", carrier="TEST"),
    # --- RESPECIFIED out of NO_VERIFIER (route DR's engineering finding) ------
    Verifier("memory_retrieval_relevance", _memory_retrieval_topk,
             "gyza/verification/respec.py:124"),
    Verifier("external_send_content", _external_send_content,
             "gyza/verification/respec.py:196"),
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
