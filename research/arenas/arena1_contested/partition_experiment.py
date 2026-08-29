"""Arena 1's mechanism: what a PARTITION does to a distributed agent fleet.

Runs on loopback to establish the ZERO-LATENCY CONTROL and to prove the harness
can detect what it claims to. The same script drives the WAN deployment; only
the node addresses change.

THE SOUNDNESS QUESTION IT ISOLATES. `try_claim` is an atomic SQLite UPDATE
LOCALLY and only then publishes the claim by gossip. During a partition there
is no gossip, so both sides see the same unclaimed items and neither can learn
of the other's claim. If both execute, the same intent produced two signed
actions -- which for an irreversible action is exactly the H7 hazard.

The design isolates that: mirror the work FIRST, cut the link, THEN start both
rosters simultaneously. Both sides begin from an identical view of unclaimed
work with no way to coordinate, which is the worst case rather than an average
one.
"""
from __future__ import annotations
import json, os, secrets, sys, time, uuid
from pathlib import Path
os.environ.setdefault("GYZA_EMBEDDER", "stub")
import numpy as np
sys.path.insert(0, "/home/xan/dev/gyza")

from gyza.identity import AgentIdentity, LocalCompositor
from gyza.network.netd_client import GossipClient, NetdClient
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.roster import RunnerThreadRoster
from gyza.schema import EMBEDDING_DIM, WorkItem
from gyza.supervisor import RunnerSpec

BIN = "/home/xan/dev/gyza/netd/bin/gyza-netd"
PROJECT = "arena1-partition"


def boot(base: Path, i: int, port: int):
    d = base / f"n{i}"; d.mkdir(parents=True, exist_ok=True)
    k = d / "node.key"
    if not k.exists():
        k.write_bytes(secrets.token_bytes(32)); k.chmod(0o600)
    sock = str(d / "netd.sock"); c = NetdClient(socket_path=sock)
    # start_daemon RETURNS the Popen; close() shuts only the gRPC channel, so
    # discarding it orphans a ~36 MB daemon holding this fixed port -- which
    # makes the NEXT run fail on bind. Harmless to the measurement (orphans are
    # isolated+no-mdns and never join a later mesh) but a leak, and 24 were
    # found alive on this host on 2026-08-29.
    proc = c.start_daemon(socket_path=sock, binary_path=BIN, listen_port=port,
                          key_path=str(k), mdns=False, dht_mode="server",
                          isolated=True)
    for _ in range(60):
        try:
            return c, sock, c.get_node_info(), d, proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"node {i} never came up")


def roster_for(node_dir, bb, n, tag):
    comp = LocalCompositor(key_path=str(node_dir / "comp.key"))
    specs = []
    for i in range(n):
        seed, man = comp.issue_agent(
            agent_type=f"{tag}{i}", model_path="mock", fs_read_paths=[],
            fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
            attestation_tier=0)
        st = node_dir / f"ag{i}.json"
        st.write_text(json.dumps({"seed_hex": seed.hex(), "manifest": man}))
        specs.append(RunnerSpec(
            agent_id=AgentIdentity(seed, man).agent_id,
            agent_state_path=str(st), blackboard_path=str(node_dir / "bb.db"),
            memory_path=str(node_dir / f"m{i}"),
            spec_db_path=str(node_dir / f"s{i}.db"),
            artifact_store_path=str(node_dir / "cas"),
            poll_interval_s=0.3, min_reward=0.0, min_similarity=-1.0,
            sandboxed=False, executor_kind="mock", command_argv=None,
            model="none"))
    return RunnerThreadRoster(specs, blackboard=bb, poll_interval_s=2.0)


def env_of(bb, wid):
    r = bb._conn().execute(
        "SELECT icp_envelope_hash FROM work_items WHERE id=?", (wid,)).fetchone()
    return r["icp_envelope_hash"] if r else None


def n_signed(bb, ids):
    return sum(1 for i in ids if env_of(bb, i))


