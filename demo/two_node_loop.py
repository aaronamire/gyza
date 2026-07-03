"""
Two-node delegation with AUDITED settlement — the loop, on real daemons.

This is the networked counterpart to the single-node `gyza run`/`exec`
story: one node delegates a *bounded* task to a second node it does not
trust, the second node executes it in a real sandbox and signs the
result, and — the point — the first node INDEPENDENTLY AUDITS the
returned work before a single credit changes hands. Payment is not a
handshake; it is the output of an audit the payer runs itself.

What makes this different from `demo/single_machine_global.py` (which
demonstrates DDIL partition tolerance) is that here both nodes attach a
content-addressed artifact store, which turns the settlement audit gate
ON. The earner ships the output artifact + agent manifest alongside the
ledger entry; the payer absorbs them, re-runs the real
`audit_provenance`, and cosigns ONLY if it passes. An over-bound or
tampered result would be declined and disputed — never paid (that
branch is pinned by tests in `tests/test_settlement.py`).

Run:
    python -m demo.two_node_loop           # real bwrap sandbox if present
    python demo/two_node_loop.py

Needs the Go daemon (`gyza-netd`) on PATH or built at netd/bin. No
public network — the two daemons find each other over loopback.
"""
from __future__ import annotations

import shutil
import sys
import time
import uuid
from pathlib import Path

# Reuse the daemon/cluster plumbing from the Phase-3 demo of record.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from demo.single_machine_global import (  # noqa: E402
    NETD_BIN,
    _build_side,
    _kill_side,
    _loopback_addr,
    _wait_until,
)
from gyza.audit import audit_from_store, render_audit_report  # noqa: E402
from gyza.identity import AgentIdentity  # noqa: E402
from gyza.network.artifact_store import ArtifactStore  # noqa: E402
from gyza.runner import AgentRunner, make_mock_executor  # noqa: E402
from gyza.schema import EMBEDDING_DIM, WorkItem  # noqa: E402

PROJECT_ID = "gyza-two-node-loop"
_SANDBOX_WORKDIR = "/tmp/gyza-demo"
_BUDGET_MB = 512


def _bar(title: str) -> None:
    print("\n" + "─" * 68)
    print(title)
    print("─" * 68)


def _build_executor(side, bwrap: bool):
    """An AgentRunner whose executor runs bounded. With bwrap present the
    artifact carries a REAL enforcement record (the audit checks the work
    stayed within its 512 MB grant); without it, a labelled mock so the
    demo still runs (the audit then verifies accountability + binding)."""
    import numpy as np

    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.memory import EpisodicMemory

    seed, manifest = side.compositor.issue_agent(
        agent_type="loop.executor", model_path="mock",
        fs_read_paths=[_SANDBOX_WORKDIR], fs_write_paths=[_SANDBOX_WORKDIR],
        memory_limit_mb=_BUDGET_MB, attestation_tier=1,
    )
    ident = AgentIdentity(seed, manifest)

    if bwrap:
        from gyza.sandbox.config import sandbox_config_from_manifest
        from gyza.sandbox.executor import make_sandboxed_executor
        Path(_SANDBOX_WORKDIR).mkdir(parents=True, exist_ok=True)
        scfg = sandbox_config_from_manifest(manifest)
        executor = make_sandboxed_executor(
            "gyza.runner:make_mock_executor",
            init_kwargs={"response": "two-node loop: bounded work complete"},
            config=scfg,
        )
    else:
        executor = make_mock_executor("two-node loop: work complete (mock)")

    spec_v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    spec_v[0] = 1.0
    runner = AgentRunner(
        identity=ident,
        blackboard=side.blackboard,
        memory=EpisodicMemory(agent_id=ident.agent_id,
                              db_path=str(side.home / "memory")),
        specialization=SpecializationTracker(
            agent_id=ident.agent_id, initial_embedding=spec_v,
            db_path=str(side.home / "spec.db")),
        lsh=LSHIndex(seed=42),
        executor=executor,
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        poll_interval_s=0.2,
        on_envelope_signed=side.cluster.runner_envelope_hook(),
        hlc=side.cluster.shared_hlc(),
    )
    return runner, ident


def _work_item(intent_id: str):
    import numpy as np

    emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    emb[0] = 1.0
    return WorkItem(
        id=str(uuid.uuid7()), lineage_root=intent_id, parent_id=None,
        description="summarize a small codebase", desc_embedding=emb,
        reward=0.5, reward_updated_ns=time.time_ns(), required_tier=0,
        input_hashes=["00" * 32], output_spec={}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )


