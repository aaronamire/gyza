"""
The task corpus — the single artifact blocking SR-1/SR-2/SR-4 and K-2/K-3/K-7.

THE R14 PART B4 TRAP, STATED FIRST. A corpus authored by the agent that will be
measured against it measures the corpus. R14's B4 conservation cell was voided
exactly that way. Mitigations applied here:

  * GROUND TRUTH NEVER COMES FROM MY JUDGEMENT. Every outcome is either
    (a) read from R8's cached run, whose verdict is the MBPP dataset's own
        asserts -- an external source; or
    (b) computed by a PRODUCTION VERIFIER that existed before this session
        (gyza/icp.py, gyza/identity.py, gyza/sandbox/config.py,
        gyza/economy/delegation.py).
  * WHAT IS MINE, DISCLOSED: the INSTANCE DISTRIBUTION for the Gyza-native
    types -- which envelopes get tampered, how many delegation chains overreach.
    The verdict on each instance is not mine; the mix is. Every downstream
    number is scoped to that mix.

A DISCLOSED LIMITATION OF THE EXTERNAL SOURCE. MBPP's "CORRECT" label is the
verdict of three asserts, so it is itself a FINITE-SAMPLE judgement. Using it as
ground truth for a semantic claim inherits that: `execution_output_content`
outcomes here mean "passed MBPP's three asserts", not "is correct". That is a
weakening and it is stated wherever the label is used.

Deterministic. SEED = 1. Zero model calls.
"""
from __future__ import annotations

import json
import os
import random
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native_verifier"))

import blake3                                                    # noqa: E402
from gyza.economy.delegation import (                            # noqa: E402
    CapabilitySpec, DelegationHop, verify_delegation,
)
from gyza.icp import ICPEnvelope, sign_envelope, verify_envelope  # noqa: E402
from gyza.identity import AgentIdentity, LocalCompositor, manifest_hash_hex  # noqa: E402
from gyza.sandbox.config import enforcement_satisfies_manifest    # noqa: E402

SEED = 1
NV_CACHE = Path(__file__).resolve().parents[1] / "native_verifier" / "nv_cache"
N_PER_GYZA_TYPE = 16


def _identity(tmp):
    kp = os.path.join(tmp, "compositor.key")
    with open(kp, "wb") as f:
        f.write(secrets.token_bytes(32))
    os.chmod(kp, 0o600)
    c = LocalCompositor(key_path=kp)
    seed, manifest = c.issue_agent(
        agent_type="corpus", model_path="mock", fs_read_paths=["/in"],
        fs_write_paths=["/out"], allowed_hosts=[], memory_limit_mb=512,
        attestation_tier=1)
    return AgentIdentity(seed, manifest)


def _task(tid, goal, claim_type, tier, carrier, outcome, source, **kw):
    return {"task_id": tid, "goal": goal, "claim_type": claim_type,
            "tier": tier, "carrier": carrier, "outcome": bool(outcome),
            "outcome_source": source,
            # A2: type assignment provenance. NEVER self-declared.
            "assigned_by": "human-audited", "audited": True,
            "type_source": kw.pop("type_source", "constructed-by-type"),
            **kw}


# --------------------------------------------------------------------------- #
#  Source 1 — R8's cached MBPP run (EXTERNAL ground truth)                     #
# --------------------------------------------------------------------------- #
def from_mbpp() -> list[dict]:
    import native_verifier as V
    mbpp = V.load_mbpp(n=V.N_CODE, seed=V.SEED)
    # GROUND TRUTH IS THE SOURCE, NOT THE CACHED LABEL. R8's status is
    # `signature == expected` over STRING REPRS (native_verifier.py:219), which
    # over-reports WRONG whenever a value compares equal but its repr differs
    # (dict key order; 1 == 1.0). Re-executing the asserts found 11 false
    # WRONGs in 196 pairs and 0 false CORRECTs -- see mbpp_truth.json.
    truth = json.loads((Path(__file__).with_name("mbpp_truth.json")).read_text())["truth"]
    out = []
    for f in sorted(NV_CACHE.glob("prog__*.json")):
        model = f.name[len("prog__"):-len(".json")].replace("__", "/")
        recs = json.loads(f.read_text())
        for i, r in enumerate(recs):
            if r["status"] == "UNRESOLVED":
                continue          # neither demonstrated-correct nor -wrong
            key = f"{model}|{i}"
            if key not in truth:
                continue
            ok = truth[key]                      # re-executed asserts
            prompt = mbpp[i]["prompt"][:110]
            # (a) the SEMANTIC claim -- tier 3, no verifier
            out.append(_task(
                f"mbpp-sem-{model.split('/')[-1]}-{i}",
                f"produce a program that {prompt}",
                "execution_output_content", 3, "NONE", ok,
                "MBPP asserts RE-EXECUTED (external source). NOTE the verdict "
                "is itself a 3-assert finite-sample judgement",
                handler=model, problem_idx=i))
            # (b) the TEST-carried claim over the SAME artifact -- tier 1
            out.append(_task(
                f"mbpp-test-{model.split('/')[-1]}-{i}",
                f"does the program pass the given tests for: {prompt}",
                "unit_test_execution", 1, "TEST", ok,
                "MBPP asserts RE-EXECUTED (external source)",
                handler=model, problem_idx=i))
    return out


