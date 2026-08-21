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
from gyza.containment.gyza_model import (
    DEFAULT_BOUNDS_FILE, PLAIN_BOUNDS_FILE, build_registries,
)
from gyza.containment.harm import UnsignedBoundsError

# H1_credits was RETIRED 2026-08-15 — credits are TOKEN_IS_FAKE, so no level
# in them is checkable. The declared set is what remains.
# H2_market_capital RETIRED 2026-08-17 alongside H1: BondedMarket has zero
# production constructors, so the class measured 0.0 in every production
# evaluation. Removing a bound is a TIGHTENING (an unset bound fails closed),
# so no loosening record was required.
BOUNDS = {"H4_authority": 0.0,
          "H5_storage_growth": 1e10, "H6_unsupervised_actions": 10000}


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
    containment claim is not available over them.

    Uses PLAIN_BOUNDS_FILE explicitly: on 2026-08-19 DEFAULT_BOUNDS_FILE became
    the SIGNED configuration, because the signature had been covering a document
    nothing loaded. This test is about the PLAIN path and must name it.
    """
    h, r = _readiness(bounds_file=PLAIN_BOUNDS_FILE)
    assert r["bounds_provenance"]["source"] == "UNSIGNED_FILE"
    assert r["bounds_signed"] is False
    assert r["can_claim_containment"] is False
    # TWO blockers now, and separating them matters. Provenance is one; the
    # other is that H3_mesh_exit_sends is REGISTERED AND UNBOUNDED on purpose
    # (measured, not bounded — the level waits on the measurement that H1's
    # retirement bought). Before H3 was declared, this list was empty and the
    # claim was blocked by provenance alone — not because the gap was smaller,
    # but because it was UNNAMED.
    assert r["unbounded"] == ["H3_mesh_exit_rate"]
    assert r["uncovered"] == []
    assert h.bound("H4_authority") == 0.0


def test_SIGNED_bounds_lift_the_claim(tmp_path):
    seed, pub = _authority()
    h, r = _readiness(bounds_file=_signed_file(tmp_path, seed),
                      authority_pubkey=pub)
    assert r["bounds_provenance"]["source"] == "SIGNED"
    assert r["bounds_signed"] is True
    # SIGNING DOES NOT MANUFACTURE THE CLAIM. C-8 (provenance) is open; D1
    # (every class bounded) is not, because H3 has no declared level. Two
    # independent gates — the property KEY_PROVENANCE.md recorded when H5 was
    # the unbounded one, now re-exercised by H3.
    assert r["can_claim_containment"] is False
    assert r["unbounded"] == ["H3_mesh_exit_rate"]
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
    doc["config"]["bounds"]["H6_unsupervised_actions"] = 10_000_000  # edit the policy
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
        build_registries(bounds_file=PLAIN_BOUNDS_FILE, authority_pubkey=pub)
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
    # including the ones the file would otherwise have declared. H3 is
    # unbounded in BOTH states, so it is added rather than compared away --
    # writing `set(BOUNDS) | {"H3..."}` keeps the assertion about the FILE's
    # effect rather than quietly widening it to whatever is registered.
    assert set(r["unbounded"]) == set(BOUNDS) | {"H3_mesh_exit_rate"}


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

    loose = dict(BOUNDS, H6_unsupervised_actions=500000)
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
    # The default now loads the SIGNED bytes with no key configured, which is
    # a DIFFERENT state from unsigned and carries a DIFFERENT remedy: configure
    # a pubkey, do not re-sign a document that is already signed.
    assert "SIGNED BUT UNVERIFIED" in out
    assert "GYZA_GUARD_AUTHORITY" in out, "the report must say what to do"
    assert "can claim containment: NO" in out
    assert "sign_guard_config.py" in out
    # the declared levels are still shown: unsigned is not the same as unknown.
    # The format moved from `10000.00` to `10,000` on 2026-08-19 when the
    # section began reporting MEASURED-of-BOUND instead of the bound alone --
    # a count of actions has no meaningful hundredths.
    assert "H6_unsupervised_actions" in out and "10,000" in out
    # AND the operator's POSITION against it, which is the point of the
    # section. Before that change H3/H5 printed a bound with no measurement and
    # every quantity was structurally 0 (research/H3_WIRING_GAP.md), so a bound
    # nobody could see their position against was one nobody could act on.
    assert " of 10,000" in out, "the measured position must be shown, not just the bound"
    assert "H5_storage_growth" in out and " of 10,000,000,000" in out
    # and a RETIRED class must still be REPORTED, not silently dropped. H2 was
    # retired 2026-08-17; if retirement removed it from the report, the operator
    # would see a smaller model rather than a named gap.
    assert "H2_market_capital" in out and "NOT MODELLED" in out
    # H3 is absent from the model and must be reported as absent, never omitted
    assert "H3_irreversible_change" in out and "NOT MODELLED" in out


def test_gyza_status_does_NOT_let_measurable_read_as_enforced(capsys):
    """The claim this section is most likely to be misread as making."""
    from gyza.cli import _print_containment_section
    from gyza.config import GyzaConfig

    _print_containment_section(GyzaConfig())
    out = capsys.readouterr().out
    # The old text claimed NO bound was consulted, which stopped being true when
    # the settlement gate landed. A stale reassurance is worse than none, so the
    # property pinned now is that enforced and measured are DISTINGUISHED.
    assert "ENFORCED at runtime" in out and "H1" in out
    assert "MEASURED but NOT enforced" in out


def test_a_correctly_signed_TIGHTENING_installs(tmp_path):
    """Counter-metric to the test above. If every update were refused, the
    loosening check would be indistinguishable from a broken store."""
    seed, pub = _authority()
    store = GuardConfigStore(pub)
    store.load_file(_signed_file(tmp_path, seed))
    # TIGHTEN an EXISTING bound. Adding a new one would be a LOOSENING
    # (unset fails closed -> refuse-all becomes admit-some), so the previous
    # version of this line stopped being a tightening the moment H2 was retired
    # out of BOUNDS.
    tight = dict(BOUNDS, H6_unsupervised_actions=5000)
    cfg = {"version": 2, "bounds": tight, "tier_assignments": {}}
    assert store.load(cfg, sign_config(cfg, seed)
                      ).bounds["H6_unsupervised_actions"] == 5000