def main() -> int:
    import asyncio

    if not NETD_BIN.exists():
        print("gyza-netd not found — build it (make -C netd build) or put "
              "it on PATH. This demo needs the network daemon.",
              file=sys.stderr)
        return 2

    bwrap = shutil.which("bwrap") is not None
    _bar("TWO-NODE DELEGATION WITH AUDITED SETTLEMENT")
    print("A coordinator delegates a BOUNDED task to an untrusted executor.")
    print("The executor runs it in a", "REAL bwrap sandbox" if bwrap
          else "labelled mock (no bwrap on this host)", "and signs the result.")
    print("The coordinator then AUDITS the returned work itself — and pays")
    print("only if that audit passes. Payment is the output of a check, not")
    print("a handshake.")

    base = Path("/tmp") / f"gyza-loop-{uuid.uuid7()}"
    coord = _build_side("coordinator", base)
    execu = _build_side("executor", base)
    runner = None
    try:
        # THE switch that turns the audit gate on: attach a content-
        # addressed store to each blackboard BEFORE the cluster starts.
        # The executor's runner persists artifact+manifest here; the
        # coordinator absorbs the earner's evidence here and audits it.
        coord.blackboard.attach_artifact_store(
            ArtifactStore(base_path=str(coord.home / "cas")))
        execu.blackboard.attach_artifact_store(
            ArtifactStore(base_path=str(execu.home / "cas")))

        _bar("[1/5] Nodes up; audit-before-cosign ENABLED on both")
        asyncio.run(coord.cluster.start())
        asyncio.run(execu.cluster.start())
        print(f"  coordinator: {coord.netd.get_node_info().peer_id[:24]}…")
        print(f"  executor:    {execu.netd.get_node_info().peer_id[:24]}…")

        _bar("[2/5] Coordinator connects directly to executor (loopback)")
        info = execu.netd.get_node_info()
        addr = _loopback_addr(info.listen_addrs)
        full = f"{addr}/p2p/{info.peer_id}"
        conn = coord.netd.connect_peer(full, execu.compositor.pubkey_hex)
        if not conn.success:
            print(f"  connect failed: {conn.error}", file=sys.stderr)
            return 3
        coord.cluster.peer_registry.add(execu.compositor.pubkey_hex, conn.peer_id)
        print(f"  linked → {conn.peer_id[:24]}…")

        coord.gossip.join_project(PROJECT_ID)
        execu.gossip.join_project(PROJECT_ID)
        coord.blackboard.attach_gossip(
            coord.gossip, PROJECT_ID, node_id=coord.compositor.pubkey_hex)
        execu.blackboard.attach_gossip(
            execu.gossip, PROJECT_ID, node_id=execu.compositor.pubkey_hex)
        time.sleep(2.0)
        execu.cluster.peer_registry.refresh()

        _bar("[3/5] Executor comes online; coordinator delegates a bounded task")
        runner, agent = _build_executor(execu, bwrap)
        runner.start()
        print(f"  executor agent {agent.agent_id[:16]}… bounded to {_BUDGET_MB} MB")

        intent_id = str(uuid.uuid7())
        coord.blackboard.post_intent({
            "intent_id": intent_id, "natural_text": "delegate bounded work",
            "category": "system_task", "actions": [],
            "authorization": {"resources": [], "preview_required": False,
                              "reversible": True},
        })
        wi = _work_item(intent_id)
        coord_pk = coord.compositor.pubkey_hex
        exec_pk = execu.compositor.pubkey_hex
        settled_before = len([e for e in coord.ledger.export_statement(exec_pk)
                             if e["settled"]])
        coord.blackboard.post_work_item(wi)
        print(f"  posted {wi.id[:8]}… — gossiping to executor")

        executed = _wait_until(
            lambda: any(w.completed_at_ns is not None
                        for w in execu.blackboard.get_by_lineage(intent_id)
                        if w.id == wi.id),
            timeout_s=25.0)
        print("  ✓ executor claimed, ran in-sandbox, signed the envelope"
              if executed else "  ✗ executor did not complete the work")
        if not executed:
            return 4

        _bar("[4/5] Coordinator AUDITS the returned work, THEN settles")
        settled = _wait_until(
            lambda: len([e for e in coord.ledger.export_statement(exec_pk)
                        if e["settled"]]) > settled_before,
            timeout_s=15.0)
        if not settled:
            print("  ✗ settlement did not complete within the window — the")
            print("    coordinator's audit gate did not accept (evidence not")
            print("    resolvable, or the work did not audit clean). Not paid.")
            return 5
        print("  ✓ audit passed on the coordinator's own store → cosigned + paid")

        # Show the independent verdict the coordinator can produce from
        # exactly the evidence it now holds — what it would hand a third
        # party as proof of what it paid for.
        store = getattr(coord.blackboard, "_artifact_store", None)
        envs = coord.blackboard.reconstruct_dag(intent_id)
        report = audit_from_store(envs, store, require_closed=False)
        print()
        for line in render_audit_report(
                report, title="COORDINATOR'S INDEPENDENT AUDIT").splitlines():
            print("  " + line)

        _bar("[5/5] VERDICT")
        coord_bal = coord.ledger.get_balance(exec_pk)
        exec_bal = execu.ledger.get_balance(coord_pk)
        print(f"  coordinator balance with executor: {coord_bal:+.1f} (owes)")
        print(f"  executor balance with coordinator: {exec_bal:+.1f} (earned)")
        print(f"  zero-sum: {coord_bal + exec_bal == 0.0}")
        print()
        print("  The credit moved ONLY after the coordinator independently")
        print("  audited the delivered work from evidence the executor")
        print("  shipped. Over-bound or tampered work is declined + disputed")
        print("  and never paid (tests/test_settlement.py::test_loop_*).")
        print("  Proven: accountable, contained, audited-before-paid.")
        print("  NOT proven: the output is *correct* — a human still decides.")
        return 0 if report.valid else 6
    finally:
        if runner is not None:
            runner.stop()
        _kill_side(coord)
        _kill_side(execu)


if __name__ == "__main__":
    raise SystemExit(main())
