"""The product surface, routed through the attested specification registry.

`gyza/audit.py` is the surface the rest of the substrate exists to support, and
until now it had ZERO references to `gyza/verification/` -- eleven attested spec
records governed nothing an evaluator would ever run. `governed=True` records
every check the audit performs as a typed claim and routes it through the
governed registry.

THE LOAD-BEARING PROPERTY IS A NEGATIVE ONE: the flag cannot move the verdict.
A governance layer that silently changed when an audit passes would be a
semantic change to a forensic verdict, so most of this file is spent proving it
does not.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_audit_governance.py -q
"""
from __future__ import annotations

import pathlib
import tempfile

from tests.test_audit import _agent, _enforcement, _honest_workflow, _sign

from gyza.audit import audit_provenance, render_audit_report
from gyza.identity import LocalCompositor


def _both(envs, arts, mans, **kw):
    """The SAME inputs audited with the flag off and on."""
    plain = audit_provenance(envs, resolve_artifact=arts.get,
                             resolve_manifest=mans.get, **kw)
    gov = audit_provenance(envs, resolve_artifact=arts.get,
                           resolve_manifest=mans.get, governed=True, **kw)
    return plain, gov


def _statuses(g):
    out: dict[str, list[str]] = {}
    for v in g.verdicts:
        out.setdefault(v.claim_type, []).append(v.status)
    return out


def _tmp():
    return pathlib.Path(tempfile.mkdtemp())


# --------------------------------------------------------------------------- #
#  1. THE FLAG CANNOT MOVE THE VERDICT — over every scenario, not just the     #
#     happy one. A property that holds only when everything passes is not the  #
#     property.                                                                #
# --------------------------------------------------------------------------- #
def _scenarios():
    """(name, envs, artifacts, manifests, kwargs) covering valid and every
    failure mode audit.py distinguishes."""
    out = []

    envs, arts, mans, _ = _honest_workflow(_tmp())
    out.append(("honest", envs, arts, mans, {}))

    envs, arts, mans, _ = _honest_workflow(_tmp())
    arts[envs[1].output_hash] = b'{"text":"forged"}'
    out.append(("tampered artifact", envs, arts, mans, {}))

    envs, arts, mans, _ = _honest_workflow(_tmp())
    del arts[envs[1].output_hash]
    out.append(("withheld artifact", envs, arts, mans, {}))

    envs, arts, mans, _ = _honest_workflow(_tmp())
    del arts[envs[1].output_hash]
    out.append(("withheld, partial replica", envs, arts, mans,
                {"require_all_artifacts": False}))

    envs, arts, mans, _ = _honest_workflow(_tmp())
    mans.clear()
    out.append(("unresolvable manifest", envs, arts, mans, {}))

    t = _tmp()
    comp = LocalCompositor(key_path=str(t / "k.key"))
    w = _agent(comp, 512)
    e, a = _sign(w, "rogue", None, text="x", enforcement=_enforcement(1024))
    out.append(("over-bound execution", [e], {e.output_hash: a},
                {w.manifest_hash: w.manifest}, {}))
    return out


def test_governed_TRUE_changes_NOTHING_about_the_verdict():
    """THE property. Six scenarios spanning valid and every failure mode."""
    for name, envs, arts, mans, kw in _scenarios():
        plain, gov = _both(envs, arts, mans, **kw)
        assert plain.valid == gov.valid, f"{name}: verdict moved"
        assert plain.summary == gov.summary, f"{name}: summary moved"
        assert len(plain.actions) == len(gov.actions), name
        for a, b in zip(plain.actions, gov.actions):
            assert a == b, f"{name}: row {a.action_id} changed"
        assert plain.dag.valid == gov.dag.valid, name


def test_the_scenarios_are_NOT_all_the_same_verdict():
    """Negative control for the test above: if every scenario were VALID, or
    every one INVALID, 'the verdict did not move' would be vacuous."""
    verdicts = {}
    for name, envs, arts, mans, kw in _scenarios():
        plain, _ = _both(envs, arts, mans, **kw)
        verdicts[name] = plain.valid
    assert True in verdicts.values() and False in verdicts.values(), verdicts


