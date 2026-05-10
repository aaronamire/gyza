"""
Phase 3 priority #21 — cross-network attestation protocol.

This module provides the **orchestration layer** for proof-of-capability
attestation: a Validator role, an Applicant role, and a 2-of-N quorum
orchestrator that turns a successful eval against ≥k validators into a
publishable ``AttestationCert``. The eval suite + verifier (the
algorithmic core) live in ``gyza.capability_eval``; this module is the
protocol on top.

What's in scope here
--------------------

The dataclasses, the role implementations, and the orchestrator all
operate **in-process**: a Validator's ``issue_challenge`` is a plain
method call; a Response is a plain dataclass. The roles are deliberately
written to be transport-agnostic — every wire-bound field is a hex
string, an int, or a list of those, so the future libp2p stream
protocol (``/gyza/capability-challenge/1.0.0``) is a mechanical
JSON-frame-and-ship layer on top of these dataclasses.

What's NOT in scope here
------------------------

  * libp2p stream framing — separate module in a future session.
  * DHT-driven validator selection — orchestrator takes a caller-supplied
    list of Validators. In production the ``CapabilityClient`` will pick
    Tier-3 nodes via ``find_agents(min_tier=3)``.
  * DHT publication of the final cert.
  * Recursive validator-tier verification: a consumer who fetches a
    cert from the DHT must independently verify each validator-pubkey
    is itself Tier-3 attested. This module produces the cert; trusting
    its validators is the consumer's policy.

Design choices
--------------

**Validator-chosen nonce.**
Each validator picks its own ``nonce`` and includes it in the
``Challenge``. The applicant runs the eval suite once per validator,
binding each response to a different nonce. This blocks replay across
validators — a malicious applicant who got one good response can't
re-use it against a second validator.

**Applicant-proposed cert payload, validator-constrained.**
All k validators must sign **the same canonical bytes**, otherwise
the quorum can't form. The applicant proposes a single
``AttestationCertPayload`` (timestamps, identity, eval version) and
sends it inside every ChallengeResponse. Each validator independently
verifies (a) the eval results, (b) the payload's timestamps are sane
(within ±1h of the validator's clock), (c) the payload's
``applicant_compositor_pubkey`` matches the response's claim. If all
pass, the validator signs the canonical bytes of that exact payload
and returns the cosignature.

**Cosig aggregation.**
The orchestrator collects cosigs from k of n validators (default
k=2, n=3). Validators that reject for any reason return a structured
``ChallengeOutcome`` with the reason; valid rejections AND failed
network attempts both count as "unable to obtain cosig" and the
orchestrator falls back to the next validator until k is met or n is
exhausted.

Threat model defended
---------------------

  * Replay across validators       — validator-chosen nonce
  * Eval result tampering          — eval verifier (gyza.capability_eval)
  * Cosignature transplant         — each cosig binds to validator_pubkey
                                     and is over canonical(payload)
  * Stale cert acceptance          — payload carries expires_at_ns;
                                     verify_attestation_cert checks
  * 1 malicious validator          — 2-of-3 quorum tolerates

NOT defended
------------

  * Sybil applicant + Sybil validators — needs DHT-driven random
    selection of Tier-3 validators (orchestrator-layer concern,
    out of scope here).
  * >k/n malicious Tier-3 validators — fundamental quorum limit.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from gyza.capability_eval import (
    EVAL_TASKS,
    EVAL_VERSION,
    EvalResult,
    EvalTask,
    run_eval_locally,
    verify_eval_results,
)
from gyza.icp import ICPEnvelope


LOG = logging.getLogger("gyza.capability_protocol")


PROTOCOL_VERSION = "v1"
CERT_SCHEMA = "gyza.attestation.tier3/v1"

# Validators reject challenges whose ``issued_at_ns`` is more than this
# far in the past or future from the validator's local clock. Bounds
# clock skew between honest peers; primary defense is the validator
# nonce, this just keeps cert timestamps reasonable.
MAX_CLOCK_SKEW_NS = 60 * 60 * 1_000_000_000  # 1 hour

# Default cosig quorum + cert lifetime.
DEFAULT_QUORUM_K = 2
DEFAULT_QUORUM_N = 3
DEFAULT_CERT_LIFETIME_NS = 30 * 24 * 60 * 60 * 1_000_000_000  # 30 days


# ---------------------------------------------------------------------------
# Wire types — all dataclasses are JSON-serializable when ``asdict`` is
# applied; ICPEnvelope is itself a dataclass with hex/int/str fields.
# ---------------------------------------------------------------------------

@dataclass
class Challenge:
    """
    Validator → Applicant. Identifies the validator, locks the eval
    version + task subset, and binds a fresh nonce. The validator's
    signature covers everything except the signature field itself.

    Why include validator_pubkey on the wire when the recipient knows
    who they're talking to: this dataclass will be forwarded across
    a libp2p stream where peer_id↔compositor binding requires an
    extra DHT lookup. Embedding the pubkey lets the applicant verify
    locally without that lookup.
    """
    validator_pubkey: str
    challenge_id: str
    eval_version: str
    task_ids: list[str]
    nonce: str
    issued_at_ns: int
    expires_at_ns: int
    signature: str = ""


@dataclass
class AttestationCertPayload:
    """
    The signed-over portion of the attestation cert. Each validator
    independently signs canonical(payload) — the bytes MUST be
    identical across validators, or the quorum cannot form.
    """
    schema: str
    applicant_compositor_pubkey: str
    eval_version: str
    issued_at_ns: int
    expires_at_ns: int


@dataclass
class ChallengeResponse:
    """
    Applicant → Validator. Contains the proposed cert payload (that
    every validator will sign over) and the eval results (that the
    validator will verify). The applicant signs the bundle so a
    middlebox can't substitute eval results from a different applicant.

    Two pubkeys, two purposes:

      * ``applicant_compositor_pubkey``: the durable identity that
        gets attested. Signs ``applicant_signature``. This is what
        ends up in ``cert_payload`` and what the cert binds.
      * ``applicant_agent_pubkey``: the ephemeral runner identity
        that signed the ICP envelopes inside ``eval_results``. The
        validator's eval verifier checks envelopes against THIS key.

    Trust chain "agent issued by compositor": established via the
    capability manifest (which carries ``compositor_pubkey`` and is
    signed by it). Forwarding the manifest in the response is a
    follow-up; for Phase 3 we accept that the validator confirms the
    agent passed the eval, and the cert binds at the compositor.
    """
    challenge_id: str
    applicant_compositor_pubkey: str
    applicant_agent_pubkey: str
    cert_payload: AttestationCertPayload
    eval_results: dict[str, EvalResult]
    nonce_echo: str
    applicant_signature: str = ""


@dataclass
class ValidatorCosig:
    """
    One validator's cosignature on the cert payload. Each cosig is
    bound to ``validator_pubkey`` so a malicious party can't transplant
    a signature from one validator's identity to another.
    """
    validator_pubkey: str
    signature: str
    cosigned_at_ns: int


@dataclass
class ChallengeOutcome:
    """
    Validator → Applicant. ``accepted=True`` carries a cosig the
    applicant aggregates into the cert; ``accepted=False`` carries a
    short reason string for diagnostics.
    """
    challenge_id: str
    accepted: bool
    cosig: ValidatorCosig | None = None
    reason: str = ""


@dataclass
class AttestationCert:
    """
    Final cert. The payload is the canonical signed-over bytes; the
    cosigs are what makes this Tier-3 (≥k of n validators agreed).

    The cert is JSON-serializable directly; future DHT publication
    just dumps and stores under a key derived from
    ``payload.applicant_compositor_pubkey``.
    """
    payload: AttestationCertPayload
    validator_cosigs: list[ValidatorCosig] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical-bytes helpers — every signature in this protocol is over
# JSON canonical bytes (sort_keys=True, no whitespace) of a specific
# structured field. Keeping the canonicalization centralized here
# guarantees signer and verifier produce identical bytes.
# ---------------------------------------------------------------------------

def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _challenge_canonical_bytes(c: Challenge) -> bytes:
    """Canonical bytes for the validator's signature on Challenge."""
    d = asdict(c)
    d.pop("signature", None)
    return _canonical(d)


