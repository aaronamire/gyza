"""A validly-signed OLD configuration is a ROLLBACK, and it needs no key.

`GuardConfigStore` checks version and permissiveness monotonicity against
`self._cfg`, which is None on every fresh store. So until 2026-08-21 a COLD
LOAD accepted any previously-signed configuration -- demonstrated below against
the real file shipped at v0.1.3, which installed cleanly over v3.

WHY THIS IS THE ONE ATTACK A SIGNATURE CANNOT SHOW YOU. It needs host write
access, which also permits replacing code -- but replacing code breaks
integrity checks, whereas a rollback leaves EVERY SIGNATURE VERIFYING.
`gyza status` would report `bounds: SIGNED (v1, authority ...)` and be telling
the truth. The version integer was the only tell, and nothing compared it
against anything.

WHAT THE FIX DOES NOT DO, asserted at the bottom rather than argued: an
attacker who can write BOTH the configuration and the history can reset both.
Local storage cannot prevent that; only trusted storage or a remote witness
can. This turns a silent downgrade into a refusal, and that is all it claims.
"""
from __future__ import annotations

import json
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.containment.guardconfig import (
    GuardConfigError, GuardConfigStore, sign_config,
)


def _authority():
    seed = secrets.token_bytes(32)
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    return seed, sk.public_key().public_bytes_raw()


def _cfg(version, bounds):
    return {"version": version, "bounds": dict(bounds), "policy": {},
            "tier_assignments": {}}


def test_a_cold_store_REFUSES_a_previously_signed_older_config(tmp_path):
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    old = _cfg(1, {"H4_authority": 0.0, "H5_storage_growth": 1e10})
    new = _cfg(3, {"H4_authority": 0.0, "H5_storage_growth": 1e9})

    GuardConfigStore(pub, history_path=hist).load(new, sign_config(new, seed))

    # A FRESH store -- as after a restart. The old config is validly signed by
    # the same authority; no key was needed to produce it.
    with pytest.raises(GuardConfigError, match="previously installed"):
        GuardConfigStore(pub, history_path=hist).load(old, sign_config(old, seed))


def test_the_SAME_version_still_installs_so_restarts_work(tmp_path):
    """The floor must not brick an ordinary restart, which reinstalls the
    configuration already in force."""
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    cfg = _cfg(3, {"H4_authority": 0.0})
    GuardConfigStore(pub, history_path=hist).load(cfg, sign_config(cfg, seed))
    again = GuardConfigStore(pub, history_path=hist).load(
        cfg, sign_config(cfg, seed))
    assert again.version == 3


def test_a_NEWER_version_still_installs(tmp_path):
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    for v in (1, 2, 5):
        c = _cfg(v, {"H4_authority": 0.0})
        assert GuardConfigStore(pub, history_path=hist).load(
            c, sign_config(c, seed)).version == v


def test_an_EDITED_history_fails_closed(tmp_path):
    """An edited history is exactly what a rollback needs, so an unverifiable
    chain must raise rather than return a floor of 0. 'I cannot tell' must not
    read as 'no floor'."""
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    for v in (1, 2, 3):
        c = _cfg(v, {"H4_authority": 0.0})
        GuardConfigStore(pub, history_path=hist).load(c, sign_config(c, seed))

    lines = hist.read_text().splitlines()
    assert len(lines) == 3
    # Drop the middle entry -- the cheapest way to lower the floor while
    # leaving a file that still parses.
    hist.write_text("\n".join([lines[0], lines[2]]) + "\n")

    c = _cfg(1, {"H4_authority": 0.0})
    with pytest.raises(GuardConfigError, match="chain breaks"):
        GuardConfigStore(pub, history_path=hist).load(c, sign_config(c, seed))


def test_a_CORRUPT_history_line_fails_closed(tmp_path):
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    c = _cfg(3, {"H4_authority": 0.0})
    GuardConfigStore(pub, history_path=hist).load(c, sign_config(c, seed))
    hist.write_text("this is not json\n")

    with pytest.raises(GuardConfigError, match="unreadable"):
        GuardConfigStore(pub, history_path=hist).load(c, sign_config(c, seed))


