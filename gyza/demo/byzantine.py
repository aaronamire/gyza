"""
Byzantine resilience demo — a compromised member of a heterogeneous
collective is prevented, detected, attributed, and quarantined, and the
collective completes the mission anyway.

Run it:

    python -m gyza.demo.byzantine

WHAT IT SHOWS (DICE Phase-2 shaped: compromised agents, deceptive
messages, resilience at measurement + policy level)

  Act 1  A heterogeneous collective — three agents wrapped by identical
         AgentAdaptors over different "brains" — runs an honest mission
         and produces a signed provenance DAG.
  Act 2  The compromised agent attempts an OUT-OF-BOUNDS action. The
         adaptor's refuse-to-sign gate blocks it at signing time — the
         attack never produces an envelope (prevention, not detection).
  Act 3  The compromised agent EQUIVOCATES — signs two contradicting
         "situation reports" for one action, the decentralized analogue
         of telling two partition sides different things. Both are
         validly signed, so both are undeniable evidence against it.
  Act 4  assess_resilience detects the equivocation, attributes it to
         the compromised agent's key, quarantines that agent, and shows
         the honest remainder still forms a valid DAG — the collective
         routed around the compromise. A resilience metric is printed.

What it does NOT claim: that a compromised agent producing well-formed,
in-bounds, self-consistent-but-wrong output is caught — that is a
human-on-the-loop judgement, the same honest limit drawn elsewhere.
"""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
from dataclasses import dataclass

from gyza.adaptor import AgentAdaptor, BoundsViolation
from gyza.demo.coordination_plane import CoordinationState
from gyza.icp import ICPEnvelope, verify_dag
from gyza.identity import LocalCompositor
from gyza.resilience import ResilienceReport, assess_resilience
from gyza.sandbox.config import SandboxBackend

INTENT = "recon-mission"
BAR = "─" * 68

# A bounds record a compromised agent supplies to try to get a bounded
# signature for out-of-bounds work: no real sandbox ran (backend=none)
# AND it declares 4096 MB against a 512 MB manifest. Either failing alone
# is enough; the gate refuses it. We do NOT hardcode `bubblewrap` here —
# a bubblewrap-backed record may only come from an actual bwrap run
# (test_enforcement_honesty pins that no source fixture fabricates one).
_OVER_BOUND = {
    "backend": SandboxBackend.NONE.value,
    "ro_paths": [],
    "rw_paths": [],
    "requires_network": False,
    "max_memory_mb": 4096,
    "max_cpu_seconds": 300,
    "timeout_s": 300,
}


@dataclass
class ByzantineResult:
    envelopes: list[ICPEnvelope]
    report: ResilienceReport
    over_bound_prevented: bool
    honest_dag_valid: bool


def run_scenario(*, verbose: bool = True) -> ByzantineResult:
    def line(s: str = "") -> None:
        if verbose:
            print(s)

    def head(title: str) -> None:
        if verbose:
            print(BAR)
            print(title)
            print(BAR)

    tmp = tempfile.mkdtemp(prefix="gyza-byz-")
    try:
        key_path = os.path.join(tmp, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        compositor = LocalCompositor(key_path=key_path)

        plane = CoordinationState()

        # Heterogeneous collective: same adaptor, three different "brains".
        planner = AgentAdaptor.from_compositor(
            compositor, lambda p, c: f"PLAN[{p}]",
            agent_type="planner", memory_limit_mb=512, sink=plane,
        )
        scout = AgentAdaptor.from_compositor(
            compositor, lambda p, c: p.upper(),
            agent_type="scout", memory_limit_mb=512, sink=plane,
        )
        compromised = AgentAdaptor.from_compositor(
            compositor, lambda p, c: p,
            agent_type="scout", memory_limit_mb=512, sink=plane,
        )

        line()
        line("GYZA — BYZANTINE RESILIENCE DEMO")
        line("=" * 68)
        line("A heterogeneous collective. One member is compromised. The")
        line("collective prevents its over-reach, proves its lie, excludes")
        line("it, and finishes the mission.")
        line()

        head("ACT 1 — the collective runs an honest mission")
        root = planner.act(intent_id=INTENT, action_id="plan", prompt="survey grid")
        recon = scout.act(
            intent_id=INTENT, action_id="recon", prompt="sector-7", parent=root,
        )
        line(f"  planner  {planner.pubkey_hex[:16]}…  signed 'plan'")
        line(f"  scout    {scout.pubkey_hex[:16]}…  signed 'recon' (parent=plan)")
        line(f"  compromised member also present: {compromised.pubkey_hex[:16]}…")
        line()

        head("ACT 2 — the compromised agent tries to exceed its authority")
        over_bound_prevented = False
        try:
            compromised.act(
                intent_id=INTENT, action_id="exfil", prompt="grab everything",
                enforcement=_OVER_BOUND,
            )
        except BoundsViolation as e:
            over_bound_prevented = True
            line(f"  ✗ refused to sign: {e}")
            line("    The out-of-bounds action produced NO envelope. Prevention")
            line("    at signing time, not after-the-fact detection.")
        line()

        head("ACT 3 — the compromised agent equivocates (deceptive messages)")
        s1 = compromised.act(
            intent_id=INTENT, action_id="sitrep", prompt="sector-7 CLEAR", parent=recon,
        )
        s2 = compromised.act(
            intent_id=INTENT, action_id="sitrep", prompt="sector-7 HOSTILE", parent=recon,
        )
        line(f"  signed 'sitrep' = CLEAR    → {s1.output_hash[:16]}…")
        line(f"  signed 'sitrep' = HOSTILE  → {s2.output_hash[:16]}…")
        line("  Two signed, contradicting reports for one action — validly")
        line("  signed, so undeniable evidence against their author.")
        line()

        head("ACT 4 — detect, attribute, quarantine, route around")
        envelopes = plane.envelopes()
        report = assess_resilience(envelopes)
        for eq in report.equivocations:
            line(f"  ✗ EQUIVOCATION by {eq.agent_pubkey[:16]}… on "
                 f"'{eq.action_id}' ({len(eq.conflicting_output_hashes)} conflicting outputs)")
        line(f"  quarantined: {len(report.quarantined_agents)} agent(s)")
        line(f"  honest remainder: {report.honest_envelopes}/"
             f"{report.total_envelopes} envelopes "
             f"({report.honest_fraction:.0%}) — DAG "
             f"{'VALID ✓' if report.honest_dag.valid else 'INVALID ✗'}")
        line()

        head("VERDICT")
        line(f"  {report.summary()}")
        line("  Over-bound action prevented at signing; equivocation proven")
        line("  and attributed; compromised member excluded; the honest")
        line("  mission DAG is intact and independently re-verifiable.")
        line()
        line("  Proven: prevention, attribution, containment, recovery.")
        line("  NOT proven: whether in-bounds, self-consistent output is")
        line("  semantically correct — that needs a human on the loop.")

        honest_only = [
            e for e in envelopes if e.agent_pubkey not in report.quarantined_agents
        ]
        honest_dag_valid = verify_dag(honest_only, require_closed=False).valid

        return ByzantineResult(
            envelopes=envelopes,
            report=report,
            over_bound_prevented=over_bound_prevented,
            honest_dag_valid=honest_dag_valid,
        )
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    result = run_scenario(verbose="--quiet" not in argv)
    ok = (
        result.over_bound_prevented
        and len(result.report.equivocations) == 1
        and len(result.report.quarantined_agents) == 1
        and result.report.mission_intact
        and result.honest_dag_valid
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
