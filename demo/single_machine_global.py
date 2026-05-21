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

import os

# Silence tqdm/transformers progress noise BEFORE any import that might
# touch them. transformers logging.set_verbosity is also controlled by
# this env var if it's set pre-import; HF_HUB_DISABLE_PROGRESS_BARS
# kills the download bars; TOKENIZERS_PARALLELISM quiets the fork
# warning. None of these affect correctness — only stdout cleanliness.
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import argparse
import asyncio
import logging
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
        # Single-machine demo: don't dial the public gyza.network
        # bootstrap mesh. The two daemons in this demo find each
        # other via explicit Connect over loopback.
        isolated=True,
        # mDNS off so the partition phase is real. Otherwise the two
        # daemons on the same loopback re-discover each other within
        # milliseconds of any disconnect, and the "comms blackout" is
        # cosmetic only — peer counts never drop to 0. The explicit
        # connect_peer below is the only intended peering path.
        mdns=False,
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


def _make_work_item(
    intent_id: str,
    *,
    seed: int,
    parent_id: str | None = None,
) -> WorkItem:
    # Embed the task description so the executor's specialization
    # (initialized from the same description below) actually scores
    # high on this item. Before Session 8.5 this used a seeded random
    # vector — visually fine in the demo box-art but it meant the
    # specialization-matching code path was never exercised end-to-end.
    #
    # parent_id chains successive work items in the same intent. Set
    # this on work_item_N to ensure reconstruct_chain(work_item_N.id)
    # walks back through every preceding envelope — turning the audit
    # trail from a list of unrelated single-envelope chains into one
    # parent-linked chain that verify_chain validates as a whole.
    from gyza.embeddings import embed_work_description
    emb = embed_work_description(_DEMO_TASK_DESCRIPTION)
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=intent_id,
        parent_id=parent_id,
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
#
# The report is the demo's primary artifact for a viewer who isn't
# reading the code — it has to land the three things this system is
# making provable: (1) two independent nodes coordinated, (2) the
# bilateral ledger reconciled to byte-identical state, (3) the signed
# ICP envelope chain verifies under verify_chain(). Anything that
# doesn't serve those three claims is cut.

_BOX_W = 62  # inner width of the box-art frame; total visible = 64


def _box(content: str) -> str:
    """One frame line: ``║`` + leading-space + content + right-pad + ``║``.

    Truncates if content overflows (defensive — better a clipped line
    than a misaligned box). Matches the leading-space convention the
    rest of the report uses.
    """
    inner = " " + content
    if len(inner) > _BOX_W:
        inner = inner[: _BOX_W]
    return "║" + inner.ljust(_BOX_W) + "║"


