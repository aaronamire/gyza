"""
Result delivery — the executor → submitter push channel.

Phase-3 problem this solves: when node A posts a work item and node
B (somewhere else on the internet) claims + executes it, B's signed
ICP envelope and the result artifact live in B's blackboard. A only
learns the *hashes* via gossipsub completion deltas. So A can see
"work item done, envelope hash = X" but cannot:

  - verify the envelope's Ed25519 signature (doesn't have the bytes)
  - read the result (doesn't have the artifact)
  - resolve envelope_hash for bilateral settlement validation

And gossipsub completion deltas are themselves unreliable for a
short-lived participant like ``gyza submit`` on a sparse mesh.

The fix: B pushes the full result directly to A over the daemon's
point-to-point libp2p MessageService — the same proven channel the
settlement service already uses to send earner-signed ledger
entries (executor → submitter). One message carries everything A
needs to verify and display the result, with no gossip dependency.

Wire format — a single ``RESULT_DELIVERY_TYPE`` MessageService
frame whose payload is UTF-8 JSON:

    {
      "v": 1,
      "work_item_id": "<uuid>",
      "envelope": { ...full ICPEnvelope incl. signature... },
      "artifact_b64": "<base64 of the result artifact bytes>"
    }

The envelope is the complete dataclass (``dataclasses.asdict``),
signature field included — A needs the signature to verify. The
artifact bytes are the canonical-JSON result payload B stored;
A checks ``blake3(artifact) == envelope.output_hash`` for
integrity, then reads the ``text`` field for display.
"""
from __future__ import annotations

import base64
import dataclasses
import json

from gyza.icp import ICPEnvelope

RESULT_DELIVERY_TYPE = "work.result.delivery.v1"

_WIRE_VERSION = 1


def encode_delivery(
    *,
    work_item_id: str,
    envelope: ICPEnvelope,
    artifact_bytes: bytes,
    manifest_bytes: bytes | None = None,
) -> bytes:
    """
    Serialize a result-delivery frame. ``envelope`` is the full
    signed ICPEnvelope; ``artifact_bytes`` is the raw result
    artifact (canonical-JSON bytes as stored on the executor's
    blackboard). Returns UTF-8 JSON bytes ready for
    ``NetdClient.send_message``.

    ``manifest_bytes`` (optional) is the canonical-JSON
    serialization of the agent's capability manifest — the exact
    bytes whose blake3 equals ``envelope.capability_manifest_hash``.
    Delivering them lets the submitter close the trustless gap on
    the brick-3 bounds-proof: re-hash to confirm manifest identity,
    re-run ``enforcement_satisfies_manifest`` against the artifact's
    ``__enforcement__``, and stamp "✓ INDEPENDENTLY VERIFIED"
    instead of trusting the runner did the check. Wire change is
    additive — old decoders simply ignore the field.
    """
    obj: dict = {
        "v": _WIRE_VERSION,
        "work_item_id": work_item_id,
        "envelope": dataclasses.asdict(envelope),
        "artifact_b64": base64.b64encode(artifact_bytes).decode("ascii"),
    }
    if manifest_bytes is not None:
        obj["manifest_b64"] = base64.b64encode(manifest_bytes).decode("ascii")
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


@dataclasses.dataclass
class ResultDelivery:
    """Decoded result-delivery frame."""
    work_item_id: str
    envelope: ICPEnvelope
    artifact_bytes: bytes
    manifest_bytes: bytes | None = None


def decode_delivery(payload: bytes) -> ResultDelivery:
    """
    Parse a result-delivery frame. Raises ValueError on a malformed
    or wrong-version payload — the caller (a message-subscription
    loop) should catch and skip rather than crash.
    """
    try:
        d = json.loads(payload.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"result-delivery payload is not UTF-8 JSON: {e}") from e

    if not isinstance(d, dict):
        raise ValueError("result-delivery payload is not a JSON object")
    if d.get("v") != _WIRE_VERSION:
        raise ValueError(
            f"result-delivery wire version {d.get('v')!r} unsupported "
            f"(this build speaks v{_WIRE_VERSION})"
        )
    wid = d.get("work_item_id")
    env_dict = d.get("envelope")
    art_b64 = d.get("artifact_b64")
    if not isinstance(wid, str) or not isinstance(env_dict, dict) \
       or not isinstance(art_b64, str):
        raise ValueError("result-delivery frame missing required fields")

    try:
        envelope = ICPEnvelope(**env_dict)
    except TypeError as e:
        raise ValueError(f"result-delivery envelope dict malformed: {e}") from e

    try:
        artifact_bytes = base64.b64decode(art_b64, validate=True)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"result-delivery artifact_b64 not valid base64: {e}") from e

    manifest_bytes: bytes | None = None
    man_b64 = d.get("manifest_b64")
    if man_b64 is not None:
        if not isinstance(man_b64, str):
            raise ValueError("result-delivery manifest_b64 is not a string")
        try:
            manifest_bytes = base64.b64decode(man_b64, validate=True)
        except Exception as e:  # noqa: BLE001
            raise ValueError(
                f"result-delivery manifest_b64 not valid base64: {e}",
            ) from e

    return ResultDelivery(
        work_item_id=wid,
        envelope=envelope,
        artifact_bytes=artifact_bytes,
        manifest_bytes=manifest_bytes,
    )
