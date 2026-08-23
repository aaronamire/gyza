"""A bundle can now commit to being COMPLETE, not merely to being authentic.

Measured 2026-08-23 (`research/evidence_bundle/OMISSION_IS_UNDETECTABLE.md`):
a bundle committed to what it contained and not to what it omitted. Deleting a
LEAF envelope -- nothing references a leaf -- left a smaller bundle that still
verified VALID. Tampering was caught; omission was not.

WHAT THE CLOSURE RECORD CAN AND CANNOT DO. It cannot force a producer to report
an action: a dishonest exporter signs a closure over a set that excluded the
inconvenient action from the start, and that bundle verifies. What it buys is
that silence becomes a SIGNED, FALSIFIABLE CLAIM -- pinned by
`test_a_producer_can_still_sign_a_closure_over_a_set_it_chose`.
"""
from __future__ import annotations

import json
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.evidence import (
    BundleError, attach_closure, closure_payload, load_bundle,
    bundle_to_bytes, verify_closure,
)


def _key():
    seed = secrets.token_bytes(32)
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    return sk, sk.public_key().public_bytes_raw().hex()


def _bundle(n=3, intent="i"):
    from gyza.release import CURRENT_RELEASE
    return {
        "format": "gyza-evidence-bundle", "version": 1, "intent_id": intent,
        "runner": CURRENT_RELEASE.as_dict(),
        "envelopes": [{
            "intent_id": intent, "action_id": f"a{k}",
            "agent_pubkey": "aa" * 32, "capability_manifest_hash": "bb" * 32,
            "input_hashes": [], "output_hash": f"{k:02d}" * 32,
            "parent_envelope_hash": None, "timestamp_ns": 1000 + k,
            "inference_backend": "mock", "model_identifier": "mock",
            "duration_ms": 1, "tokens_in": 0, "tokens_out": 0,
            "signature": "cc" * 64,
        } for k in range(n)],
        "artifacts": {}, "manifests": {},
    }


def _closed(n=3):
    sk, pub = _key()
    b = _bundle(n)
    attach_closure(b, signer_pubkey_hex=pub, sign=lambda d: sk.sign(d))
    return b, sk, pub


# --------------------------------------------------------------------------- #
def test_a_closed_bundle_asserts_and_holds():
    b, _, _ = _closed(3)
    st = verify_closure(b)
    assert st.asserted and st.valid and st.count == 3


def test_OMISSION_IS_NOW_DETECTED():
    """The attack that returned VALID before this existed."""
    b, _, _ = _closed(4)
    b["envelopes"] = b["envelopes"][:-1]
    st = verify_closure(b)
    assert st.asserted and not st.valid
    assert "REMOVED" in st.reason


def test_ADDITION_is_also_detected():
    b, _, _ = _closed(3)
    b["envelopes"].append(dict(b["envelopes"][0], action_id="smuggled"))
    assert not verify_closure(b).valid


def test_rewriting_the_closure_breaks_the_signature():
    """An attacker without the key cannot re-close a reduced set."""
    b, _, _ = _closed(4)
    b["envelopes"] = b["envelopes"][:-1]
    from gyza.evidence import _hash_of
    b["closure"].update(closure_payload(
        b["intent_id"], [_hash_of(e) for e in b["envelopes"]]))
    st = verify_closure(b)
    assert st.asserted and not st.valid
    assert "signature" in st.reason


def test_an_ABSENT_closure_is_reported_not_silently_passed():
    """"I did not say" must not read as "nothing was left out"."""
    st = verify_closure(_bundle(2))
    assert st.asserted is False and st.valid is False
    assert "NOT ASSERTED" in st.line


def test_verify_bundle_FAILS_CLOSED_on_a_broken_closure():
    from gyza.evidence import verify_bundle
    b, _, _ = _closed(4)
    b["envelopes"] = b["envelopes"][:-1]
    with pytest.raises(BundleError, match="REMOVED"):
        verify_bundle(b)


def test_a_closed_bundle_round_trips_through_load():
    b, _, _ = _closed(3)
    again = load_bundle(bundle_to_bytes(b))
    assert verify_closure(again).valid


def test_a_bundle_WITHOUT_closure_still_loads():
    """Bundles produced before completeness existed must not break."""
    again = load_bundle(bundle_to_bytes(_bundle(2)))
    assert verify_closure(again).asserted is False


def test_the_commitment_is_over_a_SET_not_an_order():
    """Bundle ordering is an artifact of the DAG walk, not part of the claim."""
    b, _, _ = _closed(4)
    b["envelopes"] = list(reversed(b["envelopes"]))
    assert verify_closure(b).valid


def test_hashes_are_RECOMPUTED_not_taken_from_a_declared_field():
    """Otherwise the closure commits to whatever the producer typed."""
    b, _, _ = _closed(3)
    for e in b["envelopes"]:
        e["output_hash"] = "ff" * 32          # change real content
    assert not verify_closure(b).valid


def test_a_producer_can_still_sign_a_closure_over_a_set_it_chose():
    """THE HONEST LIMIT, pinned so nobody later overstates the guarantee.

    A dishonest exporter omits an action before closing, and the bundle
    verifies. What it has done is put its key behind a falsifiable claim:
    anyone holding the omitted envelope now holds proof of a lie.
    """
    sk, pub = _key()
    full = _bundle(4)
    partial = dict(full, envelopes=full["envelopes"][:3])
    attach_closure(partial, signer_pubkey_hex=pub, sign=lambda d: sk.sign(d))
    st = verify_closure(partial)
    assert st.valid and st.count == 3, (
        "a producer that omits BEFORE closing still verifies -- this is the "
        "documented limit, not a defect"
    )