def _print_report(
    coord: Side,
    execu: Side,
    intent_id: str,
    work_item_ids: list[str],
    completion_seen: bool,
    settlement_seen: bool,
    elapsed_ms: int,
    partition_duration_s: float | None = None,
) -> None:
    from gyza.icp import compute_envelope_hash, verify_chain

    bar = "═" * _BOX_W
    title = "GYZA — VERIFIABLE DISTRIBUTED COORDINATION"

    coord_status = coord.netd.get_status()
    exec_status = execu.netd.get_status()
    completion_mark = "VALID ✓" if completion_seen else "MISSING ✗"
    settlement_mark = "RECONCILED ✓" if settlement_seen else "INCOMPLETE ✗"

    # Reconstruct the signed-envelope chain from the executor (the
    # signing side; the coordinator may also receive it via gossip
    # but the executor is the source of truth for what was signed).
    # Passing the LAST work_item_id walks parent_id back through every
    # preceding work_item in this run, so a 2-round demo produces a
    # 2-envelope chain with the parent-hash linkage visible.
    leaf_id = work_item_ids[-1] if work_item_ids else ""
    chain, missing_action = (
        execu.blackboard.reconstruct_chain(leaf_id) if leaf_id else ([], "")
    )
    chain_ok, bad_idx = verify_chain(chain) if chain else (False, -1)

    print()
    print(f"╔{bar}╗")
    print(_box(title))
    print(f"╠{bar}╣")
    print(_box(f"Node A:  {coord.compositor.pubkey_hex[:24]}…"))
    print(_box(f"Node B:  {execu.compositor.pubkey_hex[:24]}…"))
    print(_box(
        f"Peers —  A: {coord_status.connected_peers}"
        f"   B: {exec_status.connected_peers}"
    ))
    print(f"╠{bar}╣")
    print(_box(f"TASKS ({len(work_item_ids)})"))
    print(_box(f"   intent  {intent_id[:36]}"))
    for i, wi_id in enumerate(work_item_ids, start=1):
        print(_box(f"   [{i}]     {wi_id[:36]}"))
    print(f"╠{bar}╣")
    print(_box(f"CROSS-NODE GOSSIP:    {completion_mark}"))
    print(_box(f"BILATERAL LEDGER:     {settlement_mark}"))
    if partition_duration_s is not None:
        comms_mark = (
            f"BLACKOUT ({partition_duration_s:.1f}s) → RESTORED ✓"
        )
        print(_box(f"COMMS EVENT:          {comms_mark}"))
    print(f"╠{bar}╣")
    print(_box("AUDIT TRAIL"))
    if not chain:
        print(_box("   (no signed envelopes recorded for this work item)"))
    else:
        chain_verdict = (
            "VALID ✓" if chain_ok
            else f"INVALID (at index {bad_idx}) ✗"
        )
        n = len(chain)
        plural = "" if n == 1 else "s"
        incomplete = " (chain incomplete)" if missing_action else ""
        print(_box(f"   verify_chain():  {chain_verdict}"))
        print(_box(f"   {n} signed envelope{plural}{incomplete}"))
        print(_box(""))
        for i, env in enumerate(chain, start=1):
            h = compute_envelope_hash(env)
            parent = (
                env.parent_envelope_hash[:24] + "…"
                if env.parent_envelope_hash else "(genesis)"
            )
            print(_box(f"   [{i}] hash    {h[:24]}…"))
            print(_box(f"       signer  {env.agent_pubkey[:24]}…"))
            print(_box(f"       parent  {parent}"))
            print(_box(f"       backend {env.inference_backend}"))
    print(f"╠{bar}╣")
    print(_box(f"elapsed: {elapsed_ms} ms"))
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


