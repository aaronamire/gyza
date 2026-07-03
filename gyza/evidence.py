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
    return json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")


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
    if set(obj) != _BUNDLE_KEYS:
        raise BundleError(
            f"unexpected bundle shape: keys {sorted(set(obj) ^ _BUNDLE_KEYS)} "
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

    return audit_provenance(
        envelopes,
        resolve_artifact=artifacts.get,
        resolve_manifest=lambda h: manifests.get(h)
        if isinstance(manifests.get(h), dict) else None,
        require_closed=True,
        require_all_artifacts=True,
    )


def render_verify_verdict_line(report: AuditReport) -> str:
    """One-line verdict for CLI output; the full forensic report is
    ``gyza.audit.render_audit_report``."""
    word = "VALID" if report.valid else "INVALID"
    return f"verdict: {word}  ({report.summary})"


__all__ = [
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
