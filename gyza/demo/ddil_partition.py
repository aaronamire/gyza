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

from gyza.audit import AuditReport, audit_provenance
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
    DagVerification,
    ICPEnvelope,
    compute_envelope_hash,
    verify_chain,
    verify_dag,
)
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.release import CURRENT_RELEASE as _CURRENT_RELEASE
from gyza.sandbox.config import (
    SandboxBackend,
    SandboxConfig,
    enforcement_satisfies_manifest,
    sandbox_config_from_manifest,
)
from gyza.sandbox.runner import detect_backend

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
    production sandbox (``sandboxed_mock_executor``), which stamps
    ``backend=bubblewrap`` ONLY because bwrap actually executed.

    When bwrap did NOT run (``real`` is False, or bwrap was unavailable
    mid-run), the record honestly reports ``backend=none`` — it is NEVER
    stamped with a backend that did not run. ``enforcement_satisfies_
    manifest`` fails closed on ``backend=none`` (config.py), so an
    unenforced run can never yield "within bounds". This removes the
    fabrication primitive: a signed enforcement record now reflects what
    actually executed, not what was requested.
    """
    if real:
        from gyza.sandbox.executor import sandboxed_mock_executor
        raw = sandboxed_mock_executor(response="ddil", config=cfg)("task", {})
        enf = raw.get("__enforcement__")
        if isinstance(enf, dict):
            return enf
        # bwrap unavailable mid-run — fall through to an HONEST none record.
    rec = {
        "backend": SandboxBackend.NONE.value,   # no OS enforcement ran; never fabricate
        "ro_paths": sorted(cfg.ro_paths),
        "rw_paths": sorted(cfg.rw_paths),
        "requires_network": bool(cfg.requires_network),
        "max_memory_mb": cfg.max_memory_mb,
        "max_cpu_seconds": cfg.max_cpu_seconds,
        "timeout_s": cfg.timeout_s,
    }
    rec.update(_CURRENT_RELEASE.as_dict())
    return rec


def _fold_bytes(text: str, enforcement: dict | None) -> bytes:
    """
    Mirror of ``gyza.runner.AgentRunner._execute`` artifact construction:
    fold the enforcement record INTO the hashed artifact so the
    envelope's ``output_hash`` — and thus its signature — commits to it.
    That is what makes the bounds tamper-evident rather than a side claim.
    Returns the canonical artifact bytes (the content-addressed object the
    audit later resolves by ``output_hash``).
    """
    obj: dict = {"text": text}
    if enforcement is not None:
        obj["__enforcement__"] = enforcement
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _fold_artifact(text: str, enforcement: dict | None) -> str:
    return blake3.blake3(_fold_bytes(text, enforcement)).hexdigest()


# ----------------------------------------------------------------------
# Result object — lets tests drive the scenario headlessly.
# ----------------------------------------------------------------------

class SandboxRequiredError(RuntimeError):
    """
    Raised when ``--require-sandbox`` is set but bubblewrap is not
    available, so OS-level containment cannot be demonstrated. The demo
    refuses rather than running the disclosed no-sandbox path — the
    explicit third mode of the enforcement trichotomy.
    """


@dataclass
class DemoResult:
    envelopes: list[ICPEnvelope]
    dag: DagVerification
    audit_report: AuditReport
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
    require_sandbox: bool = False,
    pre_heal_rounds: int | None = None,
) -> DemoResult:
    """
    Execute the full partition scenario and return a self-checking
    ``DemoResult``.

    ``sandbox_mode`` selects how OS enforcement is obtained:
      * ``"auto"``      — real bwrap if present; otherwise the disclosed
                          no-sandbox path (backend=none, honestly recorded);
      * ``"bwrap"``     — force the real bwrap path (ENFORCED);
      * ``"construct"`` — never bwrap (byte-stable records for tests);
                          behaves as the disclosed no-sandbox path.

    ``require_sandbox`` turns the auto no-bwrap case into a REFUSAL
    instead of a disclosed run: if OS enforcement cannot be demonstrated,
    ``SandboxRequiredError`` is raised rather than running without it.

    Three enforcement modes result — ENFORCED, DISCLOSED-NO-SANDBOX,
    REFUSE — and the trace states which is active. The disclosed path is
    honest, not silent: every signed record carries ``backend=none`` and
    the over-bound refusal is proven by the *logical* delegation bound
    (``verify_delegation``), which needs no OS sandbox — not by OS
    enforcement.
    """
    # FUNCTIONAL probe, not mere presence. Under Docker's default seccomp
    # (and other locked-down hosts) bwrap is INSTALLED but cannot create a
    # user namespace — `shutil.which` would say "present", the demo would
    # pick enforced, and then CRASH on the first sandboxed action with
    # "No permissions to create new namespace". detect_backend() runs a
    # real no-op bwrap spawn and returns NONE in that case, so we disclose
    # honestly (or REFUSE under --require-sandbox) instead of crashing.
    # "enforced" means bwrap that actually works, never bwrap that merely
    # exists.
    has_bwrap = detect_backend() == SandboxBackend.BUBBLEWRAP
    if sandbox_mode == "bwrap":
        mode = "enforced"
    elif sandbox_mode == "construct":
        mode = "disclosed"
    elif sandbox_mode == "auto":
        if has_bwrap:
            mode = "enforced"
        elif require_sandbox:
            mode = "refuse"
        else:
            mode = "disclosed"
    else:
        raise ValueError(f"unknown sandbox_mode {sandbox_mode!r}")
    use_real = mode == "enforced"

    t = _Trace(verbose)
    t.line()
    t.line("GYZA — DDIL PARTITION DEMO")
    t.line("=" * 68)

    if mode == "refuse":
        t.line("REFUSING TO RUN — --require-sandbox was set and bubblewrap is "
               "not available on this host.")
        t.line("This host cannot demonstrate OS-level containment. Install "
               "bubblewrap (on Linux,")
        t.line("your distro's `bubblewrap` package) or run the Docker image, "
               "then retry. To see the")
        t.line("delegation-bound + provenance logic WITHOUT OS enforcement, "
               "run without --require-sandbox.")
        t.line()
        raise SandboxRequiredError(
            "bubblewrap unavailable and --require-sandbox was set"
        )

    t.line("Five nodes. One network partition. The network keeps working,")
    t.line("refuses to overstep its authority while cut off, and proves it")
    t.line("afterward.")
    t.line()
    if mode == "enforced":
        t.line("Enforcement:  OS-enforced (bubblewrap: namespaces + seccomp) — "
               "real containment on this host.")
    else:
        t.line("Enforcement:  NONE — bubblewrap (the OS sandbox) is unavailable "
               "on this platform.")
        t.line("              This run demonstrates the delegation-bound and "
               "provenance LOGIC,")
        t.line("              which is cryptographic and needs no OS sandbox — "
               "but NOT OS-level")
        t.line("              containment. Every signed record honestly carries "
               "backend=none.")
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
        # Content-addressed artifact + manifest stores, populated as the
        # workflow runs. These feed the unified audit (section 8): the
        # resolvers a third party would use to re-verify everything.
        artifacts: dict[str, bytes] = {}
        manifests: dict[str, dict] = {
            coordinator.manifest_hash: coord_manifest,
            subcontractor.manifest_hash: sub_manifest,
        }

        def sign_exec(
            identity: AgentIdentity, action_id: str,
            parent: ICPEnvelope | None, enforcement: dict, manifest: dict,
            text: str, inputs: list[str] | None = None,
        ) -> ICPEnvelope:
            art = _fold_bytes(text, enforcement)
            out_hash = blake3.blake3(art).hexdigest()
            # Default data edge is the causal parent's hash; a synthesis
            # action passes explicit ``inputs`` (multiple producers'
            # output_hashes) to express fan-in.
            if inputs is not None:
                in_hashes = list(inputs)
            elif parent is None:
                in_hashes = ["00" * 32]
            else:
                in_hashes = [compute_envelope_hash(parent)]
            env = identity.get_icp_signer().sign_action(
                intent_id=INTENT_ID, action_id=action_id,
                input_hashes=in_hashes,
                output_hash=out_hash, parent_envelope=parent,
                inference_backend="mock", model_identifier="mock",
                duration_ms=0, tokens_in=0, tokens_out=0,
            )
            audit[action_id] = (text, enforcement, manifest)
            artifacts[out_hash] = art
            return env

        def sign_coord(action_id: str, parent: ICPEnvelope | None,
                       text: str) -> ICPEnvelope:
            # Pure coordination action (no sandboxed execution).
            art = _fold_bytes(text, None)
            out_hash = blake3.blake3(art).hexdigest()
            env = coordinator.get_icp_signer().sign_action(
                intent_id=INTENT_ID, action_id=action_id,
                input_hashes=["00" * 32] if parent is None
                else [compute_envelope_hash(parent)],
                output_hash=out_hash, parent_envelope=parent,
                inference_backend="mock", model_identifier="mock",
                duration_ms=0, tokens_in=0, tokens_out=0,
            )
            artifacts[out_hash] = art
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
        # Only assert OS-enforcement passes when it ACTUALLY ran. Under
        # disclosed no-sandbox (backend=none) the gate fails closed — that
        # is correct, not an error; Stage-2 disclosed mode narrates it.
        if use_real:
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
        if use_real:
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
        # The isolated subcontractor tries to grab 1024 MB — 2x its 512 MB
        # grant. No peers beyond n4, no quorum. The action is refused with
        # zero connectivity — the critical DDIL property. HOW it is refused
        # depends on what enforcement this host can offer:
        #   * ENFORCED : the OS gate (enforcement_satisfies_manifest over a
        #     real bwrap record) rejects it — measured containment.
        #   * DISCLOSED: the LOGICAL delegation bound (verify_delegation)
        #     rejects it — a 1024 MB claim exceeds the 512 MB delegated.
        #     This holds with no OS sandbox and no connectivity, and is the
        #     more fundamental of the two bounds.
        assert not control[SUBCONTRACTOR_NODE].has_quorum()
        wide_cfg = SandboxConfig(max_memory_mb=OVER_BOUND_MEMORY_MB)
        wide_enf = _enforcement_record(wide_cfg, real=use_real)
        t.line(f"  subcontractor (isolated, quorum={control[SUBCONTRACTOR_NODE].has_quorum()}) "
               f"tries a {OVER_BOUND_MEMORY_MB} MB action")
        t.line(f"  against its {DELEGATED_MEMORY_MB} MB budget:")
        if use_real:
            ob_ok, ob_why = enforcement_satisfies_manifest(wide_enf, sub_manifest)
            over_bound_rejected = not ob_ok
            if over_bound_rejected:
                t.line(f"  ✗ REFUSED TO SIGN — a {OVER_BOUND_MEMORY_MB} MB action "
                       f"exceeds the {DELEGATED_MEMORY_MB} MB the subcontractor "
                       f"was delegated.")
                t.line("    OS-enforced, and refused with NO quorum and NO "
                       "connectivity. No envelope is produced.")
            else:
                t.line("  (unexpected: over-bound action was allowed)")
        else:
            # Disclosed: prove the refusal from the logical delegation bound.
            # A rogue hop that claims a wide (1024 MB) manifest to cover its
            # 1024 MB attempt is still caught — only 512 MB was delegated.
            rogue_root = DelegationHop(
                agent_pubkey=coordinator.pubkey_hex,
                manifest=spec_from_manifest(coord_manifest),
                enforcement=spec_from_manifest(coord_manifest),
                delegated=None,
            )
            rogue_sub = DelegationHop(
                agent_pubkey=subcontractor.pubkey_hex,
                manifest=spec_from_enforcement(wide_enf),   # claims 1024 to cover it
                enforcement=spec_from_enforcement(wide_enf),
                delegated=delegated,                        # only 512 was granted
            )
            log_ok, ob_why = verify_delegation([rogue_root, rogue_sub])
            over_bound_rejected = not log_ok
            if over_bound_rejected:
                t.line(f"  ✗ REFUSED — the delegation bound rejects it: a "
                       f"{OVER_BOUND_MEMORY_MB} MB action exceeds the "
                       f"{DELEGATED_MEMORY_MB} MB the subcontractor was")
                t.line("    delegated (verify_delegation). This check is LOGICAL "
                       "and cryptographic — it")
                t.line("    holds with no OS sandbox and no connectivity. No "
                       "envelope is produced.")
                t.line("    (OS-level containment is disclosed as none here; this "
                       "refusal came from")
                t.line("     the delegation logic, not the OS.)")
            else:
                t.line("  (unexpected: over-bound action was allowed)")
        t.line()

        # =================================================================
        t.head("6.  HEAL + DETERMINISTIC RECONCILIATION + FAN-IN")
        net.heal()
        rounds = run_until_converged(list(data.values()))
        t.line(f"  partition healed; gossip reconciled in {rounds} rounds.")

        # The coordinator can now see BOTH branches, so it synthesizes a
        # single result that consumes them. This is genuine FAN-IN,
        # expressed through input_hashes (the two branch tips' outputs) —
        # the shape a linear chain structurally cannot represent.
        e6 = sign_exec(
            coordinator, "W2-synthesize-results", e3M, ec, coord_manifest,
            "synthesis of both partition branches",
            inputs=[e3m.output_hash, e3M.output_hash],
        )
        data[COORDINATOR_NODE].record(e6)
        rounds += run_until_converged(list(data.values()))
        t.line("  coordinator synthesized both branches into one result "
               "(fan-in via data edges).")

        canonicals = {n: s.state.canonical_bytes() for n, s in data.items()}
        ref = canonicals[COORDINATOR_NODE]
        all_converged = all(c == ref for c in canonicals.values())
        t.line(f"  all 5 nodes byte-identical after merge: "
               f"{'YES ✓' if all_converged else 'NO ✗'}")
        t.line()

        # =================================================================
        t.head("7.  INDEPENDENT VERIFICATION OF THE MERGED HISTORY")
        merged = data[COORDINATOR_NODE].state
        all_envs = merged.envelopes()
        total_envs = len(merged)
        expected = 7  # e0,e1,e2M,e3M,e2m,e3m,e6
        no_loss = total_envs == expected
        t.line(f"  envelopes after merge: {total_envs} (expected {expected}) "
               f"→ {'0 lost ✓' if no_loss else 'LOSS ✗'}")

        # (a) Causal-spine view: the parent_envelope_hash tree still shows
        #     the partition fork, each branch linear + verify_chain-valid.
        chains = merged.linear_chains()
        all_chains_ok = True
        t.line(f"  causal-spine view: {len(chains)} branch(es) from the "
               f"partition, each verify_chain-valid:")
        for i, c in enumerate(chains):
            ok, bad = verify_chain(c)
            all_chains_ok = all_chains_ok and ok
            t.line(f"    branch {i + 1} ({len(c)} hops, tip '{c[-1].action_id}'): "
                   f"{'VALID ✓' if ok else f'BROKEN at {bad} ✗'}")

        # (b) Full provenance DAG: data edges re-join the fork at the
        #     synthesis — one root, one leaf. Fan-in verify_chain can't see.
        dag = verify_dag(all_envs, require_closed=True)
        t.line(f"  full provenance DAG (verify_dag): "
               f"{'VALID ✓' if dag.valid else f'✗ {dag.reason}'}  "
               f"[{len(dag.roots)} root, {len(dag.leaves)} leaf, "
               f"{len(dag.topo_order)} nodes in deterministic topo-order]")
        if dag.valid and len(dag.leaves) == 1:
            leaf = merged.get(dag.leaves[0])
            t.line(f"    '{leaf.action_id}' is the sole leaf — the two "
                   f"partition branches converged into one auditable result.")

        # (c) Compositional bounds across the delegation chain (the keystone).
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

        # (d) Per-action bounds + tamper-evident binding to the signature.
        # Binding (tamper-evidence) holds regardless of OS enforcement; the
        # OS-bounds gate only passes when bwrap actually ran (backend=none
        # fails it closed — correct, not an error).
        os_bounds_ok = True
        binding_all_ok = True
        env_by_action = {e.action_id: e for e in all_envs}
        for action_id, (text, enf, manifest) in audit.items():
            gate_ok, _ = enforcement_satisfies_manifest(enf, manifest)
            bound = env_by_action[action_id]
            binding_ok = _fold_artifact(text, enf) == bound.output_hash
            os_bounds_ok = os_bounds_ok and gate_ok
            binding_all_ok = binding_all_ok and binding_ok
        t.line(f"  every executed action bound to its signature "
               f"(tamper-evident): {'YES ✓' if binding_all_ok else 'NO ✗'}")
        if use_real:
            t.line(f"  every executed action within its manifest "
                   f"(OS-enforced): {'YES ✓' if os_bounds_ok else 'NO ✗'}")
        else:
            t.line("  OS-enforced bounds: not demonstrated on this platform "
                   "(backend=none) —")
            t.line("    the delegation bound above (verify_delegation) is the "
                   "logical guarantee that held.")
        t.line()

        # =================================================================
        t.head("8.  UNIFIED AUDIT  —  one call, one verdict")
        # The product surface: a third party with only the envelopes plus
        # content-addressed resolvers for artifacts and manifests gets a
        # single forensic verdict (graph intact + every execution within
        # bounds + tamper-evident binding) — no trust in any node.
        report = audit_provenance(
            all_envs,
            resolve_artifact=artifacts.get,
            resolve_manifest=manifests.get,
            require_closed=True,
        )
        t.line(f"  audit_provenance(): {report.summary}")
        for row in report.actions:
            tag = ("execution" if row.is_execution else "coordination")
            if row.ok:
                status = "✓"
            elif (not use_real and row.is_execution and row.binding_ok
                  and row.manifest_bound_ok and not row.within_bounds):
                # Disclosed: the ONLY failing check is the OS-bounds gate
                # (backend=none). Graph shape, tamper-evident binding, and
                # manifest binding all hold — so we say what is true rather
                # than print a bare ✗ that reads as breakage.
                status = "OS-bounds not demonstrated (backend=none)"
            else:
                status = f"✗ {row.reason}"
            t.line(f"    [{tag:12}] {row.action_id:24} {status}")
        if not use_real:
            t.line("  Every execution row's provenance + tamper-evident binding "
                   "hold; only the OS-")
            t.line("  enforcement bounds are undemonstrated on this platform. "
                   "The logical delegation")
            t.line("  bound — the more fundamental guarantee — passed in "
                   "section 7.")
        t.line()

        # Logical + provenance properties — hold with OR without an OS
        # sandbox (signatures, DAG shape, convergence, the delegation bound,
        # the over-bound refusal, control-plane quorum behavior).
        logical_ok = (
            all_converged and no_loss and all_chains_ok and dag.valid
            and deleg_ok and binding_all_ok and over_bound_rejected
            and minority_paused and majority_active
        )
        # OS-enforcement property — only meaningful when bwrap actually ran.
        os_ok = os_bounds_ok and report.valid

        t.head("VERDICT")
        if use_real:
            verdict_ok = logical_ok and os_ok
            if verdict_ok:
                t.line(f"  Provenance verified end-to-end: {total_envs} "
                       f"envelopes, 0 lost, all actions within bounds.")
                t.line("  The over-bound action was refused with no "
                       "connectivity; the control plane")
                t.line("  paused on the minority while the data plane stayed "
                       "available on both sides;")
                t.line("  the merged history is intact and independently "
                       "re-verifiable.")
                t.line()
                t.line("  Proven: accountability (every action signed), "
                       "containment (OS-enforced")
                t.line("  bounds, backend=bubblewrap), recovery (survived "
                       "partition, reconciled).")
                t.line("  NOT proven: output correctness — that needs a human "
                       "on the loop.")
            else:
                t.line("  ✗ scenario invariant violated — see flags above.")
        else:
            verdict_ok = logical_ok   # disclosed: OS bounds intentionally not required
            if verdict_ok:
                t.line(f"  Provenance verified end-to-end: {total_envs} "
                       f"envelopes, 0 lost, delegation bounds held.")
                t.line("  The over-bound action was refused by the logical "
                       "delegation bound with no")
                t.line("  connectivity; the control plane paused on the "
                       "minority while the data plane")
                t.line("  stayed available on both sides; the merged history "
                       "is intact and re-verifiable.")
                t.line()
                t.line("  Proven: accountability (every action signed), "
                       "delegation-bound compliance")
                t.line("  (logical bounds held with zero connectivity), "
                       "recovery (survived partition,")
                t.line("  reconciled). NOT shown on this platform: OS-level "
                       "containment — records")
                t.line("  honestly carry backend=none; run under bubblewrap "
                       "for that.")
                t.line("  NOT proven: output correctness — that needs a human "
                       "on the loop.")
                t.line()
                t.line("  For OS-enforced bounds: run on Linux with bubblewrap "
                       "installed, or")
                t.line("  `docker run … gyza demo`. Pass --require-sandbox to "
                       "refuse rather than")
                t.line("  run disclosed.")
            else:
                t.line("  ✗ scenario invariant violated — see flags above.")
        t.line()

        return DemoResult(
            envelopes=[e0, e1, e2M, e3M, e2m, e3m, e6],
            dag=dag,
            audit_report=report,
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
    require_sandbox = "--require-sandbox" in argv
    try:
        result = run_demo(verbose=True, sandbox_mode=mode,
                          require_sandbox=require_sandbox)
    except SandboxRequiredError:
        return 2   # refused: OS enforcement required but unavailable
    ok = (
        result.all_nodes_converged
        and result.dag.valid
        and len(result.dag.leaves) == 1
        and result.over_bound_rejected
        and result.minority_control_paused
        and result.majority_control_active
        and verify_delegation(result.delegation_hops)[0]
    )
    # The OS-level audit only passes when bwrap actually ran; under the
    # disclosed no-sandbox path it is intentionally undemonstrated
    # (backend=none), so require it only in enforced mode.
    if result.sandbox_mode == "bwrap":
        ok = ok and result.audit_report.valid
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