def test_governance_is_ABSENT_unless_asked_for():
    envs, arts, mans, _ = _honest_workflow(_tmp())
    plain, gov = _both(envs, arts, mans)
    assert plain.governance is None, \
        "the default path must not build or run the governance layer"
    assert gov.governance is not None


# --------------------------------------------------------------------------- #
#  2. THE LEDGER SEES WHAT THE AUDIT SEES — with the right verdict KIND        #
# --------------------------------------------------------------------------- #
def test_a_TAMPERED_artifact_is_REFUTED():
    envs, arts, mans, _ = _honest_workflow(_tmp())
    arts[envs[1].output_hash] = b'{"text":"forged"}'
    _p, gov = _both(envs, arts, mans)
    assert "REFUTED" in _statuses(gov.governance)["artifact_content_address"]


def test_a_WITHHELD_artifact_is_UNEVALUATED_and_never_REFUTED():
    """The distinction audit.py already draws in `reason` -- 'not resolvable'
    vs 'tampered' -- must survive into the ledger. Absent evidence and false
    evidence are opposite claims."""
    envs, arts, mans, _ = _honest_workflow(_tmp())
    del arts[envs[1].output_hash]
    _p, gov = _both(envs, arts, mans)
    st = _statuses(gov.governance)["artifact_content_address"]
    assert "UNEVALUATED" in st, st
    assert "REFUTED" not in st, "a missing artifact was reported as tampered"


def test_an_OVER_BOUND_execution_refutes_the_enforcement_claim_only():
    """Precision: the bounds check fails, and the checks that DID pass are not
    dragged down with it."""
    t = _tmp()
    w = _agent(LocalCompositor(key_path=str(t / "k.key")), 512)
    e, a = _sign(w, "rogue", None, text="x", enforcement=_enforcement(1024))
    _p, gov = _both([e], {e.output_hash: a}, {w.manifest_hash: w.manifest})
    st = _statuses(gov.governance)
    assert st["enforcement_within_manifest"] == ["REFUTED"]
    assert st["manifest_identity"] == ["VERIFIED"]
    assert st["envelope_signature"] == ["VERIFIED"]


def test_claims_are_emitted_ONLY_for_checks_actually_PERFORMED():
    """A claim is a record of an operation, not a wish. When the artifact does
    not resolve, audit never reaches the bounds check -- so no bounds claim may
    be recorded, or the ledger would assert a check that never ran."""
    envs, arts, mans, _ = _honest_workflow(_tmp())
    del arts[envs[1].output_hash]
    _p, gov = _both(envs, arts, mans)
    st = _statuses(gov.governance)
    assert "enforcement_within_manifest" not in st
    assert "manifest_identity" not in st


# --------------------------------------------------------------------------- #
#  3. GOVERNANCE COVERAGE IS A SEPARATE AXIS FROM THE VERDICT                  #
# --------------------------------------------------------------------------- #
def test_the_DAG_check_is_reported_as_UNATTESTED():
    """THE FINDING this wiring surfaces. `verify_dag` is the audit's central
    integrity check and its specification is not under attestation, so the
    registry routes it tier 3 / carrier NONE. The check RUNS and PASSES; what
    is absent is a signed statement of what it proves.

    Closing this needs a human attestation and is deliberately not done here.
    """
    envs, arts, mans, _ = _honest_workflow(_tmp())
    _p, gov = _both(envs, arts, mans)
    g = gov.governance
    assert "envelope_dag" in g.ungoverned_types, g.ungoverned_types
    assert not g.fully_governed
    dag_v = [v for v in g.verdicts if v.claim_type == "envelope_dag"][0]
    assert dag_v.status == "VERIFIED", "the check itself must still run"
    assert dag_v.tier == 3 and dag_v.carrier == "NONE"


def test_the_OTHER_checks_ARE_attested_and_PROOF_carried():
    """Counter-metric. If nothing were governed, 'not fully governed' would be
    uninformative."""
    envs, arts, mans, _ = _honest_workflow(_tmp())
    _p, gov = _both(envs, arts, mans)
    g = gov.governance
    assert g.n_governed == g.n_claims - 1, \
        f"expected exactly one ungoverned check, got {g.ungoverned_types}"
    for v in g.verdicts:
        if v.claim_type != "envelope_dag":
            assert v.governed and v.carrier == "PROOF" and v.tier == 1, v