def _response_canonical_bytes(r: ChallengeResponse) -> bytes:
    """
    Canonical bytes for the applicant's signature on ChallengeResponse.
    Excludes ``applicant_signature``. Eval results are already serializable
    via dataclass introspection — ICPEnvelope's hex fields canonicalize
    cleanly.
    """
    d = asdict(r)
    d.pop("applicant_signature", None)
    return _canonical(d)


def _payload_canonical_bytes(p: AttestationCertPayload) -> bytes:
    """Canonical bytes that EVERY validator's cosig is over. Identical
    bytes across all validators is the load-bearing invariant."""
    return _canonical(asdict(p))


# ---------------------------------------------------------------------------
# Plain Ed25519 sign / verify helpers (no envelope-shaped wrapping).
# ---------------------------------------------------------------------------

def make_seed_signer(seed: bytes) -> Callable[[bytes], str]:
    """
    Build a sign function from a 32-byte Ed25519 seed. Useful for
    tests and for integration with synthetic validator identities
    that don't go through ``LocalCompositor`` (which HKDF-derives
    its compositor signing key from a master seed).

    Production callers should pass ``LocalCompositor.sign`` directly
    — it wraps the correctly-derived compositor signing key.
    """
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    sk = Ed25519PrivateKey.from_private_bytes(seed)

    def _sign(payload: bytes) -> str:
        return sk.sign(payload).hex()
    return _sign


