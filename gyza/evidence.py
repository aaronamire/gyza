"""
Evidence bundles — a workflow's provenance, portable and self-contained.

The audit (``gyza.audit``) answers "is this workflow intact and within
bounds?" for whoever holds the envelopes and their evidence. This module
makes that question *portable*: one deterministic file carrying the
envelopes, the artifacts they commit to, and the manifests that bounded
them — everything a third party needs to run the audit themselves, with
no node, no daemon, no identity, and no trust in the sender.

Nothing in a bundle is trusted on arrival. Its integrity is interior:
envelopes are Ed25519-signed, artifacts are content-addressed by the
signed ``output_hash``, manifests by the signed
``capability_manifest_hash``. The bundle is just a carrier; forging any
byte of evidence surfaces in ``verify_bundle`` exactly as it would in a
local audit, because it IS the local audit run over the bundle's maps.

Serialization is canonical (sorted keys, no whitespace), so the same
workflow exported by the same build yields byte-identical bundles — a
bundle's BLAKE3 hash is a stable citation for "this exact body of
evidence". The ``runner`` metadata identifies the exporting build; it is
informational and unauthenticated (the *verifiable* release identity of
each action lives inside the signed artifacts, not here).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Callable
import json
from dataclasses import asdict

import blake3

from gyza.audit import AuditReport, audit_provenance
from gyza.icp import ICPEnvelope

BUNDLE_FORMAT = "gyza-evidence-bundle"
BUNDLE_VERSION = 1

# Every top-level key a v1 bundle carries — load_bundle rejects anything
# missing or extra, so a malformed/extended file fails loudly here rather
# than surfacing as a confusing audit failure later.
_BUNDLE_KEYS = {
    "format", "version", "intent_id", "runner", "envelopes",
    "artifacts", "manifests",
}
#: OPTIONAL keys. `closure` is optional so bundles produced before completeness
#: existed still load -- and `verify_closure` then reports NOT ASSERTED, which
#: is the honest reading rather than a silent pass.
_BUNDLE_OPTIONAL_KEYS = {"closure"}


class BundleError(ValueError):
    """A file that is not a well-formed v1 evidence bundle."""


def create_bundle(
    envelopes: "list[ICPEnvelope]",
    *,
    resolve_artifact,
    resolve_manifest,
    intent_id: str = "",
) -> dict:
    """
    Assemble a bundle dict from a workflow's envelopes plus the same
    content-addressed resolvers ``audit_provenance`` takes.

    Collection is permissive — whatever evidence resolves is included,
    whatever doesn't is simply absent — because exporting a *broken*
    workflow is a legitimate act (an auditor shipping proof of a
    violation). Judgment belongs to ``verify_bundle``, which fails
    closed on anything missing, exactly like the local audit.
    """
    artifacts: dict[str, str] = {}
    manifests: dict[str, dict] = {}
    for env in envelopes:
        if env.output_hash not in artifacts:
            raw = resolve_artifact(env.output_hash)
            if raw is not None:
                artifacts[env.output_hash] = base64.b64encode(raw).decode("ascii")
        if env.capability_manifest_hash not in manifests:
            manifest = resolve_manifest(env.capability_manifest_hash)
            if manifest is not None:
                manifests[env.capability_manifest_hash] = manifest

    from gyza.release import CURRENT_RELEASE
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "intent_id": intent_id,
        "runner": CURRENT_RELEASE.as_dict(),
        "envelopes": [asdict(env) for env in envelopes],
        "artifacts": artifacts,
        "manifests": manifests,
    }


def bundle_to_bytes(bundle: dict) -> bytes:
    """Canonical serialization — sorted keys, no whitespace, UTF-8."""
    return json.dumps(bundle, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def bundle_hash(bundle: dict) -> str:
    """BLAKE3 of the canonical bytes — a stable citation for this exact
    body of evidence."""
    return blake3.blake3(bundle_to_bytes(bundle)).hexdigest()


def load_bundle(data: bytes) -> dict:
    """
    Parse and structurally validate bundle bytes. Raises ``BundleError``
    on anything that is not a well-formed v1 bundle. Validation here is
    shape only — cryptographic judgment is ``verify_bundle``'s job.
    """
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise BundleError("bundle must be a JSON object")
    if obj.get("format") != BUNDLE_FORMAT:
        raise BundleError(
            f"format is {obj.get('format')!r}, expected {BUNDLE_FORMAT!r}"
        )
    if obj.get("version") != BUNDLE_VERSION:
        raise BundleError(
            f"bundle version {obj.get('version')!r} not supported "
            f"(this client reads version {BUNDLE_VERSION})"
        )
    unknown = set(obj) - _BUNDLE_KEYS - _BUNDLE_OPTIONAL_KEYS
    missing = _BUNDLE_KEYS - set(obj)
    if unknown or missing:
        raise BundleError(
            f"unexpected bundle shape: keys {sorted(unknown | missing)} "
            f"missing or unrecognized"
        )
    if not isinstance(obj["envelopes"], list) or not obj["envelopes"]:
        raise BundleError("bundle carries no envelopes")
    if not isinstance(obj["artifacts"], dict) or not isinstance(
        obj["manifests"], dict
    ):
        raise BundleError("artifacts and manifests must be objects")
    return obj


def _envelopes_of(bundle: dict) -> "list[ICPEnvelope]":
    out: list[ICPEnvelope] = []
    for i, d in enumerate(bundle["envelopes"]):
        if not isinstance(d, dict):
            raise BundleError(f"envelope [{i}] is not an object")
        try:
            out.append(ICPEnvelope(**d))
        except TypeError as exc:
            raise BundleError(f"envelope [{i}] has wrong fields: {exc}") from exc
    return out


@dataclass(frozen=True)
class ClosureStatus:
    """Whether the producer asserted this bundle is COMPLETE, and whether that
    assertion holds against the bundle's contents.

    `asserted=False` is not a pass. Measured 2026-08-23: a bundle commits to
    what it contains and not to what it omits, so deleting a LEAF envelope --
    nothing references a leaf -- leaves a smaller bundle that still verifies.
    Tampering was caught; omission was not.
    """
    asserted: bool
    valid: bool
    reason: str
    count: int = 0

    @property
    def line(self) -> str:
        if not self.asserted:
            return ("Completeness: NOT ASSERTED — this bundle does not claim "
                    "to be a complete record. Actions may have been omitted.")
        if self.valid:
            return (f"Completeness: ASSERTED over {self.count} action(s) and "
                    f"the assertion HOLDS.")
        return f"Completeness: ASSERTED but BROKEN — {self.reason}"


def closure_payload(intent_id: str, envelope_hashes: list[str]) -> dict:
    """The bytes a producer signs to claim a bundle is complete.

    Hashes are SORTED before commitment: the set is the claim, and bundle
    ordering is an artifact of how the DAG was walked, not part of what is
    being asserted. Committing to an order would make a re-serialised bundle
    fail for no reason.
    """
    ordered = sorted(set(envelope_hashes))
    joined = "\n".join(ordered).encode("utf-8")
    return {
        "intent_id": intent_id,
        "count": len(ordered),
        "root": blake3.blake3(joined).hexdigest(),
    }


def _closure_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def attach_closure(bundle: dict, *, signer_pubkey_hex: str,
                   sign: "Callable[[bytes], bytes]") -> dict:
    """Sign a claim that `bundle` is the COMPLETE record of its intent.

    WHAT THIS CAN AND CANNOT DO, because overstating it would be worse than
    omitting it. It cannot force a producer to report an action: a dishonest
    exporter signs a closure over a set that excluded the inconvenient action
    from the start, and that bundle verifies.

    What it buys is that silence becomes a SIGNED, FALSIFIABLE CLAIM. After
    this, an omission is no longer invisible -- it is a statement the producer
    put its key behind. Two different signed closures for one intent are
    cryptographic proof of equivocation, and any observer holding an envelope
    absent from a set signed "complete" holds proof of a lie. That is the
    difference between no evidence and evidence of a lie, and at scale it is
    the whole basis on which reputation can mean anything.
    """
    payload = closure_payload(bundle.get("intent_id", ""),
                              [_hash_of(e) for e in bundle.get("envelopes", [])])
    bundle["closure"] = {
        **payload,
        "asserted_by": signer_pubkey_hex,
        # `sign` may return raw bytes or hex -- AgentIdentity.sign_bytes
        # returns hex. Normalise here rather than making every caller know.
        "signature": _as_hex(sign(_closure_bytes(payload))),
    }
    return bundle


def _as_hex(sig: "bytes | str") -> str:
    return sig if isinstance(sig, str) else bytes(sig).hex()


def _hash_of(env_dict: dict) -> str:
    """Content address of one envelope, recomputed rather than trusted.

    Taking a self-declared `envelope_hash` field would make the closure a
    commitment to whatever the producer TYPED, not to the envelopes present.
    """
    from gyza.icp import ICPEnvelope, compute_envelope_hash
    try:
        return compute_envelope_hash(ICPEnvelope(**env_dict))
    except TypeError:
        return ""


def verify_closure(bundle: dict) -> ClosureStatus:
    """Check a completeness claim against what the bundle actually contains."""
    c = bundle.get("closure")
    if not isinstance(c, dict):
        return ClosureStatus(False, False, "no closure record")

    present = sorted({_hash_of(e) for e in bundle.get("envelopes", [])})
    recomputed = closure_payload(bundle.get("intent_id", ""), present)

    if recomputed["root"] != c.get("root") or recomputed["count"] != c.get("count"):
        return ClosureStatus(
            True, False,
            f"the bundle holds {recomputed['count']} action(s) but the signed "
            f"closure commits to {c.get('count')}; actions have been ADDED or "
            f"REMOVED since it was signed",
            recomputed["count"])

    pub = c.get("asserted_by") or ""
    payload = {k: c[k] for k in ("intent_id", "count", "root") if k in c}
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(
            bytes.fromhex(c.get("signature", "")), _closure_bytes(payload))
    except InvalidSignature:
        return ClosureStatus(True, False,
                             "the closure signature does not verify")
    except Exception as exc:                                   # noqa: BLE001
        return ClosureStatus(True, False,
                             f"closure signature unreadable: {exc}")
    return ClosureStatus(True, True, "", recomputed["count"])


def verify_bundle(bundle: dict) -> AuditReport:
    """
    Run the real audit over a loaded bundle. Pure function of the bundle
    contents: strict linkage (``require_closed``) and fail-closed on any
    unresolvable evidence — a third party never passes what it cannot
    check.
    """
    envelopes = _envelopes_of(bundle)
    artifacts: dict[str, bytes] = {}
    for h, b64 in bundle["artifacts"].items():
        try:
            artifacts[h] = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise BundleError(f"artifact {h[:12]}… is not valid base64") from exc
    manifests = bundle["manifests"]

    # FAIL CLOSED ON A BROKEN COMPLETENESS CLAIM. An asserted-but-invalid
    # closure means actions were added or removed after signing, which is
    # tampering and must not reach a verdict line. An ABSENT closure is not an
    # error -- older bundles have none -- but it is reported, never silently
    # treated as "fine": "I did not say" must not read as "nothing was left
    # out", which is the same rule the enforcement record follows.
    st = verify_closure(bundle)
    if st.asserted and not st.valid:
        raise BundleError(st.reason)

    return audit_provenance(
        envelopes,
        resolve_artifact=artifacts.get,
        resolve_manifest=lambda h: manifests.get(h)
        if isinstance(manifests.get(h), dict) else None,
        require_closed=True,
        require_all_artifacts=True,
        # GOVERNED FOR THE THIRD PARTY TOO. `governed` defaults to False and
        # only `gyza audit` -- the LOCAL operator, who already trusts the
        # machine -- was passing it. The third party, who trusts nothing and is
        # the entire reason this format exists, was told the verdict without
        # being told which checks ran under an attested specification, or that
        # any check did not. That asymmetry was exactly backwards.
        governed=True,
    )


def render_verify_verdict_line(report: AuditReport) -> str:
    """One-line verdict for CLI output; the full forensic report is
    ``gyza.audit.render_audit_report``."""
    word = "VALID" if report.valid else "INVALID"
    return f"verdict: {word}  ({report.summary})"


__all__ = [
    "ClosureStatus",
    "attach_closure",
    "verify_closure",
    "closure_payload",
    "BUNDLE_FORMAT",
    "BUNDLE_VERSION",
    "BundleError",
    "bundle_hash",
    "bundle_to_bytes",
    "create_bundle",
    "load_bundle",
    "render_verify_verdict_line",
    "verify_bundle",
]
