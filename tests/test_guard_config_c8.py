"""C-8 — the guard configuration in a separate trust domain, ENFORCED.

WHAT WAS WRONG. `GuardConfigStore.apply_to` documented that "bounds reach the
harm registry ONLY through a verified configuration". That sentence was FALSE:
`load_bounds` and `load_bounds_file` are public, and
`gyza_model.build_registries` called the file loader directly on an ordinary
repo file. Meanwhile `GuardConfigStore`, `verify_config` and `diff_bounds` had
**zero production callers**, and `readiness()` returned
`can_claim_containment: True` over bounds anybody could edit with a text editor.

An unenforced invariant is an assumption. These tests make it checkable.

THE INDUCTION IS THE ARGUMENT. Every containment claim here is: the invariant
holds at s0, and every admitted transition preserves it. If the constrained
system can rewrite the bound there is no base case, so unsigned bounds may be
REPORTED and must never be CLAIMED over.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_guard_config_c8.py -q
"""
from __future__ import annotations

import json
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.containment.engine import GuardEngine
from gyza.containment.guardconfig import (
    GuardConfigError, GuardConfigStore, sign_config,
)
from gyza.containment.gyza_model import DEFAULT_BOUNDS_FILE, build_registries
from gyza.containment.harm import UnsignedBoundsError

BOUNDS = {"H1_credits": 100.0, "H2_market_capital": 100.0, "H4_authority": 0.0}


def _authority():
    seed = secrets.token_bytes(32)
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    return seed, pk.public_bytes_raw()


def _signed_file(tmp_path, seed, *, bounds=None, version=1, name="signed.json"):
    config = {"version": version, "bounds": dict(bounds or BOUNDS),
              "tier_assignments": {}}
    doc = {"config": config, "signature": sign_config(config, seed)}
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


def _readiness(**kw):
    h, i = build_registries(**kw)
    return h, GuardEngine(h, i).readiness()


# --------------------------------------------------------------------------- #
#  1. THE VERDICT TURNS ON PROVENANCE, NOT ON THE NUMBERS                      #
# --------------------------------------------------------------------------- #
def test_UNSIGNED_bounds_load_but_CANNOT_claim_containment():
    """The state the repo shipped in. Bounds are in force and reportable; the
    containment claim is not available over them."""
    h, r = _readiness(bounds_file=DEFAULT_BOUNDS_FILE)
    assert r["bounds_provenance"]["source"] == "UNSIGNED_FILE"
    assert r["bounds_signed"] is False
    assert r["can_claim_containment"] is False
    # PROVENANCE is what blocks it here. H5 is unbounded by design (its level is
    # a user decision), so the check is that nothing ELSE is missing.
    assert r["unbounded"] == ["H5_storage_growth"] and r["uncovered"] == []
    assert h.bound("H1_credits") == 100.0


def test_SIGNED_bounds_lift_the_claim(tmp_path):
    seed, pub = _authority()
    h, r = _readiness(bounds_file=_signed_file(tmp_path, seed),
                      authority_pubkey=pub)
    assert r["bounds_provenance"]["source"] == "SIGNED"
    assert r["bounds_signed"] is True
    # Signing lifts C-8. It does NOT lift D1 for a class the file declares no
    # level for -- H5 has none, so containment still cannot be claimed. Two
    # independent gates, and this pins that signing does not paper over the
    # other one.
    assert r["can_claim_containment"] is False
    assert r["unbounded"] == ["H5_storage_growth"]
    assert r["bounds_provenance"]["authority_pubkey"] == pub.hex()
    assert len(r["bounds_provenance"]["config_hash"]) == 64


def test_the_BOUNDS_THEMSELVES_are_identical_either_way(tmp_path):
    """Counter-control. If signing changed the levels, the test above would be
    measuring a different policy rather than the same one under authority."""
    seed, pub = _authority()
    unsigned, _ = _readiness(bounds_file=DEFAULT_BOUNDS_FILE)
    signed, _ = _readiness(bounds_file=_signed_file(tmp_path, seed),
                           authority_pubkey=pub)
    def _levels(reg):
        out = {}
        for c in reg:
            try:
                out[c.id] = reg.bound(c.id)
            except Exception:
                out[c.id] = "UNSET"
        return out
    assert _levels(unsigned) == _levels(signed)


# --------------------------------------------------------------------------- #
#  2. NEGATIVE CONTROLS — every way the trusted path must REFUSE               #
# --------------------------------------------------------------------------- #
def test_TAMPERED_bounds_are_refused(tmp_path):
    """The attack C-8 exists for: raise a bound after it was signed."""
    seed, pub = _authority()
    p = _signed_file(tmp_path, seed)
    doc = json.loads(p.read_text())
    doc["config"]["bounds"]["H1_credits"] = 10_000.0     # edit the policy
    p.write_text(json.dumps(doc))

    with pytest.raises(UnsignedBoundsError, match="did not verify"):
        build_registries(bounds_file=p, authority_pubkey=pub)


def test_a_config_signed_by_the_WRONG_AUTHORITY_is_refused(tmp_path):
    """An agent that signs its own policy must not be able to install it."""
    attacker_seed, _ = _authority()
    _, real_pub = _authority()
    p = _signed_file(tmp_path, attacker_seed)
    with pytest.raises(UnsignedBoundsError, match="did not verify"):
        build_registries(bounds_file=p, authority_pubkey=real_pub)