def _verify_with(pubkey_hex: str, payload: bytes, sig_hex: str) -> bool:
    try:
        pk_bytes = bytes.fromhex(pubkey_hex)
    except ValueError:
        return False
    if len(pk_bytes) != 32:
        return False
    try:
        sig = bytes.fromhex(sig_hex)
    except ValueError:
        return False
    try:
        pk = Ed25519PublicKey.from_public_bytes(pk_bytes)
        pk.verify(sig, payload)
        return True
    except (InvalidSignature, ValueError):
        return False


# ---------------------------------------------------------------------------
# Validator role
# ---------------------------------------------------------------------------

class Validator:
    """
    A node willing to evaluate applicants and cosign certs.

    The validator owns a compositor private key (for issuing the
    challenge signature and the cosig) and a copy of the canonical
    eval suite (must match the applicant's). Validators are themselves
    expected to be Tier-3 attested; that property is enforced one layer
    up at validator selection (not here).
    """

    def __init__(
        self,
        *,
        sign_fn: Callable[[bytes], str],
        compositor_pubkey: str,
        eval_tasks: list[EvalTask] = EVAL_TASKS,
        clock_skew_ns: int = MAX_CLOCK_SKEW_NS,
    ):
        """
        ``sign_fn`` MUST sign with the private key whose public bytes
        equal ``compositor_pubkey``. Production callers pass
        ``LocalCompositor.sign``; tests can use ``make_seed_signer``.
        Mismatch is caught at first verify (signatures fail) — but
        we don't pre-flight here because verifying the binding
        requires signing+verifying a probe payload, which is a
        non-zero cost on every Validator construction.
        """
        self._sign = sign_fn
        self._pubkey = compositor_pubkey
        self._tasks = list(eval_tasks)
        self._task_ids = [t.task_id for t in eval_tasks]
        self._tasks_by_id = {t.task_id: t for t in eval_tasks}
        self._clock_skew_ns = clock_skew_ns

    @property
    def pubkey(self) -> str:
        return self._pubkey

    def issue_challenge(
        self,
        applicant_compositor_pubkey: str,  # noqa: ARG002 — accepted for future use
        *,
        validity_ns: int = 5 * 60 * 1_000_000_000,  # 5 min
    ) -> Challenge:
        """
        Construct a Challenge with a fresh nonce and the validator's
        signature. ``validity_ns`` bounds how long the applicant has
        to respond before the challenge expires (reject window).

        Currently the challenge enumerates the FULL eval suite. A
        future version may pick a random subset; the dataclass field
        is plural-named to accommodate that without an API change.

        ``applicant_compositor_pubkey`` is currently unused but accepted
        on the API so a future per-applicant nonce derivation
        (HMAC(applicant_pubkey, validator_secret)) doesn't break callers.
        """
        now = time.time_ns()
        c = Challenge(
            validator_pubkey=self._pubkey,
            challenge_id=str(uuid.uuid4()),
            eval_version=EVAL_VERSION,
            task_ids=list(self._task_ids),
            nonce=uuid.uuid4().hex,
            issued_at_ns=now,
            expires_at_ns=now + validity_ns,
        )
        c.signature = self._sign(_challenge_canonical_bytes(c))
        return c

    def verify_response(
        self,
        challenge: Challenge,
        response: ChallengeResponse,
        *,
        workdir: Path,
    ) -> ChallengeOutcome:
        """
        Verify a ChallengeResponse against a Challenge we previously
        issued. On accept: returns a cosig the applicant aggregates
        into the cert. On reject: structured reason for diagnostics.

        ``workdir`` is the validator's local copy of the per-task
        fixtures — the validator must independently re-create the
        fixtures (using the same ``EvalTask.setup`` calls) to compute
        the expected outputs. In production each validator does this
        in its own tmpdir; we expose it as a parameter so tests can
        share a directory across validators (no security difference —
        the eval setup is deterministic given the nonce).
        """
        cid = challenge.challenge_id
        # Quick wins: response identifies the right challenge.
        if response.challenge_id != cid:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="response.challenge_id mismatch",
            )
        if response.nonce_echo != challenge.nonce:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="nonce_echo mismatch",
            )

        # Applicant identity binding: response.applicant_compositor_pubkey
        # must equal the cert payload's applicant claim, AND the
        # applicant_signature must verify against that pubkey.
        if response.applicant_compositor_pubkey != response.cert_payload.applicant_compositor_pubkey:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="response.applicant_compositor_pubkey != cert_payload.applicant_compositor_pubkey",
            )
        if not _verify_with(
            response.applicant_compositor_pubkey,
            _response_canonical_bytes(response),
            response.applicant_signature,
        ):
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="applicant signature invalid",
            )

        # Cert payload sanity.
        p = response.cert_payload
        if p.schema != CERT_SCHEMA:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason=f"unsupported cert schema {p.schema!r}",
            )
        if p.eval_version != EVAL_VERSION:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason=f"eval_version {p.eval_version!r} != {EVAL_VERSION}",
            )
        now = time.time_ns()
        if abs(p.issued_at_ns - now) > self._clock_skew_ns:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="cert.issued_at_ns outside clock-skew window",
            )
        if p.expires_at_ns <= p.issued_at_ns:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="cert.expires_at_ns <= issued_at_ns",
            )
        # Cap the lifetime; a malicious applicant proposing a 100-year
        # cert shouldn't get our cosig on it.
        if p.expires_at_ns - p.issued_at_ns > 90 * 24 * 60 * 60 * 1_000_000_000:
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="cert lifetime exceeds 90 days",
            )

        # Independent eval verification — same code the applicant ran
        # to self-check, but the validator runs it on the responses
        # AS RECEIVED. The eval verifier checks envelope.agent_pubkey
        # matches what we pass; envelopes are signed by the AGENT key,
        # so we pass ``applicant_agent_pubkey``. The cert itself binds
        # at the COMPOSITOR level (in ``cert_payload``). The bridge
        # between the two is the capability manifest (signed by the
        # compositor, carries the agent_id) — forwarding the manifest
        # in the response and verifying that link is a follow-up.
        report = verify_eval_results(
            results=response.eval_results,
            applicant_pubkey=response.applicant_agent_pubkey,
            nonce=challenge.nonce,
            workdir=workdir,
            tasks=self._tasks,
        )
        if not report.passed:
            failed = [
                f"{tid}={msg}" for tid, msg in report.per_task.items()
                if msg != "ok"
            ]
            return ChallengeOutcome(
                challenge_id=cid, accepted=False,
                reason="eval failed: " + "; ".join(failed[:3]),
            )

        # All checks passed — sign the cert payload.
        cosig_sig = self._sign(_payload_canonical_bytes(p))
        return ChallengeOutcome(
            challenge_id=cid, accepted=True,
            cosig=ValidatorCosig(
                validator_pubkey=self._pubkey,
                signature=cosig_sig,
                cosigned_at_ns=now,
            ),
        )


