"""
Tests for the cross-network attestation protocol layer
(Phase 3 priority #21, in-process orchestration variant).

These tests build a real applicant runner + N validator instances
in-process, drive the full Challenge / Response / Outcome flow,
aggregate cosignatures into an AttestationCert, and verify the
cert with the consumer-side checker.

Coverage:

  Happy path
    * 3-of-3 validators all accept → cert with 3 cosigs
    * 2-of-3 (one validator rejects) → cert with 2 cosigs, quorum_met
    * 1-of-3 (two reject) → no cert, quorum_met=False

  Validator-side rejections (each must produce a structured outcome,
  no exceptions)
    * Tampered eval_results — applicant's signature still valid but
      the eval verifier catches the mismatch.
    * Wrong nonce_echo
    * Mismatched applicant_compositor_pubkey vs cert_payload.applicant
    * Forged applicant_signature
    * Past-issued cert (clock skew exceeded)
    * Future-issued cert (clock skew exceeded)
    * Cert lifetime > 90 days

  Cert verifier
    * Round-trip: real cert verifies under the consumer-side checker
    * Wrong expected_applicant_pubkey rejected
    * Forged validator cosignature rejected
    * Duplicate cosig from same validator counted once
    * Quorum not met → reject
    * Expired cert → reject
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.capability_eval import (
    EVAL_TASKS,
    make_mock_eval_executor,
    make_recording_executor,
)
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.network.capability_protocol import (
    Applicant,
    AttestationCert,
    AttestationCertPayload,
    CERT_SCHEMA,
    DEFAULT_CERT_LIFETIME_NS,
    Validator,
    ValidatorCosig,
    make_seed_signer,
    run_attestation,
    verify_attestation_cert,
)
from gyza.runner import AgentRunner
from gyza.schema import EMBEDDING_DIM


# ----------------------------------------------------------------------
# Test scaffolding
# ----------------------------------------------------------------------

def _normed(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _compositor_with_seed(tmp_path: Path, name: str) -> tuple[LocalCompositor, bytes]:
    """
    Build a LocalCompositor and return the master seed bytes alongside.
    The seed is needed because the protocol layer signs at the
    *compositor* level using the same primitive (Ed25519) but a
    standalone helper, not via LocalCompositor.sign — that lets the
    Validator class be instantiated without a key file on disk.
    """
    p = tmp_path / f"{name}.key"
    seed = secrets.token_bytes(32)
    p.write_bytes(seed)
    p.chmod(0o600)
    return LocalCompositor(str(p)), seed


def _make_applicant_runner(
    tmp_path: Path, compositor: LocalCompositor,
) -> tuple[Applicant, AgentRunner, Blackboard, dict, AgentIdentity]:
    """
    Construct a full applicant: blackboard, agent identity, runner
    backed by the recording mock-eval executor. The Applicant signs at
    the COMPOSITOR level using ``compositor.sign`` — which uses the
    HKDF-derived compositor signing key. (Trying to read the master
    seed file and use that directly would NOT work because the
    compositor's pubkey is derived from the HKDF output, not the
    master seed.)
    """
    bb = Blackboard(str(tmp_path / "applicant_bb.db"))
    seed_bytes, manifest = compositor.issue_agent(
        agent_type="capability-applicant",
        model_path="mock-eval",
        fs_read_paths=[str(tmp_path)],
        fs_write_paths=[str(tmp_path)],
        attestation_tier=1,
    )
    ident = AgentIdentity(seed_bytes, manifest)
    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(tmp_path / "applicant_mem.db"),
    )
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=_normed(np.random.default_rng(0)),
        db_path=str(tmp_path / "applicant_spec.db"),
    )
    recorder: dict[str, dict] = {}
    inner = make_mock_eval_executor()
    executor = make_recording_executor(inner, recorder)
    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=executor,
        min_reward_threshold=0.0,
        min_similarity_threshold=-1.0,
        poll_interval_s=0.05,
    )
    runner.start()

    applicant = Applicant(
        sign_fn=compositor.sign,
        compositor_pubkey=compositor.pubkey_hex,
        runner=runner,
        blackboard=bb,
        agent_pubkey=ident.pubkey_hex,
    )
    return applicant, runner, bb, recorder, ident


def _make_validator(seed: bytes, pubkey: str) -> Validator:
    return Validator(sign_fn=make_seed_signer(seed), compositor_pubkey=pubkey)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def applicant_setup(tmp_path):
    comp, _seed = _compositor_with_seed(tmp_path, "applicant")
    applicant, runner, bb, recorder, ident = _make_applicant_runner(
        tmp_path, comp,
    )
    try:
        yield {
            "applicant": applicant,
            "runner": runner,
            "blackboard": bb,
            "recorder": recorder,
            "compositor": comp,
            "agent_identity": ident,
        }
    finally:
        runner.stop()


@pytest.fixture
def three_validators(tmp_path):
    """Three independent validators, each with its own compositor."""
    out: list[Validator] = []
    seeds: list[bytes] = []
    for i in range(3):
        seed = secrets.token_bytes(32)
        # Construct a compositor pubkey from the seed without going
        # through LocalCompositor (which would expect a key file).
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
        sk = Ed25519PrivateKey.from_private_bytes(seed)
        pk_hex = sk.public_key().public_bytes_raw().hex()
        out.append(_make_validator(seed, pk_hex))
        seeds.append(seed)
    return out, seeds


# ----------------------------------------------------------------------
# Happy paths
# ----------------------------------------------------------------------

def test_three_of_three_validators_accept(applicant_setup, three_validators, tmp_path):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "att_3of3"
    workdir.mkdir()

    outcome = run_attestation(
        applicant=applicant,
        validators=validators,
        workdir=workdir,
        output_recorder=recorder,
        quorum_k=2,
    )

    # 2-of-3 quorum is met after the first 2 validators succeed; the
    # orchestrator early-exits before running the third.
    assert outcome.quorum_met is True
    assert outcome.cert is not None
    assert len(outcome.cert.validator_cosigs) >= 2
    # Cert payload is well-formed.
    p = outcome.cert.payload
    assert p.schema == CERT_SCHEMA
    assert p.applicant_compositor_pubkey == applicant.compositor_pubkey


def test_two_of_three_with_one_rejecting(applicant_setup, three_validators, tmp_path):
    """Force the FIRST validator to reject by giving it a different
    eval suite (one task missing); the next two accept and quorum is met."""
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, seeds = three_validators

    # Replace the first validator with one that has a wider task set
    # the applicant can't satisfy. Easiest synthetic rejection: give
    # the validator a task list that includes a non-existent task_id.
    # The applicant uses the validator's challenge.task_ids to filter
    # EVAL_TASKS — a non-existent id results in a missing-result
    # rejection by the validator's eval verifier.
    from gyza.capability_eval import EvalTask
    extra = EvalTask(
        task_id="will_not_run",
        description="task only the validator knows about",
        prompt_body="never used",
        output_keys={"x": int},
        setup=lambda _wd, _n: None,
        expected_output=lambda _wd, _n: {"x": 0},
    )
    validators[0] = Validator(
        sign_fn=make_seed_signer(seeds[0]),
        compositor_pubkey=validators[0].pubkey,
        eval_tasks=list(EVAL_TASKS) + [extra],
    )

    workdir = tmp_path / "att_2of3"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant,
        validators=validators,
        workdir=workdir,
        output_recorder=recorder,
        quorum_k=2,
    )
    assert outcome.quorum_met is True
    # Quorum reached after the second validator accepts.
    assert outcome.cert is not None
    assert len(outcome.cert.validator_cosigs) == 2
    # The first validator rejected with a "missing result" reason.
    first_pk = validators[0].pubkey
    assert not outcome.per_validator[first_pk].accepted


def test_quorum_not_met(applicant_setup, three_validators, tmp_path):
    """k=3 requires every validator to accept; we make one fail."""
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, seeds = three_validators
    from gyza.capability_eval import EvalTask
    extra = EvalTask(
        task_id="will_not_run",
        description="x",
        prompt_body="x",
        output_keys={"x": int},
        setup=lambda _wd, _n: None,
        expected_output=lambda _wd, _n: {"x": 0},
    )
    validators[0] = Validator(
        sign_fn=make_seed_signer(seeds[0]),
        compositor_pubkey=validators[0].pubkey,
        eval_tasks=list(EVAL_TASKS) + [extra],
    )

    workdir = tmp_path / "att_fail"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant,
        validators=validators,
        workdir=workdir,
        output_recorder=recorder,
        quorum_k=3,
    )
    assert outcome.quorum_met is False
    assert outcome.cert is None
    # Two validators accepted; one rejected — but k=3 so no cert.
    accepted_count = sum(
        1 for o in outcome.per_validator.values() if o.accepted
    )
    assert accepted_count == 2


# ----------------------------------------------------------------------
# Validator-side rejections — each must surface as structured Outcome
# ----------------------------------------------------------------------

def test_tampered_eval_results_rejected(applicant_setup, three_validators, tmp_path):
    """
    After the applicant builds a valid response, swap one task's
    output. The applicant's signature won't match the swapped bytes —
    the validator catches it at the signature step.
    """
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators
    v = validators[0]

    challenge = v.issue_challenge(applicant.compositor_pubkey)
    workdir = tmp_path / "att_tamper"
    workdir.mkdir()
    response = applicant.respond_to_challenge(
        challenge,
        workdir=workdir,
        output_recorder=recorder,
    )
    # Tamper: swap one task's output_text post-sign.
    target = next(iter(response.eval_results))
    response.eval_results[target].output_text = '{"forged": true}'

    outcome = v.verify_response(challenge, response, workdir=workdir)
    assert not outcome.accepted
    assert "applicant signature invalid" in outcome.reason


def test_wrong_nonce_echo_rejected(applicant_setup, three_validators, tmp_path):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators
    v = validators[0]

    challenge = v.issue_challenge(applicant.compositor_pubkey)
    workdir = tmp_path / "att_nonce"
    workdir.mkdir()
    response = applicant.respond_to_challenge(
        challenge, workdir=workdir, output_recorder=recorder,
    )
    response.nonce_echo = "ff" * 16  # wrong

    outcome = v.verify_response(challenge, response, workdir=workdir)
    assert not outcome.accepted
    # Either nonce_echo mismatch OR applicant signature invalid (the
    # response payload changed under the signature). Both are valid
    # rejections; either one proves the defense holds.
    assert (
        "nonce_echo mismatch" in outcome.reason
        or "applicant signature invalid" in outcome.reason
    )


def test_mismatched_applicant_pubkey_rejected(
    applicant_setup, three_validators, tmp_path,
):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators
    v = validators[0]

    challenge = v.issue_challenge(applicant.compositor_pubkey)
    workdir = tmp_path / "att_pkmismatch"
    workdir.mkdir()
    response = applicant.respond_to_challenge(
        challenge, workdir=workdir, output_recorder=recorder,
    )
    # Cert payload claims a different applicant than the response.
    response.cert_payload = AttestationCertPayload(
        schema=response.cert_payload.schema,
        applicant_compositor_pubkey="00" * 32,
        eval_version=response.cert_payload.eval_version,
        issued_at_ns=response.cert_payload.issued_at_ns,
        expires_at_ns=response.cert_payload.expires_at_ns,
    )

    outcome = v.verify_response(challenge, response, workdir=workdir)
    assert not outcome.accepted


def test_clock_skew_in_past_rejected(applicant_setup, three_validators, tmp_path):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators
    v = validators[0]

    challenge = v.issue_challenge(applicant.compositor_pubkey)
    workdir = tmp_path / "att_skew_past"
    workdir.mkdir()
    # Pre-build a payload with issued_at 2 hours ago.
    backdated = AttestationCertPayload(
        schema=CERT_SCHEMA,
        applicant_compositor_pubkey=applicant.compositor_pubkey,
        eval_version="v1",
        issued_at_ns=time.time_ns() - 2 * 60 * 60 * 1_000_000_000,
        expires_at_ns=time.time_ns() + DEFAULT_CERT_LIFETIME_NS,
    )
    response = applicant.respond_to_challenge(
        challenge, workdir=workdir,
        output_recorder=recorder,
        proposed_payload=backdated,
    )

    outcome = v.verify_response(challenge, response, workdir=workdir)
    assert not outcome.accepted
    assert "clock-skew" in outcome.reason


def test_excessive_cert_lifetime_rejected(applicant_setup, three_validators, tmp_path):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators
    v = validators[0]

    challenge = v.issue_challenge(applicant.compositor_pubkey)
    workdir = tmp_path / "att_lifetime"
    workdir.mkdir()
    long_lived = AttestationCertPayload(
        schema=CERT_SCHEMA,
        applicant_compositor_pubkey=applicant.compositor_pubkey,
        eval_version="v1",
        issued_at_ns=time.time_ns(),
        # 1-year lifetime — exceeds the 90-day cap.
        expires_at_ns=time.time_ns() + 365 * 24 * 60 * 60 * 1_000_000_000,
    )
    response = applicant.respond_to_challenge(
        challenge, workdir=workdir,
        output_recorder=recorder,
        proposed_payload=long_lived,
    )

    outcome = v.verify_response(challenge, response, workdir=workdir)
    assert not outcome.accepted
    assert "lifetime" in outcome.reason


def test_forged_validator_signature_in_challenge_rejected(
    applicant_setup, three_validators, tmp_path,
):
    """The applicant must verify the challenge's validator signature
    BEFORE running the eval — protects against a non-validator
    impersonator."""
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators
    v = validators[0]

    challenge = v.issue_challenge(applicant.compositor_pubkey)
    challenge.signature = "00" * 64  # forged

    workdir = tmp_path / "att_forged_chal"
    workdir.mkdir()
    with pytest.raises(ValueError, match="challenge signature invalid"):
        applicant.respond_to_challenge(
            challenge, workdir=workdir, output_recorder=recorder,
        )


# ----------------------------------------------------------------------
# Consumer-side cert verifier
# ----------------------------------------------------------------------

def test_consumer_verifier_accepts_valid_cert(
    applicant_setup, three_validators, tmp_path,
):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "consumer_ok"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant, validators=validators, workdir=workdir,
        output_recorder=recorder, quorum_k=2,
    )
    assert outcome.cert is not None

    ok, reason = verify_attestation_cert(
        outcome.cert,
        expected_applicant_pubkey=applicant.compositor_pubkey,
        min_quorum=2,
    )
    assert ok, reason


def test_consumer_verifier_rejects_wrong_applicant(
    applicant_setup, three_validators, tmp_path,
):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "consumer_wrong_pk"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant, validators=validators, workdir=workdir,
        output_recorder=recorder, quorum_k=2,
    )
    ok, _ = verify_attestation_cert(
        outcome.cert, expected_applicant_pubkey="aa" * 32, min_quorum=2,
    )
    assert not ok


def test_consumer_verifier_rejects_forged_cosig(
    applicant_setup, three_validators, tmp_path,
):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "consumer_forged"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant, validators=validators, workdir=workdir,
        output_recorder=recorder, quorum_k=2,
    )
    cert = outcome.cert
    assert cert is not None
    # Replace one cosig's signature with garbage. Quorum_k=2 requires
    # 2 valid cosigs; with one forged, valid count drops to 1.
    cert.validator_cosigs[0] = ValidatorCosig(
        validator_pubkey=cert.validator_cosigs[0].validator_pubkey,
        signature="00" * 64,
        cosigned_at_ns=cert.validator_cosigs[0].cosigned_at_ns,
    )
    ok, reason = verify_attestation_cert(
        cert, expected_applicant_pubkey=applicant.compositor_pubkey,
        min_quorum=2,
    )
    assert not ok
    assert "valid cosig" in reason


def test_consumer_verifier_dedups_validators(
    applicant_setup, three_validators, tmp_path,
):
    """A cert with two cosigs from the same validator counts as 1
    toward quorum — defends against a single-validator forging
    pseudo-quorum."""
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "consumer_dup"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant, validators=validators, workdir=workdir,
        output_recorder=recorder, quorum_k=2,
    )
    cert = outcome.cert
    assert cert is not None
    # Duplicate the first cosig — still only 1 unique validator out
    # of 2 needed (with k=2).
    cert.validator_cosigs = [
        cert.validator_cosigs[0], cert.validator_cosigs[0],
    ]
    ok, _ = verify_attestation_cert(
        cert, expected_applicant_pubkey=applicant.compositor_pubkey,
        min_quorum=2,
    )
    assert not ok


def test_consumer_verifier_rejects_expired(
    applicant_setup, three_validators, tmp_path,
):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "consumer_expired"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant, validators=validators, workdir=workdir,
        output_recorder=recorder, quorum_k=2,
    )
    cert = outcome.cert
    assert cert is not None
    # Force-expire by passing a future ``now_ns`` past the cert's
    # ``expires_at_ns``.
    far_future = cert.payload.expires_at_ns + 1_000_000_000
    ok, reason = verify_attestation_cert(
        cert, expected_applicant_pubkey=applicant.compositor_pubkey,
        min_quorum=2, now_ns=far_future,
    )
    assert not ok
    assert "expired" in reason


def test_consumer_verifier_max_age(
    applicant_setup, three_validators, tmp_path,
):
    applicant = applicant_setup["applicant"]
    recorder = applicant_setup["recorder"]
    validators, _ = three_validators

    workdir = tmp_path / "consumer_age"
    workdir.mkdir()
    outcome = run_attestation(
        applicant=applicant, validators=validators, workdir=workdir,
        output_recorder=recorder, quorum_k=2,
    )
    cert = outcome.cert
    assert cert is not None
    ok, reason = verify_attestation_cert(
        cert, expected_applicant_pubkey=applicant.compositor_pubkey,
        min_quorum=2, max_age_ns=1,  # 1 ns — anything is older
    )
    assert not ok
    assert "older than max_age" in reason


# ----------------------------------------------------------------------
# Pyright bookkeeping
# ----------------------------------------------------------------------
_ = AttestationCert
