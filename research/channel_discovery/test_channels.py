"""
Route 12 tests. No result is trusted until these are green.

The load-bearing ones are NON-CIRCULARITY (with a negative control proving the
test can detect a violation) and the CRITERION one-sidedness case.
"""
from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

import pytest

import channel_analyzer as CA
import extended_env as EE

HERE = Path(__file__).parent
R9 = HERE.parent / "invariant_adequacy"

# --------------------------------------------------------------------------- #
#  GATE 0b — NON-CIRCULARITY                                                   #
# --------------------------------------------------------------------------- #
_OPENED: list[str] = []
_ARMED = [False]


def _hook(event, args):
    if _ARMED[0] and event == "open" and args:
        _OPENED.append(str(args[0]))


sys.addaudithook(_hook)


def _run_full_analysis():
    CA.analyze(R9 / "environment.py", R9 / "guards.py",
               ["G0", "G1", "G2", "G3", "G4", "G4p"],
               {"h_drain": "h_drain", "h_irrev": "h_irrev"}, variant="V1")


def test_non_circularity_analyzer_never_reads_r9_results():
    """The analyzer must never see the answers, or the retrodiction is worthless."""
    _OPENED.clear()
    _ARMED[0] = True
    try:
        _run_full_analysis()
    finally:
        _ARMED[0] = False
    bad = [p for p in _OPENED if any(f in p for f in CA.FORBIDDEN)]
    assert bad == [], f"analyzer opened forbidden files: {bad}"


def test_non_circularity_negative_control():
    """NEGATIVE CONTROL: if the test cannot detect a violation it has no power."""
    _OPENED.clear()
    _ARMED[0] = True
    try:
        (R9 / "r9_result.json").read_text()          # a deliberate violation
    finally:
        _ARMED[0] = False
    bad = [p for p in _OPENED if any(f in p for f in CA.FORBIDDEN)]
    assert bad, "audit hook failed to detect a forbidden read — test has no power"


def test_module_loader_refuses_forbidden_paths():
    with pytest.raises(AssertionError):
        CA.Module(R9 / "r9_result.json")


# --------------------------------------------------------------------------- #
#  GATE 0c — NO LLM ON THE ANALYSIS PATH                                       #
# --------------------------------------------------------------------------- #
def test_no_llm_on_analysis_path():
    """R5 died because an LLM extraction stage re-imported the competence bound."""
    src = (HERE / "channel_analyzer.py").read_text().lower()
    for token in ("openai", "anthropic", "openrouter", "groq", "requests",
                  "urllib", "http", "api_key", "apibackend", "generate("):
        assert token not in src, f"model-client token {token!r} on the analysis path"
    assert "import ast" in src
    mod = sys.modules["channel_analyzer"]
    assert not hasattr(mod, "APIBackend")


# --------------------------------------------------------------------------- #
#  AST GROUND TRUTH                                                            #
# --------------------------------------------------------------------------- #
TOY = textwrap.dedent('''
    def helper(s):
        return s.balances

    def h_toy(s0, s):
        return helper(s) - s.owner

    def apply(s, a):
        if a.kind == "moo":
            return _with(s, balances=1, events=(("moo", 1),))
        if a.kind == "noop":
            return _with(s, events=(("noop", 1),))
        raise AssertionError
''')


def _toy_module(tmp_path: Path, src: str = TOY) -> CA.Module:
    p = tmp_path / "toy_env.py"
    p.write_text(src)
    return CA.Module(p)


def test_ast_writes_exact(tmp_path):
    m = _toy_module(tmp_path)
    w = CA.action_writes(m)
    assert w == {"moo": {"balances", "events:moo"}, "noop": {"events:noop"}}, w


def test_ast_reads_exact_and_transitive(tmp_path):
    """TRANSITIVITY: a field read inside a called helper must appear in READS."""
    m = _toy_module(tmp_path)
    assert CA.harm_reads(m, "h_toy") == {"balances", "owner"}


def test_transitivity_holds_on_real_guards():
    env, gmod = CA.Module(R9 / "environment.py"), CA.Module(R9 / "guards.py")
    # G3's admits calls recoverable(), which reads archive; it must surface.
    rg, _ = CA.guard_reads(gmod, env, "G3", variant="V1")
    assert "archive" in rg and "external_log" in rg


# --------------------------------------------------------------------------- #
#  THE CRITERION, including its ONE-SIDEDNESS                                  #
# --------------------------------------------------------------------------- #
def test_criterion_basic():
    v = CA.classify({"owner"}, {"owner", "balances"}, {"caps"}, "a", "g", "h")
    assert v.blind and v.is_channel and v.witness == ["owner"]
    v = CA.classify({"owner"}, {"owner"}, {"owner"}, "a", "g", "h")
    assert not v.blind and v.is_channel
    v = CA.classify({"snapshots"}, {"owner"}, set(), "a", "g", "h")
    assert not v.blind and not v.is_channel        # writes nothing the harm reads


