"""Authority key rotation, and the bypass it must not become.

CLAUDE.md §3 records this deferral as a FRAME HAZARD: implemented naively,
rotation reproduces R9's `G4'` exactly -- history pinned to the old key, the
live gate reading the new one, and the invariant checking against a frame the
history is not in. The prescribed fix is a signed key-succession record so the
fold resolves to the current identity, and "the invariant's frame must follow
the harm's frame, never the reverse."

THE SAFETY PROPERTY: ROTATION CHANGES WHO SIGNS AND NOTHING ELSE. `_install`
compares against `self._cfg` for BOTH version monotonicity AND permissiveness
monotonicity, so a rotation that cleared it would let an attacker rotate and
then install any bounds at any version against nothing to compare with. That
bypass is what most of this file tests.
"""
from __future__ import annotations

import pathlib
import secrets
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.containment.guardconfig import (
    GuardConfigError,
    GuardConfigStore,
    KeySuccession,
    LooseningRecord,
    sign_config,
    sign_loosening,
    sign_succession,
)

BOUNDS = {"H4_authority": 0.0, "H5_storage_growth": 1e10,
          "H6_unsupervised_actions": 10000}


def _key():
    seed = secrets.token_bytes(32)
    pub = Ed25519PrivateKey.from_private_bytes(seed).public_key(
    ).public_bytes_raw()
    return seed, pub


def _cfg(version=1, **over):
    b = dict(BOUNDS); b.update(over)
    return {"version": version, "bounds": b, "tier_assignments": {}}


def _succ(old_pub, new_pub, reason="scheduled rotation"):
    return KeySuccession(old_pubkey_hex=old_pub.hex(),
                         new_pubkey_hex=new_pub.hex(),
                         at_ns=time.time_ns(), reason=reason)


def _store():
    seed, pub = _key()
    st = GuardConfigStore(pub)
    st.load(_cfg(1), sign_config(_cfg(1), seed))
    return st, seed, pub


# --------------------------------------------------------------------------- #
#  1. THE HAPPY PATH                                                           #
# --------------------------------------------------------------------------- #
def test_rotation_lets_the_NEW_key_sign_and_retires_the_OLD():
    st, old_seed, old_pub = _store()
    new_seed, new_pub = _key()
    rec = _succ(old_pub, new_pub)
    st.rotate_authority(rec, sign_succession(rec, old_seed))

    # the new key installs
    c2 = _cfg(2)
    st.load(c2, sign_config(c2, new_seed))
    assert st.config.version == 2

    # the OLD key no longer does -- retirement must be real
    c3 = _cfg(3)
    with pytest.raises(GuardConfigError):
        st.load(c3, sign_config(c3, old_seed))


def test_the_chain_is_walkable_from_the_GENESIS_key():
    st, old_seed, old_pub = _store()
    genesis = st.genesis_authority_pubkey_hex
    _, mid_pub = _key()
    rec = _succ(old_pub, mid_pub)
    st.rotate_authority(rec, sign_succession(rec, old_seed))
    assert st.genesis_authority_pubkey_hex == genesis, "genesis must not move"
    chain = st.succession_chain
    assert len(chain) == 1
    assert chain[0]["old_pubkey"] == genesis
    assert chain[0]["new_pubkey"] == mid_pub.hex()


# --------------------------------------------------------------------------- #
#  2. THE BYPASS. Rotation must not reset what the monotonicity checks         #
#     compare against -- otherwise rotating IS the loosening path.             #
# --------------------------------------------------------------------------- #
def test_rotation_does_NOT_reset_the_LOOSENING_check():
    """THE ATTACK: rotate, then install looser bounds with no LooseningRecord."""
    st, old_seed, old_pub = _store()
    new_seed, new_pub = _key()
    rec = _succ(old_pub, new_pub)
    st.rotate_authority(rec, sign_succession(rec, old_seed))

    looser = _cfg(2, H6_unsupervised_actions=10_000_000)
    with pytest.raises(GuardConfigError, match="LOOSEN"):
        st.load(looser, sign_config(looser, new_seed))


def test_rotation_does_NOT_reset_VERSION_monotonicity():
    """THE REPLAY: rotate, then reinstate an old version."""
    st, old_seed, old_pub = _store()
    new_seed, new_pub = _key()
    rec = _succ(old_pub, new_pub)
    st.rotate_authority(rec, sign_succession(rec, old_seed))

    stale = _cfg(1)
    with pytest.raises(GuardConfigError, match="monotone"):
        st.load(stale, sign_config(stale, new_seed))