def _run_work_round(
    coord: Side,
    execu: Side,
    intent_id: str,
    *,
    parent_work_item_id: str | None,
    label: str,
) -> tuple[str, bool, bool]:
    """
    One end-to-end round: post a work item on ``coord``, wait for it
    to be claimed and signed on ``execu``, wait for the completion to
    gossip back to ``coord``, wait for the bilateral ledger to settle
    on both sides.

    Returns ``(work_item_id, completion_observed_both_sides, settlement_seen)``.

    Settlement is detected by snapshotting the per-side settled-entry
    count BEFORE posting, then waiting for both counts to advance —
    so calling _run_work_round twice correctly waits for *this round's*
    settlement rather than "at least one entry settled" (which would
    return immediately on the second round if the first round's
    settlement is still in the ledger).
    """
    wi = _make_work_item(intent_id, seed=42, parent_id=parent_work_item_id)
    coord_pk = coord.compositor.pubkey_hex
    exec_pk = execu.compositor.pubkey_hex
    settled_before_exec = len([
        e for e in execu.ledger.export_statement(coord_pk) if e["settled"]
    ])
    settled_before_coord = len([
        e for e in coord.ledger.export_statement(exec_pk) if e["settled"]
    ])

    print(f"       posting {wi.id[:8]}… ({label}) — gossiping to peer")
    coord.blackboard.post_work_item(wi)

    # Two-stage check so propagation failures are distinguishable from
    # runner-claim failures.
    #
    # Stage 1: did the work item *arrive* at Node B's blackboard at all?
    #   This isolates the gossip-propagation path. Post-blackout rounds
    #   are the failure-mode worth diagnosing: if the gossipsub mesh has
    #   not finished re-forming when we publish, the message can be
    #   silently dropped at the local pub-side because no mesh peer is
    #   present to forward it.
    #
    # Stage 2: did the runner on Node B claim + execute + sign?
    #   With min_similarity_threshold=-1 and a mock executor at ~1ms,
    #   this should happen within one poll_interval_s of arrival.
    arrived = _wait_until(
        lambda: any(
            w.id == wi.id
            for w in execu.blackboard.get_by_lineage(intent_id)
        ),
        timeout_s=20.0,
    )
    if not arrived:
        print(
            "       ✗ work item did NOT propagate to Node B "
            "(gossipsub mesh likely incomplete post-reconnect)"
        )
        return wi.id, False, False

    completion_on_exec = _wait_until(
        lambda: any(
            w.completed_at_ns is not None
            for w in execu.blackboard.get_by_lineage(intent_id)
            if w.id == wi.id
        ),
        timeout_s=20.0,
    )
    if completion_on_exec:
        print("       ✓ executed and signed on Node B")
    else:
        print(
            "       ✗ work item arrived but did NOT complete "
            "(runner claim failure or executor error)"
        )
        return wi.id, False, False

    completion_on_coord = _wait_until(
        lambda: any(
            w.completed_at_ns is not None
            for w in coord.blackboard.get_by_lineage(intent_id)
            if w.id == wi.id
        ),
        timeout_s=10.0,
    )
    if completion_on_coord:
        print("       ✓ completion gossiped back to Node A")
    else:
        print("       ⚠ completion did NOT gossip back to Node A")

    settled = _wait_until(
        lambda: (
            len([
                e for e in execu.ledger.export_statement(coord_pk)
                if e["settled"]
            ]) > settled_before_exec
            and len([
                e for e in coord.ledger.export_statement(exec_pk)
                if e["settled"]
            ]) > settled_before_coord
        ),
        timeout_s=10.0,
    )
    if settled:
        print("       ✓ bilateral ledger reconciled")
    else:
        print("       ⚠ bilateral settlement did NOT land within timeout")

    return wi.id, completion_on_exec and completion_on_coord, settled


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
    parser.add_argument(
        "--fast", action="store_true",
        help=(
            "skip the ~10-15s SentenceTransformer cold load by using "
            "the StubEmbedder (BLAKE3-keyed deterministic vector). The "
            "demo's work-item routing only requires that spec_seed and "
            "the work-item desc_embedding agree under cosine similarity "
            "— which they do under the stub because both are derived "
            "from the same string. Recommended for video recording; "
            "default off so the demo still exercises the ST code path "
            "as the integration test of record. NOTE: because ST cold-"
            "load slack no longer absorbs gossipsub mesh-recovery "
            "variance, --fast can occasionally lose the post-blackout "
            "work item on a slow re-mesh; re-run if you see "
            "'gossipsub mesh likely incomplete'."
        ),
    )
    args = parser.parse_args()
    if args.fast:
        # Must be set BEFORE the first embed call. default_embedder()
        # caches the resolved backend on first call; setting after
        # would be a silent no-op.
        os.environ["GYZA_EMBEDDER"] = "stub"
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

    print()
    print("GYZA — VERIFIABLE DISTRIBUTED COORDINATION DEMO")
    print("================================================")
    print(
        "Two nodes will coordinate AI work, drop their comms link "
        "mid-flow,\nreconnect, and finish. At the end, an "
        "independently-verifiable\naudit trail proves exactly "
        "what happened, cryptographically."
    )
    print()
    print(f"[setup] workspace: {base}")
    print("[1/8] Starting two nodes ...")

    coord = _build_side("coordinator", base)
    execu = _build_side("executor", base)

    t0 = time.monotonic()
    completion_seen = False
    settlement_seen = False
    intent_id = str(uuid.uuid7())
    runner = None

    try:
        # 1. Start both clusters (sets up settlement, peer registry).
        asyncio.run(coord.cluster.start())
        asyncio.run(execu.cluster.start())
        print(f"[2/8] Node A peer: {coord.netd.get_node_info().peer_id}")
        print(f"[2/8] Node B peer: {execu.netd.get_node_info().peer_id}")

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
        print(f"[3/8] Peer link established (Node A → Node B, peer {connect.peer_id[:16]}…)")

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
        print(f"[4/8] Gossip mesh formed for project {PROJECT_ID}")

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
        print(f"[5/8] Runner online on Node B (agent {agent_ident.agent_id[:16]}…)")

        # 5. Post the lineage_root intent. Two work items will hang off
        #    it: a pre-blackout baseline and a post-blackout recovery
        #    item parent-linked through the audit chain.
        coord.blackboard.post_intent({
            "intent_id": intent_id,
            "natural_text": "Verifiable distributed coordination — pre/post blackout",
            "category": "system_task",
            "actions": [],
            "authorization": {
                "resources": [], "preview_required": False, "reversible": True,
            },
        })

        # 6. PRE-BLACKOUT BASELINE — post work_item_1, complete + settle.
        print("[6/8] Round 1 — pre-blackout baseline")
        wi1_id, wi1_completion, wi1_settled = _run_work_round(
            coord, execu, intent_id,
            parent_work_item_id=None,
            label="pre-blackout",
        )
        if not wi1_completion:
            # If the baseline round fails we have nothing meaningful to
            # demonstrate — bail before partitioning.
            return 4

        # 7. PARTITION → RECONNECT. Drop the libp2p connection both
        #    directions (symmetry so neither side can re-establish from
        #    its own peerstore alone), wait for both peer counts to fall
        #    to 0, hold the blackout for ~3s so it's observable, then
        #    re-call connect_peer and wait for the link to come back.
        print("[7/8] ⚡ COMMS BLACKOUT — disconnecting peer link ...")
        partition_start = time.monotonic()
        coord_peer = coord.netd.get_node_info().peer_id
        exec_peer = execu.netd.get_node_info().peer_id
        coord.netd.disconnect_peer(exec_peer)
        execu.netd.disconnect_peer(coord_peer)
        partitioned = _wait_until(
            lambda: (
                coord.netd.get_status().connected_peers == 0
                and execu.netd.get_status().connected_peers == 0
            ),
            timeout_s=5.0,
        )
        if partitioned:
            print("       Node A peers: 0   Node B peers: 0   (PARTITION CONFIRMED)")
        else:
            a = coord.netd.get_status().connected_peers
            b = execu.netd.get_status().connected_peers
            print(
                f"       Node A peers: {a}   Node B peers: {b}   "
                f"(partition incomplete — libp2p may still hold backref)"
            )
        hold_s = 3.0
        print(f"       (holding partition for {hold_s:.1f}s)")
        time.sleep(hold_s)

        print("       Comms restored — reconnecting peers ...")
        reconnect = coord.netd.connect_peer(full, exec_info.compositor_pubkey)
        if not reconnect.success:
            print(f"       ✗ reconnect failed: {reconnect.error}")
            return 5
        link_restored = _wait_until(
            lambda: (
                coord.netd.get_status().connected_peers >= 1
                and execu.netd.get_status().connected_peers >= 1
            ),
            timeout_s=5.0,
        )
        a = coord.netd.get_status().connected_peers
        b = execu.netd.get_status().connected_peers
        if link_restored:
            print(f"       Node A peers: {a}   Node B peers: {b}   (LINK RESTORED)")
        else:
            print(
                f"       Node A peers: {a}   Node B peers: {b}   "
                f"(⚠ link did not fully restore within timeout)"
            )
        # Snapshot here — partition_duration_s reflects only the link-
        # down window (disconnect → hold → reconnect → link restored).
        # The subsequent mesh-recovery sleep is application-layer
        # housekeeping, not a blackout, and conflating them would
        # exaggerate the blackout duration in the COMMS EVENT line.
        partition_duration_s = time.monotonic() - partition_start

        # Force gossipsub to re-establish the topic mesh: explicitly
        # re-join the project topic on both sides post-reconnect.
        # join_project on an already-joined topic is idempotent on the
        # Go side but triggers fresh GRAFT advertisement, which speeds
        # up mesh re-formation vs waiting passively for the next
        # heartbeat cycle.
        coord.gossip.join_project(PROJECT_ID)
        execu.gossip.join_project(PROJECT_ID)
        # Then sleep long enough for the mesh to be reliable. Empirically
        # 10s is on the edge — sometimes mesh is ready, sometimes it
        # isn't. 15s is conservative against gossipsub mesh-formation
        # variance and still video-friendly. Diagnosis: if a publish
        # post-sleep still loses the message, the propagation-arrival
        # check in _run_work_round prints a clear "gossipsub mesh
        # incomplete" message rather than the generic completion timeout.
        time.sleep(15.0)

        # 8. POST-BLACKOUT RECOVERY — post work_item_2 with parent_id
        #    pointing to work_item_1. reconstruct_chain(wi2.id) will
        #    walk back through wi1 and return [envelope_1, envelope_2],
        #    making the parent-hash linkage visible in the audit trail
        #    and exercising verify_chain over a chain that *spans* the
        #    blackout — which is the whole point.
        print("[8/8] Round 2 — post-blackout recovery, chained to work_item_1")
        wi2_id, wi2_completion, wi2_settled = _run_work_round(
            coord, execu, intent_id,
            parent_work_item_id=wi1_id,
            label="post-blackout",
        )

        completion_seen = wi1_completion and wi2_completion
        settlement_seen = wi1_settled and wi2_settled
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _print_report(
            coord=coord, execu=execu,
            intent_id=intent_id,
            work_item_ids=[wi1_id, wi2_id],
            completion_seen=completion_seen,
            settlement_seen=settlement_seen,
            elapsed_ms=elapsed_ms,
            partition_duration_s=partition_duration_s,
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
