"""
Tests for the canonical eval suite (Phase 3 priority #21).

Coverage:

  * Each ``EvalTask``'s setup → expected_output produces a coherent
    result (the suite is a pure-Python contract; failure here is a
    bug in the suite definition itself).
  * The mock-eval executor produces task-correct outputs given the
    rendered prompt, including across enriched (memory-prefixed)
    prompts.
  * ``run_eval_locally`` drives a real AgentRunner against a real
    Blackboard end-to-end.
  * ``verify_eval_results`` accepts a clean run.
  * Verifier negatives: pubkey mismatch, malformed pubkey, swapped
    output, missing envelope, replay (wrong nonce).
"""
from __future__ import annotations

import secrets
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.capability_eval import (
    EVAL_TASKS,
    EVAL_VERSION,
    EvalResult,
    EvalTask,
    PROMPT_MARKER_FMT,
    make_mock_eval_executor,
    make_recording_executor,
    run_eval_locally,
    verify_eval_results,
)
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.runner import AgentRunner
from gyza.schema import EMBEDDING_DIM


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _normed(rng: np.random.Generator) -> np.ndarray:
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _make_runner(
    tmp_path: Path,
    bb: Blackboard,
    compositor: LocalCompositor,
    executor,
) -> tuple[AgentRunner, AgentIdentity]:
    seed, manifest = compositor.issue_agent(
        agent_type="eval-applicant",
        model_path="mock-eval",
        fs_read_paths=["/tmp"],
        fs_write_paths=["/tmp"],
        attestation_tier=1,
    )
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(tmp_path / "mem.db"),
    )
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=_normed(np.random.default_rng(0)),
        db_path=str(tmp_path / "spec.db"),
    )
    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=executor,
        min_reward_threshold=0.0,
        # Eval items have arbitrary embeddings; we don't want the
        # similarity gate to filter them.
        min_similarity_threshold=-1.0,
        poll_interval_s=0.05,
    )
    return runner, ident


def _compositor(tmp_path: Path) -> LocalCompositor:
    p = tmp_path / "compositor.key"
    p.write_bytes(secrets.token_bytes(32))
    p.chmod(0o600)
    return LocalCompositor(str(p))


# ----------------------------------------------------------------------
# Suite contract — each task's setup → expected_output is coherent
# ----------------------------------------------------------------------

@pytest.mark.parametrize("task", EVAL_TASKS, ids=lambda t: t.task_id)
def test_task_setup_is_consistent_with_expected_output(task: EvalTask, tmp_path):
    """
    Calling expected_output AFTER setup should produce a deterministic
    result that doesn't crash. Catches typos in the task suite.
    """
    nonce = "test_nonce_" + task.task_id
    task.setup(tmp_path, nonce)
    out = task.expected_output(tmp_path, nonce)
    assert isinstance(out, dict)
    for key, expected_type in task.output_keys.items():
        assert key in out, f"task {task.task_id} expected_output missing {key}"
        assert isinstance(out[key], expected_type), (
            f"task {task.task_id} expected_output[{key}] has type "
            f"{type(out[key]).__name__}, declared {expected_type.__name__}"
        )


# ----------------------------------------------------------------------
# Mock executor produces correct output for every task
# ----------------------------------------------------------------------

@pytest.mark.parametrize("task", EVAL_TASKS, ids=lambda t: t.task_id)
def test_mock_executor_solves_each_task(task: EvalTask, tmp_path):
    nonce = "exec_nonce_" + task.task_id
    task_dir = tmp_path / task.task_id
    task_dir.mkdir()
    task.setup(task_dir, nonce)

    fn = make_mock_eval_executor()
    prompt = task.render_prompt(task_dir, nonce)
    result = fn(prompt, {"item": None})

    import json
    parsed = json.loads(result["text"])
    expected = task.expected_output(task_dir, nonce)
    assert parsed == expected, (
        f"mock executor for {task.task_id}: got {parsed} expected {expected}"
    )


def test_mock_executor_handles_enriched_prompt(tmp_path):
    """
    The runner's ``build_enriched_prompt`` may prepend memory few-shot
    context before the task body. The marker scanner must find the
    marker regardless of prefix.
    """
    task = EVAL_TASKS[0]  # count_py_files
    nonce = "enriched_nonce"
    task_dir = tmp_path / task.task_id
    task_dir.mkdir()
    task.setup(task_dir, nonce)

    fn = make_mock_eval_executor()
    enriched = (
        "## Relevant past experience\n"
        "Some prior episode summary here.\n"
        "## Current task\n"
        + task.render_prompt(task_dir, nonce)
    )
    result = fn(enriched, {"item": None})
    import json
    parsed = json.loads(result["text"])
    assert parsed == task.expected_output(task_dir, nonce)


def test_mock_executor_unknown_task_returns_error():
    fn = make_mock_eval_executor()
    bogus_marker = PROMPT_MARKER_FMT.format(task_id="not_a_task", nonce="x")
    result = fn(bogus_marker + "\nbody\nWorkspace: /tmp", {"item": None})
    import json
    parsed = json.loads(result["text"])
    assert "error" in parsed


# ----------------------------------------------------------------------
# End-to-end: run_eval_locally + verify_eval_results round-trip
# ----------------------------------------------------------------------

