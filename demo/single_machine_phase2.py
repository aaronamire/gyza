"""
Single-machine simulation of the Phase 2 two-machine demo.

Spawns coordinator and executor as two subprocesses on localhost,
each on its own QUIC + Raft ports. The two processes share a
filesystem directory for the artifact store, persisted manifests,
and signed envelopes — that's the lab-bench substitute for what
the artifact server/client + transport would do across a real LAN.

Usage:
    python demo/single_machine_phase2.py
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    demo_script = repo_root / "demo" / "two_machine_demo.py"

    shared = Path.home() / ".gyza" / "demo-phase2"
    if shared.exists():
        shutil.rmtree(shared)
    shared.mkdir(parents=True, exist_ok=True)

    coord_quic = _free_tcp_port()
    coord_raft = _free_tcp_port()
    exec_quic = _free_tcp_port()
    exec_raft = _free_tcp_port()

    py = sys.executable
    coord_cmd = [
        py, str(demo_script),
        "--role", "coordinator",
        "--quic-port", str(coord_quic),
        "--raft-port", str(coord_raft),
        "--peer-raft-addr", f"127.0.0.1:{exec_raft}",
        "--shared-dir", str(shared),
    ]
    exec_cmd = [
        py, str(demo_script),
        "--role", "executor",
        "--quic-port", str(exec_quic),
        "--raft-port", str(exec_raft),
        "--peer-raft-addr", f"127.0.0.1:{coord_raft}",
        "--shared-dir", str(shared),
    ]

    # Start coordinator first so its Raft listener is up before the
    # executor tries to dial.
    coord = subprocess.Popen(
        coord_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True,
    )
    time.sleep(0.4)
    exec_p = subprocess.Popen(
        exec_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True,
    )

    print(f"[host] coordinator pid={coord.pid} (quic={coord_quic}, raft={coord_raft})")
    print(f"[host] executor    pid={exec_p.pid} (quic={exec_quic}, raft={exec_raft})")
    print(f"[host] shared dir: {shared}")
    print("─" * 60)

    # Drain coordinator output to stdout in real time. When coordinator
    # exits, signal the executor (via the done sentinel that coordinator
    # already drops) and reap it.
    rc_coord = 0
    try:
        assert coord.stdout is not None
        for line in coord.stdout:
            print(f"[C] {line}", end="")
        rc_coord = coord.wait(timeout=5)
    except subprocess.TimeoutExpired:
        coord.kill()
        rc_coord = -1

    # Give executor a moment to see the done sentinel.
    try:
        rc_exec = exec_p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        exec_p.kill()
        rc_exec = -1

    # Print any executor output that wasn't already streamed.
    if exec_p.stdout is not None:
        try:
            tail = exec_p.stdout.read()
            if tail:
                print("─" * 60)
                print("[host] executor output:")
                for line in tail.splitlines():
                    print(f"[E] {line}")
        except Exception:
            pass

    print("─" * 60)
    print(f"[host] coordinator rc={rc_coord}  executor rc={rc_exec}")
    return rc_coord


if __name__ == "__main__":
    sys.exit(main())
