from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = REPO_ROOT / "demo" / "two_machine_demo.py"


def _free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run_pair(shared: Path, timeout_s: float = 240.0) -> tuple[int, int, str, str]:
    """Run the coordinator+executor pair as the demo does. Returns
    (coord_rc, exec_rc, coord_stdout, exec_stdout)."""
    cq, cr = _free_tcp_port(), _free_tcp_port()
    eq, er = _free_tcp_port(), _free_tcp_port()
    py = sys.executable

    env = os.environ.copy()
    # Ensure mock executor is used — keeps the test deterministic + fast.
    env.pop("ANTHROPIC_API_KEY", None)

    coord = subprocess.Popen(
        [py, str(DEMO_SCRIPT),
         "--role", "coordinator",
         "--quic-port", str(cq), "--raft-port", str(cr),
         "--peer-raft-addr", f"127.0.0.1:{er}",
         "--shared-dir", str(shared)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=env,
    )
    time.sleep(0.5)
    exec_p = subprocess.Popen(
        [py, str(DEMO_SCRIPT),
         "--role", "executor",
         "--quic-port", str(eq), "--raft-port", str(er),
         "--peer-raft-addr", f"127.0.0.1:{cr}",
         "--shared-dir", str(shared)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=env,
    )

    try:
        coord_out, _ = coord.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        coord.kill(); exec_p.kill()
        coord_out = (coord.stdout.read() if coord.stdout else "") or ""
        exec_out = (exec_p.stdout.read() if exec_p.stdout else "") or ""
        return -1, -1, coord_out, exec_out

    try:
        exec_out, _ = exec_p.communicate(timeout=30.0)
    except subprocess.TimeoutExpired:
        exec_p.kill()
        exec_out = (exec_p.stdout.read() if exec_p.stdout else "") or ""

    return coord.returncode, exec_p.returncode, coord_out, exec_out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_full_pipeline_local_simulation(tmp_path):
    shared = tmp_path / "phase2-pipeline"
    rc_c, rc_e, coord_out, exec_out = _run_pair(shared, timeout_s=240.0)

    assert rc_c == 0, (
        f"coordinator failed (rc={rc_c}). Last output:\n{coord_out[-2000:]}"
    )
    assert rc_e == 0, (
        f"executor failed (rc={rc_e}). Last output:\n{exec_out[-2000:]}"
    )

    # Coordinator output should contain the verdict.
    assert "CHAIN INTEGRITY: VALID ✓" in coord_out
    assert "Cross-compositor trust: VERIFIED ✓" in coord_out
    assert "WORK ITEM 1: File Analysis" in coord_out
    assert "WORK ITEM 2: Architecture Summary" in coord_out

    # Executor signed exactly two envelopes, both completed.
    assert "completed_count=2" in exec_out
    # Two envelopes appeared on the shared filesystem.
    envs = list((shared / "envelopes").glob("*.json"))
    assert len(envs) == 2, f"expected 2 envelopes, got {len(envs)}"


def test_cluster_forms_within_15s(tmp_path):
    """The coordinator's status line reports cluster-formation latency.
    Confirm it's a small two-digit-ms number well under 15s."""
    shared = tmp_path / "phase2-form"
    rc_c, rc_e, coord_out, _exec_out = _run_pair(shared, timeout_s=240.0)
    assert rc_c == 0
    assert rc_e == 0
    # Look for the latency line.
    import re
    m = re.search(r"Cluster formed: (\d+)ms", coord_out)
    assert m is not None, f"no cluster-formation latency line; output:\n{coord_out[-1500:]}"
    formation_ms = int(m.group(1))
    assert formation_ms < 15_000, (
        f"cluster took {formation_ms}ms to form (>15s budget)"
    )


def test_chain_has_two_envelopes_with_distinct_envelope_hashes(tmp_path):
    """Both work items got signed envelopes; the parent-hash linkage is
    intact (verify_chain_multi_compositor said VALID, but also check the
    structural invariant directly)."""
    import json

    from gyza.icp import ICPEnvelope, compute_envelope_hash

    shared = tmp_path / "phase2-chain"
    rc_c, rc_e, _coord_out, _exec_out = _run_pair(shared, timeout_s=240.0)
    assert rc_c == 0 and rc_e == 0

    env_dir = shared / "envelopes"
    envelopes = []
    for p in env_dir.glob("*.json"):
        envelopes.append(ICPEnvelope(**json.loads(p.read_text())))
    envelopes.sort(key=lambda e: e.timestamp_ns)
    assert len(envelopes) == 2

    e1, e2 = envelopes
    assert e1.parent_envelope_hash is None
    assert e2.parent_envelope_hash == compute_envelope_hash(e1)
    # Same agent in this single-executor demo, but two distinct envelope hashes.
    assert compute_envelope_hash(e1) != compute_envelope_hash(e2)
