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
from typing import Callable

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


def audit_provenance(
    envelopes: "list[ICPEnvelope]",
    *,
    resolve_artifact: ArtifactResolver,
    resolve_manifest: ManifestResolver,
    require_closed: bool = True,
    require_all_artifacts: bool = True,
) -> AuditReport:
    """
    Audit a whole workflow in one call.

    ``require_closed`` is forwarded to ``verify_dag`` (every non-root
    spine parent must be held — DAG-form tamper/loss detection).

    ``require_all_artifacts`` closes the hide-the-evidence hole: if an
    envelope's output artifact cannot be resolved, the row fails rather
    than silently passing. (A withheld artifact could otherwise conceal
    an over-bound execution, since execution-vs-coordination is decided
    by inspecting the artifact for an ``__enforcement__`` record.)

    An envelope is a *coordination* action if its resolved artifact has
    no ``__enforcement__`` record; such rows are not bounds-checked
    (there is nothing to bound), only content-address-bound.
    """
    envs = list(envelopes)
    dag = verify_dag(envs, require_closed=require_closed)

    rows: list[ActionAudit] = []
    for env in envs:
        eh = compute_envelope_hash(env)
        art = resolve_artifact(env.output_hash)

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
                reason = "output artifact not resolvable (withheld)"
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

        row_ok = binding_ok and manifest_bound_ok and within_bounds
        if not row_ok and not reason:
            reason = "binding failed"
        rows.append(ActionAudit(
            action_id=env.action_id, envelope_hash=eh,
            is_execution=is_execution, binding_ok=binding_ok,
            manifest_bound_ok=manifest_bound_ok, within_bounds=within_bounds,
            ok=row_ok, reason=reason,
        ))

    valid = dag.valid and all(r.ok for r in rows)
    n_exec = sum(1 for r in rows if r.is_execution)
    summary = (
        f"{len(envs)} envelopes, {len(dag.roots)} root / {len(dag.leaves)} "
        f"leaf, {n_exec} bounded execution(s); "
        f"dag={'VALID' if dag.valid else 'INVALID'}; "
        f"verdict={'VALID' if valid else 'INVALID'}"
    )
    return AuditReport(dag=dag, actions=rows, valid=valid, summary=summary)


__all__ = [
    "ActionAudit",
    "AuditReport",
    "ArtifactResolver",
    "ManifestResolver",
    "audit_provenance",
]