def test_NO_history_path_keeps_the_OLD_permissive_behaviour(tmp_path):
    """Explicit, so the limitation is visible rather than implied: a store
    constructed without a history has no floor and accepts a rollback. Every
    production construction supplies one (`gyza_model.build_registries`), and
    `tests/test_declared_is_wired.py` is what keeps that true."""
    seed, pub = _authority()
    old = _cfg(1, {"H4_authority": 0.0})
    new = _cfg(3, {"H4_authority": 0.0})
    GuardConfigStore(pub).load(new, sign_config(new, seed))
    assert GuardConfigStore(pub).load(old, sign_config(old, seed)).version == 1


def test_the_fix_does_NOT_stop_an_attacker_who_can_write_BOTH_files(tmp_path):
    """The ceiling, asserted so it cannot be forgotten or overstated.

    Rollback prevention on local storage is bounded by what the attacker can
    write. Deleting the history resets the floor. Closing this needs trusted
    storage or a remote witness, and neither exists here.
    """
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    new = _cfg(3, {"H4_authority": 0.0})
    old = _cfg(1, {"H4_authority": 0.0})
    GuardConfigStore(pub, history_path=hist).load(new, sign_config(new, seed))

    hist.unlink()                       # the attacker removes the floor
    assert GuardConfigStore(pub, history_path=hist).load(
        old, sign_config(old, seed)).version == 1, (
        "if this now REFUSES, the fix became stronger than claimed and the "
        "docstring above should be corrected")


def test_the_REAL_shipped_v0_1_3_config_is_refused_after_v3(tmp_path):
    """Not a synthetic payload: the file published in the v0.1.3 release.

    A rollback payload is a file from git history, so this is the attack as it
    would actually be mounted.
    """
    import subprocess

    from gyza.config import load_config

    try:
        raw = subprocess.run(
            ["git", "show", "977fead:gyza/containment/guard_bounds.signed.json"],
            capture_output=True, text=True, timeout=30, check=True).stdout
    except Exception:                                        # noqa: BLE001
        pytest.skip("v0.1.3 blob not available in this checkout")

    old = json.loads(raw)
    pub_hex = (load_config().guard_authority_pubkey or "").strip()
    if not pub_hex:
        pytest.skip("no authority pubkey configured")
    pub = bytes.fromhex(pub_hex)

    cur = json.loads(
        (__import__("pathlib").Path("gyza/containment/guard_bounds.signed.json")
         ).read_text())
    hist = tmp_path / "history.jsonl"
    store = GuardConfigStore(pub, history_path=hist)
    store.load(cur["config"], cur["signature"])

    with pytest.raises(GuardConfigError, match="previously installed"):
        GuardConfigStore(pub, history_path=hist).load(
            old["config"], old["signature"])


# =========================================================================== #
#  A HIGHER VERSION IS NOT A LICENCE TO LOOSEN
#
#  The rollback floor closed the NO-KEY attack: replaying an old signed file.
#  It does nothing about a key-holder signing a NEW version with looser bounds,
#  which installed cleanly on any restart -- every signature verifying, `gyza
#  status` reporting SIGNED, and the containment claim now over bounds someone
#  else chose. Version monotonicity and PERMISSIVENESS monotonicity are
#  different properties and the first does not imply the second.
#
#  This does not stop a key-holder; nothing does. It makes loosening an act
#  that must be DECLARED through `install_loosening` with a separately signed
#  record -- even across a restart, which is what that mechanism was for.
# =========================================================================== #

def test_a_cold_store_REFUSES_a_LOOSENED_higher_version(tmp_path):
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    tight = _cfg(3, {"H4_authority": 0.0, "H5_storage_growth": 1e9})
    loose = _cfg(4, {"H4_authority": 999.0, "H5_storage_growth": 1e15})

    GuardConfigStore(pub, history_path=hist).load(tight, sign_config(tight, seed))
    with pytest.raises(GuardConfigError, match="LOOSEN"):
        GuardConfigStore(pub, history_path=hist).load(loose, sign_config(loose, seed))