def test_loosening_STILL_WORKS_across_a_rotation_with_a_proper_record():
    """The counter-metric: the check must refuse the bypass without refusing
    the legitimate path, or rotation would make loosening impossible."""
    st, old_seed, old_pub = _store()
    new_seed, new_pub = _key()
    rec = _succ(old_pub, new_pub)
    st.rotate_authority(rec, sign_succession(rec, old_seed))

    looser = _cfg(2, H6_unsupervised_actions=20000)
    rec = LooseningRecord(
        changes=(("H6_unsupervised_actions", 10000.0, 20000.0),),
        reason="cadence widened after review")
    st.install_loosening(looser, sign_config(looser, new_seed),
                         rec, sign_loosening(rec, new_seed))
    assert st.config.bounds["H6_unsupervised_actions"] == 20000


# --------------------------------------------------------------------------- #
#  3. NEGATIVE CONTROLS on the succession itself                                #
# --------------------------------------------------------------------------- #
def test_SELF_APPOINTMENT_is_refused():
    """A record signed by the INCOMING key would let anyone with a keypair
    take the authority.

    Matches on "does not verify" rather than on a named cause: the refusal
    states WHAT failed and lists causes as possibilities, because the first
    person to hit this message had a mismatched `at_ns` and was pointed at
    self-appointment.
    """
    st, _old_seed, old_pub = _store()
    new_seed, new_pub = _key()
    rec = _succ(old_pub, new_pub)
    with pytest.raises(GuardConfigError, match="does not verify"):
        st.rotate_authority(rec, sign_succession(rec, new_seed))


def test_a_succession_naming_the_WRONG_PREDECESSOR_is_refused():
    """Replaying a valid succession from an unrelated store."""
    st, old_seed, _old_pub = _store()
    _, stranger_pub = _key()
    _, new_pub = _key()
    rec = _succ(stranger_pub, new_pub)           # names someone else's key
    with pytest.raises(GuardConfigError, match="does not attach"):
        st.rotate_authority(rec, sign_succession(rec, old_seed))


def test_a_NO_OP_rotation_is_refused():
    st, old_seed, old_pub = _store()
    rec = _succ(old_pub, old_pub)
    with pytest.raises(GuardConfigError, match="incumbent"):
        st.rotate_authority(rec, sign_succession(rec, old_seed))


def test_a_TAMPERED_succession_is_refused():
    st, old_seed, old_pub = _store()
    _, new_pub = _key()
    _, attacker_pub = _key()
    rec = _succ(old_pub, new_pub)
    sig = sign_succession(rec, old_seed)
    forged = _succ(old_pub, attacker_pub)        # swap the successor
    with pytest.raises(GuardConfigError):
        st.rotate_authority(forged, sig)


def test_rotation_is_ALARMED_not_silent():
    st, old_seed, old_pub = _store()
    _, new_pub = _key()
    before = len(st.alarms)
    rec = _succ(old_pub, new_pub)
    st.rotate_authority(rec, sign_succession(rec, old_seed))
    assert len(st.alarms) == before + 1
    assert "ROTATED" in st.alarms[-1]


def test_the_refusal_names_the_FAILURE_and_does_not_assert_a_CAUSE():
    """A refusal that diagnoses is a refusal that can misdiagnose."""
    st, old_seed, old_pub = _store()
    _, new_pub = _key()
    rec = _succ(old_pub, new_pub)
    sig = sign_succession(rec, old_seed)
    drifted = KeySuccession(old_pubkey_hex=rec.old_pubkey_hex,
                            new_pubkey_hex=rec.new_pubkey_hex,
                            at_ns=rec.at_ns + 1, reason=rec.reason)
    with pytest.raises(GuardConfigError) as ei:
        st.rotate_authority(drifted, sig)
    msg = str(ei.value)
    assert "does not verify" in msg
    assert "Possible causes" in msg, "causes must be offered, not asserted"
    assert "at_ns" in msg, "the remedy the operator actually needs"


def test_rotation_has_a_PRODUCTION_ENTRY_POINT():
    """A mechanism only tests construct is the defect, not the fix.

    `tests/test_declared_is_wired.py` flagged `KeySuccession` on the day it was
    written, which is what the standing check is for. The remedy chosen was an
    entry point rather than a NON_ADOPTED marker.
    """
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "sign_guard_config.py").read_text()
    assert "--rotate-to" in src
    assert "KeySuccession(" in src
    assert "sign_succession(" in src
    # a rotation without a stated reason is refused: an unexplained key change
    # is indistinguishable from a key substitution
    assert "--reason is required" in src
