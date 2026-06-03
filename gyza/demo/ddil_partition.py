"""
DDIL partition demo — five nodes, one partition, three proofs.

Run it:

    python -m gyza.demo.ddil_partition
    python -m gyza.demo.ddil_partition --construct   # force no-bwrap mode

WHAT IT PROVES (and what it honestly does not)
----------------------------------------------
A five-node network delegates a *bounded* subtask, splits 3/2, keeps
working on both sides of the split, refuses an out-of-bounds action on
the isolated side with no connectivity, heals, and deterministically
reconciles into an intact, independently-verifiable provenance chain.

Three differentiators, each proven by a REAL production function — no
stubs on the safety path:

  1. DDIL-native coordination — the data plane (CRDT + gossip) stays
     available on BOTH sides of the partition while the control plane
     (quorum) correctly pauses grant authority on the minority side.
  2. Forensic auditability — ``gyza.icp.verify_chain`` validates the
     merged history end to end; nothing signed is lost.
  3. Capability-bounds enforcement — ``enforcement_satisfies_manifest``
     (the brick-3 gate) rejects an over-bound action *locally, with no
     quorum and no peers*, and ``verify_delegation`` proves bounds
     composed across the whole delegation chain.

It does NOT prove the *outputs* were correct. Gyza proves
accountability, containment, and bounds-compliance; judging whether a
result is *right* is a human-on-the-loop decision. See README.md.

Bounds are demonstrated on the MEMORY dimension (RLIMIT_AS). Memory is
the asymmetric dimension that makes boundedness *compose* (a capped
ancestor forces every descendant capped no higher — see
``gyza.economy.delegation``), and unlike filesystem paths it needs no
real host directories, so the demo runs unchanged on any machine and
under a real bubblewrap sandbox when one is present.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field

import blake3

from gyza.demo.control_plane import ControlPlane, QuorumError
from gyza.demo.coordination_plane import CoordinationState
from gyza.demo.gossip import GossipNode, Network, run_until_converged
from gyza.economy.delegation import (
    CapabilitySpec,
    DelegationGrant,
    DelegationHop,
    grant_binds_to,
    sign_grant,
    spec_from_enforcement,
    spec_from_manifest,
    verify_delegation,
    verify_grant,
)
from gyza.icp import (
    ICPEnvelope,
    compute_envelope_hash,
    verify_chain,
)
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.release import CURRENT_RELEASE as _CURRENT_RELEASE
from gyza.sandbox.config import (
    SandboxConfig,
    enforcement_satisfies_manifest,
    sandbox_config_from_manifest,
)

INTENT_ID = "ddil-demo-intent"
NODE_IDS = ["n0", "n1", "n2", "n3", "n4"]
MAJORITY = ["n0", "n1", "n2"]
MINORITY = ["n3", "n4"]
COORDINATOR_NODE = "n0"
SUBCONTRACTOR_NODE = "n3"

# Delegated authority handed to the subcontractor: a 512 MB memory
# budget, nothing else — a strict subset of the coordinator's 1024 MB.
# 512 MB is the floor at which a Python+numpy interpreter still boots
# inside a real bubblewrap sandbox (RLIMIT_AS is address space, which
# OpenBLAS reserves greedily); below it the within-bound execution
# would fail to start under --bwrap. Matches bounds_proof_demo's choice.
DELEGATED_MEMORY_MB = 512
COORDINATOR_MEMORY_MB = 1024
OVER_BOUND_MEMORY_MB = 1024  # what the rogue action tries to grab (> 512)


# ----------------------------------------------------------------------
# Enforcement records — byte-faithful to gyza/sandbox/executor.py:101.
# ----------------------------------------------------------------------

def _enforcement_record(cfg: SandboxConfig, *, real: bool) -> dict:
    """
    The host-stamped ``__enforcement__`` record for a sandbox config.

    When ``real`` and bubblewrap is present, we run the *actual*
    production sandbox (``sandboxed_mock_executor``) and use the record
    it stamps. Otherwise we construct the identical record from the
    config — a verbatim mirror of the stamp in
    ``gyza.sandbox.executor.make_sandboxed_executor`` (cited so it
    cannot drift silently). Either way the record is then judged by the
    REAL ``enforcement_satisfies_manifest`` gate.
    """
    if real:
        from gyza.sandbox.executor import sandboxed_mock_executor
        raw = sandboxed_mock_executor(response="ddil", config=cfg)("task", {})
        enf = raw.get("__enforcement__")
        if isinstance(enf, dict):
            return enf
        # bwrap unexpectedly unavailable mid-run — fall back to constructed.
    rec = {
        "backend": cfg.backend.value,
        "ro_paths": sorted(cfg.ro_paths),
        "rw_paths": sorted(cfg.rw_paths),
        "requires_network": bool(cfg.requires_network),
        "max_memory_mb": cfg.max_memory_mb,
        "max_cpu_seconds": cfg.max_cpu_seconds,
        "timeout_s": cfg.timeout_s,
    }
    rec.update(_CURRENT_RELEASE.as_dict())
    return rec


def _fold_artifact(text: str, enforcement: dict | None) -> str:
    """
    Mirror of ``gyza.runner.AgentRunner._execute`` artifact construction:
    fold the enforcement record INTO the hashed artifact so the
    envelope's ``output_hash`` — and thus its signature — commits to it.
    That is what makes the bounds tamper-evident rather than a side claim.
    """
    obj: dict = {"text": text}
    if enforcement is not None:
        obj["__enforcement__"] = enforcement
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return blake3.blake3(canonical).hexdigest()


# ----------------------------------------------------------------------
# Result object — lets tests drive the scenario headlessly.
# ----------------------------------------------------------------------

@dataclass
class DemoResult:
    envelopes: list[ICPEnvelope]
    node_states: dict[str, CoordinationState]
    delegation_hops: list[DelegationHop]
    audit: dict[str, tuple[str, dict, dict]]  # action_id -> (text, enf, manifest)
    over_bound_rejected: bool
    over_bound_reason: str
    minority_control_paused: bool
    majority_control_active: bool
    converged_canonical: bytes
    all_nodes_converged: bool
    sandbox_mode: str
    grant: DelegationGrant
    coordinator_manifest: dict = field(repr=False, default_factory=dict)
    subcontractor_manifest: dict = field(repr=False, default_factory=dict)


# ----------------------------------------------------------------------
# Trace printer
# ----------------------------------------------------------------------

class _Trace:
    BAR = "─" * 68

    def __init__(self, verbose: bool) -> None:
        self.v = verbose

    def line(self, s: str = "") -> None:
        if self.v:
            print(s)

    def head(self, title: str) -> None:
        if self.v:
            print(self.BAR)
            print(title)
            print(self.BAR)


# ----------------------------------------------------------------------
# The scenario
# ----------------------------------------------------------------------

def run_demo(
    *,
    verbose: bool = True,
    sandbox_mode: str = "auto",
    pre_heal_rounds: int | None = None,
) -> DemoResult:
    """
    Execute the full partition scenario and return a self-checking
    ``DemoResult``. ``sandbox_mode`` is ``"auto"`` (real bwrap if
    present, else constructed records), ``"construct"`` (never bwrap —
    used by tests for byte-stable records), or ``"bwrap"`` (force real).
    """
    use_real = (
        (sandbox_mode == "auto" and shutil.which("bwrap") is not None)
        or sandbox_mode == "bwrap"
    )
    mode_label = "real bubblewrap sandbox" if use_real else (
        "constructed records (no bwrap) — gate is still the real one"
    )
    t = _Trace(verbose)

    t.line()
    t.line("GYZA — DDIL PARTITION DEMO")
    t.line("=" * 68)
    t.line("Five nodes. One network partition. The network keeps working,")
    t.line("refuses to overstep its authority while cut off, and proves it")
    t.line(f"afterward.   [enforcement mode: {mode_label}]")
    t.line()

    tmpdir = tempfile.mkdtemp(prefix="gyza-ddil-demo-")
    try:
        # ---- identities ------------------------------------------------
        key_path = os.path.join(tmpdir, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        compositor = LocalCompositor(key_path=key_path)

        coord_seed, coord_manifest = compositor.issue_agent(
            agent_type="ddil.coordinator", model_path="mock",
            fs_read_paths=[], fs_write_paths=[], allowed_hosts=[],
            memory_limit_mb=COORDINATOR_MEMORY_MB, attestation_tier=1,
        )
        sub_seed, sub_manifest = compositor.issue_agent(
            agent_type="ddil.subcontractor", model_path="mock",
            fs_read_paths=[], fs_write_paths=[], allowed_hosts=[],
            memory_limit_mb=DELEGATED_MEMORY_MB, attestation_tier=1,
        )
        coordinator = AgentIdentity(coord_seed, coord_manifest)
        subcontractor = AgentIdentity(sub_seed, sub_manifest)

        # ---- network: 5 nodes, two planes ------------------------------
        net = Network(NODE_IDS)
        data = {n: GossipNode(n, net) for n in NODE_IDS}
        for n in data.values():
            n.attach_peers(list(data.values()))
        control = {n: ControlPlane(n, net) for n in NODE_IDS}

        audit: dict[str, tuple[str, dict, dict]] = {}

        def sign_exec(
            identity: AgentIdentity, action_id: str,
            parent: ICPEnvelope | None, enforcement: dict, manifest: dict,
            text: str,
        ) -> ICPEnvelope:
            out_hash = _fold_artifact(text, enforcement)
            env = identity.get_icp_signer().sign_action(
                intent_id=INTENT_ID, action_id=action_id,
                input_hashes=["00" * 32] if parent is None
                else [compute_envelope_hash(parent)],
                output_hash=out_hash, parent_envelope=parent,
                inference_backend="mock", model_identifier="mock",
                duration_ms=0, tokens_in=0, tokens_out=0,
            )
            audit[action_id] = (text, enforcement, manifest)
            return env

        def sign_coord(action_id: str, parent: ICPEnvelope | None,
                       text: str) -> ICPEnvelope:
            # Pure coordination action (no sandboxed execution).
            env = coordinator.get_icp_signer().sign_action(
                intent_id=INTENT_ID, action_id=action_id,
                input_hashes=["00" * 32] if parent is None
                else [compute_envelope_hash(parent)],
                output_hash=_fold_artifact(text, None), parent_envelope=parent,
                inference_backend="mock", model_identifier="mock",
                duration_ms=0, tokens_in=0, tokens_out=0,
            )
            return env

        # =================================================================
        t.head("1.  NETWORK FORMED")
        t.line(f"Nodes: {', '.join(NODE_IDS)}  (quorum = {net.majority()} of "
               f"{net.cluster_size()})")
        e0 = sign_coord("W0-register-root-task", None, "root task registered")
        data[COORDINATOR_NODE].record(e0)
        run_until_converged(list(data.values()))
        t.line("Coordinator registered the root task; all five nodes hold it.")
        t.line()

        # =================================================================
        t.head("2.  GRANT DELEGATED  (control-plane write, quorum present)")
        delegated = CapabilitySpec(
            ro=frozenset(), rw=frozenset(), network=False,
            mem_cap=DELEGATED_MEMORY_MB,
        )
        grant_unsigned = DelegationGrant(
            parent_envelope_hash=compute_envelope_hash(e0),
            parent_agent_pubkey=coordinator.pubkey_hex,
            parent_manifest_hash=coordinator.manifest_hash,
            child_work_item_id="W1-bounded-subtask",
            delegated_authority=delegated.to_canonical(),
            created_at_ns=time.time_ns(),
        )
        # The grant is issued THROUGH the control plane: it commits only
        # because the coordinator currently has a quorum.
        grant = control[COORDINATOR_NODE].issue_grant(
            lambda: sign_grant(grant_unsigned, coord_seed)
        )
        assert verify_grant(grant)[0], "freshly signed grant must verify"
        bind_ok, bind_why = grant_binds_to(
            grant,
            parent_envelope_hash=compute_envelope_hash(e0),
            parent_agent_pubkey=coordinator.pubkey_hex,
            parent_capability_manifest_hash=coordinator.manifest_hash,
            child_work_item_id="W1-bounded-subtask",
        )
        assert bind_ok, f"grant binding failed: {bind_why}"
        e1 = sign_coord("W1-delegate-subtask", e0,
                        "subtask W1 delegated to subcontractor")
        data[COORDINATOR_NODE].record(e1)
        run_until_converged(list(data.values()))
        t.line(f"Coordinator delegated subtask W1 with a "
               f"{DELEGATED_MEMORY_MB} MB budget")
        t.line(f"(its own budget is {COORDINATOR_MEMORY_MB} MB). Grant signed, "
               f"verified, and bound to the chain.")
        t.line()

        # =================================================================
        t.head("3.  PARTITION  —  {n0,n1,n2} | {n3,n4}")
        net.partition(MAJORITY, MINORITY)
        _, maj_why = control[COORDINATOR_NODE].quorum_status()
        _, min_why = control[SUBCONTRACTOR_NODE].quorum_status()
        t.line(f"  majority side (n0): {maj_why}")
        t.line(f"  minority side (n3): {min_why}")
        # Concretely show the control-plane pause: minority cannot mint a
        # further grant; majority still can.
        minority_paused = False
        try:
            control[SUBCONTRACTOR_NODE].issue_grant(lambda: "further-grant")
        except QuorumError:
            minority_paused = True
        majority_active = (
            control[COORDINATOR_NODE].issue_grant(lambda: "further-grant")
            == "further-grant"
        )
        t.line(f"  minority attempt to issue a NEW grant: "
               f"{'PAUSED (no quorum) ✓' if minority_paused else 'unexpectedly allowed'}")
        t.line(f"  majority attempt to issue a NEW grant: "
               f"{'COMMITTED ✓' if majority_active else 'unexpectedly blocked'}")
        t.line()

        # =================================================================
        t.head("4.  BOUNDED WORK CONTINUES ON BOTH SIDES (data plane stays up)")
        # Majority side: coordinator executes within its own 1024 MB manifest.
        ec = _enforcement_record(sandbox_config_from_manifest(coord_manifest),
                                 real=use_real)
        assert enforcement_satisfies_manifest(ec, coord_manifest)[0]
        e2M = sign_exec(coordinator, "W0-step-a", e1, ec, coord_manifest,
                        "coordinator work A")
        e3M = sign_exec(coordinator, "W0-step-b", e2M, ec, coord_manifest,
                        "coordinator work B")
        for env in (e2M, e3M):
            data[COORDINATOR_NODE].record(env)
        run_until_converged(list(data.values()),
                            max_rounds=pre_heal_rounds or 50)
        t.line("  majority: coordinator signed 2 in-budget actions; shared "
               "across n0,n1,n2.")

        # Minority side: subcontractor executes WITHIN its 256 MB grant.
        es = _enforcement_record(sandbox_config_from_manifest(sub_manifest),
                                 real=use_real)
        assert enforcement_satisfies_manifest(es, sub_manifest)[0]
        e2m = sign_exec(subcontractor, "W1-step-a", e1, es, sub_manifest,
                        "subcontractor work A")
        e3m = sign_exec(subcontractor, "W1-step-b", e2m, es, sub_manifest,
                        "subcontractor work B")
        for env in (e2m, e3m):
            data[SUBCONTRACTOR_NODE].record(env)
        run_until_converged(list(data.values()),
                            max_rounds=pre_heal_rounds or 50)
        t.line("  minority: subcontractor signed 2 in-budget actions; shared "
               "across n3,n4.")
        t.line()

        # =================================================================
        t.head("5.  OVER-BOUND ACTION REFUSED  —  locally, with NO quorum")
        # The isolated subcontractor tries to grab 1024 MB — 4x its grant.
        # No peers beyond n4, no quorum. The brick-3 gate still refuses.
        assert not control[SUBCONTRACTOR_NODE].has_quorum()
        wide_cfg = SandboxConfig(max_memory_mb=OVER_BOUND_MEMORY_MB)
        wide_enf = _enforcement_record(wide_cfg, real=use_real)
        ob_ok, ob_why = enforcement_satisfies_manifest(wide_enf, sub_manifest)
        over_bound_rejected = not ob_ok
        t.line(f"  subcontractor (isolated, quorum={control[SUBCONTRACTOR_NODE].has_quorum()}) "
               f"tries a {OVER_BOUND_MEMORY_MB} MB action")
        t.line(f"  against its {DELEGATED_MEMORY_MB} MB budget:")
        if over_bound_rejected:
            t.line(f"  ✗ REFUSED TO SIGN — {ob_why}")
            t.line("    No envelope is produced. Bounds held with zero "
                   "connectivity — the critical DDIL property.")
        else:
            t.line("  (unexpected: over-bound action was allowed)")
        t.line()

        # =================================================================
        t.head("6.  HEAL + DETERMINISTIC RECONCILIATION")
        net.heal()
        rounds = run_until_converged(list(data.values()))
        t.line(f"  partition healed; gossip reconciled in {rounds} rounds.")
        # Every node converged to byte-identical state?
        canonicals = {n: s.state.canonical_bytes() for n, s in data.items()}
        ref = canonicals[COORDINATOR_NODE]
        all_converged = all(c == ref for c in canonicals.values())
        t.line(f"  all 5 nodes byte-identical after merge: "
               f"{'YES ✓' if all_converged else 'NO ✗'}")
        t.line()

        # =================================================================
        t.head("7.  INDEPENDENT VERIFICATION OF THE MERGED HISTORY")
        merged = data[COORDINATOR_NODE].state
        chains = merged.linear_chains()
        total_envs = len(merged)
        expected = 6  # e0,e1,e2M,e3M,e2m,e3m
        no_loss = total_envs == expected
        t.line(f"  envelopes after merge: {total_envs} (expected {expected}) "
               f"→ {'0 lost ✓' if no_loss else 'LOSS ✗'}")
        t.line(f"  partition produced {len(chains)} provenance branch(es) "
               f"sharing a common prefix:")
        all_chains_ok = True
        for i, c in enumerate(chains):
            ok, bad = verify_chain(c)
            all_chains_ok = all_chains_ok and ok
            tip = c[-1].action_id
            t.line(f"    branch {i + 1} ({len(c)} hops, tip '{tip}'): "
                   f"{'verify_chain VALID ✓' if ok else f'BROKEN at {bad} ✗'}")

        # Compositional bounds across the delegation chain (the keystone).
        hop0 = DelegationHop(
            agent_pubkey=coordinator.pubkey_hex,
            manifest=spec_from_manifest(coord_manifest),
            enforcement=spec_from_enforcement(ec),
            delegated=None,
        )
        hop1 = DelegationHop(
            agent_pubkey=subcontractor.pubkey_hex,
            manifest=spec_from_manifest(sub_manifest),
            enforcement=spec_from_enforcement(es),
            delegated=delegated,
        )
        deleg_ok, deleg_why = verify_delegation([hop0, hop1])
        t.line(f"  verify_delegation (bounds compose upward): "
               f"{'VALID ✓' if deleg_ok else f'✗ {deleg_why}'}")

        # Per-action bounds + tamper-evident binding to the signed envelope.
        per_action_ok = True
        env_by_action = {e.action_id: e for c in chains for e in c}
        for action_id, (text, enf, manifest) in audit.items():
            gate_ok, _ = enforcement_satisfies_manifest(enf, manifest)
            bound = env_by_action[action_id]
            binding_ok = _fold_artifact(text, enf) == bound.output_hash
            per_action_ok = per_action_ok and gate_ok and binding_ok
        t.line(f"  every executed action within its manifest + bound to its "
               f"signature: {'YES ✓' if per_action_ok else 'NO ✗'}")
        t.line()

        verdict_ok = (
            all_converged and no_loss and all_chains_ok and deleg_ok
            and per_action_ok and over_bound_rejected and minority_paused
            and majority_active
        )
        t.head("VERDICT")
        if verdict_ok:
            t.line(f"  Chain verified end-to-end: {total_envs} envelopes, "
                   f"0 lost, all actions within bounds.")
            t.line("  The over-bound action was refused with no connectivity;")
            t.line("  the control plane paused on the minority while the data")
            t.line("  plane stayed available on both sides; the merged history")
            t.line("  is intact and independently re-verifiable.")
            t.line()
            t.line("  Proven: accountability, containment, bounds-compliance.")
            t.line("  NOT proven: output correctness — that needs a human on "
                   "the loop.")
        else:
            t.line("  ✗ scenario invariant violated — see flags above.")
        t.line()

        return DemoResult(
            envelopes=[e0, e1, e2M, e3M, e2m, e3m],
            node_states={n: s.state for n, s in data.items()},
            delegation_hops=[hop0, hop1],
            audit=audit,
            over_bound_rejected=over_bound_rejected,
            over_bound_reason=ob_why,
            minority_control_paused=minority_paused,
            majority_control_active=majority_active,
            converged_canonical=ref,
            all_nodes_converged=all_converged,
            sandbox_mode="bwrap" if use_real else "construct",
            grant=grant,
            coordinator_manifest=coord_manifest,
            subcontractor_manifest=sub_manifest,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = "construct" if "--construct" in argv else (
        "bwrap" if "--bwrap" in argv else "auto"
    )
    result = run_demo(verbose=True, sandbox_mode=mode)
    ok = (
        result.all_nodes_converged
        and result.over_bound_rejected
        and result.minority_control_paused
        and result.majority_control_active
        and verify_delegation(result.delegation_hops)[0]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