def test_a_cold_store_ACCEPTS_a_TIGHTENED_higher_version(tmp_path):
    """The counter-control. A check that refused every new version would be a
    check nobody could operate around, and tightening must stay cheap."""
    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    tight = _cfg(3, {"H5_storage_growth": 1e9})
    tighter = _cfg(4, {"H5_storage_growth": 1e8})

    GuardConfigStore(pub, history_path=hist).load(tight, sign_config(tight, seed))
    got = GuardConfigStore(pub, history_path=hist).load(
        tighter, sign_config(tighter, seed))
    assert got.bounds["H5_storage_growth"] == 1e8


def test_a_DECLARED_loosening_still_works_across_a_restart(tmp_path):
    """Loosening is PERMITTED -- it is a distinct operation, not a forbidden
    one. If this failed, the check would have turned a process control into a
    brick wall and operators would route around it."""
    from gyza.containment.guardconfig import LooseningRecord, sign_loosening

    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    tight = _cfg(3, {"H5_storage_growth": 1e9})
    loose = _cfg(4, {"H5_storage_growth": 1e10})

    GuardConfigStore(pub, history_path=hist).load(tight, sign_config(tight, seed))

    # A NEW process: load what is in force, then loosen with a signed record.
    store = GuardConfigStore(pub, history_path=hist)
    store.load(tight, sign_config(tight, seed))
    rec = LooseningRecord(changes=(("H5_storage_growth", 1e9, 1e10),),
                          reason="retention window extended")
    got = store.install_loosening(loose, sign_config(loose, seed), rec,
                                  sign_loosening(rec, seed), requested_by="op")
    assert got.bounds["H5_storage_growth"] == 1e10
    assert store.alarms and "GUARD-LOOSENED" in store.alarms[0]

    # ...and the now-looser configuration becomes the baseline, so a later cold
    # load of it is not itself treated as a fresh loosening.
    after = GuardConfigStore(pub, history_path=hist).load(
        loose, sign_config(loose, seed))
    assert after.version == 4


def test_the_chain_covers_the_BOUNDS_it_protects(tmp_path):
    """An unprotected field is a field an attacker edits instead of attacking
    the check. If `bounds` were outside the link, the recorded baseline could
    be rewritten without breaking the chain, and the loosening check would
    compare against whatever the attacker chose."""
    import json

    seed, pub = _authority()
    hist = tmp_path / "history.jsonl"
    cfg = _cfg(3, {"H5_storage_growth": 1e9})
    GuardConfigStore(pub, history_path=hist).load(cfg, sign_config(cfg, seed))
    GuardConfigStore(pub, history_path=hist).load(cfg, sign_config(cfg, seed))

    lines = hist.read_text().splitlines()
    first = json.loads(lines[0])
    assert "bounds" in first, "the history does not record bounds at all"
    first["bounds"] = {"H5_storage_growth": 1e15}          # forge the baseline
    hist.write_text("\n".join([json.dumps(first, sort_keys=True), lines[1]]) + "\n")

    with pytest.raises(GuardConfigError, match="chain breaks"):
        GuardConfigStore(pub, history_path=hist).load(cfg, sign_config(cfg, seed))


def test_BOTH_hash_sites_agree_on_what_a_link_commits_to():
    """The defect this cost an hour on. Two sites computed a link from two
    hand-written field lists; one kept the pre-bounds shape while the writer
    moved on, so every honest chain verified as BROKEN -- an integrity check
    failing on good data, which is the worst kind because the reflex is to
    weaken it. Both now call one function."""
    import inspect

    from gyza.containment import guardconfig as gc

    for fn in (gc.GuardConfigStore._version_floor,
               gc.GuardConfigStore._record_install):
        src = inspect.getsource(fn)
        assert "_link_payload" in src, (
            f"{fn.__name__} hand-rolls the link payload; it will drift from "
            f"the other site the next time a field is added")
