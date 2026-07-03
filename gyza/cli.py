"""
Gyza CLI.

Subcommands:
  init                    Initialize ~/.gyza, generate compositor key
  run TASK                Execute one task bounded + flight-recorded (local)
  exec -- CMD [ARGS]      Run YOUR command bounded + flight-recorded
  audit [INTENT]          Forensically audit a stored workflow
  bundle INTENT           Export a workflow as a portable evidence bundle
  verify FILE             Verify an evidence bundle offline (anyone can)
  demo                    Run the two-agent pipeline demo (Phase 1, local)
  demo injection          Run the injection-attack demo
  demo lan                Run the Phase 2 single-machine simulation
  demo global             Run the Phase 3 two-daemon end-to-end demo
  demo bounds             Run the bounds-proof demo (offline, no API)
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
import os
import runpy
import sqlite3
import subprocess
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
    print()
    print("next: gyza run \"your task\"   (bounded, recorded, auditable)")
    return 0


# ---------------------------------------------------------------------------
# run — bounded, flight-recorded local execution (the single-player product)
# ---------------------------------------------------------------------------

def _load_or_issue_local_agent(
    compositor, state_path: Path, *, memory_mb: int, allowed_hosts: list[str],
    read_paths: "list[str] | None" = None,
    write_paths: "list[str] | None" = None,
):
    """
    The local agent persists across runs — one identity accumulating an
    auditable history — so it's issued once and reloaded thereafter.
    Reissued only when the requested bounds change (memory, hosts, OR
    filesystem paths), because the manifest IS the authorization:
    different bounds are a different grant, and reusing the old identity
    would attribute new work to an authorization it never had.
    """
    import json as _json

    from gyza.identity import AgentIdentity

    read_paths = read_paths or []
    write_paths = write_paths or []
    if state_path.exists():
        try:
            saved = _json.loads(state_path.read_text())
            manifest = saved["manifest"]
            caps = manifest["capabilities"]
            budget = caps["spawn"]["resource_budget"]
            hosts = caps["network"]["allowed_hosts"]
            fs = caps["filesystem"]
            if (budget.get("memory_limit_mb") == memory_mb
                    and sorted(hosts) == sorted(allowed_hosts)
                    and sorted(fs.get("read", [])) == sorted(read_paths)
                    and sorted(fs.get("write", [])) == sorted(write_paths)):
                return AgentIdentity(bytes.fromhex(saved["seed_hex"]), manifest)
            print("bounds changed — issuing a fresh agent identity for "
                  "the new grant")
        except (KeyError, ValueError, TypeError, OSError):
            print("local agent state unreadable — issuing a fresh identity")

    seed, manifest = compositor.issue_agent(
        agent_type="local.worker", model_path="local",
        fs_read_paths=read_paths, fs_write_paths=write_paths,
        allowed_hosts=allowed_hosts,
        memory_limit_mb=memory_mb, attestation_tier=0,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(_json.dumps(
        {"seed_hex": seed.hex(), "manifest": manifest}, indent=2,
    ))
    state_path.chmod(0o600)  # the seed is a signing secret
    return AgentIdentity(seed, manifest)


def run_local_task(
    task: str,
    *,
    cfg: GyzaConfig,
    executor=None,
    memory_mb: int = 512,
    mock: bool = False,
    model: str | None = None,
    read_paths: "list[str] | None" = None,
    write_paths: "list[str] | None" = None,
    command_argv: "list[str] | None" = None,
    allow_network: bool = False,
    artifact_store_base: str = "~/.gyza/artifacts",
) -> "tuple[int, str]":
    """
    Execute one task through the REAL producer path — the same
    claim/execute/sign machinery the network uses, pointed at the local
    blackboard: issue (or reload) a bounded agent, run the task in a
    manifest-derived bwrap sandbox, sign the ICP envelope, persist the
    artifact + manifest content-addressed, then audit what was just
    stored and print the receipt. Returns ``(exit_code, intent_id)``.

    ``executor`` is injectable for tests; ``None`` selects the sandboxed
    Anthropic executor when a key is available (and ``mock`` is False),
    else the sandboxed mock — labeled honestly either way.
    """
    import shutil
    import time as _time
    import uuid as _uuid
    from dataclasses import replace as _dc_replace

    import numpy as _np

    # Keep the first-run experience instant: local flight-recording does
    # not need semantic memory, so default the embedder to the stub
    # (user's explicit GYZA_EMBEDDER always wins — setdefault).
    os.environ.setdefault("GYZA_EMBEDDER", "stub")

    from gyza.audit import audit_from_store
    from gyza.blackboard import Blackboard
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.identity import LocalCompositor
    from gyza.memory import EpisodicMemory
    from gyza.network.artifact_store import ArtifactStore
    from gyza.runner import AgentRunner
    from gyza.sandbox.config import sandbox_config_from_manifest
    from gyza.sandbox.executor import make_sandboxed_executor
    from gyza.schema import EMBEDDING_DIM, WorkItem

    rp = cfg.resolved_paths()
    key_path = Path(rp["compositor_key_path"])
    key_path.parent.mkdir(parents=True, exist_ok=True)

    api_key = "" if mock else (cfg.anthropic_api_key or "")
    use_anthropic = (
        executor is None and command_argv is None and bool(api_key)
    )
    if use_anthropic:
        allowed_hosts = ["api.anthropic.com"]
    elif allow_network:
        # bwrap network control is all-or-nothing; "*" declares "any
        # host" honestly rather than pretending an allowlist exists.
        allowed_hosts = ["*"]
    else:
        allowed_hosts = []

    # Filesystem grants resolve to absolute host paths BEFORE entering
    # the manifest, so what the manifest authorizes is exactly what
    # bwrap will bind — no relative-path ambiguity between the grant
    # and the enforcement. A nonexistent path is refused up front
    # (bwrap would fail the bind anyway; failing early is clearer).
    def _resolve_grants(paths: "list[str] | None") -> "list[str]":
        out = []
        for p in paths or []:
            rp_ = Path(p).expanduser().resolve()
            if not rp_.exists():
                raise FileNotFoundError(
                    f"granted path does not exist: {p}"
                )
            out.append(str(rp_))
        return out

    try:
        read_paths = _resolve_grants(read_paths)
        write_paths = _resolve_grants(write_paths)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1, ""

    compositor = LocalCompositor(key_path=str(key_path))
    ident = _load_or_issue_local_agent(
        compositor, key_path.parent / "local-agent.json",
        memory_mb=memory_mb, allowed_hosts=allowed_hosts,
        read_paths=read_paths, write_paths=write_paths,
    )

    if executor is None:
        if shutil.which("bwrap") is None:
            print(
                "gyza run needs bubblewrap for real enforcement and will "
                "not fall back to an unenforced sandbox.\n"
                "install it:  pacman -S bubblewrap  |  apt install bubblewrap",
                file=sys.stderr,
            )
            return 1, ""
        # The manifest is the single source of truth for the sandbox:
        # what it declares is, by construction, what bwrap enforces.
        scfg = sandbox_config_from_manifest(ident.manifest)
        if command_argv is not None:
            executor = make_sandboxed_executor(
                "gyza.runner:make_command_executor",
                init_kwargs={"argv": command_argv},
                config=scfg,
            )
            executor_label = (
                f"command: {' '.join(command_argv)} (sandboxed)"
            )
        elif use_anthropic:
            scfg = _dc_replace(scfg, env_set={"ANTHROPIC_API_KEY": api_key})
            executor = make_sandboxed_executor(
                "gyza.runner:make_anthropic_executor",
                init_kwargs={"api_key": api_key,
                             "model": model or cfg.default_model},
                config=scfg,
            )
            executor_label = f"anthropic {model or cfg.default_model} (sandboxed)"
        else:
            executor = make_sandboxed_executor(
                "gyza.runner:make_mock_executor",
                init_kwargs={"response": "[mock executor — no AI] "
                                         f"task acknowledged: {task[:120]}"},
                config=scfg,
            )
            executor_label = "mock — no AI, deterministic placeholder (sandboxed)"
    else:
        executor_label = "injected"

    net_note = ("on (host allowlist declared; namespace-enforced only)"
                if allowed_hosts else "off (fresh namespace, loopback only)")
    print(f"agent:    {ident.pubkey_hex[:16]}…  (persistent local identity)")
    print(f"bounds:   memory {memory_mb} MB (RLIMIT_AS) · network {net_note}")
    if read_paths or write_paths:
        fs_bits = []
        if read_paths:
            fs_bits.append(f"read {', '.join(read_paths)}")
        if write_paths:
            fs_bits.append(f"write {', '.join(write_paths)}")
        print(f"fs:       {' · '.join(fs_bits)}  (kernel-enforced binds)")
    else:
        print("fs:       none granted (tmpfs cwd; --allow-read/--allow-write "
              "to grant)")
    if command_argv is not None:
        # Honest scope: the command additionally sees the language runtime
        # (system dirs + the gyza install path) it needs to boot, but NOT
        # your home, ~/.ssh, or secrets outside the grants above.
        print("visible:  Python runtime + system dirs + granted paths only "
              "(home & secrets hidden)")
    print(f"executor: {executor_label}")

    bb = Blackboard(rp["blackboard_db_path"])
    store = ArtifactStore(base_path=artifact_store_base)
    bb.attach_artifact_store(store)

    intent_id = str(_uuid.uuid7())
    bb.post_intent({
        "intent_id": intent_id, "natural_text": task,
        "category": "local_task", "actions": [],
        "authorization": {"resources": [], "preview_required": False,
                          "reversible": True},
    })
    emb = _np.zeros(EMBEDDING_DIM, dtype=_np.float32)
    emb[0] = 1.0
    w = WorkItem(
        id=str(_uuid.uuid7()), lineage_root=intent_id, parent_id=None,
        description=task, desc_embedding=emb, reward=0.5,
        reward_updated_ns=_time.time_ns(), required_tier=0,
        input_hashes=["00" * 32], output_spec={}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None,
        claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=_time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )
    bb.post_work_item(w)

    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(Path(rp["memory_db_path"]).parent / "run-memory"),
    )
    spec_v = _np.zeros(EMBEDDING_DIM, dtype=_np.float32)
    spec_v[0] = 1.0
    spec = SpecializationTracker(
        agent_id=ident.agent_id, initial_embedding=spec_v,
        db_path=str(Path(rp["memory_db_path"]).parent / "run-spec.db"),
    )
    runner = AgentRunner(
        identity=ident, blackboard=bb, memory=mem, specialization=spec,
        lsh=LSHIndex(seed=42), executor=executor,
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        verify_chain_before_claim=False,
    )

    # One synchronous execute+sign cycle — the exact producer path the
    # runner's loop drives, without the loop (one item, one shot). The
    # brick-3 gate inside _execute refuses to sign anything whose
    # enforcement record exceeds the manifest.
    try:
        result = runner._execute(w)
        runner._complete(w, result, success=True)
    except Exception as exc:  # noqa: BLE001 — every refusal must surface
        print(f"\n✗ REFUSED TO SIGN / execution failed: {exc}", file=sys.stderr)
        print("no envelope was produced — out-of-bounds or failed work "
              "never enters the record.", file=sys.stderr)
        return 1, intent_id

    text = str(result.get("output", ""))
    print("\n--- result " + "-" * 53)
    print(text[:400] + ("…" if len(text) > 400 else ""))
    print("-" * 64)

    # Audit what was actually stored — same verifiers a third party runs.
    envelopes = bb.reconstruct_dag(intent_id)
    report = audit_from_store(envelopes, store, require_closed=True)
    verdict = "VALID" if report.valid else "INVALID"
    print(f"recorded: {len(envelopes)} signed envelope(s) · audit: {verdict}")
    print(f"intent:   {intent_id}")
    print(f"audit:    gyza audit  {intent_id}")
    print(f"receipt:  gyza bundle {intent_id}   (then anyone: gyza verify <file>)")
    return (0 if report.valid else 1), intent_id


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    code, _ = run_local_task(
        args.task, cfg=cfg, memory_mb=args.memory_mb,
        mock=args.mock, model=args.model,
        read_paths=args.allow_read, write_paths=args.allow_write,
    )
    return code


def cmd_exec(args: argparse.Namespace) -> int:
    """Run YOUR command bounded + flight-recorded — the seatbelt for the
    agent you already use, not gyza's executor."""
    import shlex
    import shutil

    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("usage: gyza exec [flags] -- COMMAND [ARGS...]", file=sys.stderr)
        return 2
    # Resolve the binary host-side: the sandbox gets a fresh environment,
    # so a bare name would not resolve inside — and failing here is a
    # clearer error than a sandbox exec failure.
    resolved = shutil.which(argv[0])
    if resolved is None:
        print(f"command not found: {argv[0]}", file=sys.stderr)
        return 1
    argv[0] = resolved

    cfg = load_config()
    code, _ = run_local_task(
        shlex.join(argv), cfg=cfg, memory_mb=args.memory_mb,
        read_paths=args.allow_read, write_paths=args.allow_write,
        command_argv=argv, allow_network=args.allow_network,
    )
    return code


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


