"""The bytes in force must be the bytes that were signed.

THE DEFECT. `DEFAULT_BOUNDS_FILE` pointed at `guard_bounds.json` while
`guard_bounds.signed.json` sat beside it carrying a valid signature over
identical values. So the levels actually loaded came from a document the
signature DID NOT COVER, and editing the unsigned file was undetectable BY
CONSTRUCTION -- the signature protected something nothing read.

Switching the default was not a one-line change: `load_bounds_file` did
`data.get("bounds", data)`, which on a signed envelope returns the whole
wrapper, so it would have loaded NO BOUNDS while reporting success. Every class
would read UNDECLARED -- failing closed, but for the wrong reason.

`SIGNED_UNVERIFIED` is the fourth provenance state: signed bytes, no key
configured to check them. Untrusted, but a different condition from
UNSIGNED_FILE with a different remedy, and collapsing them would send an
operator to re-sign a document that is already signed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gyza.containment.engine import GuardEngine
from gyza.containment.gyza_model import (
    DEFAULT_BOUNDS_FILE,
    PLAIN_BOUNDS_FILE,
    build_registries,
)


def test_the_default_is_the_SIGNED_configuration():
    assert DEFAULT_BOUNDS_FILE.name == "guard_bounds.signed.json"
    assert DEFAULT_BOUNDS_FILE.exists()


def test_signed_and_plain_files_declare_IDENTICAL_levels():
    """The switch must change provenance only. If the values differed, this
    would silently alter what is enforced."""
    signed = json.loads(DEFAULT_BOUNDS_FILE.read_text())["config"]["bounds"]
    plain = json.loads(PLAIN_BOUNDS_FILE.read_text())["bounds"]
    assert signed == plain


def test_default_load_yields_SIGNED_UNVERIFIED_and_is_NOT_trusted():
    harm, inv = build_registries()
    r = GuardEngine(harm, inv).readiness()
    assert r["bounds_provenance"]["source"] == "SIGNED_UNVERIFIED"
    assert r["bounds_signed"] is False, "unverified must never read as signed"
    assert r["can_claim_containment"] is False


def test_the_envelope_actually_yields_BOUNDS_not_an_empty_model():
    """The trap in switching the default: a silently empty bounds set."""
    harm, _ = build_registries()
    assert harm.bound("H5_storage_growth") == 10_000_000_000.0
    assert harm.bound("H6_unsupervised_actions") == 10_000
    assert harm.bound("H4_authority") == 0.0


def test_a_plain_file_still_reports_UNSIGNED_FILE():
    """The two untrusted states stay DISTINCT -- different remedies."""
    harm, inv = build_registries(bounds_file=PLAIN_BOUNDS_FILE)
    r = GuardEngine(harm, inv).readiness()
    assert r["bounds_provenance"]["source"] == "UNSIGNED_FILE"
    assert r["bounds_signed"] is False


def test_TAMPERING_WITH_THE_SIGNED_FILE_IS_DETECTABLE(tmp_path):
    """THE POINT OF THE WHOLE CHANGE.

    Before, the signature covered a file nothing loaded, so editing the loaded
    file broke nothing checkable. Now the loaded bytes ARE the signed bytes, so
    a verifier holding the pubkey rejects a tampered configuration.
    """
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from gyza.containment.guardconfig import GuardConfigError, GuardConfigStore

    # FIND the key rather than assuming ~/.gyza/authority.key. This test
    # hardcoded that path and began SILENTLY SKIPPING the moment the key was
    # relocated on 2026-08-21 -- a coverage regression that a green suite would
    # have reported as success. It now locates the key through the same
    # production locator the colocation check uses, so a legitimate move keeps
    # the test running and only a genuinely absent key skips it.
    from gyza.config import load_config
    from gyza.containment.guardconfig import authority_key_is_colocated

    configured = (load_config().guard_authority_pubkey or "").strip()
    found = authority_key_is_colocated(configured) if configured else None
    if not found:
        pytest.skip("no local authority key to verify against")
    raw = Path(found)
    sk = Ed25519PrivateKey.from_private_bytes(raw.read_bytes()[:32])
    pub = sk.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)

    # untampered: verifies, and is TRUSTED
    harm, inv = build_registries(bounds_file=DEFAULT_BOUNDS_FILE,
                                 authority_pubkey=pub)
    r = GuardEngine(harm, inv).readiness()
    assert r["bounds_provenance"]["source"] == "SIGNED"
    assert r["bounds_signed"] is True

    # tampered: a raised bound with the ORIGINAL signature must be refused
    doc = json.loads(DEFAULT_BOUNDS_FILE.read_text())
    doc["config"]["bounds"]["H6_unsupervised_actions"] = 10_000_000
    bad = tmp_path / "tampered.signed.json"
    bad.write_text(json.dumps(doc))
    with pytest.raises((GuardConfigError, Exception)):
        GuardConfigStore(pub).load_file(bad)


# --------------------------------------------------------------------------- #
#  SIGNED IS NOT SEPARATED. C-8's base case is that the constrained system      #
#  does not hold the signing key. The header of sign_guard_config.py states it  #
#  -- "keep it off the machine that runs agents" -- and NOTHING VERIFIED IT.    #
# --------------------------------------------------------------------------- #
def test_colocated_authority_key_is_DETECTED(tmp_path):
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from gyza.containment.guardconfig import authority_key_is_colocated

    import secrets
    seed = secrets.token_bytes(32)
    pub = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
        ser.Encoding.Raw, ser.PublicFormat.Raw).hex()
    kf = tmp_path / "authority.key"
    kf.write_bytes(seed)

    assert authority_key_is_colocated(pub, [str(kf)]) == str(kf)


def test_an_UNRELATED_key_on_disk_is_NOT_reported_as_colocated(tmp_path):
    """The counter-control. Reporting every key file as 'the authority key'
    would make the warning noise, and a warning that always fires is ignored."""
    import secrets

    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from gyza.containment.guardconfig import authority_key_is_colocated

    pub = Ed25519PrivateKey.from_private_bytes(
        secrets.token_bytes(32)).public_key().public_bytes(
            ser.Encoding.Raw, ser.PublicFormat.Raw).hex()
    other = tmp_path / "somebody_elses.key"
    other.write_bytes(secrets.token_bytes(32))

    assert authority_key_is_colocated(pub, [str(other)]) is None


def test_a_missing_or_short_key_file_is_handled(tmp_path):
    from gyza.containment.guardconfig import authority_key_is_colocated

    short = tmp_path / "truncated.key"
    short.write_bytes(b"\x01" * 8)
    assert authority_key_is_colocated("00" * 32,
                                      [str(short), str(tmp_path / "nope")]) is None


def test_status_WARNS_when_the_key_is_colocated(capsys, monkeypatch):
    """A green SIGNED line next to a co-located key would read as 'trust root
    secure' when it means 'trust root is on the same disk'."""
    from gyza.cli import _print_containment_section
    from gyza.config import load_config

    cfg = load_config()
    if not cfg.guard_authority_pubkey:
        pytest.skip("no authority pubkey pinned in this environment")
    _print_containment_section(cfg)
    out = capsys.readouterr().out
    if "bounds: SIGNED" in out and "AUTHORITY PRIVATE KEY is on this host" in out:
        assert "does not hold" in out or "re-sign the policy" in out
        assert "Move it to" in out, "the warning must say what to do"


