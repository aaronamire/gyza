"""
Gyza CLI.

Subcommands:
  init                    Initialize ~/.gyza, generate compositor key
  demo                    Run the two-agent pipeline demo (Phase 1, local)
  demo injection          Run the injection-attack demo
  demo lan                Run the Phase 2 single-machine simulation
  status                  Show blackboard / cluster / artifact stats
  network peers           List discovered + connected LAN peers
  network join HOST:PORT  Manually dial a peer over QUIC
  trust list              List trusted compositor pubkeys
  trust revoke PUBKEY     Revoke a compositor's trust

Designed to be runnable as both `python -m gyza.cli ...` and (after
install) `gyza ...`. No third-party CLI deps; argparse only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import runpy
import sqlite3
import sys
from pathlib import Path

from gyza.config import GyzaConfig, load_config
from gyza.identity import LocalCompositor


def _resolve(p: str) -> Path:
    return Path(p).expanduser()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    home = _resolve("~/.gyza")
    home.mkdir(parents=True, exist_ok=True)
    out_dir = home / "output"
    out_dir.mkdir(exist_ok=True)
    revoke_dir = home / "revocations"
    revoke_dir.mkdir(exist_ok=True)

    compositor = LocalCompositor(key_path=cfg.compositor_key_path)
    config_path = home / "config.json"
    if not config_path.exists():
        snapshot = {
            "blackboard_db_path": cfg.blackboard_db_path,
            "memory_db_path": cfg.memory_db_path,
            "compositor_key_path": cfg.compositor_key_path,
            "default_model": cfg.default_model,
            "poll_interval_s": cfg.poll_interval_s,
            "spawn_threshold": cfg.spawn_threshold,
            "drift_rate": cfg.drift_rate,
            "lsh_planes": cfg.lsh_planes,
            "inflation_halflife_s": cfg.inflation_halflife_s,
            "quic_port": cfg.quic_port,
            "artifact_port": cfg.artifact_port,
            "raft_port": cfg.raft_port,
            "manual_peers": cfg.manual_peers,
            "max_artifact_store_gb": cfg.max_artifact_store_gb,
        }
        config_path.write_text(json.dumps(snapshot, indent=2))

    print(f"gyza home:       {home}")
    print(f"compositor key:  {cfg.compositor_key_path}")
    print(f"compositor pk:   {compositor.pubkey_hex}")
    print(f"config:          {config_path}")
    print(f"output dir:      {out_dir}")
    print("ready.")
    return 0


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

def _run_demo_script(name: str) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "demo" / name
    if not script.exists():
        print(f"demo script not found: {script}", file=sys.stderr)
        return 2
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    runpy.run_path(str(script), run_name="__main__")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    if args.scenario == "injection":
        return _run_demo_script("injection_demo.py")
    if args.scenario == "lan":
        return _run_demo_script("single_machine_phase2.py")
    return _run_demo_script("two_agent_pipeline.py")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def _artifact_store_summary(cfg: GyzaConfig) -> tuple[int, int]:
    """Return (file_count, total_bytes) for the on-disk artifact store."""
    base = _resolve("~/.gyza/artifacts")
    if not base.exists():
        return (0, 0)
    n = 0
    total = 0
    for p in base.rglob("*"):
        if p.is_file() and not p.name.startswith(".") and ".tmp." not in p.name:
            n += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return (n, total)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n = int(n / 1024)
    return f"{n}TB"


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    bb_path = _resolve(cfg.blackboard_db_path)
    if not bb_path.exists():
        print(f"no blackboard at {bb_path} — run `gyza init` then `gyza demo` first")
        return 1

    uri = f"file:{bb_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        intents = conn.execute("SELECT COUNT(*) AS n FROM human_intents").fetchone()["n"]
        items = conn.execute("SELECT COUNT(*) AS n FROM work_items").fetchone()["n"]
        unclaimed = conn.execute(
            "SELECT COUNT(*) AS n FROM work_items WHERE claimed_by IS NULL"
        ).fetchone()["n"]
        in_flight = conn.execute(
            "SELECT COUNT(*) AS n FROM work_items "
            "WHERE claimed_by IS NOT NULL AND completed_at_ns IS NULL"
        ).fetchone()["n"]
        completed = conn.execute(
            "SELECT COUNT(*) AS n FROM work_items WHERE completed_at_ns IS NOT NULL"
        ).fetchone()["n"]
        artifacts = conn.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"]
        active = conn.execute(
            "SELECT DISTINCT claimed_by FROM work_items "
            "WHERE claimed_by IS NOT NULL AND completed_at_ns IS NULL"
        ).fetchall()
        recent = conn.execute(
            "SELECT id, description, reward, claimed_by, completed_at_ns "
            "FROM work_items ORDER BY created_at_ns DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()

    # Network mode is inferred from on-disk artifacts: if peer cache file
    # exists and has live entries, we've been in cluster mode at some point.
    peer_cache = _resolve("~/.gyza/known_peers.json")
    cluster_hint = ""
    if peer_cache.exists():
        try:
            data = json.loads(peer_cache.read_text())
            if isinstance(data, list) and data:
                cluster_hint = f" (last cluster: {len(data)} known peers)"
        except (OSError, json.JSONDecodeError):
            pass

    art_count, art_bytes = _artifact_store_summary(cfg)

    print(f"gyza blackboard: {bb_path}")
    print(f"  mode:           local{cluster_hint}")
    print(f"  intents:        {intents}")
    print(f"  work items:     {items}")
    print(f"    unclaimed:    {unclaimed}")
    print(f"    in-flight:    {in_flight}")
    print(f"    completed:    {completed}")
    print(f"  artifacts (db): {artifacts}")
    print(
        f"  artifacts (fs): {art_count} files, {_human_bytes(art_bytes)} "
        f"(cap {cfg.max_artifact_store_gb} GB)"
    )
    print(f"  active agents:  {len(active)}")
    for a in active:
        pk = a["claimed_by"] or "?"
        print(f"    - {pk[:16]}…")

    # Phase 3 — netd / global network status (probed only). Failures
    # are silent: gyza status must work on a clean install where
    # gyza-netd hasn't been built yet.
    _print_global_section(cfg)

    # Phase 3 — economy. Same failure policy: skip silently if the
    # ledger DB hasn't been created.
    _print_economy_section(cfg)

    print()
    print("recent work items:")
    for r in recent:
        state = "done" if r["completed_at_ns"] else (
            "in-flight" if r["claimed_by"] else "queued"
        )
        desc = (r["description"] or "")[:60]
        print(f"  [{state:9s}] r={r['reward']:.2f}  {r['id'][:8]}…  {desc}")
    return 0


def _print_global_section(cfg: GyzaConfig) -> None:
    sock = _resolve(cfg.netd_socket_path)
    if not sock.exists():
        return
    try:
        from gyza.network.netd_client import NetdClient
    except ImportError:
        return
    try:
        with NetdClient(str(sock)) as netd:
            if not netd.is_running():
                return
            info = netd.get_node_info()
            status = netd.get_status()
            peers = netd.list_peers()
    except Exception:  # noqa: BLE001
        return
    print()
    print("global network (gyza-netd):")
    print(f"  peer_id:        {info.peer_id}")
    print(f"  observed:       {status.observed_addr or '(none)'}")
    print(f"  dht peers:      {status.dht_routing_table_size}")
    print(f"  connected:      {status.connected_peers}")
    print(f"  uptime:         {status.uptime_seconds}s")
    if peers:
        print(f"  attested peers:")
        for p in peers[:5]:
            tier_label = f"T{p.attestation_tier}" if p.attestation_tier else "T0"
            print(f"    - {p.compositor_pubkey[:16]}…  {tier_label}  {p.multiaddr}")


def _print_economy_section(cfg: GyzaConfig) -> None:
    ledger_path = _resolve(cfg.netd_ledger_db_path)
    if not ledger_path.exists():
        return
    try:
        comp = LocalCompositor(key_path=cfg.compositor_key_path)
        from gyza.economy.ledger import ComputeLedger
        ledger = ComputeLedger(comp, str(ledger_path))
    except Exception:  # noqa: BLE001
        return
    earned = ledger.get_total_earned()
    spent = ledger.get_total_spent()
    net = earned - spent

    # Count peers above the free-rider threshold (>0.7) without
    # iterating raw entries — query the distinct counterparts.
    rows = ledger.export_statement()
    counterparts: set[str] = set()
    for r in rows:
        for k in ("from_compositor", "to_compositor"):
            if r[k] != ledger.compositor_pubkey:
                counterparts.add(r[k])
    flagged = sum(1 for pk in counterparts if ledger.free_rider_score(pk) > 0.7)

    print()
    print("economy (compute credits):")
    print(f"  earned:         {earned:>12.4f}")
    print(f"  spent:          {spent:>12.4f}")
    print(f"  net:            {net:>+12.4f}")
    print(f"  counterparties: {len(counterparts)}")
    if flagged:
        print(f"  free-rider alerts (score > 0.7): {flagged}")


# ---------------------------------------------------------------------------
# network peers / join
# ---------------------------------------------------------------------------

def cmd_network_peers(args: argparse.Namespace) -> int:
    """List peers from the local persisted cache.

    A live `gyza` process running discovery would expose this via IPC,
    but Phase 2 doesn't have a long-running daemon — peers are only
    persisted when a demo or test exits. We read whatever's on disk.
    """
    peer_cache = _resolve("~/.gyza/known_peers.json")
    if not peer_cache.exists():
        print("no peer cache yet (run a demo or `gyza demo lan` first)")
        return 0
    try:
        data = json.loads(peer_cache.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"peer cache unreadable: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, list) or not data:
        print("no peers cached")
        return 0
    print(f"{'PUBKEY':<18} {'IP':<16} {'PORT':<6} {'TIER':<5} AGENTS LAST_SEEN")
    for p in data:
        if not isinstance(p, dict):
            continue
        pk = (p.get("pubkey") or "")[:16]
        ip = p.get("ip", "")
        port = p.get("port", "?")
        tier = p.get("tier", "?")
        agents = p.get("agent_count", "?")
        last = p.get("last_seen_ns", 0) or 0
        last_human = "never" if last == 0 else f"{int((__import__('time').time() - last/1e9))}s ago"
        print(f"{pk:<18} {ip:<16} {port!s:<6} {tier!s:<5} {agents!s:<6} {last_human}")
    return 0


def cmd_network_join(args: argparse.Namespace) -> int:
    """One-shot dial of a peer's QUIC endpoint and authenticate.

    Useful for confirming a static peer is reachable. We don't
    persist a long-running connection — the local CLI process exits
    immediately after the handshake.
    """
    spec = args.peer
    try:
        host, port_s = spec.rsplit(":", 1)
        port = int(port_s)
    except ValueError:
        print(f"bad HOST:PORT: {spec!r}", file=sys.stderr)
        return 2

    cfg = load_config()
    from gyza.identity import LocalCompositor as _LC, AgentIdentity
    compositor = _LC(key_path=cfg.compositor_key_path)
    seed, manifest = compositor.issue_agent(
        agent_type="cli-probe",
        model_path="cli",
        fs_read_paths=[],
        fs_write_paths=[],
        attestation_tier=1,
    )
    identity = AgentIdentity(seed, manifest)

    from gyza.network.transport import GyzaTransport

    async def go() -> int:
        transport = GyzaTransport(
            identity, listen_port=0, heartbeat_interval_s=5.0,
        )
        await transport.start()
        try:
            conn = await transport.connect((host, port), timeout_s=10.0)
            if conn is None:
                print(f"FAIL: could not authenticate {spec}")
                return 1
            print(f"OK: connected to {spec}")
            print(f"  remote pubkey: {conn.remote_pubkey}")
            return 0
        finally:
            await transport.stop()

    return asyncio.run(go())


# ---------------------------------------------------------------------------
# trust list / revoke
# ---------------------------------------------------------------------------

def _open_trust_registry():
    from gyza.network.trust_registry import TrustRegistry
    return TrustRegistry()


def cmd_trust_list(args: argparse.Namespace) -> int:
    reg = _open_trust_registry()
    rows = reg.list_trusted()
    if not rows:
        print("no trusted compositors yet")
        return 0
    print(f"{'PUBKEY':<18} {'PEER_IP':<16} {'VERSION':<10} FIRST_SEEN")
    for r in rows:
        pk = (r.get("pubkey") or "")[:16]
        ip = r.get("peer_ip") or ""
        ver = r.get("gyza_version") or ""
        first_ns = r.get("first_seen_ns") or 0
        first = f"{int((__import__('time').time() - first_ns/1e9))}s ago"
        print(f"{pk:<18} {ip:<16} {ver:<10} {first}")
    return 0


def cmd_trust_revoke(args: argparse.Namespace) -> int:
    reg = _open_trust_registry()
    pk = args.pubkey
    reason = args.reason or "manual revoke via CLI"
    if not reg.is_trusted(pk):
        print(f"compositor {pk[:16]}... is not currently trusted", file=sys.stderr)
        return 1
    reg.revoke_compositor(pk, reason)
    print(f"revoked {pk[:16]}... ({reason})")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 3 — global federation
# ---------------------------------------------------------------------------

def _open_netd():
    """
    Open a NetdClient against the configured socket. Lazy import so
    importing this module on a stripped-down install (no grpc) still
    works for non-global subcommands like ``gyza init``.
    """
    from gyza.network.netd_client import NetdClient
    cfg = load_config()
    sock = _resolve(cfg.netd_socket_path)
    return NetdClient(str(sock)), cfg


def cmd_global_start(args: argparse.Namespace) -> int:
    """
    Spawn gyza-netd if not already running and report identity.
    Idempotent — re-running on an already-up daemon attaches to it.

    With ``--metrics``, also starts a Prometheus scrape server on
    the loopback interface (default :9100). The server lives only as
    long as this CLI invocation; for production observability,
    ``gyza global start`` is typically wrapped by a process supervisor
    that holds the Python process alive across the daemon's lifetime.
    """
    from gyza.network.netd_client import NetdClient
    if getattr(args, "metrics", False):
        from gyza.observability import start_metrics_server
        try:
            start_metrics_server(port=args.metrics_port, addr=args.metrics_addr)
            print(f"prometheus metrics: http://{args.metrics_addr}:{args.metrics_port}/metrics")
        except OSError as e:
            print(
                f"warning: failed to bind metrics server on "
                f"{args.metrics_addr}:{args.metrics_port}: {e}",
                file=sys.stderr,
            )
    cfg = load_config()
    socket = _resolve(cfg.netd_socket_path)

    # --supervised: long-running foreground supervisor. We block here
    # so the supervisor's heartbeat thread has a host process to live
    # in (CLAUDE.md §11 trip-wire — fire-and-forget supervisors die
    # with the CLI return).
    if getattr(args, "supervised", False):
        from gyza.network.daemon_supervisor import DaemonSupervisor

        sup = DaemonSupervisor(
            socket_path=str(socket),
            binary_path=cfg.netd_binary_path,
            listen_port=cfg.netd_listen_port,
            key_path=cfg.compositor_key_path,
            bootstrap=cfg.netd_bootstrap_peers,
            log_level="info",
        )
        sup.start()
        print(f"netd supervised (pid {sup.current_proc().pid if sup.current_proc() else '?'})")
        print(f"  socket:        {socket}")
        print(f"  press Ctrl-C to stop")

        import signal
        import threading
        stop_evt = threading.Event()

        def _on_signal(signum, _frame):
            print(f"\nreceived signal {signum}; stopping supervisor")
            stop_evt.set()

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
        try:
            stop_evt.wait()
        finally:
            sup.stop()
        return 0

    probe = NetdClient(str(socket))
    if probe.is_running():
        info = probe.get_node_info()
        status = probe.get_status()
        print(f"netd already running:")
        print(f"  socket:        {socket}")
        print(f"  peer_id:       {info.peer_id}")
        print(f"  observed_addr: {status.observed_addr or '(none)'}")
        print(f"  dht_peers:     {status.dht_routing_table_size}")
        print(f"  uptime:        {status.uptime_seconds}s")
        probe.close()
        return 0
    probe.close()

    proc = NetdClient.start_daemon(
        socket_path=str(socket),
        binary_path=cfg.netd_binary_path,
        listen_port=cfg.netd_listen_port,
        key_path=cfg.compositor_key_path,
        bootstrap=cfg.netd_bootstrap_peers,
        log_level="info",
        startup_timeout_s=10.0,
    )
    print(f"netd started (pid {proc.pid})")
    print(f"  socket:        {socket}")
    with NetdClient(str(socket)) as c:
        info = c.get_node_info()
        print(f"  peer_id:       {info.peer_id}")
        print(f"  listen_addrs:")
        for a in info.listen_addrs:
            print(f"    {a}")
    return 0


def cmd_global_status(args: argparse.Namespace) -> int:
    netd, _cfg = _open_netd()
    if not netd.is_running():
        print("netd not running — start with `gyza global start`")
        netd.close()
        return 1
    info = netd.get_node_info()
    status = netd.get_status()
    peers = netd.list_peers()
    print(f"peer_id:       {info.peer_id}")
    print(f"observed_addr: {status.observed_addr or '(none)'}")
    print(f"dht_peers:     {status.dht_routing_table_size}")
    print(f"connected:     {status.connected_peers}")
    print(f"nat_traversal: {status.nat_traversal_available}")
    print(f"uptime:        {status.uptime_seconds}s")
    if peers:
        print()
        print(f"{'PEER_ID':<20} {'PUBKEY':<18} {'TIER':<5} MULTIADDR")
        for p in peers:
            print(
                f"{p.peer_id[:18]:<20} {p.compositor_pubkey[:16]:<18} "
                f"{p.attestation_tier:<5} {p.multiaddr}"
            )
    netd.close()
    return 0


def cmd_global_find(args: argparse.Namespace) -> int:
    """
    Search the DHT for agents with embeddings near a query vector.

    The query string is embedded with the configured embedding backend
    (sentence-transformers by default). All nodes in the network MUST
    use the same embedder model_id for results to be comparable —
    Phase 3 hardcodes ``sentence-transformers/all-MiniLM-L6-v2``.

    Override with ``GYZA_EMBEDDER=stub`` to use the deterministic
    stub backend (useful for offline DHT inspection where retrieval
    quality doesn't matter).
    """
    netd, _cfg = _open_netd()
    if not netd.is_running():
        print("netd not running", file=sys.stderr)
        netd.close()
        return 1

    from gyza.embeddings import default_embedder
    embedder = default_embedder()
    v = embedder.embed(args.query)

    try:
        ads = netd.find_agents(v, k=args.k, min_tier=args.min_tier)
    except Exception as e:  # noqa: BLE001
        print(f"find_agents failed: {e}", file=sys.stderr)
        netd.close()
        return 1
    if not ads:
        print("(no DHT hits — DHT may be unpopulated)")
        netd.close()
        return 0
    print(f"{'PUBKEY':<18} {'TIER':<5} {'REP':<6} BALANCE  ADDRS")
    for ad in ads:
        addrs = ", ".join(ad.multiaddrs[:1]) or "(none)"
        print(
            f"{ad.compositor_pubkey[:16]:<18} "
            f"{ad.attestation_tier:<5} "
            f"{ad.reputation_score:<6.2f} "
            f"{ad.compute_credit_balance:<8} {addrs}"
        )
    netd.close()
    return 0


def cmd_global_attest(args: argparse.Namespace) -> int:
    """
    Run the canonical eval suite locally and emit a Tier-1
    self-signed attestation artifact.

    What this command does:

      1. Builds an ephemeral AgentRunner backed by the user's
         compositor key + an executor specialized to solve the eval
         suite (mock-eval; no LLM required for Tier 1).
      2. Drives the suite via ``run_eval_locally`` — every task
         posts an intent + work item, the runner claims, executes,
         and signs an ICP envelope.
      3. Verifies the bundle via ``verify_eval_results`` — the same
         pure verifier a remote Tier-3 validator will run.
      4. On pass: writes a JSON attestation artifact to disk
         (``~/.gyza/attestations/self-<nonce>.json`` by default).

    What this command does NOT yet do (deferred until the
    ``/gyza/capability-challenge/1.0.0`` libp2p protocol lands):

      * Talk to remote validators
      * Collect 2-of-3 co-signatures
      * Publish to the DHT

    Exit codes: 0 on attestation pass, 1 on attestation failure
    (some task did not verify), 2 on environment / setup errors.
    """
    import json as _json
    import secrets
    import tempfile
    from pathlib import Path as _Path

    import numpy as _np

    from gyza.blackboard import Blackboard
    from gyza.capability_eval import (
        EVAL_TASKS,
        EVAL_VERSION,
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

    cfg = load_config()
    key_path = _resolve(cfg.compositor_key_path)
    if not _Path(key_path).exists():
        print(
            f"compositor key not found at {key_path}; run `gyza init` first",
            file=sys.stderr,
        )
        return 2

    compositor = LocalCompositor(key_path)

    # Ephemeral working tree — the agent's per-attestation state
    # (memory, specialization, blackboard) is deliberately throwaway.
    # The artifact we keep is the signed attestation, not the
    # supporting databases.
    with tempfile.TemporaryDirectory(prefix="gyza-attest-") as scratch:
        scratch_path = _Path(scratch)
        bb = Blackboard(str(scratch_path / "bb.db"))

        # Issue an attest-only agent. Tier 1 — this is the floor
        # tier, "I have keys and machinery." Higher tiers come from
        # peer-reviewed cross-network attestation.
        seed, manifest = compositor.issue_agent(
            agent_type="capability-self-attest",
            model_path="mock-eval",
            fs_read_paths=[str(scratch_path)],
            fs_write_paths=[str(scratch_path)],
            attestation_tier=1,
        )
        ident = AgentIdentity(seed, manifest)

        mem = EpisodicMemory(
            agent_id=ident.agent_id,
            db_path=str(scratch_path / "mem.db"),
        )
        rng = _np.random.default_rng(0)
        seed_emb = rng.standard_normal(EMBEDDING_DIM).astype(_np.float32)
        seed_emb /= max(_np.linalg.norm(seed_emb), 1e-9)
        spec = SpecializationTracker(
            agent_id=ident.agent_id,
            initial_embedding=seed_emb,
            db_path=str(scratch_path / "spec.db"),
        )

        recorder: dict[str, dict] = {}
        executor = make_recording_executor(make_mock_eval_executor(), recorder)
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

        nonce = secrets.token_hex(16)
        eval_workdir = scratch_path / "eval"
        try:
            print(f"running {len(EVAL_TASKS)} eval tasks (nonce={nonce[:8]}...)")
            _, results = run_eval_locally(
                runner=runner,
                blackboard=bb,
                applicant_pubkey=ident.pubkey_hex,
                workdir=eval_workdir,
                nonce=nonce,
                output_recorder=recorder,
                overall_timeout_s=120.0,
            )
            report = verify_eval_results(
                results=results,
                applicant_pubkey=ident.pubkey_hex,
                nonce=nonce,
                workdir=eval_workdir,
            )
        finally:
            runner.stop()

    # Render the report regardless of pass/fail so the operator can
    # debug failed tasks.
    print()
    print(f"eval_version: {report.eval_version}")
    print(f"applicant:    {report.applicant_pubkey[:32]}...")
    print(f"passed:       {report.passed_tasks} / {report.total_tasks}")
    print()
    for tid, msg in report.per_task.items():
        marker = "✓" if msg == "ok" else "✗"
        print(f"  {marker}  {tid:24s}  {msg}")
    print()

    if not report.passed:
        print("attestation FAILED — at least one task did not verify",
              file=sys.stderr)
        return 1

    # Build the artifact. We don't yet have the protobuf-shaped
    # AttestationCert that the daemon's CapabilityService will want
    # — that's wired in the cross-network protocol step. For now,
    # emit a JSON envelope the operator can inspect and a future
    # session can promote into the proto form.
    artifact_dir = _Path(_resolve("~/.gyza/attestations"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"self-{nonce[:16]}.json"

    # The signed payload: the verifier's report plus the eval suite
    # version. Signed by the compositor (the issuing identity), not
    # the agent — the agent identity rotates per attestation but
    # the compositor is the durable identity peers index against.
    payload = {
        "schema": "gyza.attestation.self/v1",
        "tier": 1,
        "eval_version": EVAL_VERSION,
        "applicant_compositor_pubkey": compositor.pubkey_hex,
        "applicant_agent_pubkey": report.applicant_pubkey,
        "nonce": nonce,
        "passed": report.passed,
        "passed_tasks": report.passed_tasks,
        "total_tasks": report.total_tasks,
        "per_task": report.per_task,
    }
    payload_bytes = _json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    signature = compositor.sign(payload_bytes)

    artifact = {
        "payload": payload,
        "signature": signature,
        "signer_pubkey": compositor.pubkey_hex,
    }
    artifact_path.write_text(_json.dumps(artifact, indent=2))
    print(f"attestation PASSED — Tier {payload['tier']}")
    print(f"artifact: {artifact_path}")
    print()
    print("note: cross-network (Tier 3) attestation requires the")
    print("/gyza/capability-challenge/1.0.0 libp2p protocol, which")
    print("is not yet implemented. This artifact is locally-signed")
    print("and serves as proof of working machinery only.")
    return 0


def cmd_metrics_start(args: argparse.Namespace) -> int:
    """
    Start the Prometheus scrape HTTP server in this process and block
    until interrupted. Operators wire Prometheus / Grafana / etc. at
    http://<addr>:<port>/metrics.

    The server only exposes whatever counters / histograms / gauges
    have been incremented in this process — running ``gyza metrics
    start`` in a fresh shell with no other Gyza work happening will
    produce a (mostly) empty scrape. The intended use is to pass
    ``--metrics`` to ``gyza global start`` (a long-lived process), or
    to invoke ``observability.start_metrics_server`` from a Python
    embedding application.
    """
    import signal
    from gyza.observability import start_metrics_server

    addr = args.addr
    port = args.port
    try:
        start_metrics_server(port=port, addr=addr)
    except OSError as e:
        print(f"failed to bind metrics server on {addr}:{port}: {e}", file=sys.stderr)
        return 1
    print(f"prometheus metrics: http://{addr}:{port}/metrics (Ctrl-C to stop)")

    stop = False

    def _handle(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    import time as _time
    while not stop:
        _time.sleep(0.5)
    return 0


def cmd_global_project_new(args: argparse.Namespace) -> int:
    """
    Stand up a new Phase 3 project on the running daemon: join the
    gossip topic. Bringing in remote agents requires the embedding +
    AgentDescriptor wiring that the current CLI doesn't yet expose;
    operators run this from Python for now.
    """
    from gyza.network.netd_client import GossipClient
    cfg = load_config()
    sock = _resolve(cfg.netd_socket_path)
    with GossipClient(str(sock)) as g:
        try:
            mesh = g.join_project(args.project_id)
        except Exception as e:  # noqa: BLE001
            print(f"join_project failed: {e}", file=sys.stderr)
            return 1
    print(f"joined project {args.project_id} (mesh peers: {mesh})")
    return 0


# ---------------------------------------------------------------------------
# Phase 3 — credits
# ---------------------------------------------------------------------------

def _open_ledger():
    cfg = load_config()
    comp = LocalCompositor(key_path=cfg.compositor_key_path)
    from gyza.economy.ledger import ComputeLedger
    return ComputeLedger(comp, cfg.netd_ledger_db_path), comp


def cmd_credits_balance(args: argparse.Namespace) -> int:
    ledger, _comp = _open_ledger()
    earned = ledger.get_total_earned()
    spent = ledger.get_total_spent()
    print(f"earned:  {earned:>12.4f} credits")
    print(f"spent:   {spent:>12.4f} credits")
    print(f"net:     {earned - spent:>+12.4f} credits")
    return 0


def cmd_credits_statement(args: argparse.Namespace) -> int:
    ledger, _comp = _open_ledger()
    rows = ledger.export_statement(args.peer if args.peer else None)
    if not rows:
        print("(no entries)")
        return 0
    # Compact tabular view. ID truncated; full ID accessible via SQLite
    # if a user really needs it.
    print(
        f"{'ENTRY':<10} {'WHEN':<19} {'FROM':<12} {'TO':<12} "
        f"{'AMOUNT':>10} {'SETTLED':<7} WORK_ITEM"
    )
    import datetime as _dt
    for r in rows:
        when = _dt.datetime.fromtimestamp(
            r["created_at_ns"] / 1e9, _dt.timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{r['entry_id'][:8]:<10} {when:<19} "
            f"{r['from_compositor'][:10]:<12} "
            f"{r['to_compositor'][:10]:<12} "
            f"{r['amount_credits']:>10.4f} "
            f"{'yes' if r['settled'] else 'no':<7} "
            f"{r['work_item_id'][:24]}"
        )
    return 0


def cmd_credits_reconcile(args: argparse.Namespace) -> int:
    """
    Run a bilateral ledger reconciliation against a peer.

    The CLI requires a running gyza-netd (so the settlement service
    can subscribe / send messages). It opens a transient
    LedgerSettlementService bound to our local ledger, looks up the
    peer's libp2p peer_id (from PeerRegistry, or --peer-id flag),
    drives the paginated reconciliation, and prints the diff.

    Reputation hits (record_dispute) only land for ``disputed``
    entries — pruning and gossip lag manifest as ``missing_*`` and
    are NOT signalled as protocol violations.
    """
    from gyza.economy.settlement import LedgerSettlementService
    from gyza.network.netd_client import NetdClient
    from gyza.network.peer_registry import PeerRegistry

    cfg = load_config()
    sock = _resolve(cfg.netd_socket_path)
    netd = NetdClient(str(sock))
    if not netd.is_running():
        print("netd not running — start with `gyza global start`", file=sys.stderr)
        netd.close()
        return 1

    ledger, _comp = _open_ledger()

    if args.peer_id:
        peer_id = args.peer_id
    else:
        registry = PeerRegistry(netd)
        registry.refresh()
        peer_id = registry.resolve_peer_id(args.peer_pubkey)
        if not peer_id:
            print(
                f"unknown peer pubkey {args.peer_pubkey[:16]}.. — "
                f"either pass --peer-id or run `gyza global status` to "
                f"see currently-connected peers",
                file=sys.stderr,
            )
            netd.close()
            return 1

    # No real envelope_resolver needed for reconcile-only operation —
    # the settlement payment paths aren't exercised. A None resolver
    # would be cleaner; we pass a stub for type compatibility.
    svc = LedgerSettlementService(
        ledger=ledger, netd=netd,
        envelope_resolver=lambda _wid: None,
    )
    svc.start()
    try:
        result = svc.request_reconciliation(
            peer_compositor=args.peer_pubkey,
            peer_id=peer_id,
            page_size=args.page_size,
            page_timeout_s=args.page_timeout,
        )
    finally:
        svc.stop()
        netd.close()

    print(f"reconcile against {args.peer_pubkey[:16]}.. (peer_id={peer_id[:16]}..)")
    print(f"  pages:           {result.pages}")
    print(f"  entries seen:    {result.entries_received}")
    print(f"  agreed:          {len(result.agreed)}")
    print(f"  disputed:        {len(result.disputed)}")
    print(f"  missing_ours:    {len(result.missing_ours)}  (they have, we don't)")
    print(f"  missing_theirs:  {len(result.missing_theirs)}  (we have, they don't)")
    if result.error:
        print(f"  error:           {result.error}", file=sys.stderr)
    if result.disputed:
        print()
        print("DISPUTED entry_ids (these bumped the peer's dispute count):")
        for eid in result.disputed:
            print(f"  {eid}")
    return 0 if result.error is None else 2


def cmd_credits_peers(args: argparse.Namespace) -> int:
    """
    Per-peer balances + free-rider scores. Useful for spot-checking
    who we've been working with and whether anyone's sliding into
    free-rider territory (score > 0.7).
    """
    ledger, _comp = _open_ledger()
    rows = ledger.export_statement()
    if not rows:
        print("(no entries)")
        return 0
    counterparts: set[str] = set()
    self_pk = ledger.compositor_pubkey
    for r in rows:
        if r["from_compositor"] != self_pk:
            counterparts.add(r["from_compositor"])
        if r["to_compositor"] != self_pk:
            counterparts.add(r["to_compositor"])
    if not counterparts:
        print("(no counterparties)")
        return 0
    print(
        f"{'PEER':<18} {'BALANCE':>12} {'TRANSACTED':>12} "
        f"{'FREE_RIDER':>10}"
    )
    for pk in sorted(counterparts):
        bal = ledger.get_balance(pk)
        total = ledger.get_total_transacted_with(pk)
        score = ledger.free_rider_score(pk)
        flag = " *" if score > 0.7 else ""
        print(
            f"{pk[:16]:<18} {bal:>+12.4f} {total:>12.4f} "
            f"{score:>10.3f}{flag}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gyza", description="Gyza coordination network CLI"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize ~/.gyza and generate compositor key")

    p_demo = sub.add_parser("demo", help="run a Gyza demo")
    p_demo.add_argument(
        "scenario",
        nargs="?",
        choices=["pipeline", "injection", "lan"],
        default="pipeline",
        help="pipeline (default), injection, or lan (Phase-2 sim)",
    )

    sub.add_parser("status", help="show blackboard, artifact store, and cluster stats")

    p_net = sub.add_parser("network", help="LAN peer commands")
    netsub = p_net.add_subparsers(dest="network_cmd", required=True)
    netsub.add_parser("peers", help="list known LAN peers from local cache")
    p_join = netsub.add_parser("join", help="manually dial a peer (HOST:PORT)")
    p_join.add_argument("peer", help="HOST:PORT of remote QUIC listener")

    p_trust = sub.add_parser("trust", help="trusted-compositor registry")
    trustsub = p_trust.add_subparsers(dest="trust_cmd", required=True)
    trustsub.add_parser("list", help="list trusted compositors")
    p_rev = trustsub.add_parser("revoke", help="revoke a compositor by pubkey")
    p_rev.add_argument("pubkey", help="compositor pubkey hex (64 chars)")
    p_rev.add_argument(
        "--reason", default="", help="why this compositor is being revoked",
    )

    # Phase 3 — global federation.
    p_global = sub.add_parser("global", help="Phase 3 global network commands")
    globsub = p_global.add_subparsers(dest="global_cmd", required=True)
    p_gstart = globsub.add_parser("start", help="start gyza-netd if not running")
    p_gstart.add_argument(
        "--metrics", action="store_true",
        help="also start the Prometheus scrape HTTP server",
    )
    p_gstart.add_argument(
        "--metrics-addr", default="127.0.0.1",
        help="bind address for the metrics server (default: 127.0.0.1)",
    )
    p_gstart.add_argument(
        "--metrics-port", type=int, default=9100,
        help="port for the metrics server (default: 9100)",
    )
    p_gstart.add_argument(
        "--supervised", action="store_true",
        help=(
            "run as a long-lived foreground supervisor: spawn gyza-netd, "
            "watch for crashes, respawn with backoff. Blocks until SIGINT. "
            "Without this flag, the command is one-shot (default)."
        ),
    )
    globsub.add_parser("status", help="show netd identity, DHT peers, connections")
    p_find = globsub.add_parser("find", help="search the DHT for agents")
    p_find.add_argument("query", help="natural-language hint hashed to a query vector")
    p_find.add_argument("--k", type=int, default=10, help="max results (default 10)")
    p_find.add_argument(
        "--min-tier", type=int, default=0, help="minimum attestation tier",
    )
    globsub.add_parser(
        "attest",
        help="run the canonical eval suite + emit a Tier-1 self-attestation",
    )
    p_proj = globsub.add_parser("project", help="project lifecycle")
    projsub = p_proj.add_subparsers(dest="project_cmd", required=True)
    p_pnew = projsub.add_parser("new", help="join (or create) a project's gossip topic")
    p_pnew.add_argument("project_id", help="opaque project identifier shared with peers")

    # Phase 3 — observability (Prometheus scrape endpoint).
    p_metrics = sub.add_parser(
        "metrics", help="Prometheus metrics endpoint",
    )
    msub = p_metrics.add_subparsers(dest="metrics_cmd", required=True)
    p_mstart = msub.add_parser(
        "start", help="bind the metrics server and block",
    )
    p_mstart.add_argument(
        "--addr", default="127.0.0.1",
        help="bind address (default: 127.0.0.1; use 0.0.0.0 to expose externally)",
    )
    p_mstart.add_argument(
        "--port", type=int, default=9100,
        help="port (default: 9100)",
    )

    # Phase 3 — credits.
    p_credits = sub.add_parser("credits", help="compute-credit ledger")
    csub = p_credits.add_subparsers(dest="credits_cmd", required=True)
    csub.add_parser("balance", help="net credits earned/spent")
    p_stmt = csub.add_parser("statement", help="ledger entries as a table")
    p_stmt.add_argument(
        "--peer", default="", help="filter to entries with one peer (pubkey hex)",
    )
    csub.add_parser(
        "peers",
        help="per-peer balance + free-rider score (* marks score > 0.7)",
    )
    p_recon = csub.add_parser(
        "reconcile",
        help="bilateral ledger reconciliation against a peer",
    )
    p_recon.add_argument(
        "peer_pubkey", help="compositor pubkey hex (64 chars)",
    )
    p_recon.add_argument(
        "--peer-id", default="",
        help="libp2p peer_id (skip PeerRegistry lookup)",
    )
    p_recon.add_argument(
        "--page-size", type=int, default=500,
        help="entries per round-trip (default: 500)",
    )
    p_recon.add_argument(
        "--page-timeout", type=float, default=5.0,
        help="seconds to wait for each page response (default: 5.0)",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "network":
        if args.network_cmd == "peers":
            return cmd_network_peers(args)
        if args.network_cmd == "join":
            return cmd_network_join(args)
    if args.command == "trust":
        if args.trust_cmd == "list":
            return cmd_trust_list(args)
        if args.trust_cmd == "revoke":
            return cmd_trust_revoke(args)
    if args.command == "global":
        if args.global_cmd == "start":
            return cmd_global_start(args)
        if args.global_cmd == "status":
            return cmd_global_status(args)
        if args.global_cmd == "find":
            return cmd_global_find(args)
        if args.global_cmd == "attest":
            return cmd_global_attest(args)
        if args.global_cmd == "project":
            if args.project_cmd == "new":
                return cmd_global_project_new(args)
    if args.command == "metrics":
        if args.metrics_cmd == "start":
            return cmd_metrics_start(args)
    if args.command == "credits":
        if args.credits_cmd == "balance":
            return cmd_credits_balance(args)
        if args.credits_cmd == "statement":
            return cmd_credits_statement(args)
        if args.credits_cmd == "peers":
            return cmd_credits_peers(args)
        if args.credits_cmd == "reconcile":
            return cmd_credits_reconcile(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
