"""
Executor factories that are LIGHT TO IMPORT — and that is the whole point.

`make_sandboxed_executor` spawns a fresh interpreter inside bwrap and RE-IMPORTS
the factory's module on every single action. These factories used to live in
`gyza/runner.py`, so every sandboxed action paid for numpy, blake3 and
cryptography before it could run `uname`. Measured on 2026-08-25:

    bare interpreter        0.034 s
    import gyza             0.039 s
    import gyza.sandbox     0.207 s
    import gyza.runner      0.525 s      <- what every action used to pay

At the 500-agent ladder that import was the dominant per-action cost: service
time was ~2.6 s against a research figure of 305 ms, and throughput sat flat at
~3 actions/sec however many agents were added.

**THIS MODULE MUST STAY CHEAP TO IMPORT.** It lives at the top level rather
than under `gyza/sandbox/` because that package costs 0.207 s to reach, and it
imports nothing beyond the standard library. `subprocess` and `shlex` are
imported inside the function body, not at module scope, so even a mock action
does not pay for them. A test asserts the cost, so an accidental heavy import
here fails loudly rather than quietly taxing every sandboxed action in the
fleet.
"""
from __future__ import annotations

import os
from typing import Callable


def make_mock_executor(response: str = "mock output") -> Callable[[str, dict], dict]:
    def _executor(_prompt: str, _context: dict) -> dict:
        return {
            "text": response,
            "tokens_in": 10,
            "tokens_out": 5,
            "model_identifier": "mock",
            "inference_backend": "mock",
        }
    return _executor


def make_planning_executor(
    parts: int = 2,
    combine: bool = True,
    description: str = "subtask",
) -> Callable[[str, dict], dict]:
    """An executor whose action is to REQUEST A DECOMPOSITION.

    The reference implementation of the `__subtasks__` contract, and the
    counterpart to `make_command_executor`: one does external work, this one
    divides it. An executor asks for a split exactly as the sandbox wrapper
    stamps `__enforcement__` -- by returning a key the runner recognises --
    so decomposition needs no separate code path and inherits the signing
    gate, the manifest spawn bound and the depth cap unchanged.

    THE SPLIT HERE IS SCRIPTED, AND THAT IS THE HONEST SHAPE FOR A REFERENCE
    IMPLEMENTATION. In a real deployment the decision of how to divide a task
    comes from a model, and whether that division is GOOD is a correctness
    property of natural-language reasoning, which this program measured as not
    cheaply verifiable. What the substrate can prove is unchanged either way:
    that the split stayed inside the signed grant, and which children it
    produced. Bounding the decision is the mechanism; judging it is not.
    """
    def _executor(_prompt: str, _context: dict) -> dict:
        subs: list[dict] = [{"description": f"{description} {i}"}
                            for i in range(parts)]
        if combine:
            subs.append({"description": f"combine {parts} result(s)",
                         "output_spec": {"kind": "combine"}})
        return {
            "text": f"decomposed into {parts} part(s)"
                    f"{' plus a combiner' if combine else ''}",
            "__subtasks__": subs,
            "tokens_in": 0, "tokens_out": 0,
            "model_identifier": "scripted-planner",
            "inference_backend": "none",
        }
    return _executor


def make_command_executor(
    argv: list[str],
    max_output_bytes: int = 1_000_000,
    cwd: str | None = None,
) -> Callable[[str, dict], dict]:
    """
    Run one arbitrary command as the agent's action — the `gyza exec`
    executor. Designed to be instantiated INSIDE the sandbox (via
    ``make_sandboxed_executor``), so the child process inherits the
    sandbox's namespaces and rlimits: bwrap's mount/net isolation and
    RLIMIT_AS/RLIMIT_CPU apply to the command, not just to this wrapper.

    The command line itself is folded into the artifact text (the
    ``$ ...`` header), so the signed ``output_hash`` commits to WHAT ran,
    not just what it printed. A non-zero exit raises — surfacing as an
    execution failure so no envelope is signed: a valid signed envelope
    keeps implying completed, bounded work.

    ``argv[0]`` should be an absolute path (the sandbox has a fresh
    environment; the CLI resolves it host-side before entering).

    ``cwd`` is the directory to run the command in. It must be a path
    that is visible (bound) inside the sandbox — the CLI passes the host
    working directory only when that directory is among the granted
    paths, so a relative-path command (``cat notes.txt``) works exactly
    where the user launched it. ``None`` runs in the fresh /workspace
    tmpfs.
    """
    def _executor(_prompt: str, _context: dict) -> dict:
        import shlex
        import subprocess

        run_cwd = cwd if cwd and os.path.isdir(cwd) else None
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": run_cwd or os.getcwd(),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        proc = subprocess.run(
            argv, capture_output=True, env=env, check=False, cwd=run_cwd,
        )
        out = proc.stdout[:max_output_bytes]
        truncated = len(proc.stdout) > max_output_bytes
        if proc.returncode != 0:
            tail = proc.stderr[-2000:].decode("utf-8", "replace")
            raise RuntimeError(
                f"command exited {proc.returncode}: {tail.strip()}"
            )
        text = f"$ {shlex.join(argv)}\n[exit 0]\n" + out.decode("utf-8", "replace")
        if truncated:
            text += f"\n[output truncated at {max_output_bytes} bytes]"
        return {
            "text": text,
            "tokens_in": 0,
            "tokens_out": 0,
            "model_identifier": f"exec:{os.path.basename(argv[0])}",
            "inference_backend": "subprocess",
        }
    return _executor