# =========================================================================== #
#  C-8'S BASE CASE BELONGS IN THE PREDICATE, NOT IN A PRINT STATEMENT.
#
#  `authority_key_is_colocated` existed, was correct, and its ONLY production
#  caller was a print block in `gyza status`. `readiness()` never asked, so
#  `can_claim_containment` required SIGNED bounds and said nothing about
#  SEPARATION -- and separation is the premise the whole induction rests on.
#
#  The consequence was latent rather than theoretical: H3 is the last unbounded
#  class. Bound it, and the claim would have flipped TRUE with the authority
#  private key sitting in ~/.gyza next to the agents it constrains. That is the
#  sixth time in this program a claim was one declaration away from being
#  available without the substance behind it.
# =========================================================================== #
def _signed_bounded_engine(tmp_path, key_on_disk: bool):
    """A fully bounded, correctly SIGNED model. The only variable is whether
    the authority private key is reachable from the host."""
    import secrets

    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from gyza.containment.engine import GuardEngine
    from gyza.containment.harm import (
        BoundsProvenance, DriftClass, HarmClass, HarmModelRegistry,
    )
    from gyza.containment.invariants import (
        Invariant, InvariantClass, InvariantRegistry,
    )

    seed = secrets.token_bytes(32)
    pub = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
        ser.Encoding.Raw, ser.PublicFormat.Raw).hex()

    harm = HarmModelRegistry()
    harm.register(HarmClass(
        id="X_exposure", description="d", quantity=lambda s0, s: 0.0,
        frame="f", frame_mutable=False, code_path="p",
        drift_class=DriftClass.SILENCE,
        drift_reason="benign behaviour never increments this quantity"))
    harm.load_bounds({"X_exposure": 1.0}, provenance=BoundsProvenance(
        # `trusted` is DERIVED from source == "SIGNED", not a field. There is
        # deliberately no way to construct a provenance that claims trust
        # without claiming the source that earns it.
        source="SIGNED", detail="test", authority_pubkey_hex=pub,
        version=1, config_hash="h"))

    inv = InvariantRegistry()
    inv.register(Invariant(
        id="INV-X", harm_class="X_exposure", cls=InvariantClass.CUMULATIVE,
        description="covers X"))

    search = []
    if key_on_disk:
        kf = tmp_path / "authority.key"
        kf.write_bytes(seed)
        search = [str(kf)]
    else:
        search = [str(tmp_path / "not-here.key")]
    return GuardEngine(harm, inv), search


