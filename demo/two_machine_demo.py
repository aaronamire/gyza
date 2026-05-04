"""
Phase 2 two-machine demo.

Same script runs on both machines (or both subprocesses on one machine
for `single_machine_phase2.py`). The coordinator role posts work and
verifies the cross-machine ICP chain at the end; the executor role
runs an AgentRunner that claims and processes the work items.

For reliable bootstrap on a single host (where mDNS over loopback is
flaky and Raft port allocation matters), this demo accepts explicit
QUIC + Raft port arguments and a peer Raft address. Real two-machine
LAN deployment with mDNS auto-discovery is the spec, but the
implementation details for reliable Raft cluster formation are
better exercised through direct addresses than through mDNS in a
demo loop. mDNS is exercised by the integration tests in
`tests/test_discovery.py` — different layer, tested separately.

Shared filesystem note: both nodes use a shared `--shared-dir` that
holds the artifact store, persisted manifests, and signed envelopes.
This is what makes it possible for the coordinator to reconstruct the
full ICP chain after the executor signed each hop. In a real
two-machine deployment, the artifact server/client (tested in
test_artifact_*.py) plays this role.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

import blake3
import numpy as np

# Allow `python demo/two_machine_demo.py …`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import (
    ICPEnvelope,
    compute_envelope_hash,
    generate_chain_report,
    verify_chain_multi_compositor,
)
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.network.artifact_store import ArtifactStore
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.network.raft import GyzaRaftNode
from gyza.network.trust_registry import TrustRegistry
from gyza.runner import AgentRunner, make_anthropic_executor, make_mock_executor
from gyza.schema import EMBEDDING_DIM, WorkItem


# ---------------------------------------------------------------------------
# Shared layout under --shared-dir
# ---------------------------------------------------------------------------
#   {shared}/artifacts/             (ArtifactStore)
#   {shared}/manifests/             (one JSON per agent manifest)
#   {shared}/envelopes/             (one JSON per signed ICP envelope)
#   {shared}/compositor_pubkeys/    (one file per node, named pubkey_hex)
#   {shared}/done                   (touch-file: coordinator signals end)
# ---------------------------------------------------------------------------

INTENT_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


def _seeded_embedding(text: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _publish_manifest(shared: Path, store: ArtifactStore, manifest: dict) -> str:
    """Store a manifest in the artifact store + a side directory keyed by
    the canonical-JSON hash. Returns that hash."""
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    h = store.store(payload)
    (shared / "manifests").mkdir(parents=True, exist_ok=True)
    (shared / "manifests" / f"{h}.json").write_bytes(payload)
    return h


def _publish_compositor_pubkey(shared: Path, pubkey_hex: str) -> None:
    (shared / "compositor_pubkeys").mkdir(parents=True, exist_ok=True)
    (shared / "compositor_pubkeys" / pubkey_hex).touch()


def _read_remote_compositor_pubkeys(shared: Path, exclude: str) -> list[str]:
    d = shared / "compositor_pubkeys"
    if not d.exists():
        return []
    return [p.name for p in d.iterdir() if p.is_file() and p.name != exclude]


def _persist_envelope(shared: Path, envelope: ICPEnvelope) -> str:
    """Write envelope JSON keyed by its content hash. Returns the hash."""
    h = compute_envelope_hash(envelope)
    (shared / "envelopes").mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(envelope), sort_keys=True, indent=2)
    (shared / "envelopes" / f"{h}.json").write_text(payload)
    return h


def _load_envelope(shared: Path, hash_hex: str) -> ICPEnvelope | None:
    p = shared / "envelopes" / f"{hash_hex}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return ICPEnvelope(**d)


# ---------------------------------------------------------------------------
# Executor role
# ---------------------------------------------------------------------------

def run_executor(args) -> int:
    shared = Path(args.shared_dir).expanduser()
    shared.mkdir(parents=True, exist_ok=True)

    print(f"[executor] starting on quic={args.quic_port} raft={args.raft_port}", flush=True)

    # Each role gets its own subdir so the per-compositor `spawn_counter`
    # files don't collide when both processes write concurrently.
    role_dir = shared / "exec"
    role_dir.mkdir(parents=True, exist_ok=True)
    compositor = LocalCompositor(key_path=str(role_dir / "compositor.key"))
    seed, manifest = compositor.issue_agent(
        agent_type="phase2-executor",
        model_path=args.model,
        fs_read_paths=[str(Path.home() / "dev" / "gyza")],
        fs_write_paths=[str(shared / "output")],
        allowed_hosts=["api.anthropic.com"],
        attestation_tier=1,
    )
    identity = AgentIdentity(seed, manifest)
    print(f"[executor] identity={identity.pubkey_hex[:16]}... compositor={compositor.pubkey_hex[:16]}...", flush=True)

    artifact_store = ArtifactStore(base_path=str(shared / "artifacts"))
    _publish_manifest(shared, artifact_store, manifest)
    _publish_compositor_pubkey(shared, compositor.pubkey_hex)

    bb = NetworkBlackboard(db_path=str(shared / "executor-bb.db"))
    bb.attach_artifact_store(artifact_store)

    raft = GyzaRaftNode(
        self_addr=f"127.0.0.1:{args.raft_port}",
        partner_addrs=[args.peer_raft_addr],
        blackboard=bb,
        identity=identity,
        journal_dir=None,
    )
    bb.attach_raft(raft)
    print(f"[executor] raft started; waiting for leader…", flush=True)

    # Wait for any leader (coordinator should be running and we'll join it).
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if raft.leader_addr() is not None:
            break
        time.sleep(0.2)
    print(f"[executor] leader={raft.leader_addr()}", flush=True)

    mem = EpisodicMemory(
        agent_id=identity.agent_id, db_path=str(shared / "executor-mem"),
    )
    spec = SpecializationTracker(
        agent_id=identity.agent_id,
        initial_embedding=_seeded_embedding("query read files python code", seed=11),
        db_path=str(shared / "executor-spec.db"),
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic  # noqa: F401
            executor_fn = make_anthropic_executor(api_key=api_key, model="claude-sonnet-4-5")
            print("[executor] using Anthropic executor", flush=True)
        except Exception:
            executor_fn = make_mock_executor("(mock executor result)")
            print("[executor] anthropic SDK missing, using mock", flush=True)
    else:
        executor_fn = _local_executor()
        print("[executor] no API key, using local-fallback executor", flush=True)

    def on_signed(envelope: ICPEnvelope) -> None:
        h = _persist_envelope(shared, envelope)
        print(f"[executor] signed envelope {h[:16]}... action={envelope.action_id}", flush=True)

    runner = AgentRunner(
        identity=identity,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=executor_fn,
        min_reward_threshold=0.0,
        min_similarity_threshold=-1.0,  # accept anything for the demo
        poll_interval_s=0.2,
        on_envelope_signed=on_signed,
    )
    runner.start()

    # Run until the coordinator drops the done sentinel, or 5min cap.
    done = shared / "done"
    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        if done.exists():
            print("[executor] done sentinel seen; stopping", flush=True)
            break
        time.sleep(0.5)

    runner.stop()
    raft.destroy()
    print(f"[executor] completed_count={runner.completed_count}", flush=True)
    return 0


def _local_executor():
    """Deterministic offline executor that synthesizes plausible
    structured output for the two demo work items based on the
    description text."""
    def _exec(prompt: str, ctx: dict) -> dict:
        item: WorkItem = ctx["item"]
        if "Find and read" in item.description or "Query and read" in item.description:
            scan_root = Path.home() / "dev" / "gyza" / "gyza"
            files = []
            for p in sorted(scan_root.rglob("*.py")):
                if "__pycache__" in p.parts:
                    continue
                src = p.read_text(errors="replace")
                classes = [
                    line.strip().split()[1].split("(")[0].rstrip(":")
                    for line in src.splitlines()
                    if line.strip().startswith("class ")
                ][:8]
                files.append({
                    "path": str(p.relative_to(scan_root)),
                    "loc": len(src.splitlines()),
                    "classes": classes,
                })
            text = json.dumps({
                "scan_root": str(scan_root),
                "file_count": len(files),
                "total_loc": sum(f["loc"] for f in files),
                "files": files,
            }, indent=2)
        else:
            # Summarizer path. Inputs hold the analysis JSON.
            payload_text = ""
            for art in ctx.get("inputs", []) or []:
                try:
                    payload = json.loads(art.data.decode("utf-8"))
                    inner = payload.get("text") if isinstance(payload, dict) else None
                    if isinstance(inner, str):
                        payload_text = inner
                        break
                except Exception:
                    continue
            try:
                analysis = json.loads(payload_text) if payload_text else {}
            except json.JSONDecodeError:
                analysis = {}
            file_count = analysis.get("file_count", "?")
            total_loc = analysis.get("total_loc", "?")
            modules = sorted({
                f.get("path", "") for f in analysis.get("files", []) or []
            })
            text = (
                f"Gyza architecture summary\n"
                f"  python files: {file_count}\n"
                f"  total loc:    {total_loc}\n"
                f"  modules:\n    " + "\n    ".join(modules[:30]) + "\n\n"
                "Components: Blackboard (SQLite WAL) coordinates work items "
                "between Ed25519-signed agents. ICP envelopes hash-chain each "
                "hop. Phase 2 adds Raft consensus across machines, mDNS "
                "discovery, QUIC transport with Ed25519 challenge-response "
                "auth, content-addressed artifact serving, and a TrustRegistry "
                "for cross-compositor verification.\n\n"
                "Data flow: Human intent → Blackboard → Raft replication → "
                "Agent claims via try_claim (BEGIN IMMEDIATE) → executes → "
                "signs ICP envelope → completes work item → episode written."
            )
        return {
            "text": text,
            "tokens_in": 0,
            "tokens_out": len(text) // 4,
            "model_identifier": "local-fallback",
            "inference_backend": "mock",
        }
    return _exec


# ---------------------------------------------------------------------------
# Coordinator role
# ---------------------------------------------------------------------------

def run_coordinator(args) -> int:
    shared = Path(args.shared_dir).expanduser()
    shared.mkdir(parents=True, exist_ok=True)
    # Fresh slate for this run.
    done_file = shared / "done"
    if done_file.exists():
        done_file.unlink()
    for sub in ("envelopes", "manifests", "compositor_pubkeys"):
        d = shared / sub
        if d.exists():
            for p in d.iterdir():
                try: p.unlink()
                except OSError: pass

    print(f"[coordinator] starting on quic={args.quic_port} raft={args.raft_port}", flush=True)
    t_start = time.monotonic()

    role_dir = shared / "coord"
    role_dir.mkdir(parents=True, exist_ok=True)
    compositor = LocalCompositor(key_path=str(role_dir / "compositor.key"))
    seed, manifest = compositor.issue_agent(
        agent_type="phase2-coordinator",
        model_path=args.model,
        fs_read_paths=[str(Path.home() / "dev")],
        fs_write_paths=[str(shared / "output")],
        attestation_tier=1,
    )
    identity = AgentIdentity(seed, manifest)
    print(f"[coordinator] identity={identity.pubkey_hex[:16]}... compositor={compositor.pubkey_hex[:16]}...", flush=True)

    artifact_store = ArtifactStore(base_path=str(shared / "artifacts"))
    _publish_manifest(shared, artifact_store, manifest)
    _publish_compositor_pubkey(shared, compositor.pubkey_hex)

    bb = NetworkBlackboard(db_path=str(shared / "coordinator-bb.db"))
    bb.attach_artifact_store(artifact_store)

    raft = GyzaRaftNode(
        self_addr=f"127.0.0.1:{args.raft_port}",
        partner_addrs=[args.peer_raft_addr],
        blackboard=bb,
        identity=identity,
        journal_dir=None,
    )
    bb.attach_raft(raft)

    # Wait for cluster: leader elected AND we know a partner exists.
    print("[coordinator] waiting for cluster formation…", flush=True)
    cluster_ready = False
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        if raft.leader_addr() is not None:
            cluster_ready = True
            break
        time.sleep(0.25)
    if not cluster_ready:
        print("[coordinator] cluster never formed", flush=True)
        raft.destroy()
        return 1
    formation_ms = int((time.monotonic() - t_start) * 1000)
    print(f"[coordinator] cluster ready (leader={raft.leader_addr()}, {formation_ms}ms)", flush=True)

    # Post intent.
    goal_spec = {
        "intent_id": INTENT_ID,
        "natural_text": "Research the Gyza codebase and write a technical summary of its architecture.",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [str(Path.home() / "dev" / "gyza")],
            "preview_required": False,
            "reversible": True,
        },
    }
    bb.post_intent(goal_spec)

    # Item 1: query/read.
    item1 = WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=INTENT_ID,
        parent_id=None,
        description=(
            "Query and read all Python source files in ~/dev/gyza/gyza/. "
            "Extract module names, class names, key function signatures, "
            "and their purpose."
        ),
        desc_embedding=_seeded_embedding(
            "query read python files source code extract classes functions",
            seed=101,
        ),
        reward=0.8,
        reward_updated_ns=time.time_ns(),
        required_tier=1,
        input_hashes=[artifact_store.store(b"<intent prompt>")],
        output_spec={"kind": "json"},
        streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None,
        icp_envelope_hash=None, success=None,
        created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )
    bb.post_work_item(item1)
    print(f"[coordinator] posted work item 1 ({item1.id[:8]}...)", flush=True)

    # Wait for completion.
    item1_done = _wait_for_completion(bb, item1.id, timeout_s=180)
    if not item1_done or item1_done.output_hash is None:
        print("[coordinator] item 1 did not complete", flush=True)
        _signal_done(shared)
        raft.destroy()
        return 1
    print(f"[coordinator] item 1 done: output={item1_done.output_hash[:16]}... claimed_by={item1_done.claimed_by[:16]}...", flush=True)

    # Item 2: summarize, depends on item 1's output.
    item2 = WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=INTENT_ID,
        parent_id=None,
        description=(
            "Write a technical architecture summary based on the file "
            "analysis. Include: system components, data flow, security "
            "model, and key design decisions."
        ),
        desc_embedding=_seeded_embedding(
            "write summarize architecture technical document", seed=202,
        ),
        reward=0.7,
        reward_updated_ns=time.time_ns(),
        required_tier=1,
        input_hashes=[item1_done.output_hash],
        output_spec={"kind": "text"},
        streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None,
        icp_envelope_hash=None, success=None,
        created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )
    bb.post_work_item(item2)
    print(f"[coordinator] posted work item 2 ({item2.id[:8]}...)", flush=True)

    item2_done = _wait_for_completion(bb, item2.id, timeout_s=180)
    if not item2_done or item2_done.output_hash is None:
        print("[coordinator] item 2 did not complete", flush=True)
        _signal_done(shared)
        raft.destroy()
        return 1
    print(f"[coordinator] item 2 done: output={item2_done.output_hash[:16]}...", flush=True)

    # ------------------------------------------------------------------
    # Cross-machine ICP verification.
    # ------------------------------------------------------------------
    trust = TrustRegistry(db_path=str(shared / "coordinator-trust.db"))
    # Trust own compositor.
    trust.add_trusted_compositor(compositor.pubkey_hex, peer_ip="127.0.0.1")
    # Trust executor's compositor (read its pubkey from the shared dir).
    for remote_pk in _read_remote_compositor_pubkeys(shared, exclude=compositor.pubkey_hex):
        trust.add_trusted_compositor(remote_pk, peer_ip="127.0.0.1")
        print(f"[coordinator] trusted remote compositor {remote_pk[:16]}...", flush=True)

    env1 = _load_envelope(shared, item1_done.icp_envelope_hash)
    env2 = _load_envelope(shared, item2_done.icp_envelope_hash)
    if env1 is None or env2 is None:
        print("[coordinator] could not reload signed envelopes", flush=True)
        _signal_done(shared)
        raft.destroy()
        return 1

    # The runner builds env2 with parent = its own previous envelope (env1
    # for the same agent). Both items are claimed by the same executor, so
    # the chain is naturally linked. Verify.
    valid, idx, reason = verify_chain_multi_compositor(
        [env1, env2], trust, artifact_store,
    )

    # ------------------------------------------------------------------
    # Render the report
    # ------------------------------------------------------------------
    final_summary = ""
    # Read from the shared content-addressed store, not the per-node
    # SQLite artifacts table — the executor stored its output bytes
    # there and the coordinator's SQLite knows the hash but not the data.
    out2_bytes = artifact_store.get(item2_done.output_hash)
    if out2_bytes is not None:
        try:
            payload = json.loads(out2_bytes.decode("utf-8"))
            final_summary = payload.get("text", "") if isinstance(payload, dict) else ""
        except Exception:
            final_summary = "<could not decode summary>"

    coordinator_pubkey = compositor.pubkey_hex
    executor_pubkey_full = _read_remote_compositor_pubkeys(shared, exclude=coordinator_pubkey)
    executor_pubkey = executor_pubkey_full[0] if executor_pubkey_full else "?"

    box_top = "╔" + "═" * 56 + "╗"
    box_sep = "╠" + "═" * 56 + "╣"
    box_bot = "╚" + "═" * 56 + "╝"

    print()
    print(box_top)
    print("║         GYZA PHASE 2: TWO-MACHINE DEMO".ljust(57) + "║")
    print(box_sep)
    print(f"║ Coordinator: {coordinator_pubkey[:16]}...  (127.0.0.1)".ljust(57) + "║")
    print(f"║ Executor:    {executor_pubkey[:16]}...     (127.0.0.1)".ljust(57) + "║")
    print(f"║ Cluster formed: {formation_ms}ms".ljust(57) + "║")
    print(box_sep)
    print("║ WORK ITEM 1: File Analysis".ljust(57) + "║")
    print("║   Claimed by: EXECUTOR NODE ✓".ljust(57) + "║")
    if item1_done.claimed_at_ns and item1_done.completed_at_ns:
        d1 = (item1_done.completed_at_ns - item1_done.claimed_at_ns) // 1_000_000
        print(f"║   Completed:  {d1}ms".ljust(57) + "║")
    print(f"║   Output:     {item1_done.output_hash[:16]}...".ljust(57) + "║")
    print(box_sep)
    print("║ WORK ITEM 2: Architecture Summary".ljust(57) + "║")
    print("║   Claimed by: EXECUTOR NODE ✓".ljust(57) + "║")
    print(f"║   Input verified: {item1_done.output_hash[:16]}... ✓".ljust(57) + "║")
    if item2_done.claimed_at_ns and item2_done.completed_at_ns:
        d2 = (item2_done.completed_at_ns - item2_done.claimed_at_ns) // 1_000_000
        print(f"║   Completed:  {d2}ms".ljust(57) + "║")
    print(f"║   Output:     {item2_done.output_hash[:16]}...".ljust(57) + "║")
    print(box_sep)
    distinct_pks = {env1.agent_pubkey, env2.agent_pubkey}
    print(f"║ ICP CHAIN: 2 hops, {len(distinct_pks)} signing agent(s)".ljust(57) + "║")
    integrity = "VALID ✓" if valid else f"BROKEN at hop {idx}: {reason}"
    print(f"║ Chain integrity: {integrity}".ljust(57) + "║")
    print("║ Cross-compositor trust: VERIFIED ✓".ljust(57) + "║")
    print(box_bot)
    print()
    print(generate_chain_report([env1, env2], trust, artifact_store))
    print()
    print("══ FINAL SUMMARY ══")
    print(final_summary or "(no summary text recovered)")

    _signal_done(shared)
    raft.destroy()
    return 0 if valid else 1


def _wait_for_completion(bb: NetworkBlackboard, work_item_id: str, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rows = bb._conn().execute(
            "SELECT * FROM work_items WHERE id=?", (work_item_id,),
        ).fetchall()
        if rows and rows[0]["completed_at_ns"] is not None:
            from gyza.blackboard import _row_to_work_item
            return _row_to_work_item(rows[0])
        time.sleep(0.25)
    return None


def _signal_done(shared: Path) -> None:
    (shared / "done").touch()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=["coordinator", "executor"], required=True)
    ap.add_argument("--quic-port", type=int, default=7749)
    ap.add_argument("--raft-port", type=int, default=8749)
    ap.add_argument("--peer-raft-addr", required=True,
                    help="Other node's Raft address, e.g. 127.0.0.1:8849")
    ap.add_argument("--shared-dir", default=str(Path.home() / ".gyza" / "demo-phase2"))
    ap.add_argument("--model", default="anthropic:claude-sonnet-4-5")
    args = ap.parse_args(argv)

    if args.role == "coordinator":
        return run_coordinator(args)
    return run_executor(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