# --------------------------------------------------------------------------- #
#  Source 2 — Gyza-native, PRODUCTION VERIFIERS as ground truth                #
# --------------------------------------------------------------------------- #
def from_gyza() -> list[dict]:
    rng = random.Random(SEED)
    out: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        idn = _identity(tmp)

        # artifact_content_address -- blake3 recomputation
        for i in range(N_PER_GYZA_TYPE):
            data = f"artifact-{i}".encode()
            addr = blake3.blake3(data).hexdigest()
            corrupt = rng.random() < 0.4
            claimed = blake3.blake3(b"other").hexdigest() if corrupt else addr
            out.append(_task(
                f"gyza-addr-{i}", "verify an artifact's content address",
                "artifact_content_address", 1, "PROOF",
                blake3.blake3(data).hexdigest() == claimed,
                "gyza/network/artifact_store.py:47 (blake3 recomputation)"))

        # manifest_identity
        for i in range(N_PER_GYZA_TYPE):
            m = dict(idn.manifest)
            claimed = manifest_hash_hex(m)
            if rng.random() < 0.4:
                m = dict(m, agent_id="tampered")
            out.append(_task(
                f"gyza-manifest-{i}", "verify a manifest's identity hash",
                "manifest_identity", 1, "PROOF",
                manifest_hash_hex(m) == claimed,
                "gyza/identity.py:101 manifest_hash_hex"))

        # enforcement_within_manifest
        for i in range(N_PER_GYZA_TYPE):
            wide = rng.random() < 0.4
            enf = {"backend": "bubblewrap",
                   "ro_paths": ["/in", "/etc"] if wide else ["/in"],
                   "rw_paths": ["/out"], "requires_network": False,
                   "max_memory_mb": 256}
            ok, _ = enforcement_satisfies_manifest(enf, idn.manifest)
            out.append(_task(
                f"gyza-enf-{i}", "verify enforcement stayed within the manifest",
                "enforcement_within_manifest", 1, "PROOF", ok,
                "gyza/sandbox/config.py:286 enforcement_satisfies_manifest"))

        # delegation_attenuation
        for i in range(N_PER_GYZA_TYPE):
            root = CapabilitySpec(ro=frozenset({"/in"}), rw=frozenset({"/out"}),
                                  network=False, mem_cap=512)
            overreach = rng.random() < 0.4
            child = CapabilitySpec(
                ro=frozenset({"/in", "/secret"}) if overreach else frozenset({"/in"}),
                rw=frozenset(), network=False, mem_cap=256)
            chain = [DelegationHop("root", root, root, None),
                     DelegationHop("child", child, child, child)]
            ok, _ = verify_delegation(chain)
            out.append(_task(
                f"gyza-deleg-{i}", "verify authority attenuated down the chain",
                "delegation_attenuation", 1, "PROOF", ok,
                "gyza/economy/delegation.py:213 verify_delegation"))

        # envelope_signature
        pk = bytes.fromhex(idn.pubkey_hex)
        for i in range(N_PER_GYZA_TYPE):
            env = ICPEnvelope(
                intent_id=f"i{i}", action_id=f"a{i}", agent_pubkey=idn.pubkey_hex,
                capability_manifest_hash=manifest_hash_hex(idn.manifest),
                input_hashes=[], output_hash=blake3.blake3(f"o{i}".encode()).hexdigest(),
                parent_envelope_hash=None, timestamp_ns=1_000 + i,
                inference_backend="mock", model_identifier="mock",
                duration_ms=1, tokens_in=1, tokens_out=1)
            signed = sign_envelope(env, idn._seed)
            if rng.random() < 0.4:
                signed = ICPEnvelope(**{**signed.__dict__, "output_hash": "tampered"})
            out.append(_task(
                f"gyza-sig-{i}", "verify an ICP envelope signature",
                "envelope_signature", 1, "PROOF", verify_envelope(signed, pk),
                "gyza/icp.py:82 verify_envelope"))
    return out


def build() -> list[dict]:
    return from_mbpp() + from_gyza()


if __name__ == "__main__":
    tasks = build()
    Path(__file__).with_name("corpus.json").write_text(json.dumps(tasks, indent=1))
    from collections import Counter
    print(f"tasks: {len(tasks)}")
    print("by claim_type:", dict(Counter(t['claim_type'] for t in tasks)))
    print("by carrier   :", dict(Counter(t['carrier'] for t in tasks)))
    print("by tier      :", dict(Counter(t['tier'] for t in tasks)))
    print("outcome true :", sum(t['outcome'] for t in tasks), "/", len(tasks))