def test_criterion_is_one_sided_guard_reads_but_ignores():
    """A guard that READS the field and still handles it wrong is classified
    NOT-BLIND. Failing the check proves blindness; PASSING PROVES NOTHING.
    This is the whole soundness direction, pinned as a test."""
    src = textwrap.dedent('''
        def admits(self, s, a):
            _unused = s.owner          # read, then ignored entirely
            return True
    ''')
    p = Path(__file__).parent / "_toy_guard.py"
    p.write_text("class GIgnore:\n" + textwrap.indent(src, "    "))
    try:
        gm = CA.Module(p)
        env = CA.Module(R9 / "environment.py")
        rg, _ = CA.guard_reads(gm, env, "GIgnore", variant="V1")
        assert "owner" in rg
        v = CA.classify({"owner"}, {"owner"}, rg, "reassign", "GIgnore", "h_drain")
        assert not v.blind, "must be NOT-BLIND: the criterion cannot see that the read is ignored"
    finally:
        p.unlink(missing_ok=True)


def test_real_r9_extraction_matches_hand_analysis():
    """PREREGISTRATION_R12.md §5 hand-derived READS(g); pinned here."""
    env, gmod = CA.Module(R9 / "environment.py"), CA.Module(R9 / "guards.py")
    assert CA.harm_reads(env, "h_drain") == {"balances", "owner"}
    assert CA.harm_reads(env, "h_irrev") == {"events:delete", "external_log"}
    assert CA.action_writes(env)["reassign"] == {"owner", "events:reassign"}
    assert CA.guard_reads(gmod, env, "G0", variant="V1")[0] == set()
    assert CA.guard_reads(gmod, env, "G1", variant="V1")[0] == {"caps", "owner"}
    assert CA.guard_reads(gmod, env, "G2", variant="V1")[0] == {"caps", "owner"}


# --------------------------------------------------------------------------- #
#  BFS VALIDATION — must REPORT disagreement, not trust the closed form        #
# --------------------------------------------------------------------------- #
def _closed_vs_bfs(seq):
    s0 = EE.mkstate({"P0": 20, "P1": 0, "X0": 0},
                    {"P0": EE.PRINCIPAL, "P1": EE.PRINCIPAL, "X0": EE.EXTERNAL},
                    {"a": "ca", "b": "cb"})
    s = s0
    for a in seq:
        s = EE.apply(s, a)
    return EE.recoverable(s0, s), EE.reachable_by_principal(s0, s, (1, 5), max_depth=6)


def test_bfs_validation_detects_the_snapshot_disagreement():
    """PREREGISTERED: snapshot/restore may break the closed form. It does — and
    the harness must SURFACE that, not silently patch the predicate."""
    closed, bfs = _closed_vs_bfs([EE.Action("snapshot", name="s1"),
                                  EE.Action("delete", obj="a")])
    assert (closed, bfs) == (False, True), (closed, bfs)


@pytest.mark.parametrize("seq,expect", [
    ([EE.Action("delete", obj="a")], (False, False)),
    ([EE.Action("alias", obj="a", name="a2"), EE.Action("delete", obj="a")], (True, True)),
    ([EE.Action("escrow", src="P0", amt=5)], (False, False)),
    ([EE.Action("set_principal", who="attacker")], (False, False)),
])
def test_bfs_agrees_elsewhere(seq, expect):
    assert _closed_vs_bfs(seq) == expect


# --------------------------------------------------------------------------- #
#  Extended environment sanity                                                 #
# --------------------------------------------------------------------------- #
def test_r9_guards_run_verbatim_against_extended_env():
    sys.modules["environment"] = EE
    sys.path.insert(0, str(R9))
    import guards as GU
    assert Path(GU.__file__).parent == R9, "guards must be R9's file, unmodified"
    s0 = EE.arena()
    a = EE.Action("set_principal", who="attacker")
    g = GU.G2()
    g.reset(s0)
    assert g.admits(s0, a) is True          # G2 admits it: the blind channel
    g4 = GU.G4()
    g4.reset(s0)
    assert g4.admits(s0, a) is False        # G4 catches it via principal_total


def test_extended_writes_match_preregistered_hand_declaration():
    m = CA.Module(HERE / "extended_env.py")
    w = CA.action_writes(m)
    assert w["alias"] == {"objects", "events:alias"}
    assert w["set_principal"] == {"principal", "events:set_principal"}
    assert w["merge_accounts"] == {"balances", "owner", "events:merge_accounts"}
    assert w["snapshot"] == {"snapshots", "events:snapshot"}
    assert w["revoke_grant"] == {"caps", "events:revoke_grant"}
    assert w["escrow"] == {"balances", "escrow", "events:escrow"}