def wait_cut(ca, cb, timeout=15.0):
    """TRUTH PREDICATE IS THE PEER COUNT ON BOTH SIDES, never the absence of a
    connection event -- a 'partition' that only one side believes in is not one."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if len(ca.list_peers()) == 0 and len(cb.list_peers()) == 0:
            return True
        time.sleep(0.1)
    return False


def main() -> int:
    base = Path(sys.argv[1]); base.mkdir(parents=True, exist_ok=True)
    agents = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    items = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    ca, sa, ia, da, pa = boot(base, 1, 7870)
    cb, sb, ib, db, pb = boot(base, 2, 7871)
    bbA = NetworkBlackboard(str(da / "bb.db"))
    bbB = NetworkBlackboard(str(db / "bb.db"))
    ga, gb = GossipClient(sa), GossipClient(sb)
    lo = next(m for m in ib.listen_addrs if m.startswith("/ip4/127.0.0.1/"))
    addr = lo if "/p2p/" in lo else f"{lo}/p2p/{ib.peer_id}"
    assert ca.connect_peer(addr).success
    ga.join_project(PROJECT); gb.join_project(PROJECT)
    bbA.attach_gossip(ga, PROJECT, node_id=ia.compositor_pubkey)
    bbB.attach_gossip(gb, PROJECT, node_id=ib.compositor_pubkey)
    time.sleep(4)
    print(f"mesh formed: A={len(ca.list_peers())} B={len(cb.list_peers())} peer(s)")

    # ---- 1. mirror the work BEFORE cutting ---------------------------
    bbA.post_intent({"intent_id": PROJECT, "natural_text": "p",
                     "category": "system_task", "actions": [],
                     "authorization": {"resources": [], "preview_required": False,
                                       "reversible": True}})
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32); e[0] = 1.0
    ids = []
    for _ in range(items):
        w = WorkItem(id=str(uuid.uuid7()), lineage_root=PROJECT, parent_id=None,
            description="partition work", desc_embedding=e, reward=0.9,
            reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
            output_spec={"kind": "t"}, streaming_ok=False, claimed_by=None,
            claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
            completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
            success=None, created_at_ns=time.time_ns(), ttl_ns=3600*10**9)
        bbA.post_work_item(w); ids.append(w.id)
        # PACE THE POSTS. Measured 2026-08-25: posting in a tight loop loses
        # ~7% of gossip deltas on a healthy loopback mesh, and losses are never
        # recovered because the CRDT converges over deltas RECEIVED. A 5 ms gap
        # takes it to zero. Without this the harness measures its own burst
        # loss and calls it partition behaviour.
        time.sleep(0.01)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30 and len(bbB.get_by_lineage(PROJECT)) < items:
        time.sleep(0.2)
    mirrored = len(bbB.get_by_lineage(PROJECT))
    print(f"work mirrored to B: {mirrored}/{items} in {time.monotonic()-t0:.2f}s")
    assert mirrored == items, "the control failed: work never mirrored"

    # ---- 2. CUT, then start both rosters from an identical view -------
    ca.disconnect_peer(ib.peer_id)
    cut = wait_cut(ca, cb)
    print(f"\nPARTITION: peers 0 on both sides = {cut}")
    assert cut, "the cut is cosmetic; every number below would be void"

    rA = roster_for(da, bbA, agents, "a")
    rB = roster_for(db, bbB, agents, "b")
    rA.start(); rB.start()
    end = time.monotonic() + 45
    while time.monotonic() < end:
        if n_signed(bbA, ids) + n_signed(bbB, ids) >= items * 2:
            break
        time.sleep(0.5)
    sa_, sb_ = n_signed(bbA, ids), n_signed(bbB, ids)
    dup_during = sum(1 for i in ids
                     if env_of(bbA, i) and env_of(bbB, i)
                     and env_of(bbA, i) != env_of(bbB, i))
    print(f"during partition: A signed {sa_}/{items}, B signed {sb_}/{items}")
    print(f"  SAME item executed on BOTH sides with DIFFERENT envelopes: "
          f"{dup_during} ({dup_during/items:.0%})")

    # ---- 3. HEAL and time the first cross-node delivery ---------------
    heal = time.monotonic()
    ca.connect_peer(addr)
    probe = None
    ttr = None
    while time.monotonic() - heal < 90:
        pid = f"probe-{uuid.uuid4().hex[:8]}"
        w = WorkItem(id=str(uuid.uuid7()), lineage_root=PROJECT, parent_id=None,
            description=pid, desc_embedding=e, reward=0.1,
            reward_updated_ns=time.time_ns(), required_tier=3, input_hashes=[],
            output_spec={"kind": "probe"}, streaming_ok=False, claimed_by=None,
            claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
            completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
            success=None, created_at_ns=time.time_ns(), ttl_ns=3600*10**9)
        bbA.post_work_item(w)
        t1 = time.monotonic()
        seen = False
        while time.monotonic() - t1 < 2.0:
            if any(x.id == w.id for x in bbB.get_by_lineage(PROJECT)):
                seen = True; break
            time.sleep(0.05)
        if seen:
            ttr = time.monotonic() - heal
            probe = w.id
            break
    print(f"\nHEAL: first cross-node delivery after "
          f"{'TIMEOUT' if ttr is None else f'{ttr:.2f}s'}")

    time.sleep(8)
    rA.stop(timeout_s=20); rB.stop(timeout_s=20)

    # ---- 4. convergence ----------------------------------------------
    dup_final = sum(1 for i in ids
                    if env_of(bbA, i) and env_of(bbB, i)
                    and env_of(bbA, i) != env_of(bbB, i))
    agree = sum(1 for i in ids if env_of(bbA, i) == env_of(bbB, i))
    print(f"\nafter heal: boards AGREE on {agree}/{items} items; "
          f"{dup_final} still hold DIFFERENT envelopes")
    print(f"  -> LWW convergence did NOT erase the duplicate WORK: both "
          f"envelopes exist and both actions ran." if dup_final else
          "  -> boards converged with no divergent envelopes")
    for c in (ca, cb):
        try: c.close()
        except Exception: pass
    for pr in (pa, pb):                  # the channel is not the process
        try:
            pr.terminate(); pr.wait(timeout=10)
        except Exception:
            try: pr.kill()
            except Exception: pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
