"""
The local adaptor — wrap any heterogeneous agent behind a bounded,
attributable, DDIL-survivable coordination endpoint.

WHAT THIS IS
------------
A decentralized collective of AI agents needs each member to be three
things at once, without a central orchestrator enforcing them:

  * **attributable** — every action it takes is signed and traceable to
    an identity (trust lineage);
  * **bounded** — it cannot exceed the authority it was granted, and
    that fact is provable after the fact (authority boundaries);
  * **coordinable under loss** — its actions propagate to whoever it can
    still reach and reconcile when a partition heals (recoverability).

``AgentAdaptor`` is the thin, vendor-agnostic wrapper that gives an
*arbitrary* agent all three. The agent itself is just a callable
``(prompt, context) -> str`` — an LLM, a VLM behind an API, a classical
policy, or a plain Python function. The adaptor does not care what is
inside; it attaches a signed identity + capability manifest, enforces
the manifest as a hard bound (refusing to sign an action whose
enforcement record exceeds it), emits one ``ICPEnvelope`` per action,
and records that envelope into whatever coordination sink it is given.

Heterogeneity is therefore free: two adaptors wrapping two completely
different agents produce byte-comparable, mutually verifiable envelopes
and interoperate in the same collective. That uniform envelope — not
the agent behind it — is what makes emergence *controlled* rather than
merely hoped-for: you can audit what the collective did and prove no
member overstepped, whoever built the members.

LAYERING
--------
This module is deliberately transport-agnostic. It depends only on a
small ``EnvelopeSink`` protocol (anything with ``add(envelope)``), so
it neither imports nor assumes the CRDT/gossip data plane — that plane
(or a production libp2p transport, or nothing) is injected by the
caller. Verification stays orthogonal: the adaptor produces envelopes;
``gyza.icp.verify_chain`` / ``verify_dag`` and
``gyza.economy.delegation.verify_delegation`` judge them.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional, Protocol, runtime_checkable

import blake3

from gyza.icp import ICPEnvelope, compute_envelope_hash
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.sandbox.config import enforcement_satisfies_manifest

# The agent's "brain": anything that turns a prompt + context into text.
# Vendor-agnostic by construction — an LLM/VLM adapter, a classical
# controller, or a pure function all satisfy this.
Agent = Callable[[str, Mapping[str, Any]], str]


@runtime_checkable
class EnvelopeSink(Protocol):
    """
    A place produced envelopes go. ``gyza.demo.coordination_plane
    .CoordinationState`` satisfies this (its ``add`` is the CRDT
    insert), and so would any future transport. Kept to one method so
    the adaptor stays free of the data plane's concrete type.
    """

    def add(self, envelope: ICPEnvelope) -> str:  # pragma: no cover - protocol
        ...


class BoundsViolation(RuntimeError):
    """
    Raised when an action's host-stamped enforcement record is wider
    than the agent's capability manifest. The adaptor refuses to sign,
    so a valid signed envelope can never attest out-of-bounds work —
    the refuse-to-sign gate, at the adaptor layer.
    """


def _fold_artifact_bytes(text: str, enforcement: Optional[dict]) -> bytes:
    """
    Canonical artifact bytes the envelope's ``output_hash`` commits to.

    Mirrors ``gyza/runner.py`` (_execute, artifact construction): the
    enforcement record is folded INTO the hashed artifact so the
    signature commits to the bounds the work ran under — the bounds-proof
    lives inside the signed bytes, not in trust of the runner. Cited so
    it cannot drift from the runner silently.
    """
    obj: dict = {"text": text}
    if enforcement is not None:
        obj["__enforcement__"] = enforcement
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


class AgentAdaptor:
    """
    Wrap one heterogeneous agent as a bounded, attributable collective
    member.

    Construct directly from a signed ``AgentIdentity`` (see
    ``from_compositor`` for the common case), then call ``act`` per
    action. Every ``act`` yields a signed ``ICPEnvelope``; when an
    enforcement record is supplied it is checked against the manifest
    and refused if wider (``BoundsViolation``); when a sink is attached
    the envelope is recorded there for propagation.
    """

    def __init__(
        self,
        identity: AgentIdentity,
        agent_fn: Agent,
        *,
        model_identifier: str = "unknown",
        inference_backend: str = "adaptor",
        agent_type: str = "unknown",
        sink: Optional[EnvelopeSink] = None,
    ) -> None:
        self._identity = identity
        self._agent_fn = agent_fn
        self._model = model_identifier
        self._backend = inference_backend
        # The manifest binds an agent_id + capabilities but not a
        # human-readable type; carry it here for traces/audit labels.
        self._agent_type = agent_type
        self._sink = sink
        self._signer = identity.get_icp_signer()
        # output_hash -> the canonical artifact bytes it commits to, so a
        # caller can feed the unified audit (which resolves by output_hash).
        self._artifacts: dict[str, bytes] = {}

    # -- identity surface ----------------------------------------------------

    @property
    def pubkey_hex(self) -> str:
        return self._identity.pubkey_hex

    @property
    def manifest(self) -> dict:
        return self._identity.manifest

    @property
    def manifest_hash(self) -> str:
        return self._identity.manifest_hash

    @property
    def agent_type(self) -> str:
        return self._agent_type

    # -- the one operation ---------------------------------------------------

    def act(
        self,
        *,
        intent_id: str,
        action_id: str,
        prompt: str,
        context: Optional[Mapping[str, Any]] = None,
        parent: Optional[ICPEnvelope] = None,
        inputs: Optional[list[str]] = None,
        enforcement: Optional[dict] = None,
        duration_ms: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> ICPEnvelope:
        """
        Run the wrapped agent for one action and emit a signed envelope.

        Order matters: the agent runs, then — if an ``enforcement``
        record is present — the manifest bound is checked and signing is
        refused if the record is wider (``BoundsViolation``). Only then
        is the artifact folded, hashed, signed, and (if a sink is set)
        recorded. So no over-bound action is ever recorded or signed.

        ``inputs`` overrides the default single data edge (the causal
        parent's envelope hash) to express fan-in — a synthesis action
        consuming several producers' ``output_hash`` values.
        """
        text = self._agent_fn(prompt, dict(context or {}))

        if enforcement is not None:
            ok, why = enforcement_satisfies_manifest(enforcement, self._identity.manifest)
            if not ok:
                raise BoundsViolation(
                    f"{self.agent_type}/{action_id}: enforcement exceeds manifest — {why}"
                )

        artifact = _fold_artifact_bytes(text, enforcement)
        output_hash = blake3.blake3(artifact).hexdigest()

        if inputs is not None:
            input_hashes = list(inputs)
        elif parent is None:
            input_hashes = ["00" * 32]
        else:
            input_hashes = [compute_envelope_hash(parent)]

        envelope = self._signer.sign_action(
            intent_id=intent_id,
            action_id=action_id,
            input_hashes=input_hashes,
            output_hash=output_hash,
            parent_envelope=parent,
            inference_backend=self._backend,
            model_identifier=self._model,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

        self._artifacts[output_hash] = artifact
        if self._sink is not None:
            self._sink.add(envelope)
        return envelope

    def artifact(self, output_hash: str) -> Optional[bytes]:
        """The canonical artifact bytes for an output_hash this adaptor produced."""
        return self._artifacts.get(output_hash)

    # -- convenience construction -------------------------------------------

    @classmethod
    def from_compositor(
        cls,
        compositor: LocalCompositor,
        agent_fn: Agent,
        *,
        agent_type: str,
        memory_limit_mb: int,
        model_path: str = "mock",
        model_identifier: str = "unknown",
        inference_backend: str = "adaptor",
        fs_read_paths: Optional[list[str]] = None,
        fs_write_paths: Optional[list[str]] = None,
        allowed_hosts: Optional[list[str]] = None,
        attestation_tier: int = 1,
        sink: Optional[EnvelopeSink] = None,
    ) -> "AgentAdaptor":
        """
        Issue a fresh bounded identity for ``agent_fn`` under
        ``compositor`` and wrap it. The capability manifest is the
        authority envelope every ``act`` is held to.
        """
        seed, manifest = compositor.issue_agent(
            agent_type=agent_type,
            model_path=model_path,
            fs_read_paths=list(fs_read_paths or []),
            fs_write_paths=list(fs_write_paths or []),
            allowed_hosts=list(allowed_hosts or []),
            memory_limit_mb=memory_limit_mb,
            attestation_tier=attestation_tier,
        )
        identity = AgentIdentity(seed, manifest)
        return cls(
            identity,
            agent_fn,
            model_identifier=model_identifier,
            inference_backend=inference_backend,
            agent_type=agent_type,
            sink=sink,
        )


__all__ = ["Agent", "EnvelopeSink", "BoundsViolation", "AgentAdaptor"]