def test_a_VALID_audit_can_have_an_INADMISSIBLE_ledger_and_that_is_correct():
    """`valid` reports what was REQUIRED and met; the ledger reports what was
    PROVED. On a partial replica, an unresolvable artifact is legitimately
    skipped -- so the audit is VALID while the content-address claim is
    UNEVALUATED. Collapsing the two would destroy the distinction."""
    envs, arts, mans, _ = _honest_workflow(_tmp())
    del arts[envs[1].output_hash]
    plain, gov = _both(envs, arts, mans, require_all_artifacts=False)
    assert plain.valid, "partial-replica audit should pass"
    assert not gov.governance.admissible, \
        "an unproved claim must not read as proved"


# --------------------------------------------------------------------------- #
#  4. THE RENDERED REPORT MUST NOT MISLEAD                                     #
# --------------------------------------------------------------------------- #
def test_the_report_never_lets_a_GOVERNANCE_gap_read_as_a_FAILED_audit():
    envs, arts, mans, _ = _honest_workflow(_tmp())
    _p, gov = _both(envs, arts, mans)
    text = render_audit_report(gov)
    assert "VERDICT: VALID" in text
    assert "NOT ATTESTED: envelope_dag" in text
    assert "does NOT weaken the verdict" in text
    # the governance block must sit ABOVE the verdict, so the verdict is the
    # last thing read
    assert text.index("NOT ATTESTED") < text.index("VERDICT:")


def test_the_default_report_is_UNCHANGED():
    """No caller that did not ask for governance may see it."""
    envs, arts, mans, _ = _honest_workflow(_tmp())
    plain, _gov = _both(envs, arts, mans)
    text = render_audit_report(plain)
    assert "governance" not in text.lower()
    assert "ATTESTED" not in text


# --------------------------------------------------------------------------- #
#  5. `gyza audit` ACTUALLY RUNS IT                                            #
#                                                                              #
#  `cmd_audit` had NO test coverage at all, so wiring a flag into it would     #
#  otherwise be the "registering a checker is not evidence that it runs"       #
#  defect exactly: reachable, plausible, and never executed. This drives the   #
#  real command over a real Blackboard.                                        #
# --------------------------------------------------------------------------- #
def _cli_fixture(tmp_path, monkeypatch, *, tamper=False):
    import argparse
    import json

    import gyza.cli as cli
    import gyza.network.artifact_store as store_mod
    from gyza.blackboard import Blackboard
    from gyza.config import GyzaConfig
    from tests.test_audit import INTENT

    envs, arts, mans, _ = _honest_workflow(tmp_path)
    if tamper:
        arts[envs[1].output_hash] = b'{"text":"forged"}'

    bb_path = tmp_path / "bb.sqlite"
    bb = Blackboard(str(bb_path))
    for e in envs:
        bb.store_envelope(e)

    # Manifests are stored as artifacts too — the convention `audit_from_store`
    # documents — so one dict serves as the whole content-addressed store.
    blob = dict(arts)
    for h, m in mans.items():
        blob[h] = json.dumps(m, sort_keys=True, separators=(",", ":")).encode()

    monkeypatch.setattr(
        cli, "load_config",
        lambda *a, **k: GyzaConfig(blackboard_db_path=str(bb_path)))
    monkeypatch.setattr(store_mod, "ArtifactStore", lambda **k: blob)
    return argparse.Namespace(intent_id=INTENT)


def test_gyza_audit_RUNS_the_governance_layer(tmp_path, monkeypatch, capsys):
    import gyza.cli as cli

    args = _cli_fixture(tmp_path, monkeypatch)
    rc = cli.cmd_audit(args)
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "VERDICT: VALID" in out
    # the wiring is EXERCISED, not merely reachable
    assert "Specification governance" in out, out
    assert "NOT ATTESTED: envelope_dag" in out, out


def test_gyza_audit_still_FAILS_a_tampered_workflow(tmp_path, monkeypatch,
                                                    capsys):
    """Negative control for the test above: if the command passed everything,
    'it printed the governance block' would say nothing about correctness."""
    import gyza.cli as cli

    args = _cli_fixture(tmp_path, monkeypatch, tamper=True)
    rc = cli.cmd_audit(args)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "VERDICT: INVALID" in out
    assert "tampered" in out
