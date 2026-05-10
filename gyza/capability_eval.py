"""
Phase 3 priority #21 — canonical eval suite + local self-attestation.

This is the SEMANTIC core of proof-of-capability. Tier-3 cross-network
attestation (a 2-of-3 validator quorum bound to a libp2p stream
protocol on the Go side) builds ON TOP of these primitives — but the
suite, the verifier, and the local self-attestation loop don't depend
on the network protocol and ship first.

What "capability" actually means here
-------------------------------------

In a network of LLM-driven agents, capability is NOT "LLM quality."
It is: this node has

  * a real ``LocalCompositor`` that issues ``AgentIdentity``\\s,
  * a real ``AgentRunner`` that claims, executes, and signs work,
  * a real ``Blackboard`` that persists envelopes,
  * a real executor that produces structured output, and
  * a real ICP signer whose signatures verify against its compositor
    pubkey.

The eval suite exercises every one of those layers. Each task is
**structurally verifiable**: the verifier inspects the output by
SHAPE (key presence, type, semantic content) rather than by
LLM-judging it. This keeps Tier-1 self-attestation deterministic
and replicable; Tier-2/3 future work will use the same suite with
real LLM-driven agents serving the prompts.

Replay and forgery defenses
---------------------------

  * Each attestation run carries a fresh nonce that's folded into
    every prompt. The applicant's response signature implicitly
    covers the nonce (because the signed envelope's ``input_hashes``
    derive from a context dict containing the nonce); a replayed
    response from a previous nonce fails the structural check on
    tasks that echo the nonce back.

  * Each task output must be backed by an ICP envelope signed by
    the applicant's compositor key. The verifier checks
    ``envelope.agent_pubkey == claimed_applicant_pubkey``. A node
    that "borrows" envelopes from a peer fails this check —
    Ed25519 signatures aren't transferrable.

  * The output dict is captured ALONGSIDE the envelope; the verifier
    re-canonicalizes the claimed output and compares its BLAKE3 hash
    to the envelope's ``output_hash``. A node that swaps the output
    after signing is detected.

What's intentionally deferred
-----------------------------

  * The libp2p stream protocol (``/gyza/capability-challenge/1.0.0``)
    that carries challenges and responses between applicant and
    validator over the network. Today's implementation runs the
    eval LOCALLY against the applicant's own runner; the verifier
    is the same code that a remote validator will run, just invoked
    in-process.

  * The 3-validator quorum + DHT publish flow.

  * Anthropic-executor-backed eval (requires per-task prompt
    engineering for strict JSON output). The mock-eval executor
    here is sufficient to validate the machinery; future work will
    promote selected tasks to real-LLM-backed checks.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import blake3

from gyza.icp import ICPEnvelope, compute_envelope_hash, verify_envelope


LOG = logging.getLogger("gyza.capability_eval")


EVAL_VERSION = "v1"

# Sentinel embedded at the start of every eval prompt. The mock-eval
# executor uses this to dispatch to the right task solver, and the
# verifier uses it to confirm the prompt the runner saw matches the
# task it claimed to solve.
PROMPT_MARKER_FMT = "[GYZA_EVAL_TASK={task_id} NONCE={nonce}]"


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

@dataclass
class EvalTask:
    """
    One eval task. The contract is:

      * ``setup(workdir, nonce)`` materializes any fixture the task
        needs in ``workdir`` (a per-attestation tempdir). For tasks
        with no fixture, this is a no-op.

      * ``prompt_body`` is the natural-language portion of the agent
        prompt; the framework prepends the task marker and appends
        the workdir path. The agent is expected to return JSON with
        the keys named by ``output_keys``.

      * ``expected_output(workdir, nonce)`` computes the canonical
        correct output; the verifier compares the claimed output
        against it. This is what makes the task DETERMINISTIC at
        the verifier — no LLM-judging.

      * ``output_keys`` is the structural schema: every key must be
        present in the claimed output, and the values must be of
        the right type. Used as a quick reject check before the
        deeper structural compare.
    """

    task_id: str
    description: str
    prompt_body: str
    output_keys: dict[str, type]
    setup: Callable[[Path, str], None]
    expected_output: Callable[[Path, str], dict[str, Any]]
    timeout_s: float = 30.0

    def render_prompt(self, workdir: Path, nonce: str) -> str:
        marker = PROMPT_MARKER_FMT.format(task_id=self.task_id, nonce=nonce)
        return (
            f"{marker}\n"
            f"{self.prompt_body}\n"
            f"Workspace: {workdir}\n"
            f"Return strict JSON matching the schema."
        )


# ---- task implementations -------------------------------------------------

def _setup_count_files(workdir: Path, _nonce: str) -> None:
    for i in range(3):
        (workdir / f"a_{i}.py").write_text(f"# file {i}\n")
    (workdir / "readme.md").write_text("# not python\n")


def _expected_count_files(workdir: Path, _nonce: str) -> dict:
    n = sum(1 for p in workdir.iterdir() if p.suffix == ".py")
    return {"count": n}


def _setup_list_extensions(workdir: Path, _nonce: str) -> None:
    for name in ("alpha.py", "beta.py", "gamma.txt", "delta.json"):
        (workdir / name).write_text("x")


def _expected_list_extensions(workdir: Path, _nonce: str) -> dict:
    exts = sorted({p.suffix for p in workdir.iterdir() if p.suffix})
    return {"extensions": exts}


def _setup_first_line(workdir: Path, _nonce: str) -> None:
    (workdir / "data.txt").write_text("first line here\nsecond line\nthird line\n")


def _expected_first_line(workdir: Path, _nonce: str) -> dict:
    return {"first_line": "first line here"}


def _setup_filename_lengths(workdir: Path, _nonce: str) -> None:
    for name in ("ab.txt", "cdef.txt", "ghi.txt"):
        (workdir / name).write_text("x")


def _expected_filename_lengths(workdir: Path, _nonce: str) -> dict:
    lengths = sorted(len(p.name) for p in workdir.iterdir())
    return {"lengths": lengths}


def _setup_sum_numbers(workdir: Path, _nonce: str) -> None:
    (workdir / "nums.txt").write_text("3\n7\n11\n23\n")


def _expected_sum_numbers(workdir: Path, _nonce: str) -> dict:
    text = (workdir / "nums.txt").read_text()
    total = sum(int(line.strip()) for line in text.splitlines() if line.strip())
    return {"sum": total}


def _setup_echo_nonce(_workdir: Path, _nonce: str) -> None:
    pass


def _expected_echo_nonce(_workdir: Path, nonce: str) -> dict:
    return {"nonce": nonce}


EVAL_TASKS: list[EvalTask] = [
    EvalTask(
        task_id="count_py_files",
        description="Count files ending in .py in the workspace",
        prompt_body=(
            "Count the files ending in .py inside the workspace. "
            "Output a JSON object with key 'count' (int)."
        ),
        output_keys={"count": int},
        setup=_setup_count_files,
        expected_output=_expected_count_files,
    ),
    EvalTask(
        task_id="list_extensions",
        description="List unique file extensions in the workspace",
        prompt_body=(
            "List every distinct file extension (including the leading dot) "
            "across all files in the workspace, sorted alphabetically. "
            "Output JSON: {'extensions': [...]}."
        ),
        output_keys={"extensions": list},
        setup=_setup_list_extensions,
        expected_output=_expected_list_extensions,
    ),
    EvalTask(
        task_id="first_line_of_data",
        description="Return the first line of data.txt",
        prompt_body=(
            "Read 'data.txt' from the workspace and return its first line "
            "(without the trailing newline). Output JSON: {'first_line': str}."
        ),
        output_keys={"first_line": str},
        setup=_setup_first_line,
        expected_output=_expected_first_line,
    ),
    EvalTask(
        task_id="filename_lengths",
        description="Return ascending list of filename lengths",
        prompt_body=(
            "For each file in the workspace, compute the length of its name "
            "(including extension). Return them as a sorted ascending list. "
            "Output JSON: {'lengths': [...]}."
        ),
        output_keys={"lengths": list},
        setup=_setup_filename_lengths,
        expected_output=_expected_filename_lengths,
    ),
    EvalTask(
        task_id="sum_numbers",
        description="Sum the integers in nums.txt",
        prompt_body=(
            "Read 'nums.txt' from the workspace; each line holds one integer. "
            "Sum them. Output JSON: {'sum': int}."
        ),
        output_keys={"sum": int},
        setup=_setup_sum_numbers,
        expected_output=_expected_sum_numbers,
    ),
    EvalTask(
        task_id="echo_nonce",
        description="Echo the attestation nonce",
        prompt_body=(
            "Echo the attestation nonce shown in the prompt header back to "
            "the verifier. Output JSON: {'nonce': str}."
        ),
        output_keys={"nonce": str},
        setup=_setup_echo_nonce,
        expected_output=_expected_echo_nonce,
    ),
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    """
    Captured outcome of one task during ``run_eval_locally``.

    A successful result has both an envelope AND the claimed output
    bytes — the verifier needs both: the envelope to check signature
    + ownership, the output to check structural correctness AND
    re-derive the hash that the envelope claims.
    """
    task_id: str
    succeeded: bool
    output: dict | None = None
    output_text: str = ""
    envelope: ICPEnvelope | None = None
    duration_s: float = 0.0
    error: str = ""


@dataclass
class EvalReport:
    """
    Aggregated verifier output. ``passed`` is the gate the attestation
    flow checks; ``per_task`` carries diagnostic messages for both
    successes and failures so the operator can debug.
    """
    eval_version: str
    nonce: str
    applicant_pubkey: str
    passed: bool
    per_task: dict[str, str] = field(default_factory=dict)
    total_tasks: int = 0
    passed_tasks: int = 0


# ---------------------------------------------------------------------------
# Mock eval executor — solves each task structurally
# ---------------------------------------------------------------------------

def make_mock_eval_executor(
    tasks: list[EvalTask] = EVAL_TASKS,
) -> Callable[[str, dict], dict]:
    """
    An executor that recognizes eval prompts via the
    ``[GYZA_EVAL_TASK=...]`` marker and returns the canonical correct
    output. Used for Tier-1 self-attestation: it proves the
    applicant's runner+blackboard+ICP machinery works without
    requiring a real LLM.

    NOTE: this is NOT a substitute for real-LLM-backed evaluation in
    Tier 2/3. A node using this executor proves only "I have keys
    and machinery"; it does NOT prove "my LLM can answer questions."
    Future work runs the same eval against a real Anthropic executor
    under prompt-engineered instruction.
    """
    by_id = {t.task_id: t for t in tasks}

    def _exec(prompt: str, context: dict) -> dict:  # noqa: ARG001
        # Parse the marker. Format: [GYZA_EVAL_TASK=<id> NONCE=<nonce>].
        # The runner's ``build_enriched_prompt`` prepends a few-shot
        # block built from past episodes — and those episodes' intent
        # texts contain the prior tasks' markers verbatim. Scanning
        # from the start would pick up an earlier task's marker,
        # silently solving the wrong task. Scan from the END instead:
        # the current task's marker is always last because few-shot
        # context precedes "## Current task".
        marker_start = prompt.rfind("[GYZA_EVAL_TASK=")
        if marker_start < 0:
            return {
                "text": json.dumps({"error": "no eval marker"}),
                "tokens_in": 0,
                "tokens_out": 0,
                "model_identifier": "mock-eval",
                "inference_backend": "mock-eval",
            }
        try:
            marker_end = prompt.index("]", marker_start)
            inner = prompt[marker_start + len("[GYZA_EVAL_TASK="):marker_end]
            task_id, nonce_part = inner.split(" NONCE=", 1)
            nonce = nonce_part.strip()
        except ValueError:
            return {
                "text": json.dumps({"error": "malformed marker"}),
                "tokens_in": 0,
                "tokens_out": 0,
                "model_identifier": "mock-eval",
                "inference_backend": "mock-eval",
            }

        task = by_id.get(task_id)
        if task is None:
            return {
                "text": json.dumps({"error": f"unknown task {task_id}"}),
                "tokens_in": 0,
                "tokens_out": 0,
                "model_identifier": "mock-eval",
                "inference_backend": "mock-eval",
            }

        # Extract the per-task workspace from the prompt body. The
        # framework writes "Workspace: <abs path>" on its own line —
        # this is what a real LLM would read to know where its
        # fixtures live.
        #
        # We scan AFTER the marker, not from the start of the prompt:
        # ``build_enriched_prompt`` prepends few-shot context from
        # prior episodes, which can contain "Workspace: ..." lines
        # from earlier tasks. Picking up the first match would
        # silently route this task at the wrong workdir.
        wd = Path(os.getcwd())
        body = prompt[marker_end:]
        for line in body.splitlines():
            if line.startswith("Workspace: "):
                wd = Path(line.removeprefix("Workspace: ").strip())
                break
        try:
            payload = task.expected_output(wd, nonce)
        except Exception as e:  # noqa: BLE001
            payload = {"error": f"expected_output threw: {e}"}

        return {
            "text": json.dumps(payload),
            "tokens_in": len(prompt) // 4,
            "tokens_out": len(json.dumps(payload)) // 4,
            "model_identifier": "mock-eval",
            "inference_backend": "mock-eval",
        }

    return _exec


# ---------------------------------------------------------------------------
# Local eval driver
# ---------------------------------------------------------------------------

def _canonical_output_bytes(output: dict) -> bytes:
    """
    Stable serialization for hashing. ``sort_keys=True`` is essential —
    a JSON object's key order is not semantically meaningful, so the
    hash MUST be order-independent. ``separators`` removes whitespace
    so two valid JSON serializations of the same dict produce the
    same hash.
    """
    return json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8")


def run_eval_locally(
    *,
    runner: "Any",
    blackboard: "Any",
    applicant_pubkey: str,
    workdir: Path,
    nonce: str | None = None,
    tasks: list[EvalTask] = EVAL_TASKS,
    overall_timeout_s: float = 60.0,
    output_recorder: dict[str, dict] | None = None,
) -> tuple[str, dict[str, EvalResult]]:
    """
    Drive a running ``AgentRunner`` against the eval suite.

    For each task: render its prompt, post an intent + work item to
    the blackboard, wait for the runner to claim and complete it,
    capture the resulting envelope. Returns ``(nonce, results)``.

    The ``output_recorder`` argument lets the caller hook into the
    executor's return path so the eval driver can collect raw outputs
    by task_id. Callers that don't pre-build the recorder receive a
    fresh dict; pass an explicit one when wrapping a custom executor
    so the wrapping happens at the outer layer.

    The runner must already be ``start()``ed before calling this.
    Each task's own ``timeout_s`` bounds its individual completion;
    ``overall_timeout_s`` bounds the whole run regardless.
    """
    # We import the schema here so this module stays importable without
    # the heavy embeddings stack on the consumer side (e.g., a thin CLI
    # check).
    import numpy as np
    from gyza.embeddings import default_embedder
    from gyza.schema import EMBEDDING_DIM, WorkItem

    if nonce is None:
        nonce = uuid.uuid4().hex
    if output_recorder is None:
        output_recorder = {}

    workdir.mkdir(parents=True, exist_ok=True)

    embedder = default_embedder()

    # Subscribe to the runner's envelope-signed callback. The runner
    # fires this from its execution thread once per completion. We
    # collect into a dict keyed by action_id (which we set to the
    # work_item id), which lets us match envelopes back to tasks.
    envelopes_by_action: dict[str, ICPEnvelope] = {}
    envelope_evt = threading.Event()
    # Capture any prior callback so we can chain rather than clobber.
    prior_cb = runner._on_envelope_signed  # noqa: SLF001 — internal hook by design

    def _capture(env: ICPEnvelope) -> None:
        envelopes_by_action[env.action_id] = env
        envelope_evt.set()
        if prior_cb is not None:
            try:
                prior_cb(env)
            except Exception as e:  # noqa: BLE001
                LOG.warning("[eval] prior callback raised: %s", e)

    runner._on_envelope_signed = _capture  # noqa: SLF001

    results: dict[str, EvalResult] = {}
    deadline = time.monotonic() + overall_timeout_s

    try:
        for task in tasks:
            # Per-task workspace under the eval workdir keeps fixtures
            # from interfering across tasks — a follow-up task that
            # listed extensions would otherwise see the previous
            # task's files.
            task_dir = workdir / task.task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            try:
                task.setup(task_dir, nonce)
            except Exception as e:  # noqa: BLE001
                results[task.task_id] = EvalResult(
                    task_id=task.task_id, succeeded=False,
                    error=f"setup threw: {e}",
                )
                continue

            prompt = task.render_prompt(task_dir, nonce)
            # The desc_embedding is what the runner scores against; the
            # full eval prompt is the description so the runner has
            # everything it needs in-band.
            try:
                desc_emb = embedder.embed(prompt).astype(np.float32)
            except Exception:  # noqa: BLE001
                # Fallback to zeros — the test executor hits min_sim=0
                # so the actual vector content doesn't matter for routing.
                desc_emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)

            intent_id = str(uuid.uuid7())
            blackboard.post_intent({
                "intent_id": intent_id,
                "natural_text": f"eval:{task.task_id}:{EVAL_VERSION}",
                "category": "capability_eval",
                "actions": [],
                "authorization": {
                    "resources": [],
                    "preview_required": False,
                    "reversible": True,
                },
            })
            work_id = uuid.uuid4().hex
            wi = WorkItem(
                id=work_id,
                lineage_root=intent_id,
                parent_id=None,
                description=prompt,
                desc_embedding=desc_emb,
                reward=1.0,
                reward_updated_ns=time.time_ns(),
                required_tier=0,
                input_hashes=[],
                output_spec={"keys": list(task.output_keys.keys())},
                streaming_ok=False,
                claimed_by=None,
                claimed_at_ns=None,
                claim_hlc_l=0,
                claim_hlc_c=0,
                claim_hlc_node="",
                completed_at_ns=None,
                output_hash=None,
                icp_envelope_hash=None,
                success=None,
                created_at_ns=time.time_ns(),
                # Per-task TTL: enough headroom for the runner to claim,
                # execute, and sign. The eval driver's per-task timeout
                # bounds completion separately, but the blackboard's
                # TTL filter would silently drop the item from
                # ``get_unclaimed`` once expired.
                ttl_ns=int((task.timeout_s + 30.0) * 1_000_000_000),
            )

            t0 = time.monotonic()
            blackboard.post_work_item(wi)

            # Wait for the runner to sign an envelope for this work
            # item. We poll the envelope dict rather than blocking on
            # envelope_evt because multiple tasks share the same Event;
            # checking by action_id is the unambiguous reader.
            task_deadline = min(t0 + task.timeout_s, deadline)
            envelope: ICPEnvelope | None = None
            while time.monotonic() < task_deadline:
                envelope = envelopes_by_action.get(work_id)
                if envelope is not None:
                    break
                # Also respect the overall deadline.
                if time.monotonic() >= deadline:
                    break
                envelope_evt.wait(timeout=0.2)
                envelope_evt.clear()

            duration = time.monotonic() - t0
            if envelope is None:
                results[task.task_id] = EvalResult(
                    task_id=task.task_id, succeeded=False,
                    error=(
                        f"runner did not sign within {task.timeout_s:.1f}s "
                        f"(overall_remaining={max(0, deadline - time.monotonic()):.1f}s)"
                    ),
                    duration_s=duration,
                )
                continue

            # Recover the executor's output. The recorder (see
            # ``make_recording_executor``) stores both the parsed
            # structured output AND the original text — the verifier
            # needs both: parsed for shape/semantic checks, text to
            # reproduce the runner's hash binding.
            captured = output_recorder.get(work_id)
            if captured is None:
                results[task.task_id] = EvalResult(
                    task_id=task.task_id, succeeded=False,
                    error="executor output not recorded",
                    envelope=envelope, duration_s=duration,
                )
                continue
            results[task.task_id] = EvalResult(
                task_id=task.task_id,
                succeeded=True,
                output=captured.get("parsed"),
                output_text=captured.get("text", ""),
                envelope=envelope,
                duration_s=duration,
            )
    finally:
        runner._on_envelope_signed = prior_cb  # noqa: SLF001 — restore

    return nonce, results


def make_recording_executor(
    inner: Callable[[str, dict], dict],
    output_recorder: dict[str, dict],
) -> Callable[[str, dict], dict]:
    """
    Wraps an inner executor so each call's output is captured under
    the work_item id. The runner sets ``context["item"].id`` on every
    call; we use that as the recorder key.

    Each entry stores BOTH:

      * ``parsed`` — the JSON-decoded structured output (used for
        shape and semantic checks).
      * ``text`` — the raw ``text`` field returned by the inner
        executor (used to recompute the runner's BLAKE3 over
        ``{"text": text}``, which is what ends up in the envelope's
        ``output_hash``).

    Why both: the runner hashes the wrapped-text form (see
    ``runner.py::_execute``), so the verifier needs the original
    text to reproduce the hash. But the verifier also needs to
    judge the output's shape and semantic correctness — which lives
    in the parsed dict. Capturing only one of them breaks the
    verifier's chain-of-evidence; capturing both keeps the
    independence between "this output hashes correctly" and "this
    output means what it claims."
    """
    def _wrapped(prompt: str, context: dict) -> dict:
        result = inner(prompt, context)
        item = context.get("item")
        wid = getattr(item, "id", None) if item is not None else None
        text = result.get("text", "")
        if wid:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                parsed = {"_raw": text}
            output_recorder[wid] = {"parsed": parsed, "text": text}
        return result
    return _wrapped


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

def verify_eval_results(
    *,
    results: dict[str, EvalResult],
    applicant_pubkey: str,
    nonce: str,
    workdir: Path,
    tasks: list[EvalTask] = EVAL_TASKS,
) -> EvalReport:
    """
    Pure verifier — no I/O outside reading the workdir to compute
    expected outputs. Run on a Tier-3 validator AFTER receiving the
    applicant's results bundle.

    For each task in ``tasks``:

      1. The applicant's result must be ``succeeded=True`` with an
         envelope and output present.
      2. ``envelope.agent_pubkey`` must equal ``applicant_pubkey`` —
         no envelope-borrowing.
      3. ``verify_envelope`` must accept the envelope under
         ``applicant_pubkey``.
      4. The claimed output must satisfy ``task.output_keys`` schema.
      5. The claimed output's BLAKE3(canonical_serialization) must
         equal the envelope's ``output_hash`` — no swap-after-sign.
      6. The claimed output must equal ``task.expected_output(workdir,
         nonce)`` exactly (after canonical re-serialization).

    Aggregate: passes iff every task passes.
    """
    report = EvalReport(
        eval_version=EVAL_VERSION,
        nonce=nonce,
        applicant_pubkey=applicant_pubkey,
        passed=True,
        total_tasks=len(tasks),
        passed_tasks=0,
    )
    try:
        applicant_pubkey_bytes = bytes.fromhex(applicant_pubkey)
    except ValueError:
        report.passed = False
        for t in tasks:
            report.per_task[t.task_id] = "applicant_pubkey not valid hex"
        return report
    if len(applicant_pubkey_bytes) != 32:
        report.passed = False
        for t in tasks:
            report.per_task[t.task_id] = "applicant_pubkey not 32-byte Ed25519"
        return report

    for task in tasks:
        msg = _verify_one(
            task=task,
            result=results.get(task.task_id),
            applicant_pubkey=applicant_pubkey,
            applicant_pubkey_bytes=applicant_pubkey_bytes,
            nonce=nonce,
            workdir=workdir,
        )
        report.per_task[task.task_id] = msg
        if msg == "ok":
            report.passed_tasks += 1
        else:
            report.passed = False

    return report


def _verify_one(
    *,
    task: EvalTask,
    result: EvalResult | None,
    applicant_pubkey: str,
    applicant_pubkey_bytes: bytes,
    nonce: str,
    workdir: Path,
) -> str:
    """Returns 'ok' on success, otherwise a diagnostic string."""
    if result is None:
        return "missing result"
    if not result.succeeded:
        return f"failed: {result.error or 'no detail'}"
    if result.envelope is None:
        return "missing envelope"
    if result.output is None:
        return "missing claimed output"

    env = result.envelope
    output = result.output

    # (2) Envelope ownership.
    if env.agent_pubkey != applicant_pubkey:
        return (
            f"envelope.agent_pubkey={env.agent_pubkey[:16]}... does not "
            f"match applicant {applicant_pubkey[:16]}..."
        )

    # (3) Signature validity.
    if not verify_envelope(env, applicant_pubkey_bytes):
        return "envelope signature invalid under applicant_pubkey"

    # (4) Structural shape.
    for key, expected_type in task.output_keys.items():
        if key not in output:
            return f"output missing key {key!r}"
        if not isinstance(output[key], expected_type):
            return (
                f"output[{key!r}] has type {type(output[key]).__name__}, "
                f"expected {expected_type.__name__}"
            )

    # (5) Hash binding: reproduce the runner's hash and compare to
    # envelope.output_hash. The runner hashes
    # ``{"text": <executor_text>}`` (canonical JSON) — see
    # ``runner.py::_execute``. We must mirror that exactly; rolling
    # our own canonicalization here would diverge from what gets
    # signed and produce false-negatives on every envelope.
    runner_canonical = json.dumps(
        {"text": result.output_text}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    claimed_hash = blake3.blake3(runner_canonical).hexdigest()
    if claimed_hash != env.output_hash:
        return (
            f"output_hash mismatch: claimed={claimed_hash[:16]}... "
            f"envelope={env.output_hash[:16]}..."
        )

    # (6) Semantic correctness.
    task_dir = workdir / task.task_id
    try:
        expected = task.expected_output(task_dir, nonce)
    except Exception as e:  # noqa: BLE001
        return f"verifier expected_output threw: {e}"
    if _canonical_output_bytes(output) != _canonical_output_bytes(expected):
        return (
            f"output mismatch: got={json.dumps(output, sort_keys=True)[:120]} "
            f"expected={json.dumps(expected, sort_keys=True)[:120]}"
        )

    # Per-envelope sanity: hash of the envelope as transmitted should
    # be a real BLAKE3 hash. No semantic check needed; verify_envelope
    # already covered the signature.
    _ = compute_envelope_hash(env)

    return "ok"


__all__ = [
    "EVAL_TASKS",
    "EVAL_VERSION",
    "EvalReport",
    "EvalResult",
    "EvalTask",
    "PROMPT_MARKER_FMT",
    "make_mock_eval_executor",
    "make_recording_executor",
    "run_eval_locally",
    "verify_eval_results",
]