# ---------------------------------------------------------------------------
# Applicant role
# ---------------------------------------------------------------------------

class Applicant:
    """
    A node seeking attestation. Holds a compositor identity and an
    AgentRunner (its primary work-claiming runner OR a dedicated
    attestation runner). The applicant runs the eval suite once per
    validator (different nonce each time) and proposes the cert
    payload that validators will independently sign.
    """

    def __init__(
        self,
        *,
        sign_fn: Callable[[bytes], str],
        compositor_pubkey: str,
        runner: Any,
        blackboard: Any,
        agent_pubkey: str,
        cert_lifetime_ns: int = DEFAULT_CERT_LIFETIME_NS,
    ):
        """
        ``sign_fn`` signs at the COMPOSITOR level. Production callers
        pass ``LocalCompositor.sign``; tests use ``make_seed_signer``.
        """
        self._sign = sign_fn
        self._pubkey = compositor_pubkey
        self._runner = runner
        self._bb = blackboard
        self._agent_pubkey = agent_pubkey
        self._cert_lifetime_ns = cert_lifetime_ns

    @property
    def compositor_pubkey(self) -> str:
        return self._pubkey

    def respond_to_challenge(
        self,
        challenge: Challenge,
        *,
        workdir: Path,
        output_recorder: dict[str, dict],
        proposed_payload: AttestationCertPayload | None = None,
        eval_overall_timeout_s: float = 60.0,
    ) -> ChallengeResponse:
        """
        Run the eval suite under the validator's nonce, build the
        proposed cert payload, sign the bundle.

        ``proposed_payload`` is supplied by the orchestrator so all
        validators receive the SAME canonical payload bytes. If None,
        the applicant constructs a fresh payload (single-validator
        mode, used by tests).
        """
        if challenge.eval_version != EVAL_VERSION:
            raise ValueError(
                f"validator demands eval_version={challenge.eval_version!r}; "
                f"applicant supports {EVAL_VERSION!r} only",
            )
        if not _verify_with(
            challenge.validator_pubkey,
            _challenge_canonical_bytes(challenge),
            challenge.signature,
        ):
            raise ValueError("challenge signature invalid")
        now = time.time_ns()
        if challenge.expires_at_ns < now:
            raise ValueError("challenge already expired")

        _, results = run_eval_locally(
            runner=self._runner,
            blackboard=self._bb,
            applicant_pubkey=self._agent_pubkey,
            workdir=workdir,
            nonce=challenge.nonce,
            output_recorder=output_recorder,
            tasks=[t for t in EVAL_TASKS if t.task_id in challenge.task_ids],
            overall_timeout_s=eval_overall_timeout_s,
        )

        if proposed_payload is None:
            proposed_payload = AttestationCertPayload(
                schema=CERT_SCHEMA,
                applicant_compositor_pubkey=self._pubkey,
                eval_version=EVAL_VERSION,
                issued_at_ns=now,
                expires_at_ns=now + self._cert_lifetime_ns,
            )

        response = ChallengeResponse(
            challenge_id=challenge.challenge_id,
            applicant_compositor_pubkey=self._pubkey,
            applicant_agent_pubkey=self._agent_pubkey,
            cert_payload=proposed_payload,
            eval_results=results,
            nonce_echo=challenge.nonce,
        )
        response.applicant_signature = self._sign(
            _response_canonical_bytes(response),
        )
        return response


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class AttestationOutcome:
    """
    What ``run_attestation`` returns. ``cert`` is None on quorum
    failure; ``per_validator`` carries each validator's outcome for
    diagnostics.
    """
    cert: AttestationCert | None
    per_validator: dict[str, ChallengeOutcome] = field(default_factory=dict)
    quorum_met: bool = False


