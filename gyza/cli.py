"""
Minimal Gyza CLI.

Subcommands:
  init                Initialize ~/.gyza, generate compositor key
  demo                Run the two-agent pipeline demo
  demo injection      Run the injection-attack demo
  status              Show blackboard stats and pending work items

Designed to be runnable as both `python -m gyza.cli ...` and (after
install) `gyza ...`. No third-party CLI deps; argparse only.
"""
from __future__ import annotations

import argparse
import json
import runpy
import sqlite3
import sys
import time
from pathlib import Path

from gyza.config import GyzaConfig, load_config
from gyza.identity import LocalCompositor


def _resolve(p: str) -> Path:
    return Path(p).expanduser()


def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    home = _resolve("~/.gyza")
    home.mkdir(parents=True, exist_ok=True)
    out_dir = home / "output"
    out_dir.mkdir(exist_ok=True)
    revoke_dir = home / "revocations"
    revoke_dir.mkdir(exist_ok=True)

    # Touch the master compositor seed so the home dir is fully provisioned.
    compositor = LocalCompositor(key_path=cfg.compositor_key_path)
    config_path = home / "config.json"
    if not config_path.exists():
        # Persist the resolved config (minus the API key) so users can edit it.
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
        }
        config_path.write_text(json.dumps(snapshot, indent=2))

    print(f"gyza home:       {home}")
    print(f"compositor key:  {cfg.compositor_key_path}")
    print(f"compositor pk:   {compositor.pubkey_hex}")
    print(f"config:          {config_path}")
    print(f"output dir:      {out_dir}")
    print("ready.")
    return 0


def _run_demo_script(name: str) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "demo" / name
    if not script.exists():
        print(f"demo script not found: {script}", file=sys.stderr)
        return 2
    # Make sure both the gyza package and the demo dir are importable.
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    runpy.run_path(str(script), run_name="__main__")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    if args.scenario == "injection":
        return _run_demo_script("injection_demo.py")
    return _run_demo_script("two_agent_pipeline.py")


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    bb_path = _resolve(cfg.blackboard_db_path)
    if not bb_path.exists():
        print(f"no blackboard at {bb_path} — run `gyza init` then `gyza demo` first")
        return 1

    # Connect read-only so we don't fight a live runner for the writer lock.
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
        # Active agents = distinct claimers of in-flight items.
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

    print(f"gyza blackboard: {bb_path}")
    print(f"  intents:        {intents}")
    print(f"  work items:     {items}")
    print(f"    unclaimed:    {unclaimed}")
    print(f"    in-flight:    {in_flight}")
    print(f"    completed:    {completed}")
    print(f"  artifacts:      {artifacts}")
    print(f"  active agents:  {len(active)}")
    for a in active:
        pk = a["claimed_by"] or "?"
        print(f"    - {pk[:16]}…")
    print()
    print("recent work items:")
    for r in recent:
        state = "done" if r["completed_at_ns"] else ("in-flight" if r["claimed_by"] else "queued")
        desc = (r["description"] or "")[:60]
        print(f"  [{state:9s}] r={r['reward']:.2f}  {r['id'][:8]}…  {desc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gyza", description="Gyza coordination network CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize ~/.gyza and generate compositor key")

    p_demo = sub.add_parser("demo", help="run a Gyza demo")
    p_demo.add_argument(
        "scenario",
        nargs="?",
        choices=["pipeline", "injection"],
        default="pipeline",
        help="which demo to run (default: pipeline)",
    )

    sub.add_parser("status", help="show blackboard stats")

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
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
