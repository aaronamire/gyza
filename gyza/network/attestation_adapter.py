"""
Phase 3 priority #21-bridge — Python-side cross-network attestation adapter.

The Go daemon owns the libp2p ``/gyza/capability-challenge/1.0.0`` stream;
Python owns AgentRunner state. They meet on the bidirectional gRPC
``CapabilityService.RequestAttestation`` stream — frames flow in both
directions; the daemon ferries Challenge→Python and ChallengeResponse→
validator.

This module provides the upcall: given a Challenge from a remote
validator, build an ephemeral applicant runner, drive the canonical
eval suite, and return a properly-signed ChallengeResponse proto.
The runner is set up ONCE per attestation session and reused across
multiple Challenge frames (a future caller may attest to many
validators in sequence and would otherwise pay the runner-bootstrap
cost N times).

Why not extend ``gyza.network.capability_protocol``: that module
implements an in-process, JSON-canonicalized attestation flow used
for IN-PROCESS Tier-1 self-attestation. Cross-network attestation
is Go-protobuf-canonicalized — the two cosignatures CANNOT
aggregate, so the modules deliberately stay separate. See CLAUDE.md
§5a for the architectural decision.
"""
from __future__ import annotations

import contextlib
import logging
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from gyza.capability_eval import (
    EVAL_TASKS,
    EvalResult,
    EvalTask,
    make_mock_eval_executor,
    make_recording_executor,
    run_eval_locally,
)
from gyza.icp import ICPEnvelope, _payload_bytes  # noqa: SLF001 — used for the canonical bytes Go verifies against
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.proto import netd_pb2 as pb

LOG = logging.getLogger("gyza.attestation_adapter")


__all__ = [
    "EvalCallbackError",
    "applicant_eval_session",
    "make_eval_callback",
    "build_response_for_challenge",
]


class EvalCallbackError(RuntimeError):
    """
    Raised when the eval callback can't produce a valid ChallengeResponse
    for a particular Challenge. The daemon will surface this as a
    ``failed to recv response from python`` libp2p stream error which
    the validator side reports as a clean stream close. Callers see
    the original exception via the gRPC stream's error path.
    """