def run_attestation(
    *,
    applicant: Applicant,
    validators: list[Validator],
    workdir: Path,
    output_recorder: dict[str, dict],
    quorum_k: int = DEFAULT_QUORUM_K,
    eval_overall_timeout_s: float = 60.0,
) -> AttestationOutcome:
    """
    Drive a full Tier-3 attestation against ``validators`` (n in size).
    Aggregates k cosignatures into a final ``AttestationCert``.

    The applicant proposes ONE cert payload (timestamps, identity)
    that every validator will sign over. Each validator independently
    issues a challenge (with its own nonce); the applicant runs the
    eval suite once per challenge.

    Why not parallelize the per-validator runs: the applicant has a
    single AgentRunner; multiple concurrent ``run_eval_locally`` calls
    would cross-pollute the same blackboard's work_item table. Future
    optimization: per-validator dedicated agents under one compositor.

    Returns an ``AttestationOutcome``. ``cert is None`` and
    ``quorum_met=False`` on insufficient cosigs.
    """
    if quorum_k < 1:
        raise ValueError("quorum_k must be >= 1")
    if quorum_k > len(validators):
        raise ValueError(
            f"quorum_k={quorum_k} exceeds n={len(validators)} validators",
        )

    now = time.time_ns()
    proposed_payload = AttestationCertPayload(
        schema=CERT_SCHEMA,
        applicant_compositor_pubkey=applicant.compositor_pubkey,
        eval_version=EVAL_VERSION,
        issued_at_ns=now,
        expires_at_ns=now + DEFAULT_CERT_LIFETIME_NS,
    )

    cosigs: list[ValidatorCosig] = []
    per_validator: dict[str, ChallengeOutcome] = {}
    for v in validators:
        try:
            challenge = v.issue_challenge(applicant.compositor_pubkey)
            v_workdir = workdir / f"v_{v.pubkey[:16]}"
            v_workdir.mkdir(parents=True, exist_ok=True)
            response = applicant.respond_to_challenge(
                challenge,
                workdir=v_workdir,
                output_recorder=output_recorder,
                proposed_payload=proposed_payload,
                eval_overall_timeout_s=eval_overall_timeout_s,
            )
            outcome = v.verify_response(
                challenge, response, workdir=v_workdir,
            )
        except Exception as e:  # noqa: BLE001
            outcome = ChallengeOutcome(
                challenge_id="(threw)",
                accepted=False,
                reason=f"applicant/validator threw: {type(e).__name__}: {e}",
            )
        per_validator[v.pubkey] = outcome
        if outcome.accepted and outcome.cosig is not None:
            cosigs.append(outcome.cosig)
        # Early exit: if we have quorum_k, no need to bother the rest.
        if len(cosigs) >= quorum_k:
            break

    if len(cosigs) >= quorum_k:
        return AttestationOutcome(
            cert=AttestationCert(
                payload=proposed_payload,
                validator_cosigs=cosigs,
            ),
            per_validator=per_validator,
            quorum_met=True,
        )
    return AttestationOutcome(
        cert=None,
        per_validator=per_validator,
        quorum_met=False,
    )


