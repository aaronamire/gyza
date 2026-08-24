"""Spawn authority must be REACHABLE from a production entry point.

On 2026-08-23 the runner learned to decompose a task into subtasks, bounded by
`spawn.permitted` and `max_children` from the compositor-signed manifest. On
2026-08-24 an AST census over every `issue_agent` call site in `gyza/` found
**9 of 9 granting no spawn authority at all**, so the capability was real,
tested, and unreachable from every production path.

That is this program's signature failure -- "ask what supplies the quantity,
not whether the checker exists" -- with the halves reversed: previously the
grant existed and nothing consumed it; now the consumer existed and nothing
granted it.
"""
from __future__ import annotations

import json

import pytest

from gyza.cli import _load_or_issue_local_agent
from gyza.identity import LocalCompositor


def _comp(tmp_path):
    return LocalCompositor(key_path=str(tmp_path / "k.key"))


def _spawn(ident):
    return ident.manifest["capabilities"]["spawn"]


def test_the_DEFAULT_grants_no_spawn_authority(tmp_path):
    """Least privilege. An operator who says nothing gets an agent that cannot
    create work for anyone."""
    i = _load_or_issue_local_agent(
        _comp(tmp_path), tmp_path / "a.json", memory_mb=512,
        allowed_hosts=[], read_paths=[], write_paths=[])
    assert _spawn(i)["permitted"] == []
    assert _spawn(i)["resource_budget"]["max_children"] == 0


def test_an_explicit_grant_reaches_the_manifest(tmp_path):
    i = _load_or_issue_local_agent(
        _comp(tmp_path), tmp_path / "a.json", memory_mb=512,
        allowed_hosts=[], read_paths=[], write_paths=[], max_children=4)
    assert _spawn(i)["permitted"] == ["worker"]
    assert _spawn(i)["resource_budget"]["max_children"] == 4


def test_raising_the_grant_RE_ISSUES_rather_than_reusing(tmp_path):
    """THE TRAP THIS ALMOST WALKED INTO. The saved-manifest reuse check
    compared memory, hosts, reads and writes -- not `max_children`. Without
    adding it, an operator raising the grant would silently get the old
    zero-spawn identity back: the flag would appear to work and grant nothing.

    Same species as a field-by-field rebuild that drops the field added last.
    """
    c, state = _comp(tmp_path), tmp_path / "a.json"
    first = _load_or_issue_local_agent(
        c, state, memory_mb=512, allowed_hosts=[], read_paths=[],
        write_paths=[], max_children=0)
    second = _load_or_issue_local_agent(
        c, state, memory_mb=512, allowed_hosts=[], read_paths=[],
        write_paths=[], max_children=4)
    assert _spawn(second)["resource_budget"]["max_children"] == 4
    assert second.agent_id != first.agent_id, (
        "the old zero-spawn identity was reused under a wider grant")


def test_an_UNCHANGED_grant_is_still_reused(tmp_path):
    """Negative control: the check must not re-issue on every call, or agent
    identity would churn on every restart."""
    c, state = _comp(tmp_path), tmp_path / "a.json"
    kw = dict(memory_mb=512, allowed_hosts=[], read_paths=[], write_paths=[],
              max_children=2)
    a = _load_or_issue_local_agent(c, state, **kw)
    b = _load_or_issue_local_agent(c, state, **kw)
    assert a.agent_id == b.agent_id


def test_a_granted_agent_can_ACTUALLY_decompose(tmp_path):
    """End to end: the grant is not merely present in the manifest, it is the
    thing the runner's gate reads."""
    import numpy as np

    from gyza.blackboard import Blackboard
    from tests.test_task_decomposition import _item, _runner, _splitter

    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _load_or_issue_local_agent(
        _comp(tmp_path), tmp_path / "a.json", memory_mb=512,
        allowed_hosts=[], read_paths=[], write_paths=[], max_children=3)
    r = _runner(tmp_path, ident, bb, _splitter(2))
    root = _item(bb, claim_for=ident.agent_id)
    r._complete(root, r._execute(root), success=True)
    assert len(bb.children_of(root.id)) == 2


def test_an_UNGRANTED_agent_is_refused_by_the_runner(tmp_path):
    """The default is not merely conservative on paper."""
    from gyza.blackboard import Blackboard
    from tests.test_task_decomposition import _item, _runner, _splitter

    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _load_or_issue_local_agent(
        _comp(tmp_path), tmp_path / "a.json", memory_mb=512,
        allowed_hosts=[], read_paths=[], write_paths=[])
    r = _runner(tmp_path, ident, bb, _splitter(2))
    root = _item(bb, claim_for=ident.agent_id)
    with pytest.raises(RuntimeError, match="no spawn authority"):
        r._execute(root)


def test_gyza_serve_exposes_the_grant_as_an_explicit_flag():
    """A capability reachable only by editing code is not reachable."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "gyza.cli", "serve", "--help"],
        capture_output=True, text=True, cwd="/home/xan/dev/gyza").stdout
    assert "--spawn-children" in out