# ---------------------------------------------------------------------------
# Ephemeral applicant session — context manager that owns a runner
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def applicant_eval_session(
    compositor: LocalCompositor,
    *,
    scratch_dir: Path | None = None,
    tasks: list[EvalTask] = EVAL_TASKS,
    executor_factory: Callable[[], Callable[[str, dict], dict]] = make_mock_eval_executor,
    overall_timeout_s: float = 120.0,
) -> Iterator[Callable[[pb.Challenge], pb.ChallengeResponse]]:
    """
    Context manager that owns an ephemeral AgentRunner under
    ``compositor``'s identity. Yields an eval callback ready to plug
    into ``CapabilityClient.request_attestation``. On exit the runner
    is stopped, the temp directory removed.

    Reusing the same runner across multiple Challenge frames is the
    intended pattern: a future Tier-3 orchestrator that contacts 3
    validators in sequence pays the runner-bootstrap cost once,
    not three times. Each Challenge is run in its own per-call
    workdir (under ``scratch_dir/eval_<nonce>/``), so cross-task and
    cross-call isolation is preserved.

    ``scratch_dir`` defaults to a fresh tempdir. Callers who need to
    inspect the on-disk state (debugging) can pass an explicit path.
    """
    # Lazy imports — these pull in heavy ML deps (numpy is fine,
    # but EpisodicMemory ➜ LanceDB ➜ pyarrow loads big native libs).
    from gyza.blackboard import Blackboard
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.memory import EpisodicMemory
    from gyza.runner import AgentRunner
    from gyza.schema import EMBEDDING_DIM

    owns_scratch = scratch_dir is None
    if scratch_dir is None:
        scratch_dir = Path(tempfile.mkdtemp(prefix="gyza-tier3-applicant-"))
    else:
        scratch_dir = Path(scratch_dir)
        scratch_dir.mkdir(parents=True, exist_ok=True)

    bb = Blackboard(str(scratch_dir / "bb.db"))

    # Issue an attest-only agent under the user's compositor. The
    # ICP envelopes are signed with this AGENT key; the
    # ChallengeResponse body is signed with the COMPOSITOR key
    # (which is what the libp2p PeerID is derived from, and what the
    # validator verifies ApplicantSignature against).
    seed, manifest = compositor.issue_agent(
        agent_type="capability-tier3-applicant",
        model_path="mock-eval",
        fs_read_paths=[str(scratch_dir)],
        fs_write_paths=[str(scratch_dir)],
        attestation_tier=1,  # bootstrap; the cert we're collecting upgrades us to 3
    )
    ident = AgentIdentity(seed, manifest)

    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(scratch_dir / "mem.db"),
    )
    rng = np.random.default_rng(0)
    seed_emb = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    seed_emb /= max(np.linalg.norm(seed_emb), 1e-9)
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=seed_emb,
        db_path=str(scratch_dir / "spec.db"),
    )

    recorder: dict[str, dict] = {}
    executor = make_recording_executor(executor_factory(), recorder)
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

    try:
        cb = make_eval_callback(
            compositor=compositor,
            agent_identity=ident,
            runner=runner,
            blackboard=bb,
            recorder=recorder,
            scratch_dir=scratch_dir,
            tasks=tasks,
            overall_timeout_s=overall_timeout_s,
        )
        yield cb
    finally:
        runner.stop()
        if owns_scratch:
            shutil.rmtree(scratch_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Eval callback — the actual Challenge → ChallengeResponse machinery
# ---------------------------------------------------------------------------

def make_eval_callback(
    *,
    compositor: LocalCompositor,
    agent_identity: AgentIdentity,
    runner,
    blackboard,
    recorder: dict[str, dict],
    scratch_dir: Path,
    tasks: list[EvalTask] = EVAL_TASKS,
    overall_timeout_s: float = 120.0,
) -> Callable[[pb.Challenge], pb.ChallengeResponse]:
    """
    Build a callable that turns a daemon-delivered Challenge into a
    fully-signed ChallengeResponse. Suitable for passing to
    ``CapabilityClient.request_attestation``.

    Stateful: the caller-supplied runner / blackboard / recorder are
    shared across all calls. The callable is intended to be invoked
    ONCE per attestation request (one validator); orchestrators that
    need 2-of-3 quorum call ``request_attestation`` once per
    validator and aggregate cosigs after.
    """
    tasks_by_id = {t.task_id: t for t in tasks}

    def _callback(challenge: pb.Challenge) -> pb.ChallengeResponse:
        return build_response_for_challenge(
            challenge=challenge,
            compositor=compositor,
            agent_identity=agent_identity,
            runner=runner,
            blackboard=blackboard,
            recorder=recorder,
            scratch_dir=scratch_dir,
            tasks_by_id=tasks_by_id,
            overall_timeout_s=overall_timeout_s,
        )

    return _callback


def build_response_for_challenge(
    *,
    challenge: pb.Challenge,
    compositor: LocalCompositor,
    agent_identity: AgentIdentity,
    runner,
    blackboard,
    recorder: dict[str, dict],
    scratch_dir: Path,
    tasks_by_id: dict[str, EvalTask],
    overall_timeout_s: float = 120.0,
) -> pb.ChallengeResponse:
    """
    The hot path. Takes a validator's Challenge proto and returns a
    fully-signed ChallengeResponse proto. Pure(-ish): mutates ``recorder``
    and uses ``runner`` / ``blackboard`` as shared state.

    Raises ``EvalCallbackError`` on any failure that prevents producing
    a valid response — unknown task_ids, eval timeout, missing
    envelope. The daemon surfaces these via the gRPC stream's clean
    close path; the validator's libp2p side reports a "read response"
    error.
    """
    if challenge.body is None or not challenge.body.task_ids:
        raise EvalCallbackError("challenge body missing or has no task_ids")

    # Filter the canonical eval suite to the tasks the validator asked
    # for. Order matters: the response's task_results MUST be in the
    # same order as the challenge's task_ids (matches what the validator
    # iterates over in capability.VerifyResponse).
    requested: list[EvalTask] = []
    for tid in challenge.body.task_ids:
        task = tasks_by_id.get(tid)
        if task is None:
            raise EvalCallbackError(
                f"validator requested unknown task {tid!r}; supported: "
                f"{sorted(tasks_by_id)}"
            )
        requested.append(task)

    # Validator-chosen nonce is RAW BYTES on the wire. Our eval driver
    # accepts a hex string (it embeds the nonce text into prompts).
    # Use lower-case hex consistently — the canonical_eval module's
    # own nonce generator uses uuid4().hex which is lower-case.
    nonce_bytes: bytes = bytes(challenge.body.nonce)
    nonce_hex: str = nonce_bytes.hex()

    # Per-call workdir under the session scratch. Different validators
    # in sequence get different subdirs, so eval fixtures don't
    # collide across calls.
    eval_workdir = scratch_dir / f"eval_{nonce_hex[:16]}"
    eval_workdir.mkdir(parents=True, exist_ok=True)

    LOG.info(
        "[attestation_adapter] running eval for validator %s nonce=%s tasks=%d",
        challenge.body.challenger_pubkey[:16], nonce_hex[:8], len(requested),
    )

    # Recorder is a shared dict — clear ONLY the keys we're about to
    # reuse. Other entries from prior calls stay in place (harmless
    # but not load-bearing). Empirically the recorder is keyed by
    # work_item id (uuids), so collisions across calls are
    # cryptographically impossible — but be explicit.
    # (We do NOT clear globally because a concurrent call would race.)

    _, results = run_eval_locally(
        runner=runner,
        blackboard=blackboard,
        applicant_pubkey=agent_identity.pubkey_hex,
        workdir=eval_workdir,
        nonce=nonce_hex,
        tasks=requested,
        output_recorder=recorder,
        overall_timeout_s=overall_timeout_s,
    )

    # Build TaskResult protos in challenge order.
    task_results: list[pb.TaskResult] = []
    for task in requested:
        r: EvalResult | None = results.get(task.task_id)
        if r is None or not r.succeeded or r.envelope is None:
            err = (r.error if r is not None else "no result") or "unknown"
            raise EvalCallbackError(
                f"eval task {task.task_id} failed: {err}"
            )
        env: ICPEnvelope = r.envelope
        # The bytes the agent BLAKE3-hashed and signed. Go's verifier
        # mirrors this exact computation:
        #   ed25519.Verify(pubkey, blake3(icp_payload_bytes), sig).
        payload = _payload_bytes(env)
        try:
            sig_bytes = bytes.fromhex(env.signature)
        except ValueError as e:
            raise EvalCallbackError(
                f"eval task {task.task_id} produced non-hex signature: {e}"
            ) from e
        # output_json: canonical JSON of the parsed output. Validator
        # may inspect this for shape checks; capability.VerifyResponse
        # currently treats it as opaque (the structural verification
        # is done locally before signing on the applicant side, so
        # the validator only needs to check the ICP envelope binding).
        # We still ship the parsed output so a future stricter
        # verifier on the Go side has the bytes to inspect.
        import json as _json
        parsed = r.output if r.output is not None else {}
        output_json = _json.dumps(
            parsed, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        task_results.append(pb.TaskResult(
            task_id=task.task_id,
            output_json=output_json,
            icp_payload_bytes=payload,
            icp_signature_hex=env.signature,
            icp_agent_pubkey_hex=env.agent_pubkey,
            duration_ms=int(r.duration_s * 1000) if r.duration_s else 0,
        ))
        # Free the per-call recorder entry so memory doesn't grow
        # unboundedly across many attestations in one session.
        recorder.pop(env.action_id, None)

    body = pb.ResponseBody(
        applicant_pubkey=compositor.pubkey_hex,  # COMPOSITOR — load-bearing
        challenger_pubkey=challenge.body.challenger_pubkey,
        nonce=nonce_bytes,
        task_results=task_results,
        completed_at_ns=time.time_ns(),
    )
    # Deterministic marshal — Go's VerifyResponse uses
    # proto.MarshalOptions{Deterministic: true}.Marshal(body) and
    # ed25519.Verify against the applicant pubkey. Python's
    # SerializeToString with deterministic=True produces byte-identical
    # output for the same proto since the fields are in the same
    # canonical order. (Tested in tests/test_attestation_adapter.py.)
    body_bytes = body.SerializeToString(deterministic=True)
    sig_hex = compositor.sign(body_bytes)
    try:
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError as e:
        raise EvalCallbackError(
            f"compositor.sign produced non-hex signature: {e}"
        ) from e

    return pb.ChallengeResponse(
        body=body,
        applicant_signature=sig_bytes,
    )
