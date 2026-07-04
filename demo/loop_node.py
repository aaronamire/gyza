"""
Two-MACHINE delegation with audited settlement — one command per side.

The loopback demo (`demo/two_node_loop.py`) runs both roles in one
process. This runs them as two independent nodes so a tester on another
machine can take one side. Same loop: a host delegates a bounded task, a
joiner executes it in a real sandbox, and the host INDEPENDENTLY audits
the returned work before a single credit settles.

On the host machine:

    python -m demo.loop_node host

It prints one or more dialable addresses. Share the one reachable from
the other machine (a LAN IP for the same network; a public IP with
UDP forwarded for the internet). Then, on the other machine:

    python -m demo.loop_node join /ip4/<host-ip>/udp/<port>/quic-v1/p2p/<peer-id>

The host posts a bounded task, the joiner runs it sandboxed and ships
the evidence back, the host audits and pays. Both print the outcome.

Needs the Go daemon (`gyza-netd`) on PATH or built at netd/bin, and
bubblewrap for a real sandbox (falls back to a labelled mock without it).
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from demo.single_machine_global import (  # noqa: E402
    NETD_BIN,
    _build_side,
    _kill_side,
    _wait_until,
)
from demo.two_node_loop import (  # noqa: E402
    _BUDGET_MB,
    _build_executor,
    _work_item,
)
from gyza.audit import audit_from_store, render_audit_report  # noqa: E402
from gyza.network.artifact_store import ArtifactStore  # noqa: E402

PROJECT_ID = "gyza-loop-demo"


def _bar(t: str) -> None:
    print("\n" + "─" * 68 + "\n" + t + "\n" + "─" * 68)


def _attach_cas(side) -> None:
    side.blackboard.attach_artifact_store(
        ArtifactStore(base_path=str(side.home / "cas")))


def _dialable_addrs(side) -> list[str]:
    info = side.netd.get_node_info()
    out, seen = [], set()
    st = side.netd.get_status()
    if getattr(st, "observed_addr", ""):
        a = f"{st.observed_addr.split('/p2p/')[0]}/p2p/{info.peer_id}"
        out.append(a); seen.add(a)
    for a in info.listen_addrs:
        full = f"{a.split('/p2p/')[0]}/p2p/{info.peer_id}"
        if full not in seen:
            out.append(full); seen.add(full)
    return out


def run_host(base: Path) -> int:
    import asyncio

    side = _build_side("host", base)
    try:
        _attach_cas(side)
        asyncio.run(side.cluster.start())

        _bar("HOST — delegating a bounded task, will audit before paying")
        print(f"  peer: {side.netd.get_node_info().peer_id}")
        print("\n  Share ONE of these with the other machine")
        print("  (LAN IP for same network; public IP + forwarded UDP for internet):")
        for a in _dialable_addrs(side):
            print(f"    {a}")
        print("\n  On the other machine, run:")
        print("    python -m demo.loop_node join <address-above>\n")

        side.gossip.join_project(PROJECT_ID)
        side.blackboard.attach_gossip(
            side.gossip, PROJECT_ID, node_id=side.compositor.pubkey_hex)

        print("  waiting for a joiner to connect…")
        if not _wait_until(lambda: side.netd.get_status().connected_peers >= 1,
                           timeout_s=300.0, poll_s=0.5):
            print("  ✗ no joiner connected within 5 minutes.", file=sys.stderr)
            return 3
        side.cluster.peer_registry.refresh()
        print("  ✓ joiner connected; letting the gossip mesh form…")
        time.sleep(3.0)

        intent_id = str(uuid.uuid7())
        side.blackboard.post_intent({
            "intent_id": intent_id, "natural_text": "delegate bounded work",
            "category": "system_task", "actions": [],
            "authorization": {"resources": [], "preview_required": False,
                              "reversible": True}})
        wi = _work_item(intent_id)
        exec_peers = side.netd.list_peers()
        exec_pk = exec_peers[0].compositor_pubkey if exec_peers else None
        settled_before = 0
        if exec_pk:
            settled_before = len([e for e in side.ledger.export_statement(exec_pk)
                                 if e["settled"]])
        side.blackboard.post_work_item(wi)
        print(f"  posted bounded task {wi.id[:8]}… — gossiping to joiner")

        _bar("HOST — auditing the returned work, then settling")
        got = _wait_until(
            lambda: exec_pk is not None and len([
                e for e in side.ledger.export_statement(exec_pk) if e["settled"]
            ]) > settled_before, timeout_s=60.0, poll_s=0.3)
        if not got:
            # exec_pk may have only been learned after connect; re-derive.
            peers = side.netd.list_peers()
            exec_pk = peers[0].compositor_pubkey if peers else exec_pk
            got = exec_pk is not None and len([
                e for e in side.ledger.export_statement(exec_pk) if e["settled"]
            ]) > 0
        if not got:
            print("  ✗ no settled entry — the joiner may not have executed, or")
            print("    the audit gate declined/deferred. Not paid.")
            return 5
        print("  ✓ audit passed on the host's own store → cosigned + paid")

        store = getattr(side.blackboard, "_artifact_store", None)
        envs = side.blackboard.reconstruct_dag(intent_id)
        report = audit_from_store(envs, store, require_closed=False)
        print()
        for ln in render_audit_report(
                report, title="HOST'S INDEPENDENT AUDIT").splitlines():
            print("  " + ln)

        _bar("HOST — VERDICT")
        bal = side.ledger.get_balance(exec_pk)
        print(f"  host balance with joiner: {bal:+.1f} (owes)")
        print("  The credit moved ONLY after the host independently audited")
        print("  the delivered work. Over-bound/tampered work is declined and")
        print("  never paid. Accountable · contained · audited-before-paid.")
        return 0 if report.valid else 6
    finally:
        _kill_side(side)


def run_join(base: Path, host_addr: str) -> int:
    import asyncio

    import shutil

    if "/p2p/" not in host_addr:
        print("host address must include /p2p/<peer-id> (copy it exactly from "
              "the host's output)", file=sys.stderr)
        return 2

    side = _build_side("join", base)
    runner = None
    try:
        _attach_cas(side)
        asyncio.run(side.cluster.start())

        _bar("JOIN — executing a delegated task in a sandbox")
        print(f"  peer: {side.netd.get_node_info().peer_id}")
        print(f"  dialing host {host_addr.split('/p2p/')[-1][:16]}…")
        conn = side.netd.connect_peer(host_addr)
        if not conn.success:
            print(f"  ✗ could not reach the host: {conn.error}", file=sys.stderr)
            return 3
        side.cluster.peer_registry.add(conn.verified_pubkey or "", conn.peer_id)
        print(f"  ✓ connected to host {conn.peer_id[:16]}…")

        side.gossip.join_project(PROJECT_ID)
        side.blackboard.attach_gossip(
            side.gossip, PROJECT_ID, node_id=side.compositor.pubkey_hex)
        time.sleep(2.0)
        side.cluster.peer_registry.refresh()

        bwrap = shutil.which("bwrap") is not None
        runner, agent = _build_executor(side, bwrap)
        # Chain a flag onto the envelope-signed hook so we know when this
        # node has actually executed + signed a delegated item (we don't
        # know the host's intent id to poll the blackboard for).
        signed = {"done": False}
        _prior = runner._on_envelope_signed  # noqa: SLF001 — internal hook by design

        def _mark(env):
            if _prior is not None:
                _prior(env)
            signed["done"] = True
        runner._on_envelope_signed = _mark  # noqa: SLF001
        runner.start()
        print(f"  executor online (agent {agent.agent_id[:16]}…, bounded to "
              f"{_BUDGET_MB} MB, {'real bwrap sandbox' if bwrap else 'mock'})")
        print("  waiting for the host to delegate a task…")

        # Run until we have signed + shipped one completed item, then a
        # short grace so settlement round-trips before we tear down.
        done = _wait_until(lambda: signed["done"], timeout_s=300.0, poll_s=0.3)
        if not done:
            print("  ✗ no task arrived within 5 minutes.", file=sys.stderr)
            return 4
        print("  ✓ claimed, ran in-sandbox, signed, and shipped the evidence")
        print("  the host is now auditing it and settling the credit.")
        time.sleep(6.0)
        _bar("JOIN — done")
        print("  You executed a bounded task for the host and proved it stayed")
        print("  in bounds. Check the host's terminal for the audit + payment.")
        return 0
    finally:
        if runner is not None:
            runner.stop()
        _kill_side(side)


def main() -> int:
    if not NETD_BIN.exists():
        print("gyza-netd not found — build it (make -C netd build) or put it "
              "on PATH.", file=sys.stderr)
        return 2
    args = sys.argv[1:]
    role = args[0] if args else ""
    base = Path("/tmp") / f"gyza-loopnode-{uuid.uuid7()}"
    if role == "host":
        return run_host(base)
    if role == "join" and len(args) >= 2:
        return run_join(base, args[1])
    print("usage:\n  python -m demo.loop_node host\n"
          "  python -m demo.loop_node join <host-multiaddr>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
