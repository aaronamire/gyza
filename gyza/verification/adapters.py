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
    return blake3.blake3(data).hexdigest() == address


def _unit_test_execution(fn, cases) -> bool:
    """The unit-test adapter. Deliberately labelled TEST-carried at the call
    site: SR-3 measured that a finite sample catches NOTHING under composition
    (0.000, n=4), so a chain containing this adapter is tier 3 per the tier
    algebra even though the adapter itself is mechanical."""
    try:
        return all(fn(x) == y for x, y in cases)
    except Exception:
        return False


NATIVE: list[Verifier] = [
    Verifier("envelope_signature", _envelope_signature, "gyza/icp.py:82"),
    Verifier("envelope_chain", _envelope_chain, "gyza/icp.py:105"),
    Verifier("envelope_dag", _envelope_dag, "gyza/icp.py:217"),
    Verifier("manifest_identity", _manifest_identity, "gyza/identity.py:101"),
    Verifier("enforcement_within_manifest", _enforcement_within_manifest,
             "gyza/sandbox/config.py:286"),
    Verifier("delegation_attenuation", _delegation_attenuation,
             "gyza/economy/delegation.py:213"),
    Verifier("ledger_entry_signatures", _ledger_entry_signatures,
             "gyza/economy/ledger.py:348"),
    Verifier("balance_fold", _balance_fold, "gyza/economy/wallet.py:274"),
    Verifier("market_capital_fold", _market_capital_fold,
             "gyza/economy/market.py:CapitalEntry fold"),
    Verifier("artifact_content_address", _artifact_content_address,
             "gyza/network/artifact_store.py:47"),
    Verifier("unit_test_execution", _unit_test_execution, "V-3 adapter (TEST-carried)"),
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
NO_VERIFIER: list[str] = [
    "execution_output_content",      # gyza/runner.py:374
    "memory_retrieval_relevance",    # gyza/memory.py:402
    "routing_match_quality",         # gyza/demand.py:35
    "external_send_content",         # gyza/network/netd_client.py:461 (C15)
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