# ---------------------------------------------------------------------------
# Consumer-side cert verification — pure function
# ---------------------------------------------------------------------------

def verify_attestation_cert(
    cert: AttestationCert,
    *,
    expected_applicant_pubkey: str | None = None,
    min_quorum: int = DEFAULT_QUORUM_K,
    max_age_ns: int | None = None,
    now_ns: int | None = None,
) -> tuple[bool, str]:
    """
    Independent consumer-side check on an aggregated AttestationCert.

    Returns ``(passed, reason)``. The consumer is expected to ALSO
    verify each ``validator_cosig.validator_pubkey`` is itself
    Tier-3-attested via DHT lookup — that's a separate concern outside
    this pure function (it requires network IO). What we check here:

      1. Schema string matches ``CERT_SCHEMA``.
      2. ``expected_applicant_pubkey``, if given, matches the payload.
      3. Each cosig's signature verifies under its claimed validator_pubkey.
      4. No duplicate validators in the cosig list (a single validator
         can't double-sign for quorum).
      5. ≥ ``min_quorum`` valid cosigs.
      6. Cert hasn't expired (vs ``now_ns``).
      7. ``max_age_ns``, if given, bounds how old the cert can be.

    A future "Tier-3 lookup" verifier wraps this with the DHT IO.
    """
    p = cert.payload
    if p.schema != CERT_SCHEMA:
        return False, f"unsupported cert schema {p.schema!r}"
    if expected_applicant_pubkey is not None and (
        p.applicant_compositor_pubkey != expected_applicant_pubkey
    ):
        return False, (
            f"cert applicant {p.applicant_compositor_pubkey[:16]}... "
            f"!= expected {expected_applicant_pubkey[:16]}..."
        )

    now = now_ns if now_ns is not None else time.time_ns()
    if p.expires_at_ns < now:
        return False, "cert expired"
    if max_age_ns is not None and (now - p.issued_at_ns) > max_age_ns:
        return False, "cert older than max_age_ns"

    payload_bytes = _payload_canonical_bytes(p)
    seen_validators: set[str] = set()
    valid_count = 0
    for cosig in cert.validator_cosigs:
        if cosig.validator_pubkey in seen_validators:
            # Don't count a double-cosigning validator twice.
            continue
        if not _verify_with(
            cosig.validator_pubkey, payload_bytes, cosig.signature,
        ):
            continue
        seen_validators.add(cosig.validator_pubkey)
        valid_count += 1

    if valid_count < min_quorum:
        return False, (
            f"only {valid_count} valid cosig(s), need {min_quorum}"
        )
    return True, "ok"


__all__ = [
    "AttestationCert",
    "AttestationCertPayload",
    "AttestationOutcome",
    "Applicant",
    "CERT_SCHEMA",
    "Challenge",
    "ChallengeOutcome",
    "ChallengeResponse",
    "DEFAULT_CERT_LIFETIME_NS",
    "DEFAULT_QUORUM_K",
    "DEFAULT_QUORUM_N",
    "MAX_CLOCK_SKEW_NS",
    "PROTOCOL_VERSION",
    "Validator",
    "ValidatorCosig",
    "make_seed_signer",
    "run_attestation",
    "verify_attestation_cert",
]


# Pyright bookkeeping — these are referenced from method signatures /
# type annotations or surface for tests.
_ = ICPEnvelope
_ = EvalResult
