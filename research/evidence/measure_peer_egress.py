"""Measure REAL peer egress from a live two-daemon deployment.

WHY THIS EXISTS. `recommend_h3_rate.py` sizes an H3 level from the measured
INFERENCE floor (1,077 B/action, production `_executor`). It says nothing about
PEER traffic, and the peer figure sitting in `evidence.json` came from a mix
this project's own harness invented -- labelled
`attestable_share_OF_HARNESS_CHOSEN_MIX` and reported as UNTESTED precisely so
it could not later be quoted as a measurement.

So the level was about to be chosen from one measured component and one
imagined one. This measures the second: two real `gyza-netd` daemons on
loopback, a real gossip mesh, a real `NetworkBlackboard` cycle, and the egress
counted by the PRODUCTION recorder out of the append-only log.

WHAT IT CANNOT SAY, and one thing I first got wrong about that. My initial
caveat claimed these bytes are a FLOOR because gossip fans out to ~6 mesh
peers. THEY ARE NOT. `netd_client.py:1061` records ONE row per publish carrying
`proto.ByteSize()` -- the payload -- and its own comment says the site
understates PEER COUNT, not bytes. The measurand is "bytes this node
published", which does not scale with mesh degree, so the figure is accurate
for what H3 measures rather than a lower bound on it.

What it genuinely omits: `send_message` (settlement) and `publish_agent` (a DHT
republish every 30 minutes). Neither appeared here -- the economy is dormant
(TOKEN_IS_FAKE) and the republish interval dwarfs the run. The republish is
negligible per action at any real rate; settlement is per-transaction and would
add on top.
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NETD_BIN = REPO / "netd" / "bin" / "gyza-netd"
PROJECT_ID = "h3-egress-measurement"
ACTIONS = 40


def _boot(tmp: Path, name: str):
    from gyza.network.netd_client import NetdClient

    seed = tmp / f"{name}.key"
    seed.write_bytes(secrets.token_bytes(32))
    os.chmod(seed, 0o600)
    sock = tmp / f"{name}.sock"
    proc = NetdClient.start_daemon(
        isolated=True, socket_path=str(sock), binary_path=str(NETD_BIN),
        key_path=str(seed), listen_port=0, log_level="error",
        # `--dht-mode server`: ModeAuto stays Client forever on loopback and
        # the failure is silent (CLAUDE.md trip-wire).
        dht_mode="server", startup_timeout_s=10.0,
    )
    with NetdClient(str(sock)) as c:
        info = c.get_node_info()
    return proc, sock, info


def _kill(proc) -> None:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)


def main() -> int:
    if not NETD_BIN.exists():
        print(f"daemon not built at {NETD_BIN}; run `make -C netd build`")
        return 2

    import numpy as np

    from gyza.blackboard import Blackboard
    from gyza.containment.egress import EgressClass, EgressRecorder
    from gyza.network.netd_client import GossipClient, NetdClient
    from gyza.network.network_blackboard import NetworkBlackboard
    from gyza.schema import EMBEDDING_DIM, HLC, WorkItem

    tmp = Path(tempfile.mkdtemp(prefix="h3_peer_"))
    procA = procB = None
    try:
        procA, sockA, infoA = _boot(tmp, "A")
        procB, sockB, infoB = _boot(tmp, "B")

        # ONE blackboard holds both the work state and the egress log, so the
        # bytes counted are the ones the production recorder wrote.
        bbA = NetworkBlackboard(str(tmp / "A.db"))
        bbB = NetworkBlackboard(str(tmp / "B.db"))
        recA = EgressRecorder(Blackboard(str(tmp / "A.db")), attested_peers=None)

        gossipA = GossipClient(str(sockA), egress_recorder=recA)
        gossipB = GossipClient(str(sockB))

        loopback = next(m for m in infoB.listen_addrs
                        if m.startswith("/ip4/127.0.0.1/"))
        with NetdClient(str(sockA)) as ca:
            res = ca.connect_peer(f"{loopback}/p2p/{infoB.peer_id}")
            assert res.success, res.error

        gossipA.join_project(PROJECT_ID)
        gossipB.join_project(PROJECT_ID)
        bbA.attach_gossip(gossipA, PROJECT_ID, node_id=infoA.compositor_pubkey)
        bbB.attach_gossip(gossipB, PROJECT_ID, node_id=infoB.compositor_pubkey)
        # Gossipsub mesh formation: 10-15 s on a 2-node loopback mesh, and 5 s
        # is flaky (CLAUDE.md trip-wire).
        time.sleep(12.0)

        intent = "h3-egress-intent"
        bbA.post_intent({
            "intent_id": intent, "natural_text": "egress measurement",
            "category": "system_task", "actions": [],
            "authorization": {"resources": [], "preview_required": False,
                              "reversible": True}})

        hlc = HLC(node_id=infoA.compositor_pubkey)
        t0 = time.time()
        for i in range(ACTIONS):
            emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            emb[i % EMBEDDING_DIM] = 1.0
            w = WorkItem(
                id=f"item-{i:04d}-{secrets.token_hex(6)}",
                lineage_root=intent, parent_id=None,
                description=f"measured work item {i}",
                desc_embedding=emb, reward=0.5,
                reward_updated_ns=time.time_ns(), required_tier=0,
                input_hashes=[], output_spec={"kind": "test"},
                streaming_ok=False, claimed_by=None, claimed_at_ns=None,
                claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
                completed_at_ns=None, output_hash=None,
                icp_envelope_hash=None, success=None,
                created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9)
            bbA.post_work_item(w)
            bbA.try_claim(w.id, "agent_A", hlc)
        elapsed = time.time() - t0
        time.sleep(3.0)          # let in-flight publishes land

        log = Blackboard(str(tmp / "A.db"))
        by_channel = log.egress_by_channel_since(0)
        rows = log._conn().execute(
            "SELECT egress_class, channel, byte_count FROM egress_log"
        ).fetchall()

        mesh_bytes = sum(int(r["byte_count"] or 0) for r in rows
                         if r["egress_class"] in EgressClass.MESH_EXIT)
        mesh_sends = sum(1 for r in rows
                         if r["egress_class"] in EgressClass.MESH_EXIT)
        per_channel_bytes: dict[str, int] = {}
        for r in rows:
            if r["egress_class"] in EgressClass.MESH_EXIT:
                per_channel_bytes[r["channel"]] = (
                    per_channel_bytes.get(r["channel"], 0)
                    + int(r["byte_count"] or 0))

        INFERENCE_BPA = 1077.0        # measured, R-EVID Part B
        SANDBOX_APH = 3600 / 0.305    # measured sandbox ceiling
        peer_bpa = mesh_bytes / ACTIONS if ACTIONS else 0.0
        total_bpa = peer_bpa + INFERENCE_BPA

        result = {
            "actions": ACTIONS,
            "wall_seconds": round(elapsed, 2),
            "mesh_exit_sends": mesh_sends,
            "mesh_exit_bytes": mesh_bytes,
            "sends_per_action": mesh_sends / ACTIONS,
            "peer_bytes_per_action": peer_bpa,
            "inference_bytes_per_action_MEASURED_ELSEWHERE": INFERENCE_BPA,
            "total_bytes_per_action": total_bpa,
            "by_channel_count": by_channel,
            "by_channel_bytes": per_channel_bytes,
            "saturated_MB_per_hour_per_core": total_bpa * SANDBOX_APH / 1e6,
        }
        out = Path(__file__).parent / "peer_egress.json"
        out.write_text(json.dumps(result, indent=2, sort_keys=True))

        print(f"actions                 : {ACTIONS} in {elapsed:.1f}s")
        print(f"MESH_EXIT sends         : {mesh_sends} "
              f"({mesh_sends / ACTIONS:.2f}/action)")
        print(f"MESH_EXIT bytes         : {mesh_bytes:,} "
              f"({peer_bpa:,.0f} B/action)")
        print(f"by channel (count)      : {by_channel}")
        print(f"by channel (bytes)      : {per_channel_bytes}")
        print()
        print(f"peer      B/action      : {peer_bpa:>10,.0f}   MEASURED here")
        print(f"inference B/action      : {INFERENCE_BPA:>10,.0f}   "
              f"measured in R-EVID Part B")
        print(f"TOTAL     B/action      : {total_bpa:>10,.0f}")
        print(f"saturated MB/h per core : "
              f"{total_bpa * SANDBOX_APH / 1e6:>10.1f}")
        print()
        print("ATTESTABILITY, which decides how a level should be chosen:")
        print("  `is_attestable_channel` is True for send_message ALONE -- a")
        print("  gossip publish and a DHT put have no single destination, so")
        print("  'is the destination attested?' is not a well-formed question")
        print("  for them and they can NEVER be reclassified out of the exit")
        print("  count. This workload is 100% publish_delta, so 0% of the")
        print("  measured egress is reducible by wiring attestation.")
        print(f"\nwrote {out}")
        return 0
    finally:
        for p in (procA, procB):
            if p is not None:
                _kill(p)


if __name__ == "__main__":
    raise SystemExit(main())