def _run_demo_subprocess(name: str) -> int:
    # For demos that own their own argparse and/or spawn subprocesses,
    # run them in a fresh Python interpreter so the parent's sys.argv
    # doesn't leak into the demo's parser and the demo's signal
    # handlers / tmp dirs stay isolated.
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "demo" / name
    if not script.exists():
        print(f"demo script not found: {script}", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(script)])


def cmd_demo(args: argparse.Namespace) -> int:
    if args.scenario == "injection":
        return _run_demo_script("injection_demo.py")
    if args.scenario == "lan":
        return _run_demo_script("single_machine_phase2.py")
    if args.scenario == "global":
        return _run_demo_subprocess("single_machine_global.py")
    if args.scenario == "bounds":
        return _run_demo_script("bounds_proof_demo.py")
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


def cmd_audit(args: argparse.Namespace) -> int:
    """Forensically audit a stored workflow: reconstruct its provenance
    DAG from the envelope log and run the unified bounds + integrity
    audit, resolving artifacts/manifests from the local artifact store."""
    from gyza.audit import audit_from_store, render_audit_report
    from gyza.blackboard import Blackboard
    from gyza.network.artifact_store import ArtifactStore

    cfg = load_config()
    rp = cfg.resolved_paths()
    bb_path = Path(rp["blackboard_db_path"])
    if not bb_path.exists():
        print(f"no blackboard at {bb_path} — nothing to audit", file=sys.stderr)
        return 1

    bb = Blackboard(str(bb_path))

    # No intent given → list intents that have logged envelopes.
    if not args.intent_id:
        rows = bb._conn().execute(
            "SELECT intent_id, COUNT(*) AS n FROM icp_envelopes "
            "GROUP BY intent_id ORDER BY MAX(timestamp_ns) DESC"
        ).fetchall()
        if not rows:
            print("no logged envelopes to audit yet")
            return 1
        print("intents with logged provenance (pass one to audit):")
        for r in rows:
            print(f"  {r['intent_id']}   ({r['n']} envelopes)")
        return 0

    envelopes = bb.reconstruct_dag(args.intent_id)
    if not envelopes:
        print(f"no envelopes logged for intent {args.intent_id!r}",
              file=sys.stderr)
        return 1

    store = ArtifactStore(base_path="~/.gyza/artifacts")
    report = audit_from_store(envelopes, store, require_closed=True)
    print(render_audit_report(report, title=f"GYZA AUDIT — {args.intent_id}"))
    return 0 if report.valid else 1


