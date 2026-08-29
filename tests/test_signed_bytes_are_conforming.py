"""Signed bytes must be reproducible by a conforming JSON parser.

THE INVARIANT THAT WAS DOCUMENTED AND UNENFORCED. `ICPEnvelope` annotates every
field `str` / `int` / `list[str]`, so "no float can reach the signed payload" is
true of the annotations and enforced by nothing: dataclasses do not check types
at runtime. Python then emits bare `NaN` / `Infinity`, which RFC 8259 does not
define and Rust's serde_json refuses -- producing a BLAKE3 hash and an Ed25519
signature over bytes no other implementation can reproduce.

This is the ASCII invariant's twin. That one was recorded as a mistake for
exactly this reason; this file is the mechanism the ASCII case lacked.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_signed_bytes_are_conforming.py -q
"""
from __future__ import annotations

import json

import pytest

from gyza.icp import ICPEnvelope, _payload_bytes, compute_envelope_hash
from gyza.identity import manifest_canonical_bytes


def _env(**kw):
    base = dict(intent_id="i", action_id="a", agent_pubkey="p",
                capability_manifest_hash="h", input_hashes=[], output_hash="o",
                parent_envelope_hash=None, timestamp_ns=1,
                inference_backend="b", model_identifier="m",
                duration_ms=10, tokens_in=0, tokens_out=0)
    base.update(kw)
    return ICPEnvelope(**base)


def _strict_loads(b: bytes):
    """Reject exactly what a conforming parser rejects. Python's own
    `json.loads` accepts NaN, so validating our output with it proves
    nothing -- a self-check between two lenient implementations."""
    def _boom(c):
        raise ValueError(f"non-finite constant {c!r} is not JSON")
    return json.loads(b.decode("utf-8"), parse_constant=_boom)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_field_REFUSES_TO_SIGN(bad):
    with pytest.raises(ValueError, match="not JSON compliant"):
        _payload_bytes(_env(duration_ms=bad))
    with pytest.raises(ValueError, match="not JSON compliant"):
        compute_envelope_hash(_env(tokens_out=bad))


def test_a_finite_envelope_still_signs_and_is_STRICTLY_parseable():
    b = _payload_bytes(_env())
    assert _strict_loads(b)["duration_ms"] == 10
    assert b"NaN" not in b and b"Infinity" not in b


def test_the_manifest_path_is_guarded_too():
    """Manifests are hashed into the envelope, so the same hole there would
    poison the capability_manifest_hash rather than the payload."""
    with pytest.raises(ValueError, match="not JSON compliant"):
        manifest_canonical_bytes({"memory_limit_mb": float("nan")})
    assert b"NaN" not in manifest_canonical_bytes({"memory_limit_mb": 512})


def test_the_lenient_self_check_would_have_MISSED_this():
    """Kept as a negative control: Python validating its own output is not
    evidence, and this is the assertion that would have passed while the bug
    was live."""
    payload = b'{"duration_ms":NaN}'
    assert json.loads(payload)              # Python accepts its own NaN
    with pytest.raises(ValueError):
        _strict_loads(payload)              # a conforming parser does not


# --------------------------------------------------------------------------- #
#  THE SWEEP. `allow_nan=False` was applied to icp.py and identity.py and NOT  #
#  to the other eight canonical encoders -- the same shape as the             #
#  "kernel-enforced swept from README only" defect. This asserts every        #
#  canonical-bytes function in gyza/ carries the guard, so the next one added  #
#  cannot quietly omit it.                                                     #
# --------------------------------------------------------------------------- #
def test_every_canonical_encoder_refuses_non_finite():
    """A signed-bytes function without allow_nan=False emits bare NaN --
    not RFC 8259, unparseable by Rust's serde_json, and hashed + signed."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "gyza"
    offenders = []
    for p in sorted(root.rglob("*.py")):
        src = p.read_text()
        # canonical encoders are the sort_keys=True + compact-separators form
        for m in re.finditer(r"json\.dumps\((?:[^()]|\([^()]*\))*?\)", src,
                             re.DOTALL):
            call = m.group(0)
            if "sort_keys=True" not in call:
                continue
            if 'separators=(",", ":")' not in call:
                continue          # pretty-printed config writes, not signed
            if "allow_nan=False" not in call:
                line = src[:m.start()].count("\n") + 1
                offenders.append(f"{p.relative_to(root)}:{line}")
    assert offenders == [], (
        "canonical encoders missing allow_nan=False: " + ", ".join(offenders))