@pytest.fixture
def applicant(tmp_path):
    """
    Build a complete applicant: blackboard + compositor + runner with
    a recording mock-eval executor. Yields (runner, identity, bb,
    recorder) and tears down the runner cleanly.
    """
    bb = Blackboard(str(tmp_path / "bb.db"))
    comp = _compositor(tmp_path)
    recorder: dict[str, dict] = {}
    inner = make_mock_eval_executor()
    executor = make_recording_executor(inner, recorder)
    runner, ident = _make_runner(tmp_path, bb, comp, executor)
    runner.start()
    try:
        yield runner, ident, bb, recorder
    finally:
        runner.stop()


def test_full_attestation_loop_passes(applicant, tmp_path):
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval"
    nonce, results = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    # Every task completed.
    for task in EVAL_TASKS:
        r = results[task.task_id]
        assert r.succeeded, (
            f"task {task.task_id} did not complete: {r.error}"
        )
        assert r.envelope is not None
        assert r.output is not None

    # Verifier accepts the bundle.
    report = verify_eval_results(
        results=results,
        applicant_pubkey=ident.pubkey_hex,
        nonce=nonce,
        workdir=workdir,
    )
    assert report.passed, f"verifier rejected: {report.per_task}"
    assert report.passed_tasks == len(EVAL_TASKS)
    assert report.eval_version == EVAL_VERSION


def test_full_attestation_with_explicit_nonce(applicant, tmp_path):
    """
    Caller-provided nonce flows through to the prompt and the
    verifier. Sanity check that the nonce isn't being silently
    overwritten.
    """
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval2"
    expected_nonce = "deadbeef" * 4
    nonce, _ = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        nonce=expected_nonce,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    assert nonce == expected_nonce


# ----------------------------------------------------------------------
# Verifier negatives — the actual security-relevant tests
# ----------------------------------------------------------------------

def test_verifier_rejects_pubkey_mismatch(applicant, tmp_path):
    """
    An applicant submitting envelopes from an attacker's compositor
    key under a victim's claimed pubkey gets rejected — the envelope's
    agent_pubkey field carries the real signer.
    """
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval"
    nonce, results = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    fake_pubkey = "00" * 32
    report = verify_eval_results(
        results=results,
        applicant_pubkey=fake_pubkey,
        nonce=nonce,
        workdir=workdir,
    )
    assert not report.passed
    # Each per-task message should flag the ownership mismatch.
    for task in EVAL_TASKS:
        msg = report.per_task[task.task_id]
        assert (
            "agent_pubkey" in msg
            or "signature invalid" in msg
        ), f"unexpected verifier msg for {task.task_id}: {msg}"


def test_verifier_rejects_malformed_pubkey(applicant, tmp_path):
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval"
    nonce, results = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    report = verify_eval_results(
        results=results,
        applicant_pubkey="not-hex",
        nonce=nonce,
        workdir=workdir,
    )
    assert not report.passed


def test_verifier_rejects_swapped_output(applicant, tmp_path):
    """
    If the applicant's claimed output dict doesn't hash to the
    envelope's output_hash, the verifier rejects. Defends against
    "sign one thing, claim another."
    """
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval"
    nonce, results = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    # Tamper: swap one task's claimed output_text to something else.
    target = "count_py_files"
    swapped = EvalResult(
        task_id=target,
        succeeded=True,
        output={"count": 999},
        output_text='{"count": 999}',
        envelope=results[target].envelope,  # original envelope, swapped output
        duration_s=results[target].duration_s,
    )
    results[target] = swapped
    report = verify_eval_results(
        results=results,
        applicant_pubkey=ident.pubkey_hex,
        nonce=nonce,
        workdir=workdir,
    )
    assert not report.passed
    assert "output_hash mismatch" in report.per_task[target]


def test_verifier_rejects_missing_result(applicant, tmp_path):
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval"
    nonce, results = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    # Drop one task's result entirely.
    del results["sum_numbers"]
    report = verify_eval_results(
        results=results,
        applicant_pubkey=ident.pubkey_hex,
        nonce=nonce,
        workdir=workdir,
    )
    assert not report.passed
    assert "missing result" in report.per_task["sum_numbers"]


def test_verifier_rejects_wrong_nonce_for_echo_task(applicant, tmp_path):
    """
    The echo_nonce task's expected output literally is the nonce.
    A run with nonce A whose results are verified under nonce B must
    fail at least the echo task — proving the nonce binding works
    even at the structural level (without the cryptographic envelope
    binding, which catches it at a different layer).
    """
    runner, ident, bb, recorder = applicant
    workdir = tmp_path / "eval"
    nonce_a = "00" * 16
    nonce_b = "ff" * 16
    _, results = run_eval_locally(
        runner=runner,
        blackboard=bb,
        applicant_pubkey=ident.pubkey_hex,
        workdir=workdir,
        nonce=nonce_a,
        output_recorder=recorder,
        overall_timeout_s=30.0,
    )
    report = verify_eval_results(
        results=results,
        applicant_pubkey=ident.pubkey_hex,
        nonce=nonce_b,
        workdir=workdir,
    )
    assert not report.passed
    # echo_nonce must specifically fail; other tasks may pass since
    # their setup doesn't depend on the nonce.
    assert "mismatch" in report.per_task["echo_nonce"].lower(), (
        f"echo_nonce should mismatch; got: {report.per_task['echo_nonce']}"
    )


def test_eval_version_is_stable_string():
    """
    EVAL_VERSION ends up in the attestation cert. Pin its current
    value so a bump is intentional, not accidental.
    """
    assert EVAL_VERSION == "v1"


# Pyright bookkeeping
_ = uuid
_ = time
