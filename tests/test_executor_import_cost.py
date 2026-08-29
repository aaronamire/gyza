"""`gyza.executors` must stay cheap to import.

`make_sandboxed_executor` spawns a fresh interpreter inside bwrap and
RE-IMPORTS the factory's module on EVERY action. These factories used to live
in `gyza/runner.py`, so every sandboxed action paid for numpy, blake3 and
cryptography before it could run `uname` — measured at 0.51 s per action, which
was the dominant cost at the 500-agent ladder and held throughput flat at ~3
actions/sec however many agents were added.

A heavy import added here would not fail anything. It would quietly tax every
sandboxed action in the fleet, which is why the cost is asserted rather than
described in a comment.
"""
from __future__ import annotations

import subprocess
import sys

import pytest


def _import_cost(mod: str, n: int = 3) -> float:
    import time
    best = float("inf")
    for _ in range(n):
        t0 = time.monotonic()
        subprocess.run([sys.executable, "-c", f"import {mod}"],
                       capture_output=True)
        best = min(best, time.monotonic() - t0)
    return best


def test_the_light_module_is_MUCH_cheaper_than_the_runner():
    """A ratio, not an absolute: absolute timings vary by machine and would
    make this flaky, while the ratio is the property that matters."""
    light = _import_cost("gyza.executors")
    heavy = _import_cost("gyza.runner")
    assert light * 3 < heavy, (
        f"gyza.executors ({light:.3f}s) is no longer much cheaper than "
        f"gyza.runner ({heavy:.3f}s); a heavy import has crept in and every "
        f"sandboxed action now pays for it"
    )


def test_it_pulls_in_NOTHING_heavy():
    """Named rather than timed, so the failure message says WHICH import."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, gyza.executors; "
         "print(','.join(sorted(m for m in ('numpy','blake3','cryptography',"
         "'sentence_transformers','torch','sqlite3') if m in sys.modules)))"],
        capture_output=True, text=True)
    heavy = [m for m in out.stdout.strip().split(",") if m]
    assert heavy == [], f"gyza.executors now imports: {heavy}"


def test_the_factories_are_still_reachable_from_the_runner():
    """Every existing caller imports them from `gyza.runner`; the qualname
    passed to the sandbox is what moved, not the Python import path."""
    from gyza.runner import (
        make_command_executor, make_mock_executor, make_planning_executor,
    )
    assert make_mock_executor("x")("", {})["text"] == "x"


def test_the_sandbox_call_sites_name_the_LIGHT_module():
    """A cheap module nothing points at saves nothing."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    stale = []
    for p in list((root / "gyza").rglob("*.py")):
        t = p.read_text()
        for f in ("make_mock_executor", "make_command_executor",
                  "make_planning_executor"):
            if f"gyza.runner:{f}" in t:
                stale.append(f"{p.relative_to(root)} -> {f}")
    assert stale == [], stale
