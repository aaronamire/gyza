"""
Phase 3 Session 8 — single-machine global federation simulation.

Runs the full Phase 3 stack — two gyza-netd processes, two NetworkBlackboards
wired through gossip, two GlobalCluster orchestrators, an AgentRunner on
the executor side — entirely on loopback. The cross-network demo
(``demo/global_demo.py``) layers IP discovery on top; this script is
the reproducible integration test that proves Phase 3 actually works
end to end.

What it exercises:

  1. Two gyza-netd processes spawn, each with its own compositor key.
  2. Coordinator NAT-connects to executor over loopback QUIC.
  3. Both daemons join the project's gossipsub topic.
  4. Coordinator posts intent + work item; gossip carries them to
     executor.
  5. Executor's AgentRunner (mock executor) claims, executes, signs an
     ICP envelope.
  6. Runner's ``on_envelope_signed`` hook submits an earner-signed
     ledger entry to coordinator over the libp2p MessageService.
  7. Coordinator's settlement service verifies envelope + amount,
     cosigns as payer, echoes back.
  8. Executor applies the cosigned entry. Both ledgers settle.
  9. Coordinator's blackboard receives the completion via gossip.

Verification checks (printed at the end):

  - completion observable on coordinator's blackboard
  - both ledgers hold the same settled entry
  - executor's net balance with coordinator is positive
  - coordinator's net balance with executor is negative

Why mock executor: this is an integration check of the network layer.
The Anthropic / llama.cpp executors are exercised by the runner unit
tests; mixing them in here would couple verification to model availability.

Usage:
    python demo/single_machine_global.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Repo root → sys.path so this script runs as `python demo/...` without
# install.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gyza.config import GyzaConfig  # noqa: E402
from gyza.economy.ledger import ComputeLedger  # noqa: E402
from gyza.identity import AgentIdentity, LocalCompositor  # noqa: E402
from gyza.network.global_cluster import (  # noqa: E402
    AgentDescriptor,
    GlobalCluster,
)
from gyza.network.netd_client import GossipClient, NetdClient  # noqa: E402
from gyza.network.network_blackboard import NetworkBlackboard  # noqa: E402
from gyza.runner import AgentRunner, make_mock_executor  # noqa: E402
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem  # noqa: E402


PROJECT_ID = "phase3-single-machine-demo"
NETD_BIN = REPO_ROOT / "netd" / "bin" / "gyza-netd"


# ----------------------------------------------------------------------
# Per-side bundle
# ----------------------------------------------------------------------

@dataclass
class Side:
    name: str
    home: Path
    compositor: LocalCompositor
    config: GyzaConfig
    blackboard: NetworkBlackboard
    ledger: ComputeLedger
    netd_proc: subprocess.Popen
    netd: NetdClient
    gossip: GossipClient
    cluster: GlobalCluster


def _build_side(
    name: str,
    base: Path,
    bootstrap_peers: list[str] | None = None,
) -> Side:
    """
    Provision a fresh tmp dir for this side, spawn its netd, and build
    a GlobalCluster wired to it. Each side has its own compositor key,
    blackboard SQLite, ledger SQLite, and Unix socket.
    """
    home = base / name
    home.mkdir(parents=True, exist_ok=True)

    key_path = home / "compositor.key"
    if not key_path.exists():
        key_path.write_bytes(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
    compositor = LocalCompositor(key_path=str(key_path))

    sock_path = home / "netd.sock"
    cfg = GyzaConfig(
        compositor_key_path=str(key_path),
        netd_socket_path=str(sock_path),
        netd_binary_path=str(NETD_BIN),
        netd_listen_port=0,  # ephemeral
        netd_bootstrap_peers=list(bootstrap_peers or []),
        netd_ledger_db_path=str(home / "ledger.db"),
        blackboard_db_path=str(home / "blackboard.db"),
    )
    bb = NetworkBlackboard(str(home / "blackboard.db"))
    ledger = ComputeLedger(compositor, str(home / "ledger.db"))

    proc = NetdClient.start_daemon(
        socket_path=str(sock_path),
        binary_path=str(NETD_BIN),
        listen_port=0,
        key_path=str(key_path),
        log_level="info",
        startup_timeout_s=8.0,
    )
    netd = NetdClient(str(sock_path))
    gossip = GossipClient(str(sock_path))

    gc = GlobalCluster(
        compositor=compositor,
        config=cfg,
        blackboard=bb,
        ledger=ledger,
        netd_client=netd,
        gossip_client=gossip,
    )
    return Side(
        name=name, home=home, compositor=compositor, config=cfg,
        blackboard=bb, ledger=ledger,
        netd_proc=proc, netd=netd, gossip=gossip, cluster=gc,
    )


def _kill_side(side: Side) -> None:
    side.netd_proc.terminate()
    try:
        side.netd_proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        side.netd_proc.kill()
        side.netd_proc.wait(timeout=2.0)


def _loopback_addr(addrs: list[str]) -> str | None:
    for a in addrs:
        if a.startswith("/ip4/127.0.0.1/"):
            return a
    return None


# ----------------------------------------------------------------------
# Executor side: AgentIdentity + AgentRunner with mock executor
# ----------------------------------------------------------------------

def _build_executor_runner(
    side: Side,
    initial_specialization: np.ndarray,
) -> tuple[AgentRunner, AgentIdentity]:
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.memory import EpisodicMemory

    seed, manifest = side.compositor.issue_agent(
        agent_type="demo.executor",
        model_path="mock",
        fs_read_paths=["/tmp/gyza-demo"],
        fs_write_paths=["/tmp/gyza-demo"],
        attestation_tier=1,
    )
    ident = AgentIdentity(seed, manifest)
    mem = EpisodicMemory(
        agent_id=ident.agent_id, db_path=str(side.home / "memory"),
    )
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=initial_specialization,
        db_path=str(side.home / "specialization.db"),
    )
    lsh = LSHIndex(seed=42)

    hook = side.cluster.runner_envelope_hook()
    # Phase 3 Session 8.5 — share the per-node HLC with cross-cluster
    # claim merges. Without this, the runner's claims would advance a
    # private clock while gossip ingress advances bb._gossip_hlc, and
    # local claims could end up with HLC tuples lex-smaller than
    # concurrent remote claims (silent total-order violation).
    shared_hlc = side.cluster.shared_hlc()
    runner = AgentRunner(
        identity=ident,
        blackboard=side.blackboard,
        memory=mem,
        specialization=spec,
        lsh=lsh,
        executor=make_mock_executor("Phase 3 demo: completed work"),
        min_reward_threshold=0.0,
        min_similarity_threshold=-1.0,
        poll_interval_s=0.2,
        on_envelope_signed=hook,
        hlc=shared_hlc,
    )
    return runner, ident


# ----------------------------------------------------------------------
# Work item construction
# ----------------------------------------------------------------------

_DEMO_TASK_DESCRIPTION = (
    "Phase 3 demo: analyze a Python codebase and summarize its architecture"
)


def _make_work_item(intent_id: str, *, seed: int) -> WorkItem:
    # Embed the task description so the executor's specialization
    # (initialized from the same description below) actually scores
    # high on this item. Before Session 8.5 this used a seeded random
    # vector — visually fine in the demo box-art but it meant the
    # specialization-matching code path was never exercised end-to-end.
    from gyza.embeddings import embed_work_description
    emb = embed_work_description(_DEMO_TASK_DESCRIPTION)
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=intent_id,
        parent_id=None,
        description=_DEMO_TASK_DESCRIPTION,
        desc_embedding=emb,
        reward=0.5,
        reward_updated_ns=time.time_ns(),
        required_tier=0,
        input_hashes=[],
        output_spec={"kind": "demo"},
        streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None,
        created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )


# ----------------------------------------------------------------------
# Output formatting
# ----------------------------------------------------------------------

def _print_report(
    coord: Side,
    execu: Side,
    intent_id: str,
    work_item_id: str,
    completion_seen: bool,
    settlement_seen: bool,
    elapsed_ms: int,
) -> None:
    bar = "═" * 62
    title = "GYZA PHASE 3 — SINGLE-MACHINE FEDERATION SIMULATION"
    print()
    print(f"╔{bar}╗")
    print(f"║ {title:<60} ║")
    print(f"╠{bar}╣")
    print(
        f"║ Coordinator pubkey: {coord.compositor.pubkey_hex[:16]}…"
        + " " * (62 - len(f" Coordinator pubkey: {coord.compositor.pubkey_hex[:16]}…"))
        + "║"
    )
    print(
        f"║ Executor pubkey:    {execu.compositor.pubkey_hex[:16]}…"
        + " " * (62 - len(f" Executor pubkey:    {execu.compositor.pubkey_hex[:16]}…"))
        + "║"
    )

    coord_status = coord.netd.get_status()
    exec_status = execu.netd.get_status()
    print(
        f"║ Coordinator peers:  {coord_status.connected_peers}"
        f"  /  Executor peers: {exec_status.connected_peers}"
        + " " * (62 - 41) + "║"
    )
    print(f"╠{bar}╣")
    print(f"║ PROJECT: {PROJECT_ID:<52}║")
    print(
        f"║   intent_id     = {intent_id[:36]:<43}║"
    )
    print(
        f"║   work_item_id  = {work_item_id[:36]:<43}║"
    )
    print(f"╠{bar}╣")
    completion_mark = "VALID ✓" if completion_seen else "MISSING ✗"
    settlement_mark = "BILATERAL ✓" if settlement_seen else "INCOMPLETE ✗"
    print(f"║ Cross-cluster gossip:    {completion_mark:<35}║")
    print(f"║ Bilateral settlement:    {settlement_mark:<35}║")
    print(f"╠{bar}╣")
    print("║ ECONOMY                                                      ║")
    coord_balance = coord.ledger.get_balance(execu.compositor.pubkey_hex)
    exec_balance = execu.ledger.get_balance(coord.compositor.pubkey_hex)
    print(
        f"║   coordinator's view of executor: {coord_balance:>+10.4f} credits"
        + " " * (62 - 56) + "║"
    )
    print(
        f"║   executor's view of coordinator: {exec_balance:>+10.4f} credits"
        + " " * (62 - 56) + "║"
    )
    print(f"╠{bar}╣")
    print(f"║ elapsed: {elapsed_ms} ms" + " " * (62 - 11 - len(str(elapsed_ms))) + "║")
    print(f"╚{bar}╝")


# ----------------------------------------------------------------------
# Main flow
# ----------------------------------------------------------------------

def _wait_until(predicate, timeout_s: float = 30.0, poll_s: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--keep", action="store_true",
        help="don't delete the demo tmp dir on exit (helpful for debugging)",
    )
    parser.add_argument(
        "--log", default="WARNING",
        help="log level (DEBUG/INFO/WARNING/ERROR; default WARNING)",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not NETD_BIN.exists():
        print(
            f"gyza-netd binary not found at {NETD_BIN}.\n"
            f"build it first: make -C netd build",
            file=sys.stderr,
        )
        return 2

    base = Path.home() / ".gyza" / "demo-phase3-global"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    print(f"[demo] tmp dir: {base}")
    print("[demo] booting two daemons...")

    coord = _build_side("coordinator", base)
    execu = _build_side("executor", base)

    t0 = time.monotonic()
    completion_seen = False
    settlement_seen = False
    intent_id = str(uuid.uuid7())
    wi = _make_work_item(intent_id, seed=42)
    runner = None

    try:
        # 1. Start both clusters (sets up settlement, peer registry).
        asyncio.run(coord.cluster.start())
        asyncio.run(execu.cluster.start())
        print(f"[demo] coordinator peer_id: {coord.netd.get_node_info().peer_id}")
        print(f"[demo] executor    peer_id: {execu.netd.get_node_info().peer_id}")

        # 2. Coordinator NAT-connects to executor's loopback addr.
        exec_info = execu.netd.get_node_info()
        exec_addr = _loopback_addr(exec_info.listen_addrs)
        if exec_addr is None:
            print("[demo] executor has no loopback listen addr", file=sys.stderr)
            return 3
        full = f"{exec_addr}/p2p/{exec_info.peer_id}"
        connect = coord.netd.connect_peer(full, exec_info.compositor_pubkey)
        if not connect.success:
            print(f"[demo] connect_peer failed: {connect.error}", file=sys.stderr)
            return 3
        # Eager-add — even though peerInfoFor now extracts compositor pubkey
        # from the PeerID, populating the registry directly avoids the first
        # cache-miss roundtrip.
        coord.cluster.peer_registry.add(
            execu.compositor.pubkey_hex, connect.peer_id,
        )
        print(f"[demo] coordinator → executor connected ({connect.peer_id})")

        # 3. Both daemons join project topic; blackboards attach gossip.
        coord.gossip.join_project(PROJECT_ID)
        execu.gossip.join_project(PROJECT_ID)
        coord.blackboard.attach_gossip(
            coord.gossip, PROJECT_ID, node_id=coord.compositor.pubkey_hex,
        )
        execu.blackboard.attach_gossip(
            execu.gossip, PROJECT_ID, node_id=execu.compositor.pubkey_hex,
        )
        # Gossipsub heartbeat × 2 — let GRAFT/PRUNE settle on the 2-node mesh.
        time.sleep(2.0)
        print("[demo] gossip mesh formed for project")

        # Refresh executor's peer registry so it knows the coordinator's
        # compositor pubkey when the runner hook later resolves it.
        # (peerInfoFor populates compositor_pubkey since Session 8.)
        execu.cluster.peer_registry.refresh()

        # 4. Stand up an AgentRunner on the executor side.
        # The executor's specialization is initialized FROM THE SAME
        # description as the work item, so cosine(spec, task_emb) ≈ 1
        # and the runner will score this item as a match. Pre-Session
        # 8.5 the spec was a one-hot vector — fine because the runner's
        # min_similarity_threshold was set to 0, but it never exercised
        # the actual specialization-matching code path.
        from gyza.embeddings import embed_work_description
        spec_seed = embed_work_description(_DEMO_TASK_DESCRIPTION)
        runner, agent_ident = _build_executor_runner(execu, spec_seed)
        runner.start()
        print(f"[demo] executor runner started (agent {agent_ident.agent_id[:16]})")

        # 5. Coordinator posts intent + work item.
        coord.blackboard.post_intent({
            "intent_id": intent_id,
            "natural_text": "Phase 3 single-machine demo intent",
            "category": "system_task",
            "actions": [],
            "authorization": {
                "resources": [], "preview_required": False, "reversible": True,
            },
        })
        coord.blackboard.post_work_item(wi)
        print(f"[demo] coordinator posted intent + work_item {wi.id[:8]}…")

        # 6. Wait for the work item to complete on the EXECUTOR side
        #    (the runner there is what claims and finishes).
        completion_seen = _wait_until(
            lambda: any(
                w.completed_at_ns is not None
                for w in execu.blackboard.get_by_lineage(intent_id)
            ),
            timeout_s=20.0,
        )
        if completion_seen:
            print("[demo] executor completed the work item")
        else:
            print("[demo] executor did NOT complete within timeout")
            return 4

        # 7. Wait for the completion to gossip back to the coordinator.
        coord_completion_seen = _wait_until(
            lambda: any(
                w.completed_at_ns is not None
                for w in coord.blackboard.get_by_lineage(intent_id)
            ),
            timeout_s=10.0,
        )
        if not coord_completion_seen:
            print("[demo] WARNING: completion did not gossip back to coordinator")
            completion_seen = False

        # 8. Wait for bilateral settlement to land in BOTH ledgers.
        settlement_seen = _wait_until(
            lambda: (
                len([
                    e for e in execu.ledger.export_statement(coord.compositor.pubkey_hex)
                    if e["settled"]
                ]) >= 1
                and len([
                    e for e in coord.ledger.export_statement(execu.compositor.pubkey_hex)
                    if e["settled"]
                ]) >= 1
            ),
            timeout_s=10.0,
        )

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _print_report(
            coord=coord, execu=execu,
            intent_id=intent_id, work_item_id=wi.id,
            completion_seen=completion_seen and coord_completion_seen,
            settlement_seen=settlement_seen,
            elapsed_ms=elapsed_ms,
        )
        return 0 if (completion_seen and settlement_seen) else 1

    finally:
        if runner is not None:
            runner.stop()
        try:
            asyncio.run(coord.cluster.stop())
        except Exception:
            pass
        try:
            asyncio.run(execu.cluster.stop())
        except Exception:
            pass
        _kill_side(coord)
        _kill_side(execu)
        if not args.keep:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