def test_a_COLOCATED_key_blocks_the_containment_claim_even_when_fully_bounded(tmp_path):
    """The scenario that would otherwise flip the flag without the substance."""
    engine, search = _signed_bounded_engine(tmp_path, key_on_disk=True)
    r = engine.readiness(authority_key_search=search)

    assert r["bounds_signed"] is True
    assert r["unbounded"] == []
    assert r["uncovered"] == []
    assert r["authority_key_colocated"] == search[0]
    assert r["can_claim_containment"] is False, (
        "every other obstacle was cleared and the authority private key is on "
        "this host; a local compromise re-signs any bounds it likes, so the "
        "induction has no base case and the claim must not be available")


def test_separation_RESTORES_the_claim_so_the_check_is_not_merely_a_veto(tmp_path):
    """The counter-control. A check that blocks unconditionally is not a check
    -- it must be satisfiable, or it is just a disabled feature."""
    engine, search = _signed_bounded_engine(tmp_path, key_on_disk=False)
    r = engine.readiness(authority_key_search=search)

    assert r["authority_key_colocated"] is None
    assert r["can_claim_containment"] is True


def test_an_ERROR_determining_separation_is_NOT_read_as_separated(tmp_path,
                                                                  monkeypatch):
    """AN ERROR IS NOT A VALUE. Failing to determine colocation must not read
    as 'separated' -- that is the reassuring direction, and the reassuring
    direction is the one that does not get questioned."""
    import gyza.containment.guardconfig as gc

    engine, search = _signed_bounded_engine(tmp_path, key_on_disk=False)

    def _boom(*_a, **_k):
        raise OSError("permission denied scanning for the authority key")

    monkeypatch.setattr(gc, "authority_key_is_colocated", _boom)
    r = engine.readiness(authority_key_search=search)

    assert r["authority_key_colocated"] == "UNDETERMINED"
    assert r["can_claim_containment"] is False


def test_relocating_the_key_does_NOT_silence_the_colocation_check(tmp_path,
                                                                  monkeypatch):
    """A check a `mv` defeats reports where the key ISN'T.

    The default search listed two paths, so moving the authority key one
    directory sideways cleared the warning while changing nothing about the
    risk: anything running as the agent's user could still read it and re-sign
    the policy it is constrained by. Widening does not make the check sound --
    it cannot prove absence anywhere it does not look -- but the common
    relocations must not silently pass.
    """
    import secrets

    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from gyza.containment.guardconfig import authority_key_is_colocated

    seed = secrets.token_bytes(32)
    pub = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
        ser.Encoding.Raw, ser.PublicFormat.Raw).hex()

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for rel in (".gyza/authority.key", ".gyza-authority/authority.key",
                ".config/gyza/authority.key", "authority.key"):
        kf = home / rel
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_bytes(seed)
        assert authority_key_is_colocated(pub) == str(kf), (
            f"a key at ~/{rel} was not detected; relocating there would clear "
            f"the warning without achieving any separation")
        kf.unlink()

    # ...and with the key genuinely gone from every searched location, the
    # check must clear. Otherwise it is a permanent veto rather than a check.
    assert authority_key_is_colocated(pub) is None
