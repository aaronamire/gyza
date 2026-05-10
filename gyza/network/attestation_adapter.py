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
    "Tier3AttestationError",
    "Tier3AttestationResult",
    "applicant_eval_session",
    "make_eval_callback",
    "build_response_for_challenge",
    "request_tier3_attestation",
]


class EvalCallbackError(RuntimeError):
    """
    Raised when the eval callback can't produce a valid ChallengeResponse
    for a particular Challenge. The daemon will surface this as a
    ``failed to recv response from python`` libp2p stream error which
    the validator side reports as a clean stream close. Callers see
    the original exception via the gRPC stream's error path.
    """


class Tier3AttestationError(RuntimeError):
    """
    Raised when the Tier-3 orchestration as a whole cannot succeed —
    insufficient validators discovered, quorum not met after polling
    every candidate, or self-verification of the assembled cert
    failed. Distinct from per-validator rejection (which is a soft
    failure that the orchestrator handles internally).
    """


from dataclasses import dataclass


@dataclass
class Tier3AttestationResult:
    """
    Outcome of a ``request_tier3_attestation`` call. Always inspectable;
    ``cert`` is non-None on success.

    ``cert``               — the assembled, self-verified
                              AttestationCert proto. None on quorum
                              failure.
    ``cosignatures``       — every cosig collected (incl. those
                              beyond the quorum threshold).
    ``contacted_peer_ids`` — peer IDs the orchestrator drove
                              `request_attestation` against, in order.
    ``per_peer_errors``    — peer_id → error string for validators
                              that rejected or were unreachable.
    """
    cert: pb.AttestationCert | None
    cosignatures: list[pb.CoSignature]
    contacted_peer_ids: list[str]
    per_peer_errors: dict[str, str]


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
    proposed_attestation_body: pb.AttestationBody | None = None,
    expected_validator_task_ids: list[str] | None = None,
    attestation_lifetime_s: float = 30 * 24 * 3600,
) -> Iterator[Callable[[pb.Challenge], pb.ChallengeResponse]]:
    """
    Context manager that owns an ephemeral AgentRunner under
    ``compositor``'s identity. Yields an eval callback ready to plug
    into ``CapabilityClient.request_attestation``. On exit the runner
    is stopped, the temp directory removed.

    Reusing the same runner across multiple Challenge frames is the
    intended pattern: the Tier-3 orchestrator (#21d) contacts N
    validators in sequence and pays the runner-bootstrap cost once.
    Each Challenge is run in its own per-call workdir (under
    ``scratch_dir/eval_<nonce>/``), so cross-task and cross-call
    isolation is preserved.

    ``scratch_dir`` defaults to a fresh tempdir. Callers who need to
    inspect the on-disk state (debugging) can pass an explicit path.

    ``proposed_attestation_body`` — load-bearing for #21d quorum
    aggregation. Every validator must sign IDENTICAL canonical bytes
    or their cosignatures cannot aggregate into a quorum-verifiable
    cert. The applicant authors ONE body and includes it (unmodified)
    in every ChallengeResponse. If None, the session generates a
    fresh body keyed to the applicant's compositor pubkey, with
    timestamps from `time.time_ns()` and a `tier_granted` of 3.
    For multi-validator orchestration ALL validators MUST be called
    against the SAME session (so they all see the same body).

    ``expected_validator_task_ids`` — locks the body's
    ``challenge_task_ids`` to a specific task list. Required when a
    proposed body is being constructed (the validator's plausibility
    check rejects bodies whose task_ids don't match the validator's
    challenge). Defaults to the canonical EVAL_TASKS ids — matches
    what every gyza-netd daemon currently issues.

    ``attestation_lifetime_s`` — bounds how long the cert stays
    valid. Default 30 days; capped at 90 days by the validator's
    plausibility check (capability.MaxAttestationTTL).
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

    # Build the proposed AttestationBody once. Every validator that
    # accepts a Challenge issued during this session MUST sign these
    # exact bytes, so they aggregate into a quorum-verifiable cert.
    if proposed_attestation_body is None:
        if expected_validator_task_ids is None:
            expected_validator_task_ids = [t.task_id for t in tasks]
        now_ns = time.time_ns()
        proposed_attestation_body = pb.AttestationBody(
            applicant_pubkey=compositor.pubkey_hex,
            issued_at_ns=now_ns,
            expires_at_ns=now_ns + int(attestation_lifetime_s * 1_000_000_000),
            tier_granted=3,
            challenge_task_ids=list(expected_validator_task_ids),
        )

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
            proposed_attestation_body=proposed_attestation_body,
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
    proposed_attestation_body: pb.AttestationBody | None = None,
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
            proposed_attestation_body=proposed_attestation_body,
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
    proposed_attestation_body: pb.AttestationBody | None = None,
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

    response = pb.ChallengeResponse(
        body=body,
        applicant_signature=sig_bytes,
    )
    if proposed_attestation_body is not None:
        # Field-by-field copy so the caller's instance isn't mutated by
        # protobuf's reference assignment. The validator's plausibility
        # check rejects bodies whose challenge_task_ids don't match
        # THIS challenge's task_ids, so callers driving multi-validator
        # quorum MUST ensure every validator they contact uses the
        # same canonical task list (gyza-netd's main.go currently
        # hardcodes this; a future negotiation protocol could relax it).
        response.proposed_attestation_body.CopyFrom(proposed_attestation_body)
    return response


# ---------------------------------------------------------------------------
# Tier-3 orchestrator — discover validators, drive quorum attestation
# ---------------------------------------------------------------------------

def request_tier3_attestation(
    *,
    cap,  # CapabilityClient
    netd,  # NetdClient
    compositor: LocalCompositor,
    quorum_k: int = 2,
    candidate_n: int = 3,
    explicit_validator_peer_ids: list[str] | None = None,
    discovery_query_embedding=None,
    eval_overall_timeout_s: float = 120.0,
    per_validator_timeout_s: float = 130.0,
    attestation_lifetime_s: float = 30 * 24 * 3600,
    self_verify: bool = True,
) -> Tier3AttestationResult:
    """
    Drive Tier-3 attestation against ≥``quorum_k`` of ≤``candidate_n``
    validators, returning a self-verified ``AttestationCert`` proto on
    success.

    Validator selection: if ``explicit_validator_peer_ids`` is supplied
    the orchestrator uses exactly those peers in order (skips DHT). This
    is the test path AND the operator-override path. Otherwise the
    orchestrator calls ``netd.find_agents(min_tier=3, k=candidate_n)``
    against ``discovery_query_embedding`` (or a fresh random vector if
    None), deduplicates by ``compositor_pubkey``, and resolves each
    advertisement's first multiaddr to a peer_id by parsing the
    trailing ``/p2p/<id>`` segment.

    Per-validator failures are SOFT — they're recorded in
    ``per_peer_errors`` and the orchestrator continues to the next
    candidate until either ``quorum_k`` cosigs are collected or the
    candidate pool is exhausted. A complete pool exhaustion below
    quorum returns ``cert=None``; callers then surface to the operator.

    Cert assembly: every collected cosignature signs the SAME
    ``AttestationBody`` proposed by ``applicant_eval_session``. The
    quorum is k DISTINCT validator pubkeys (validator-pubkey
    deduplication happens here AND inside ``capability.VerifyAttestation``,
    so a single Tier-3 node can't pad a cert by signing multiple times).

    On success: builds an ``AttestationCert`` proto, optionally calls
    ``cap.verify_attestation`` for cross-language self-verification
    (defaults to True; pass False to skip the network round-trip in
    contexts where the daemon is the same one that's about to publish).
    """
    if quorum_k < 1:
        raise ValueError(f"quorum_k must be ≥ 1, got {quorum_k}")
    if candidate_n < quorum_k:
        raise ValueError(
            f"candidate_n ({candidate_n}) < quorum_k ({quorum_k})"
        )

    # Step 1: resolve the candidate peer ID list.
    if explicit_validator_peer_ids is not None:
        candidate_peer_ids = list(explicit_validator_peer_ids)
        LOG.info(
            "[tier3] using %d explicit validator peer ids",
            len(candidate_peer_ids),
        )
    else:
        candidate_peer_ids = _discover_tier3_validators(
            netd=netd,
            n=candidate_n,
            query_embedding=discovery_query_embedding,
            self_compositor_pubkey=compositor.pubkey_hex,
        )
        if len(candidate_peer_ids) < quorum_k:
            raise Tier3AttestationError(
                f"DHT yielded {len(candidate_peer_ids)} Tier-3 validators, "
                f"need ≥{quorum_k} for quorum"
            )

    # Step 2: construct the proposed AttestationBody — every validator
    # MUST sign these exact bytes for cosignatures to aggregate. Using
    # gyza-netd's hardcoded canonical task list (kept in sync with
    # gyza/capability_eval.py's EVAL_TASKS).
    now_ns = time.time_ns()
    proposed_body = pb.AttestationBody(
        applicant_pubkey=compositor.pubkey_hex,
        issued_at_ns=now_ns,
        expires_at_ns=now_ns + int(attestation_lifetime_s * 1_000_000_000),
        tier_granted=3,
        challenge_task_ids=[t.task_id for t in EVAL_TASKS],
    )

    # Step 3: open one applicant session, drive each validator.
    cosigs: list[pb.CoSignature] = []
    seen_validator_pubkeys: set[str] = set()
    contacted: list[str] = []
    errors: dict[str, str] = {}

    with applicant_eval_session(
        compositor,
        proposed_attestation_body=proposed_body,
        overall_timeout_s=eval_overall_timeout_s,
    ) as eval_cb:
        for peer_id in candidate_peer_ids:
            if len(cosigs) >= quorum_k:
                break  # quorum already met
            contacted.append(peer_id)
            try:
                success, cosig, err = cap.request_attestation(
                    target_peer_id=peer_id,
                    eval_callback=eval_cb,
                    timeout_s=per_validator_timeout_s,
                )
            except Exception as e:  # noqa: BLE001 — soft per-peer failure
                errors[peer_id] = f"transport: {e}"
                LOG.warning("[tier3] peer %s transport error: %s", peer_id[:16], e)
                continue
            if not success:
                errors[peer_id] = err or "unspecified"
                LOG.info("[tier3] peer %s rejected: %s", peer_id[:16], err)
                continue
            if cosig is None:
                errors[peer_id] = "success without cosig"
                continue
            if cosig.validator_pubkey in seen_validator_pubkeys:
                # Distinct peer_ids resolving to the same compositor.
                # The Go-side VerifyAttestation also dedups on this,
                # but rejecting up front keeps `cosigs` valid for
                # AssembleAttestation.
                errors[peer_id] = "duplicate validator pubkey"
                continue
            seen_validator_pubkeys.add(cosig.validator_pubkey)
            cosigs.append(cosig)
            LOG.info(
                "[tier3] cosig %d/%d from validator %s",
                len(cosigs), quorum_k, cosig.validator_pubkey[:16],
            )

    if len(cosigs) < quorum_k:
        return Tier3AttestationResult(
            cert=None,
            cosignatures=cosigs,
            contacted_peer_ids=contacted,
            per_peer_errors=errors,
        )

    # Step 4: assemble the cert. The body is the same proposed_body
    # every validator signed; the proto carries it once and the cosigs
    # alongside. We don't call Go's AssembleAttestation here (it'd
    # require another RPC); the proto construction is trivial. The
    # self-verify step below catches any aggregation bug.
    cert = pb.AttestationCert(body=proposed_body, co_signatures=cosigs)

    if self_verify:
        valid, cosig_count, reason = cap.verify_attestation(cert)
        if not valid:
            return Tier3AttestationResult(
                cert=None,
                cosignatures=cosigs,
                contacted_peer_ids=contacted,
                per_peer_errors={
                    **errors,
                    "_self_verify": (
                        f"assembled cert failed self-verify: {reason} "
                        f"(cosig_count={cosig_count})"
                    ),
                },
            )

    return Tier3AttestationResult(
        cert=cert,
        cosignatures=cosigs,
        contacted_peer_ids=contacted,
        per_peer_errors=errors,
    )


def _discover_tier3_validators(
    *,
    netd,  # NetdClient
    n: int,
    query_embedding,
    self_compositor_pubkey: str,
) -> list[str]:
    """
    Query the DHT for up to ``n`` Tier-3 validator advertisements,
    dedup by compositor pubkey, exclude self, and return their
    peer IDs (extracted from the trailing ``/p2p/<id>`` of each
    advertisement's first multiaddr).
    """
    if query_embedding is None:
        # Random unit vector — uniform-ish bucket distribution.
        # Different invocations get different validator subsets,
        # which is the property we want (no bias by compositor key).
        rng = np.random.default_rng()
        query_embedding = rng.standard_normal(384).astype(np.float32)
        query_embedding /= max(np.linalg.norm(query_embedding), 1e-9)

    ads = netd.find_agents(
        query_embedding=query_embedding,
        k=n * 4,  # over-fetch — some will dedup or fail to resolve
        min_tier=3,
    )
    seen_compositor: set[str] = set()
    peer_ids: list[str] = []
    for ad in ads:
        if ad.compositor_pubkey == self_compositor_pubkey:
            continue  # don't attest to ourselves
        if ad.compositor_pubkey in seen_compositor:
            continue
        peer_id = _extract_peer_id_from_multiaddr(ad.multiaddrs)
        if peer_id is None:
            LOG.warning(
                "[tier3] advertisement for %s had no /p2p/ multiaddr",
                ad.compositor_pubkey[:16],
            )
            continue
        seen_compositor.add(ad.compositor_pubkey)
        peer_ids.append(peer_id)
        if len(peer_ids) >= n:
            break
    return peer_ids


def _extract_peer_id_from_multiaddr(multiaddrs: list[str]) -> str | None:
    """Return the peer ID from the first multiaddr containing /p2p/."""
    for ma in multiaddrs:
        idx = ma.find("/p2p/")
        if idx < 0:
            continue
        rest = ma[idx + len("/p2p/"):]
        # Everything up to the next "/" is the peer ID.
        slash = rest.find("/")
        if slash < 0:
            return rest
        return rest[:slash]
    return None
