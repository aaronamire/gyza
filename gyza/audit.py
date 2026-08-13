"""
Provenance audit — compose the real verifiers into one forensic verdict.

This is the product surface the rest of the substrate exists to support.
Given the envelopes of a workflow (possibly multi-agent, possibly
forked-by-partition and re-joined by fan-in) plus a way to resolve the
artifacts and manifests they reference, produce a single,
independently-verifiable answer:

  * the provenance graph is intact — ``verify_dag``: every signature,
    acyclicity, and (optionally) closed parent linkage;
  * every executed action stayed within the bounds its manifest
    authorized — ``enforcement_satisfies_manifest`` (the brick-3 gate);
  * each executed action's signed ``output_hash`` actually commits to
    the artifact being audited — content-address binding, so a forged
    enforcement record cannot be substituted post-signing;
  * the manifest an envelope names really is the one resolved —
    ``manifest_hash_hex`` binding.

It *composes*, never reimplements: ``verify_dag`` (``gyza.icp``),
``enforcement_satisfies_manifest`` (``gyza.sandbox.config``),
``manifest_hash_hex`` (``gyza.identity``). Capability *composition*
across a delegation chain is an orthogonal predicate
(``gyza.economy.delegation.verify_delegation``) and is left to the
caller, which holds the ``DelegationGrant`` records — conflating the
two would be a modeling error, the same separation those modules keep.

Storage-agnostic by construction: it takes resolver callables, so it
runs against an in-memory dict, the SQLite blackboard's artifact store,
or a remote fetch, without importing any of them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:                    # no runtime import: see `governed` below
    from gyza.verification.ledger import LedgerReport

import blake3

from gyza.icp import DagVerification, ICPEnvelope, compute_envelope_hash, verify_dag
from gyza.identity import manifest_hash_hex
from gyza.sandbox.config import enforcement_satisfies_manifest

# output_hash -> artifact bytes (None if not held); capability_manifest_hash
# -> manifest dict (None if not held).
ArtifactResolver = Callable[[str], "bytes | None"]
ManifestResolver = Callable[[str], "dict | None"]


@dataclass
class ActionAudit:
    """Per-envelope audit row."""
    action_id: str
    envelope_hash: str
    is_execution: bool          # carried a folded __enforcement__ record
    binding_ok: bool            # output artifact resolves AND hashes to output_hash
    manifest_bound_ok: bool     # manifest resolves AND hashes to its named hash
    within_bounds: bool         # enforcement ⊆ manifest (executions only)
    ok: bool                    # this row passed every applicable check
    reason: str                 # empty when ok


@dataclass
class AuditReport:
    dag: DagVerification
    actions: list[ActionAudit]
    valid: bool                 # dag.valid AND every action row ok
    summary: str
    # Present only when audited with ``governed=True``. It records, for every
    # check this audit performed, whether the check's SPECIFICATION is under
    # attestation -- a strictly separate question from whether the check
    # passed. ``valid`` above is computed identically either way and never
    # reads this field; see ``audit_provenance``.
    governance: "LedgerReport | None" = None


def audit_provenance(
    envelopes: "list[ICPEnvelope]",
    *,
    resolve_artifact: ArtifactResolver,
    resolve_manifest: ManifestResolver,
    require_closed: bool = True,
    require_all_artifacts: bool = True,
    governed: bool = False,
) -> AuditReport:
    """
    Audit a whole workflow in one call.

    ``governed`` (opt-in) additionally records every check this audit performs
    as a typed claim, routes each through the ATTESTED specification registry,
    and returns the result on ``report.governance``. It answers a question the
    verdict cannot: *is the specification of the check I just ran under
    attestation?*

    **It cannot change the verdict.** ``valid`` is computed identically with
    the flag on or off (pinned by test), for two reasons. Gating the product
    surface on the governance layer would change when an audit passes, which is
    a semantic change to a forensic verdict rather than wiring. And the two
    answer different questions: ``valid`` reports what was REQUIRED and met,
    ``governance`` reports what was PROVED and under whose attested spec. An
    audit run with ``require_all_artifacts=False`` on a partial replica is
    legitimately VALID while leaving content-address claims UNEVALUATED, and
    collapsing those would destroy the distinction.

    Off by default: with the flag unset nothing in ``gyza.verification`` is
    imported or executed, so the audit path is unchanged byte for byte.

    ``require_closed`` is forwarded to ``verify_dag`` (every non-root
    spine parent must be held — DAG-form tamper/loss detection).

    ``require_all_artifacts`` (default) closes the hide-the-evidence hole:
    if an envelope's output artifact cannot be resolved, the row fails
    rather than silently passing. (A withheld artifact could otherwise
    conceal an over-bound execution, since execution-vs-coordination is
    decided by inspecting the artifact for an ``__enforcement__`` record.)
    Turned off, an unresolvable row is instead *skipped* — treated as
    not-yet-auditable, not failed — so a partial replica mid-gossip can
    still audit the envelopes whose artifacts it does hold (the same
    partial-view concession ``require_closed=False`` makes for spine
    parents). Only turn it off when auditing a known-partial replica.

    An envelope is a *coordination* action if its resolved artifact has
    no ``__enforcement__`` record; such rows are not bounds-checked
    (there is nothing to bound), only content-address-bound.
    """
    envs = list(envelopes)
    dag = verify_dag(envs, require_closed=require_closed)

    ledger = None
    if governed:
        from gyza.verification.ledger import ClaimLedger
        ledger = ClaimLedger()
        # `require_closed` is a VERDICT-CHANGING PARAMETER, so the claim names
        # it. An unnamed one is the determinacy failure the carrier rule
        # refuses -- the same verifier would prove a different proposition
        # depending on a value the claim did not carry.
        ledger.emit("envelope_dag", envs, require_closed=require_closed,
                    note=f"{len(envs)} envelopes")

    rows: list[ActionAudit] = []
    for env in envs:
        eh = compute_envelope_hash(env)
        art = resolve_artifact(env.output_hash)

        if ledger is not None:
            try:
                pk = bytes.fromhex(env.agent_pubkey)
            except ValueError:
                # A malformed key is UNEVALUABLE, not a forgery. Passing None
                # makes the verifier raise, which the ledger records as
                # UNEVALUATED -- never as a refutation.
                pk = None
            ledger.emit("envelope_signature", env, pk, note=env.action_id)
            # `art` is None when the artifact did not resolve. The registered
            # verifier REFUSES a non-bytes input, so that lands as UNEVALUATED
            # ("could not check") rather than REFUTED ("the bytes are wrong"),
            # which is exactly the distinction `reason` draws below.
            ledger.emit("artifact_content_address", art, env.output_hash,
                        note=env.action_id)

        binding_ok = (
            art is not None
            and blake3.blake3(art).hexdigest() == env.output_hash
        )
        is_execution = False
        manifest_bound_ok = True
        within_bounds = True
        reason = ""

        if art is None:
            if require_all_artifacts:
                reason = "output artifact not resolvable (not in store)"
        elif not binding_ok:
            reason = "output artifact does not hash to output_hash (tampered)"
        else:
            try:
                obj = json.loads(art.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                obj = None
            enf = obj.get("__enforcement__") if isinstance(obj, dict) else None
            if isinstance(enf, dict):
                is_execution = True
                manifest = resolve_manifest(env.capability_manifest_hash)
                if manifest is None:
                    manifest_bound_ok = False
                    within_bounds = False
                    reason = "manifest not resolvable for an execution"
                elif manifest_hash_hex(manifest) != env.capability_manifest_hash:
                    manifest_bound_ok = False
                    within_bounds = False
                    reason = (
                        "resolved manifest hash != envelope."
                        "capability_manifest_hash"
                    )
                else:
                    within_bounds, why = enforcement_satisfies_manifest(
                        enf, manifest
                    )
                    if not within_bounds:
                        reason = f"out of bounds: {why}"
                if ledger is not None and manifest is not None:
                    ledger.emit("manifest_identity", manifest,
                                env.capability_manifest_hash, note=env.action_id)
                    ledger.emit("enforcement_within_manifest", enf, manifest,
                                note=env.action_id)

        # A missing artifact fails closed under require_all_artifacts (a
        # withheld artifact could conceal an over-bound execution); with the
        # flag off, an unresolvable row is *skipped* — treated as not-yet-
        # auditable rather than failed — so a partial replica mid-gossip can
        # still audit the envelopes whose artifacts it does hold. binding_ok
        # itself stays honest: it is True only for an artifact that resolved
        # AND hashed to output_hash.
        binding_satisfied = binding_ok or (art is None and not require_all_artifacts)
        row_ok = binding_satisfied and manifest_bound_ok and within_bounds
        if not row_ok and not reason:
            reason = "binding failed"
        rows.append(ActionAudit(
            action_id=env.action_id, envelope_hash=eh,
            is_execution=is_execution, binding_ok=binding_ok,
            manifest_bound_ok=manifest_bound_ok, within_bounds=within_bounds,
            ok=row_ok, reason=reason,
        ))

    # NOTE the ordering: `valid` is computed from `dag` and `rows` alone. The
    # governance fold happens afterwards and feeds nothing back.
    valid = dag.valid and all(r.ok for r in rows)
    n_exec = sum(1 for r in rows if r.is_execution)
    summary = (
        f"{len(envs)} envelopes, {len(dag.roots)} root / {len(dag.leaves)} "
        f"leaf, {n_exec} bounded execution(s); "
        f"dag={'VALID' if dag.valid else 'INVALID'}; "
        f"verdict={'VALID' if valid else 'INVALID'}"
    )

    governance = None
    if ledger is not None:
        from gyza.verification.adapters import build_registries
        from gyza.verification.migration import governed_router
        verifiers, _specs = build_registries()
        governance = ledger.verify_all(governed_router(), verifiers)

    return AuditReport(dag=dag, actions=rows, valid=valid, summary=summary,
                       governance=governance)


def audit_from_store(
    envelopes: "list[ICPEnvelope]",
    store: "object",
    **kwargs,
) -> AuditReport:
    """
    Convenience wrapper that builds the resolvers from a content-
    addressed store exposing ``get(hash) -> bytes | None`` (e.g.
    ``gyza.network.artifact_store.ArtifactStore``, or any dict-like whose
    values are bytes). Manifests are stored as artifacts too — the same
    convention ``verify_chain_multi_compositor`` uses — so the manifest
    resolver decodes the same bytes as JSON. Extra kwargs pass through to
    ``audit_provenance``.
    """
    def _artifact(h: str) -> "bytes | None":
        return store.get(h)  # type: ignore[attr-defined]

    def _manifest(h: str) -> "dict | None":
        raw = store.get(h)  # type: ignore[attr-defined]
        if raw is None:
            return None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return None
        return obj if isinstance(obj, dict) else None

    return audit_provenance(
        envelopes, resolve_artifact=_artifact, resolve_manifest=_manifest,
        **kwargs,
    )


def render_audit_report(
    report: AuditReport, *, title: str = "GYZA PROVENANCE AUDIT"
) -> str:
    """A forensic report readable by a non-engineer evaluator."""
    bar = "=" * 64
    thin = "-" * 64
    d = report.dag
    lines: list[str] = [bar, title, thin]
    if d.valid:
        lines.append("Provenance graph: INTACT")
        lines.append(
            f"  {len(d.topo_order)} actions, {len(d.roots)} root / "
            f"{len(d.leaves)} leaf (deterministic content-addressed order)"
        )
    else:
        lines.append(f"Provenance graph: BROKEN — {d.reason}")
    lines.append(thin)
    for r in report.actions:
        kind = "exec " if r.is_execution else "coord"
        mark = "OK " if r.ok else "FAIL"
        lines.append(f"  [{kind}] {mark}  {r.action_id}")
        if not r.ok:
            lines.append(f"           reason: {r.reason}")
    g = report.governance
    if g is not None:
        lines.append(thin)
        lines.append("Specification governance (separate from the verdict):")
        lines.append(
            f"  {g.n_claims} checks recorded — {g.counts.get('VERIFIED', 0)} "
            f"verified, {g.counts.get('REFUTED', 0)} refuted, "
            f"{g.counts.get('UNEVALUATED', 0)} unevaluated")
        if g.fully_governed:
            lines.append(
                f"  All {g.n_governed} run under an ATTESTED specification.")
        else:
            lines.append(
                f"  {g.n_governed}/{g.n_claims} run under an attested "
                f"specification.")
            lines.append(
                f"  NOT ATTESTED: {', '.join(g.ungoverned_types)}")
            lines.append(
                "  These checks RAN and are reported above. What is missing is "
                "a signed")
            lines.append(
                "  specification fixing what they prove — so their result is "
                "not")
            lines.append(
                "  independently interpretable. This does NOT weaken the "
                "verdict below.")
    lines.append(thin)
    if report.valid:
        lines.append("VERDICT: VALID")
        lines.append("  Accountable (every action signed + attributable),")
        lines.append("  contained (every action within its granted bounds),")
        lines.append("  bounds-compliant (no capability laundering).")
    else:
        lines.append("VERDICT: INVALID — see failing rows above.")
    lines.append("  NOT a claim about output correctness — that needs a "
                 "human on the loop.")
    lines.append(bar)
    return "\n".join(lines)


__all__ = [
    "ActionAudit",
    "AuditReport",
    "ArtifactResolver",
    "ManifestResolver",
    "audit_provenance",
    "audit_from_store",
    "render_audit_report",
]
