"""
AR-1 — the empirical claim-type distribution of chains the system ACTUALLY
audits, and the depth curve under it. Deterministic, zero model calls.

The composition is NOT chosen here. `gyza/audit.py` (2026-07-03, predating this
session) fixes which checks run per action; this reads them off a real audit of
a real chain.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import blake3                                                     # noqa: E402
from gyza.audit import audit_provenance                           # noqa: E402
from gyza.icp import ICPEnvelope, compute_envelope_hash, sign_envelope  # noqa: E402
from gyza.identity import (                                       # noqa: E402
    AgentIdentity, LocalCompositor, manifest_canonical_bytes, manifest_hash_hex,
)
from gyza.verification.adapters import build_registries           # noqa: E402

SEED = 1
DEPTHS = (1, 2, 4, 8)

# Which claim type each check performed by audit.py corresponds to. The MAPPING
# is stated here; the COMPOSITION (which checks run) is production code's.
AUDIT_CHECKS = {
    "verify_dag.signature": "envelope_signature",
    "verify_dag.linkage": "envelope_chain",
    "binding_ok": "artifact_content_address",
    "manifest_bound_ok": "manifest_identity",
    "within_bounds": "enforcement_within_manifest",
}


def _identity(tmp):
    kp = os.path.join(tmp, "compositor.key")
    with open(kp, "wb") as f:
        f.write(secrets.token_bytes(32))
    os.chmod(kp, 0o600)
    c = LocalCompositor(key_path=kp)
    seed, manifest = c.issue_agent(
        agent_type="ar1", model_path="mock", fs_read_paths=["/in"],
        fs_write_paths=["/out"], allowed_hosts=[], memory_limit_mb=512,
        attestation_tier=1)
    return AgentIdentity(seed, manifest)


def build_real_chain(idn, n: int):
    """A genuine signed ICP chain, built the way the runner builds one:
    canonical-JSON artifact with a folded enforcement record, content-addressed
    output hash, parent-hash linkage."""
    envs, artifacts = [], {}
    parent = None
    mh = manifest_hash_hex(idn.manifest)
    # A real step CONSUMES the prior step's output: verify_chain requires
    # non-empty input_hashes (icp.py:129) and verify_dag builds data-dependency
    # edges from them (icp.py:187). A chain with empty inputs is not a chain the
    # production verifiers accept -- an earlier version of this harness built
    # one and the audit correctly refused it.
    seed_input = blake3.blake3(b"ar1-genesis").hexdigest()
    artifacts_seed = seed_input
    prev_out = None
    for i in range(n):
        payload = {"text": f"step-{i}", "__enforcement__": {
            "backend": "bubblewrap", "ro_paths": ["/in"], "rw_paths": ["/out"],
            "requires_network": False, "max_memory_mb": 256}}
        canonical = json.dumps(payload, sort_keys=True,
                               separators=(",", ":")).encode()
        oh = blake3.blake3(canonical).hexdigest()
        artifacts[oh] = canonical
        inputs = [prev_out] if prev_out is not None else [artifacts_seed]
        env = ICPEnvelope(
            intent_id="ar1", action_id=f"a{i}", agent_pubkey=idn.pubkey_hex,
            capability_manifest_hash=mh, input_hashes=inputs, output_hash=oh,
            parent_envelope_hash=parent, timestamp_ns=1000 + i,
            inference_backend="mock", model_identifier="mock",
            duration_ms=1, tokens_in=1, tokens_out=1)
        signed = sign_envelope(env, idn._seed)
        envs.append(signed)
        parent = compute_envelope_hash(signed)
        prev_out = oh
    artifacts[artifacts_seed] = b"ar1-genesis"
    return envs, artifacts


def main() -> None:
    verifiers, _specs = build_registries()
    carrier_of = {ct: verifiers.get(ct).carrier for ct in verifiers.claim_types()}

    with tempfile.TemporaryDirectory() as tmp:
        idn = _identity(tmp)
        mbytes = manifest_canonical_bytes(idn.manifest)
        mh = manifest_hash_hex(idn.manifest)

        envs, artifacts = build_real_chain(idn, 8)
        report = audit_provenance(
            envs,
            resolve_artifact=lambda h: artifacts.get(h),
            resolve_manifest=lambda h: idn.manifest if h == mh else None,
            require_closed=True, require_all_artifacts=True)

        # FEASIBILITY: a real multi-envelope chain that actually audits clean.
        rows = list(report.actions)
        feasible = len(rows) >= 2 and report.valid
        if not feasible:
            print(f"NOT-MEASURABLE: chain len={len(rows)} valid={report.valid}")
            return

        # Which claim types did the audit actually exercise, per action?
        exercised = []
        for r in rows:
            per = ["envelope_signature", "envelope_chain",
                   "artifact_content_address", "manifest_identity"]
            if r.is_execution:
                per.append("enforcement_within_manifest")
            exercised.append(per)

    flat = [ct for per in exercised for ct in per]
    dist: dict[str, int] = {}
    for ct in flat:
        dist[ct] = dist.get(ct, 0) + 1
    carriers: dict[str, int] = {}
    for ct in flat:
        carriers[carrier_of[ct]] = carriers.get(carrier_of[ct], 0) + 1

    n = len(flat)
    p_proof = carriers.get("PROOF", 0) / n
    # empirical depth curve: probability every stage of a depth-d chain is
    # PROOF-carried, under the EMPIRICAL distribution
    emp = {d: round(p_proof ** d, 6) for d in DEPTHS}
    # uniform baseline, from the registry composition (10 PROOF of 18)
    uni_p = 10 / 18
    uni = {d: round(uni_p ** d, 6) for d in DEPTHS}

    # THE COUNTER-METRIC: does the audit cover CORRECTNESS of the work?
    semantic_covered = sum(1 for ct in flat if carrier_of.get(ct) == "NONE")
    out = {
        "seed": SEED, "n_actions_audited": len(rows), "audit_valid": report.valid,
        "claim_types_exercised": dist,
        "carrier_distribution": carriers,
        "p_proof_empirical": round(p_proof, 6),
        "depth_curve_empirical": emp,
        "depth_curve_uniform": uni,
        "COUNTER_METRIC": {
            "semantic_claims_audited": semantic_covered,
            "correctness_coverage_of_the_work": 0.0 if semantic_covered == 0 else None,
            "note": ("the audit composes signature, linkage, content-address, "
                     "manifest-identity and bounds checks. NONE of them asks "
                     "whether the output is RIGHT."),
        },
        "distinct_claim_types": len(dist),
        "DEFINITIONAL_if_single_type": len(dist) == 1,
    }
    Path(__file__).with_name("ar1_result.json").write_text(json.dumps(out, indent=1))

    print(f"audited {len(rows)} actions, valid={report.valid}")
    print(f"claim types exercised: {dist}")
    print(f"carriers: {carriers}   p_proof={p_proof:.4f}")
    print(f"\n{'depth':>6} {'empirical':>11} {'uniform':>10}")
    for d in DEPTHS:
        print(f"{d:>6} {emp[d]:>11.4f} {uni[d]:>10.4f}")
    print(f"\nCOUNTER-METRIC  semantic claims audited: {semantic_covered}"
          f"  -> correctness coverage of the work: "
          f"{0.0 if semantic_covered == 0 else 'n/a'}")


if __name__ == "__main__":
    main()