def test_a_PLAIN_file_under_an_authority_is_refused_AS_UNSIGNED(tmp_path):
    """The refusal must name the right failure. 'These bounds are unsigned' and
    'this signature is wrong' have different remedies, and an operator handed
    the wrong one debugs the wrong thing."""
    _, pub = _authority()
    with pytest.raises(UnsignedBoundsError) as ei:
        build_registries(bounds_file=DEFAULT_BOUNDS_FILE, authority_pubkey=pub)
    msg = str(ei.value)
    assert "not a SIGNED configuration" in msg
    assert "sign_guard_config.py" in msg, "the refusal must say what to do"
    assert "did not verify" not in msg


def test_a_MISSING_config_under_an_authority_is_refused(tmp_path):
    _, pub = _authority()
    with pytest.raises(UnsignedBoundsError, match="absent policy"):
        build_registries(bounds_file=tmp_path / "nope.json", authority_pubkey=pub)


# --------------------------------------------------------------------------- #
#  3. UNSET IS NOT UNSIGNED — an absent thing must not hide behind a weak one  #
# --------------------------------------------------------------------------- #
def test_NO_bounds_is_a_DISTINCT_state_from_UNSIGNED_bounds():
    h, r = _readiness(bounds_file=None)
    assert r["bounds_provenance"]["source"] == "UNSET"
    assert r["bounds_signed"] is False
    assert r["can_claim_containment"] is False
    # and it is distinguishable: here EVERY class is genuinely unbounded,
    # including the ones the file would otherwise have declared
    assert set(r["unbounded"]) == set(BOUNDS) | {"H5_storage_growth"}


# --------------------------------------------------------------------------- #
#  4. SIGNED PROVENANCE HAS EXACTLY ONE SOURCE                                 #
# --------------------------------------------------------------------------- #
def test_the_PUBLIC_SETTER_cannot_stamp_a_trusted_provenance():
    """`load_bounds` is public. Calling it directly must record UNSIGNED --
    otherwise the trusted path is a convention rather than a mechanism."""
    h, _i = build_registries(bounds_file=None)
    h.load_bounds(BOUNDS)
    assert h.bounds_provenance.source == "UNSIGNED_FILE"
    assert h.bounds_provenance.trusted is False


def test_apply_to_is_the_ONLY_call_site_that_stamps_SIGNED():
    """Pinned by inspection, because the guarantee is 'one source' and a second
    one could be added without any test noticing."""
    import pathlib
    hits = []
    for p in pathlib.Path("gyza").rglob("*.py"):
        for n, line in enumerate(p.read_text().splitlines(), 1):
            if 'source="SIGNED"' in line or "source='SIGNED'" in line:
                hits.append(f"{p}:{n}")
    assert hits == ["gyza/containment/guardconfig.py:"
                    + hits[0].split(":")[1]], hits
    assert "guardconfig.py" in hits[0]


def test_the_store_still_REFUSES_a_silent_loosening(tmp_path):
    """C-8's other half, unchanged and re-pinned here because `build_registries`
    now depends on it: a bound may not loosen through the ordinary path."""
    seed, pub = _authority()
    store = GuardConfigStore(pub)
    store.load_file(_signed_file(tmp_path, seed))

    loose = dict(BOUNDS, H1_credits=500.0)
    cfg = {"version": 2, "bounds": loose, "tier_assignments": {}}
    with pytest.raises(GuardConfigError, match="LOOSEN"):
        store.load(cfg, sign_config(cfg, seed))


# --------------------------------------------------------------------------- #
#  5. THE GAP IS VISIBLE TO AN OPERATOR                                        #
#     A gap nobody can see is one nobody closes, and adding a status section    #
#     that is never executed would be the same defect one layer up.             #
# --------------------------------------------------------------------------- #
def test_gyza_status_REPORTS_that_the_bounds_are_unsigned(capsys):
    from gyza.cli import _print_containment_section
    from gyza.config import GyzaConfig

    _print_containment_section(GyzaConfig())
    out = capsys.readouterr().out
    assert "NOT SIGNED" in out
    assert "can claim containment: NO" in out
    assert "sign_guard_config.py" in out, "the report must say what to do"
    # the declared levels are still shown: unsigned is not the same as unknown
    assert "H1_credits" in out and "100.00" in out
    # H3 is absent from the model and must be reported as absent, never omitted
    assert "H3_irreversible_change" in out and "NOT MODELLED" in out


def test_gyza_status_does_NOT_let_measurable_read_as_enforced(capsys):
    """The claim this section is most likely to be misread as making."""
    from gyza.cli import _print_containment_section
    from gyza.config import GyzaConfig

    _print_containment_section(GyzaConfig())
    out = capsys.readouterr().out
    assert "no runtime gate consults these bounds" in out
    assert "not enforced" in out


def test_a_correctly_signed_TIGHTENING_installs(tmp_path):
    """Counter-metric to the test above. If every update were refused, the
    loosening check would be indistinguishable from a broken store."""
    seed, pub = _authority()
    store = GuardConfigStore(pub)
    store.load_file(_signed_file(tmp_path, seed))
    tight = dict(BOUNDS, H1_credits=50.0)
    cfg = {"version": 2, "bounds": tight, "tier_assignments": {}}
    assert store.load(cfg, sign_config(cfg, seed)).bounds["H1_credits"] == 50.0