def cmd_bundle(args: argparse.Namespace) -> int:
    """Export a stored workflow as a portable evidence bundle that anyone
    can check with `gyza verify` — no node, no daemon, no identity.
    Exports even a failing workflow (shipping proof of a violation is a
    legitimate act); the verdict is printed either way."""
    import json as _json

    from gyza.blackboard import Blackboard
    from gyza.evidence import (
        bundle_hash,
        bundle_to_bytes,
        create_bundle,
        render_verify_verdict_line,
        verify_bundle,
    )
    from gyza.network.artifact_store import ArtifactStore

    cfg = load_config()
    rp = cfg.resolved_paths()
    bb_path = Path(rp["blackboard_db_path"])
    if not bb_path.exists():
        print(f"no blackboard at {bb_path} — nothing to bundle", file=sys.stderr)
        return 1

    bb = Blackboard(str(bb_path))
    envelopes = bb.reconstruct_dag(args.intent_id)
    if not envelopes:
        print(f"no envelopes logged for intent {args.intent_id!r}",
              file=sys.stderr)
        return 1

    store = ArtifactStore(base_path="~/.gyza/artifacts")

    def _manifest(h: str) -> "dict | None":
        raw = store.get(h)
        if raw is None:
            return None
        try:
            obj = _json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, _json.JSONDecodeError):
            return None
        return obj if isinstance(obj, dict) else None

    bundle = create_bundle(
        envelopes, resolve_artifact=store.get, resolve_manifest=_manifest,
        intent_id=args.intent_id,
    )
    report = verify_bundle(bundle)

    out = Path(args.output or f"gyza-evidence-{args.intent_id[:12]}.json")
    out.write_bytes(bundle_to_bytes(bundle))
    print(f"wrote {out}  ({len(envelopes)} envelopes)")
    print(f"bundle hash: {bundle_hash(bundle)}")
    print(render_verify_verdict_line(report))
    if not report.valid:
        print("note: bundle written anyway — exporting evidence of a "
              "violation is a legitimate act.")
    return 0 if report.valid else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify an evidence bundle offline. Pure function of the file:
    touches no config, no identity, no daemon — a third party's command."""
    from gyza.audit import render_audit_report
    from gyza.evidence import (
        BundleError,
        bundle_hash,
        load_bundle,
        verify_bundle,
    )

    path = Path(args.bundle)
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1
    try:
        bundle = load_bundle(path.read_bytes())
        report = verify_bundle(bundle)
    except BundleError as exc:
        print(f"not a verifiable evidence bundle: {exc}", file=sys.stderr)
        return 1
    title = f"GYZA EVIDENCE VERIFY — bundle {bundle_hash(bundle)[:16]}…"
    print(render_audit_report(report, title=title))
    return 0 if report.valid else 1


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
    Run the canonical eval suite and emit an attestation artifact.

    Two modes:

      ``--tier 1`` (default) — local self-attestation.

        1. Builds an ephemeral AgentRunner under the user's compositor.
        2. Drives the suite via ``run_eval_locally``.
        3. Verifies via ``verify_eval_results``.
        4. On pass: writes ``~/.gyza/attestations/self-<nonce>.json``
           signed by the compositor key.

      ``--tier 3`` — cross-network quorum attestation.

        1. Probes the daemon (must be running) for its peer ID.
        2. Either uses ``--peer`` (one or more explicit validator
           peer IDs) or, with no ``--peer``, calls
           ``find_agents(min_tier=3, k=candidate_n)`` for DHT
           discovery.
        3. Drives ``request_tier3_attestation`` against each
           candidate; collects ≥``--quorum-k`` cosignatures over
           one applicant-proposed AttestationBody.
        4. Self-verifies the assembled cert via the daemon's
           CapabilityService.VerifyAttestation.
        5. Publishes the cert to the DHT under
           ``/gyza/attestations/{compositor_pubkey}`` via
           ``CapabilityService.PublishAttestation``.
        6. Writes a JSON-serialized cert to
           ``~/.gyza/attestations/cert-<nonce>.json`` for inspection.

    Exit codes: 0 on attestation pass, 1 on attestation failure
    (some task did not verify, or quorum not met), 2 on environment
    / setup errors (no compositor key, daemon not running, etc.).
    """
    if getattr(args, "tier", 1) == 3:
        return _cmd_global_attest_tier3(args)
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
    print("note: this is a Tier-1 self-attestation. Run with")
    print("`--tier 3` to collect a quorum-signed cert from peer")
    print("validators and publish it to the DHT.")
    return 0


def _cmd_global_attest_tier3(args: argparse.Namespace) -> int:
    """
    Cross-network Tier-3 attestation. See ``cmd_global_attest`` for the
    full mode contract; this function implements the ``--tier 3`` branch.

    Failure modes (each maps to a distinct exit code):

      2 — env: no compositor key, daemon socket unreachable, or no
          validators discovered (and none provided via --peer).
      1 — quorum not met: contacted validators all rejected, or fewer
          than --quorum-k accepted within their per-validator timeout.
      0 — success: cert assembled, self-verified, and published to DHT.
    """
    import json as _json
    from pathlib import Path as _Path

    from gyza.identity import LocalCompositor
    from gyza.network.attestation_adapter import (
        Tier3AttestationError,
        request_tier3_attestation,
    )
    from gyza.network.netd_client import CapabilityClient, NetdClient

    cfg = load_config()
    key_path = _resolve(cfg.compositor_key_path)
    if not _Path(key_path).exists():
        print(
            f"compositor key not found at {key_path}; run `gyza init` first",
            file=sys.stderr,
        )
        return 2

    socket_path = str(_resolve(cfg.netd_socket_path))
    probe = NetdClient(socket_path)
    if not probe.is_running():
        print(
            f"daemon not running at {socket_path}; "
            f"run `gyza global start` first",
            file=sys.stderr,
        )
        probe.close()
        return 2

    compositor = LocalCompositor(str(key_path))
    info = probe.get_node_info()
    print(f"applicant compositor: {compositor.pubkey_hex[:32]}...")
    print(f"applicant peer_id:    {info.peer_id}")
    if args.peer:
        print(f"validators (--peer):  {len(args.peer)} explicit")
    else:
        print(f"validators (DHT):     up to {args.candidate_n} discovered")
    print(f"quorum:               {args.quorum_k} cosignatures")
    print()

    explicit = args.peer if args.peer else None
    try:
        with NetdClient(socket_path) as nc, CapabilityClient(socket_path) as cap:
            result = request_tier3_attestation(
                cap=cap,
                netd=nc,
                compositor=compositor,
                quorum_k=args.quorum_k,
                candidate_n=args.candidate_n,
                explicit_validator_peer_ids=explicit,
                self_verify=True,
            )
    except Tier3AttestationError as e:
        print(f"tier-3 attestation failed: {e}", file=sys.stderr)
        probe.close()
        return 2
    finally:
        probe.close()

    print(f"contacted {len(result.contacted_peer_ids)} validator(s)")
    for pid in result.contacted_peer_ids:
        marker = "✓" if any(c.validator_pubkey == _peer_to_pubkey_hint(pid)
                             for c in result.cosignatures) else "?"
        err = result.per_peer_errors.get(pid, "")
        if err:
            print(f"  ✗  {pid[:24]}...  {err}")
        else:
            print(f"  ✓  {pid[:24]}...  cosig accepted")
    print()

    if result.cert is None:
        print(
            f"quorum not met: {len(result.cosignatures)} of "
            f"{args.quorum_k} cosigs collected",
            file=sys.stderr,
        )
        if "_self_verify" in result.per_peer_errors:
            print(
                f"  self-verify: {result.per_peer_errors['_self_verify']}",
                file=sys.stderr,
            )
        return 1

    print(
        f"quorum met: {len(result.cert.co_signatures)} cosignatures over "
        f"applicant body"
    )
    print(f"  tier:         {result.cert.body.tier_granted}")
    print(f"  issued:       {result.cert.body.issued_at_ns} (ns)")
    print(f"  expires:      {result.cert.body.expires_at_ns} (ns)")
    print()

    # Publish to DHT.
    try:
        with CapabilityClient(socket_path) as cap:
            dht_key = cap.publish_attestation(result.cert)
    except Exception as e:  # noqa: BLE001
        print(
            f"cert assembled but publish failed: {e}",
            file=sys.stderr,
        )
        # Still write the artifact so the operator has it.
        _write_tier3_artifact(result.cert, compositor.pubkey_hex)
        return 1

    print(f"published to DHT: {dht_key}")
    artifact_path = _write_tier3_artifact(result.cert, compositor.pubkey_hex)
    print(f"artifact:         {artifact_path}")
    print()
    print(f"Tier-3 attestation PASSED")
    return 0


def _peer_to_pubkey_hint(_peer_id: str) -> str:
    """
    Placeholder for peer_id → compositor_pubkey resolution. The
    libp2p PeerID encodes the Ed25519 pubkey but converting requires
    libp2p-style multibase decoding. For the CLI's progress display
    we don't actually need this — used as a sentinel that always
    fails the `any(... == ...)` comparison so the per-peer marker
    falls back to "?".
    """
    return ""


def _write_tier3_artifact(cert, compositor_pubkey_hex: str):
    """Write a JSON-serialized cert (proto fields) to disk for inspection."""
    import json as _json
    from pathlib import Path as _Path

    artifact_dir = _Path(_resolve("~/.gyza/attestations"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"cert-{compositor_pubkey_hex[:16]}.json"
    payload = {
        "schema": "gyza.attestation.cert/v1",
        "tier": cert.body.tier_granted,
        "applicant_pubkey": cert.body.applicant_pubkey,
        "issued_at_ns": cert.body.issued_at_ns,
        "expires_at_ns": cert.body.expires_at_ns,
        "challenge_task_ids": list(cert.body.challenge_task_ids),
        "co_signatures": [
            {
                "validator_pubkey": c.validator_pubkey,
                "signature": c.signature.hex(),
                "signed_at_ns": c.signed_at_ns,
            }
            for c in cert.co_signatures
        ],
    }
    artifact_path.write_text(_json.dumps(payload, indent=2))
    return artifact_path


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


# ---------------------------------------------------------------------------
# submit — public demo task submission
# ---------------------------------------------------------------------------

def cmd_submit(args: argparse.Namespace) -> int:
    """
    Submit a free-text task to the public demo project. The user's
    running daemon (started via ``gyza global start``) gossips the
    task to ``gyza-demo-public-v1``; a hosted demo agent claims it,
    runs it, signs an ICP envelope, and pushes the full result back
    to us over a direct libp2p stream. We verify the Ed25519
    signature + the artifact hash, then print the result.

    The verification is the point: you get cryptographic proof that
    this exact output was produced by this exact agent identity at
    this timestamp under this capability manifest — no central
    server, no trust in us.
    """
    import threading
    import time as _time
    import uuid as _uuid

    import blake3

    from gyza.embeddings import embed_work_description
    from gyza.icp import verify_envelope
    from gyza.network.demo_agent import DEMO_PROJECT_ID
    from gyza.network.global_cluster import GlobalCluster
    from gyza.network.netd_client import GossipClient, NetdClient
    from gyza.network.network_blackboard import NetworkBlackboard
    from gyza.network.result_delivery import (
        RESULT_DELIVERY_TYPE,
        decode_delivery,
    )
    from gyza.schema import WorkItem

    cfg = load_config()
    sock = str(_resolve(cfg.netd_socket_path))

    # Sanity: is the daemon running? If not, fail fast with a
    # helpful message rather than blocking on a non-existent socket.
    if not Path(sock).exists():
        print(
            f"daemon socket not found at {sock}\n"
            f"start it first with: gyza global start",
            file=sys.stderr,
        )
        return 2

    # Resolved (tilde-expanded) paths — cfg.* are raw config strings.
    rp = cfg.resolved_paths()
    compositor = LocalCompositor(key_path=rp["compositor_key_path"])
    bb = NetworkBlackboard(rp["blackboard_db_path"])
    netd = NetdClient(sock)
    gossip = GossipClient(sock)

    cluster = GlobalCluster(
        compositor=compositor,
        config=cfg,
        blackboard=bb,
        netd_client=netd,
        gossip_client=gossip,
    )

    # Result-delivery subscription. The executor pushes the full
    # signed envelope + result artifact directly to us over the
    # daemon's point-to-point MessageService — no gossip dependency
    # for the result. Runs on its own NetdClient (own gRPC channel)
    # so the blocking Subscribe stream is independent of every other
    # call. Started BEFORE we post the work item so a fast executor
    # can't deliver into a void.
    sub_netd = NetdClient(sock)
    delivered: dict = {}
    delivered_evt = threading.Event()
    wanted: dict[str, str | None] = {"work_item_id": None}

    def _sub_loop() -> None:
        try:
            for incoming in sub_netd.subscribe_messages([RESULT_DELIVERY_TYPE]):
                try:
                    rd = decode_delivery(incoming.payload)
                except ValueError:
                    continue  # malformed frame — skip, don't crash
                if wanted["work_item_id"] and rd.work_item_id == wanted["work_item_id"]:
                    delivered["rd"] = rd
                    delivered_evt.set()
                    return
        except Exception:  # noqa: BLE001
            # Channel closed (we're shutting down) or transport error.
            pass

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    sub_thread: threading.Thread | None = None
    try:
        loop.run_until_complete(cluster.start())
        gossip.join_project(DEMO_PROJECT_ID)
        bb.attach_gossip(
            gossip, DEMO_PROJECT_ID, node_id=compositor.pubkey_hex,
        )

        sub_thread = threading.Thread(target=_sub_loop, daemon=True)
        sub_thread.start()
        _time.sleep(0.5)  # let the server-side Subscribe register

        # Build the intent + work item. The intent is signed by the
        # local compositor; the work item carries an embedding of
        # the task so the executor's specialization-matching scores
        # it. The intent embeds our compositor_pubkey so the agent
        # can (a) rate-limit per submitter and (b) route the result
        # delivery back to us.
        intent_id = str(_uuid.uuid7())
        bb.post_intent({
            "intent_id": intent_id,
            "natural_text": args.task,
            "category": "public_demo",
            "compositor_pubkey": compositor.pubkey_hex,
            "actions": [],
            "authorization": {
                "resources": [],
                "preview_required": False,
                "reversible": True,
            },
        })

        emb = embed_work_description(args.task)
        wi = WorkItem(
            id=str(_uuid.uuid7()),
            lineage_root=intent_id,
            parent_id=None,
            description=args.task,
            desc_embedding=emb,
            reward=0.5,
            reward_updated_ns=_time.time_ns(),
            required_tier=0,
            input_hashes=[],
            output_spec={"kind": "public_demo"},
            streaming_ok=False,
            claimed_by=None,
            claimed_at_ns=None,
            claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
            completed_at_ns=None,
            output_hash=None,
            icp_envelope_hash=None,
            success=None,
            created_at_ns=_time.time_ns(),
            ttl_ns=3600 * 1_000_000_000,
        )
        wanted["work_item_id"] = wi.id
        bb.post_work_item(wi)

        print(f"[submit] posted intent={intent_id[:16]}… work_item={wi.id[:16]}…")
        print(f"[submit] gossiping to {DEMO_PROJECT_ID} — waiting for a hosted agent…")

        # Wait for the result-delivery push. Announce the claim as a
        # progress signal if we observe it via gossip (best-effort —
        # the delivery push is the load-bearing path).
        start = _time.monotonic()
        deadline = start + args.timeout
        claim_announced = False
        while _time.monotonic() < deadline:
            if delivered_evt.wait(timeout=0.5):
                break
            if not claim_announced:
                items = bb.get_by_lineage(intent_id)
                if items and items[0].claimed_by:
                    print(f"[submit] claimed by {items[0].claimed_by[:16]}…")
                    claim_announced = True

        rd = delivered.get("rd")
        bar = "─" * 72
        if rd is None:
            print(
                f"[submit] timed out after {args.timeout}s waiting for a result.\n"
                f"  - Is a hosted agent running on the demo project? "
                f"(check `gyza global status` peer count)\n"
                f"  - The work item may still complete; the delivery "
                f"push just didn't arrive in time.",
                file=sys.stderr,
            )
            return 3

        # Verify. Two independent checks:
        #   1. Ed25519 signature over the envelope — proves the agent
        #      identity that claims to have done this work actually
        #      signed it.
        #   2. BLAKE3(artifact) == envelope.output_hash — proves the
        #      result bytes we're about to print are exactly what the
        #      envelope commits to (artifact integrity).
        env = rd.envelope
        sig_ok = verify_envelope(env, bytes.fromhex(env.agent_pubkey))
        artifact_hash = blake3.blake3(rd.artifact_bytes).hexdigest()
        artifact_ok = artifact_hash == env.output_hash

        result_text = ""
        enforcement = None
        try:
            payload = json.loads(rd.artifact_bytes.decode("utf-8"))
            if isinstance(payload, dict):
                result_text = payload.get("text", "")
                enforcement = payload.get("__enforcement__")
        except Exception:  # noqa: BLE001
            result_text = "<artifact decode failed>"

        # Independent bounds-proof verification. If the executor
        # delivered the canonical manifest bytes, we can close the
        # trustless gap on brick 3: prove the manifest is the one
        # the envelope commits to (hash match), then re-run
        # enforcement_satisfies_manifest ourselves. Three distinct
        # checks; ALL must pass for "INDEPENDENTLY VERIFIED".
        manifest_hash_ok: bool | None = None
        bounds_within_manifest_ok: bool | None = None
        bounds_failure_reason = ""
        if rd.manifest_bytes is not None:
            mh = blake3.blake3(rd.manifest_bytes).hexdigest()
            manifest_hash_ok = (mh == env.capability_manifest_hash)
            if manifest_hash_ok and isinstance(enforcement, dict):
                try:
                    from gyza.sandbox import enforcement_satisfies_manifest
                    parsed_manifest = json.loads(rd.manifest_bytes.decode("utf-8"))
                    bounds_within_manifest_ok, bounds_failure_reason = \
                        enforcement_satisfies_manifest(enforcement, parsed_manifest)
                except Exception as _e:  # noqa: BLE001
                    bounds_within_manifest_ok = False
                    bounds_failure_reason = f"manifest decode error: {_e}"

        # Runner-attestation axis (G1a / ADR-0017). ORTHOGONAL to the
        # bounds predicate: V4 proves enforcement ⊆ manifest; this
        # proves *which binary* produced that enforcement record.
        # An untrusted build does not flip the result to failure —
        # the bounds are still cryptographically checked — but it
        # caps the strength of the claim, because a malicious build
        # could have stamped a fictitious enforcement record that
        # then trivially satisfies the predicate. Self-reported;
        # trusted-set membership only bounds which lie is accepted.
        runner_version = None
        runner_tree_hash = None
        runner_trusted: bool | None = None
        runner_trust_reason = ""
        if isinstance(enforcement, dict):
            runner_version = enforcement.get("runner_version")
            runner_tree_hash = enforcement.get("runner_source_tree_hash")
            if isinstance(runner_version, str) and isinstance(runner_tree_hash, str):
                try:
                    from gyza.release import is_trusted_release
                    runner_trusted, runner_trust_reason = \
                        is_trusted_release(runner_version, runner_tree_hash)
                except Exception as _e:  # noqa: BLE001
                    runner_trusted = False
                    runner_trust_reason = f"release lookup error: {_e}"

        elapsed = _time.monotonic() - start
        verified = sig_ok and artifact_ok

        print(f"[submit] result delivered + verified in {elapsed:.1f}s")
        print()
        print(bar)
        print(f"  RESULT")
        print(bar)
        print(result_text or "<no text payload>")
        print(bar)
        print(f"  PROVENANCE")
        print(bar)
        print(f"  intent:        {intent_id}")
        print(f"  work item:     {env.action_id}")
        print(f"  signed by:     {env.agent_pubkey}")
        print(f"  model:         {env.model_identifier}")
        print(f"  backend:       {env.inference_backend}")
        print(f"  duration:      {env.duration_ms} ms")
        print(f"  output hash:   {env.output_hash}")
        print(f"  signature:     {'✓ VALID' if sig_ok else '✗ INVALID'}")
        print(f"  artifact hash: {'✓ MATCHES envelope' if artifact_ok else '✗ MISMATCH'}")
        print(bar)
        # Bounds-proof. If the artifact carries an __enforcement__
        # record, the agent's runner executed this work inside a
        # kernel-enforced sandbox AND refused to sign unless that
        # sandbox was no wider than its capability manifest (see
        # runner._execute). Because the record is INSIDE the hashed
        # artifact, the signature above also commits to it — these
        # bounds are tamper-evident, not a claim you take on trust.
        if isinstance(enforcement, dict):
            ro = enforcement.get("ro_paths") or []
            rw = enforcement.get("rw_paths") or []
            print(f"  BOUNDS-PROOF (committed in the signed artifact)")
            print(bar)
            print(f"  sandbox:       {enforcement.get('backend', '?')}"
                  f" (kernel-enforced)")
            print(f"  fs read:       {ro if ro else 'NONE (no host filesystem)'}")
            print(f"  fs write:      {rw if rw else 'NONE (no host filesystem)'}")
            print(f"  network:       "
                  f"{'open' if enforcement.get('requires_network') else 'NONE'}")
            mem = enforcement.get("max_memory_mb")
            if isinstance(mem, int) and mem > 0:
                print(f"  memory cap:    {mem} MB (RLIMIT_AS)")
            cpu = enforcement.get("max_cpu_seconds")
            if isinstance(cpu, int) and cpu > 0:
                print(f"  cpu cap:       {cpu} s (RLIMIT_CPU)")
            # Show the three independent verification lines whenever
            # the executor delivered the manifest. Each is a distinct
            # cryptographic / predicate check the submitter ran here,
            # not a value reported by the runner.
            if manifest_hash_ok is not None:
                print(f"  manifest hash: "
                      f"{'✓ MATCHES envelope' if manifest_hash_ok else '✗ MISMATCH'}")
            if bounds_within_manifest_ok is not None:
                label = (
                    "✓ enforcement ⊆ manifest (re-verified here)"
                    if bounds_within_manifest_ok
                    else f"✗ violation: {bounds_failure_reason}"
                )
                print(f"  bounds check:  {label}")
            # Runner identity — which binary stamped this enforcement
            # record (G1a). Orthogonal to the predicate above.
            if isinstance(runner_version, str):
                if runner_trusted is True:
                    rstate = "✓ trusted release"
                elif runner_trusted is False:
                    rstate = f"⚠ unverified build — {runner_trust_reason}"
                else:
                    rstate = "not reported"
                short = (runner_tree_hash[:12] + "…") \
                    if isinstance(runner_tree_hash, str) else "?"
                print(f"  runner build:  {runner_version} "
                      f"(tree {short})  {rstate}")
            print(bar)
        # Aggregate verdict — sig + artifact integrity for the
        # provenance proof; manifest hash + bounds predicate for the
        # bounds proof (when claimed at all).
        bounds_claimed = isinstance(enforcement, dict)
        bounds_independently_verified = (
            bounds_claimed
            and manifest_hash_ok is True
            and bounds_within_manifest_ok is True
        )
        bounds_claimed_but_unverifiable = (
            bounds_claimed and rd.manifest_bytes is None
        )
        bounds_claim_failed = (
            bounds_claimed
            and rd.manifest_bytes is not None
            and (manifest_hash_ok is False or bounds_within_manifest_ok is False)
        )
        all_ok = verified and (
            not bounds_claimed or bounds_independently_verified
        )

        if all_ok and bounds_independently_verified and runner_trusted is True:
            print("  ✓ cryptographically verified — this output was produced")
            print("    by the agent identity above, signed, tamper-evident.")
            print("  ✓ bounded (INDEPENDENTLY VERIFIED + RUNNER ATTESTED) —")
            print("    you re-hashed the manifest and re-ran the bounds")
            print("    predicate here, AND the binary that stamped the")
            print("    enforcement record is a trusted release. This is the")
            print("    strongest claim the protocol makes.")
        elif all_ok and bounds_independently_verified:
            print("  ✓ cryptographically verified — this output was produced")
            print("    by the agent identity above, signed, tamper-evident.")
            print("  ✓ bounded (INDEPENDENTLY VERIFIED) — you re-hashed the")
            print("    manifest and re-ran the bounds predicate on this")
            print("    machine. The enforcement record satisfies the")
            print("    manifest.")
            print("  ⚠ runner build is NOT a verified release — a malicious")
            print("    build could have stamped a fictitious enforcement")
            print(f"    record. {runner_trust_reason}")
        elif verified and bounds_claimed_but_unverifiable:
            print("  ✓ cryptographically verified — this output was produced")
            print("    by the agent identity above, signed, tamper-evident.")
            print("  ⚠ bounds CLAIMED but not independently verifiable — the")
            print("    executor did not deliver the manifest bytes. The")
            print("    bounds shown are committed in the signature but rely")
            print("    on trusting the runner's gate.")
        elif verified and not bounds_claimed:
            print("  ✓ cryptographically verified — this output was produced")
            print("    by the agent identity above, signed, tamper-evident.")
            print("  • no bounds-proof — this envelope makes no claim about")
            print("    sandbox enforcement (v1 / legacy executor).")
        elif bounds_claim_failed:
            print("  ✗ BOUNDS-PROOF FAILED — the executor's claimed bounds do")
            print("    NOT match its declared manifest. Do not trust this")
            print("    result as bounded. (Signature itself may still be")
            print("    valid — see lines above.)")
        else:
            print("  ✗ VERIFICATION FAILED — do not trust this result.")
        print(bar)
        return 0 if all_ok else 5
    finally:
        # Close the subscription channel first — that unblocks the
        # _sub_loop iterator so the thread can exit.
        try:
            sub_netd.close()
        except Exception:  # noqa: BLE001
            pass
        if sub_thread is not None:
            sub_thread.join(timeout=2.0)
        try:
            loop.run_until_complete(cluster.stop())
        except Exception:  # noqa: BLE001
            pass
        loop.close()


# ---------------------------------------------------------------------------
# watch — live view of the public demo project
# ---------------------------------------------------------------------------

def cmd_watch(args: argparse.Namespace) -> int:
    """
    Live view of the public demo project: stream and pretty-print
    every work-item-lifecycle event — intent posted, work item
    posted, claimed, completed — as it happens on the network.

    Scope, honestly: gossip is per-topic, so this shows the project
    you're watching (``gyza-demo-public-v1`` by default — where all
    public ``gyza submit`` traffic flows), not "the whole network".
    Settlement is point-to-point libp2p and is NOT gossiped, so it
    doesn't appear here. What you see is the work lifecycle.

    Read-only: joining the topic to receive deltas also makes this
    node a gossip relay for it — which slightly *helps* mesh
    reliability — but `gyza watch` never posts anything.
    """
    import datetime as _dt
    import time as _time

    from gyza.network.demo_agent import DEMO_PROJECT_ID
    from gyza.network.netd_client import GossipClient, NetdClient

    use_color = sys.stdout.isatty()

    def c(code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if use_color else s

    # A live-streaming tool MUST flush every line. Python block-buffers
    # stdout when it isn't a tty (piped / redirected / under a process
    # supervisor), so without an explicit flush nothing appears until
    # the buffer fills or the process exits cleanly — and a SIGTERM
    # (e.g. `timeout`, systemd stop) then loses the whole buffer.
    def out(s: str = "", *, file=None) -> None:
        print(s, flush=True, file=file or sys.stdout)

    cfg = load_config()
    sock = str(_resolve(cfg.netd_socket_path))
    if not Path(sock).exists():
        out(
            f"daemon socket not found at {sock}\n"
            f"start it first with: gyza global start",
            file=sys.stderr,
        )
        return 2

    project = args.project or DEMO_PROJECT_ID
    netd = NetdClient(sock)
    gossip = GossipClient(sock)

    def ts(ns: int) -> str:
        if not ns:
            ns = _time.time_ns()
        return _dt.datetime.fromtimestamp(ns / 1e9).strftime("%H:%M:%S")

    try:
        info = netd.get_node_info()
        status = netd.get_status()
    except Exception as e:  # noqa: BLE001
        out(f"could not query daemon: {e}", file=sys.stderr)
        return 2

    bar = "─" * 72
    out(bar)
    out(f"  gyza watch — live view of {project}")
    out(f"  daemon {info.peer_id[:20]}…  ·  {status.connected_peers} peers connected")
    out(bar)
    out("  shows OTHER peers' activity on this project. The daemon")
    out("  suppresses self-loops, so your own submits don't appear")
    out("  here — see `gyza submit`'s own output for those.")
    out()

    try:
        gossip.join_project(project)
    except Exception as e:  # noqa: BLE001
        out(f"join_project failed: {e}", file=sys.stderr)
        return 1

    # Bounded dedup — gossipsub can redeliver a delta; we don't want
    # the same event printed twice. Keyed by (kind, id...).
    seen: set = set()

    def first_time(key: tuple) -> bool:
        if key in seen:
            return False
        seen.add(key)
        if len(seen) > 8192:
            seen.clear()
        return True

    try:
        for delta in gossip.subscribe_deltas([project]):
            for it in delta.new_intents:
                if not first_time(("intent", it.intent_id)):
                    continue
                text = ""
                try:
                    spec = json.loads(it.goal_spec_json)
                    if isinstance(spec, dict):
                        text = spec.get("natural_text", "")
                except Exception:  # noqa: BLE001
                    pass
                out(f"  {ts(it.created_at_ns)}  {c('36', 'intent    ')} "
                      f"{it.intent_id[:12]}…  \"{text[:52]}\"")
            for w in delta.new_items:
                if not first_time(("item", w.id)):
                    continue
                out(f"  {ts(w.created_at_ns)}  {c('36', 'work item ')} "
                      f"{w.id[:12]}…  tier-{w.required_tier} "
                      f"reward {w.reward:.2f}  \"{w.description[:40]}\"")
            for cl in delta.claim_updates:
                if not first_time(("claim", cl.work_item_id, cl.agent_pubkey)):
                    continue
                out(f"  {ts(delta.timestamp_ns)}  {c('33', 'claimed   ')} "
                      f"{cl.work_item_id[:12]}…  ← agent {cl.agent_pubkey[:12]}…")
            for cp in delta.completions:
                if not first_time(("done", cp.work_item_id)):
                    continue
                mark = (c('32', '✓ success') if cp.success
                        else c('31', '✗ failed'))
                out(f"  {ts(cp.completed_at_ns)}  {c('32', 'completed ')} "
                      f"{cp.work_item_id[:12]}…  {mark}  "
                      f"output {cp.output_hash[:12]}…")
    except KeyboardInterrupt:
        out("\n  watch stopped.")
    finally:
        try:
            gossip.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            netd.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


# ---------------------------------------------------------------------------
# demo-agent — long-running hosted executor
# ---------------------------------------------------------------------------

def cmd_demo_agent(args: argparse.Namespace) -> int:
    """
    Run a hosted demo agent that claims work items posted to the
    public demo project. Long-running; intended for systemd or a
    bootstrap-node sidecar process. Blocks on SIGTERM/SIGINT.
    """
    from gyza.network.demo_agent import run_hosted_demo_agent
    return run_hosted_demo_agent(socket_path=args.socket_path)


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
        choices=["pipeline", "injection", "lan", "global", "bounds"],
        default="pipeline",
        help=(
            "pipeline (default — Phase-1 two-agent local demo), "
            "injection (tamper attack on the envelope chain), "
            "lan (Phase-2 single-machine cluster sim), "
            "global (Phase-3 end-to-end: two daemons on loopback "
            "complete a project through bilateral settlement; needs "
            "gyza-netd binary)"
        ),
    )

    sub.add_parser("status", help="show blackboard, artifact store, and cluster stats")

    p_audit = sub.add_parser(
        "audit",
        help="forensically audit a stored workflow's provenance DAG + bounds",
    )
    p_audit.add_argument(
        "intent_id", nargs="?",
        help="intent to audit; omit to list intents with logged envelopes",
    )

    p_run = sub.add_parser(
        "run",
        help="execute one task bounded + flight-recorded: real sandbox, "
             "signed envelope, auditable receipt",
    )
    p_run.add_argument("task", help="what the agent should do")
    p_run.add_argument(
        "--memory-mb", type=int, default=512,
        help="memory bound for the agent's manifest AND sandbox (default 512)",
    )
    p_run.add_argument(
        "--mock", action="store_true",
        help="force the mock executor (no AI call) even if an API key is set",
    )
    p_run.add_argument(
        "--model", default=None,
        help="model for the anthropic executor (default: config default_model)",
    )
    p_run.add_argument(
        "--allow-read", action="append", default=[], metavar="PATH",
        help="host path the agent may read (repeatable; kernel-enforced "
             "read-only bind; becomes part of the signed grant)",
    )
    p_run.add_argument(
        "--allow-write", action="append", default=[], metavar="PATH",
        help="host path the agent may write (repeatable; use sparingly)",
    )

    p_exec = sub.add_parser(
        "exec",
        help="run YOUR command bounded + flight-recorded: "
             "gyza exec [flags] -- COMMAND [ARGS...]",
    )
    p_exec.add_argument(
        "--memory-mb", type=int, default=512,
        help="memory bound (RLIMIT_AS) for the command (default 512)",
    )
    p_exec.add_argument(
        "--allow-read", action="append", default=[], metavar="PATH",
        help="host path the command may read (repeatable)",
    )
    p_exec.add_argument(
        "--allow-write", action="append", default=[], metavar="PATH",
        help="host path the command may write (repeatable; use sparingly)",
    )
    p_exec.add_argument(
        "--allow-network", action="store_true",
        help="open the network namespace (all-or-nothing; declared in "
             "the signed grant)",
    )
    p_exec.add_argument(
        "argv", nargs=argparse.REMAINDER,
        help="the command to run (prefix with -- to stop flag parsing)",
    )

    p_bundle = sub.add_parser(
        "bundle",
        help="export a stored workflow as a portable evidence bundle "
             "(verifiable by anyone via 'gyza verify')",
    )
    p_bundle.add_argument("intent_id", help="intent whose provenance to export")
    p_bundle.add_argument(
        "-o", "--output", default=None,
        help="output path (default: gyza-evidence-<intent12>.json)",
    )

    p_verify = sub.add_parser(
        "verify",
        help="verify an evidence bundle offline — no node, daemon, or "
             "identity required",
    )
    p_verify.add_argument("bundle", help="path to a gyza-evidence-bundle file")

    # Public demo task submission. Submits a free-text task to the
    # gyza-demo-public-v1 project, waits for a hosted agent on the
    # network to claim it, then verifies + prints the signed result.
    p_submit = sub.add_parser(
        "submit",
        help="post a free-text task to the public demo network and wait for a signed result",
    )
    p_submit.add_argument(
        "task",
        help="free-text task description (e.g. \"summarize https://example.com\")",
    )
    p_submit.add_argument(
        "--timeout", type=float, default=60.0,
        help="max seconds to wait for a hosted agent to complete the work (default 60)",
    )

    # Live view of the public demo project's work-item lifecycle.
    p_watch = sub.add_parser(
        "watch",
        help="live-stream the public demo project: intents, claims, completions",
    )
    p_watch.add_argument(
        "--project", default=None,
        help="project topic to watch (default: the public demo project)",
    )

    # Long-running hosted agent. Claims public demo work items and
    # signs results. Intended for systemd / sidecar deployment.
    p_demoagent = sub.add_parser(
        "demo-agent",
        help="run a hosted demo executor that claims and signs public demo work",
    )
    p_demoagent.add_argument(
        "--socket-path", default=None,
        help="gyza-netd socket (defaults to config.netd_socket_path)",
    )

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
    p_attest = globsub.add_parser(
        "attest",
        help="run the canonical eval suite + emit an attestation artifact",
    )
    p_attest.add_argument(
        "--tier", type=int, choices=(1, 3), default=1,
        help=(
            "attestation tier. 1 = local self-attestation (default, "
            "no daemon needed). 3 = cross-network quorum attestation "
            "(requires running daemon + reachable Tier-3 validators)."
        ),
    )
    p_attest.add_argument(
        "--peer", action="append", default=[],
        help=(
            "(--tier 3 only) explicit validator peer ID. May be repeated. "
            "Skips DHT discovery; uses these peers in order. The applicant "
            "must already be libp2p-connected to each (use `gyza global "
            "connect` if needed)."
        ),
    )
    p_attest.add_argument(
        "--quorum-k", type=int, default=2,
        help="(--tier 3 only) cosignatures needed for quorum (default 2)",
    )
    p_attest.add_argument(
        "--candidate-n", type=int, default=3,
        help=(
            "(--tier 3 only) max validators to contact via DHT discovery "
            "(ignored when --peer is provided; default 3)"
        ),
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
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "exec":
        return cmd_exec(args)
    if args.command == "bundle":
        return cmd_bundle(args)
    if args.command == "verify":
        return cmd_verify(args)
    if args.command == "submit":
        return cmd_submit(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "demo-agent":
        return cmd_demo_agent(args)
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
