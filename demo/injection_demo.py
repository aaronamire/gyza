"""
Injection-attack demo.

Tampers with Agent 1's output AFTER it was written and signed but BEFORE
Agent 2 reads it. Re-walks the chain and shows verify_chain() returning
(False, 1) along with a human-readable explanation of which hop broke
and why.

Run two_agent_pipeline.py first to produce ~/.gyza/demo/chain.json. If
that file is absent this demo synthesizes a fresh two-hop chain on the
fly so it remains runnable standalone.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import blake3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gyza.icp import (
    ICPEnvelope,
    ICPSigner,
    compute_envelope_hash,
    explain_chain_failure,
    verify_chain,
    verify_envelope,
)
from gyza.identity import AgentIdentity, LocalCompositor


CHAIN_PATH = Path.home() / ".gyza" / "demo" / "chain.json"


def _load_or_synthesize() -> tuple[ICPEnvelope, ICPEnvelope, str, str]:
    if CHAIN_PATH.exists():
        data = json.loads(CHAIN_PATH.read_text())
        env_dicts = data["envelopes"]
        agent_pubkeys = data["agent_pubkeys"]
        env1 = ICPEnvelope(**env_dicts[0])
        env2 = ICPEnvelope(**env_dicts[1])
        return env1, env2, agent_pubkeys[0], agent_pubkeys[1]

    # Fallback synthesis — build a fresh two-hop chain so the demo runs
    # standalone if no prior pipeline output is on disk.
    compositor = LocalCompositor(
        key_path=str(Path.home() / ".gyza" / "demo" / "synthetic-compositor.key")
    )
    seed1, manifest1 = compositor.issue_agent(
        "synthetic-query", "anthropic:mock", ["/tmp"], ["/tmp"], attestation_tier=1,
    )
    seed2, manifest2 = compositor.issue_agent(
        "synthetic-summ", "anthropic:mock", ["/tmp"], ["/tmp"], attestation_tier=1,
    )
    id1 = AgentIdentity(seed1, manifest1)
    id2 = AgentIdentity(seed2, manifest2)
    s1 = id1.get_icp_signer()
    s2 = id2.get_icp_signer()

    in_h = blake3.blake3(b"prompt").hexdigest()
    out1_h = blake3.blake3(b"agent1 output").hexdigest()
    out2_h = blake3.blake3(b"agent2 output").hexdigest()
    intent = "11111111-1111-4111-8111-111111111111"

    env1 = s1.sign_action(
        intent, "act-1", [in_h], out1_h, None,
        "mock", "synth", 100, 50, 100,
    )
    env2 = s2.sign_action(
        intent, "act-2", [out1_h], out2_h, env1,
        "mock", "synth", 80, 60, 90,
    )
    return env1, env2, id1.agent_id, id2.agent_id


def main() -> int:
    print("=== INJECTION ATTACK DEMO ===")
    print()
    print(f"Loading two-hop chain from {CHAIN_PATH if CHAIN_PATH.exists() else '(synthesized)'}…")
    env1, env2, pk1_hex, pk2_hex = _load_or_synthesize()

    pk1 = bytes.fromhex(pk1_hex)
    pk2 = bytes.fromhex(pk2_hex)

    # ------------------------------------------------------------------
    # Honest baseline.
    # ------------------------------------------------------------------
    print()
    print("--- Step 1: verify the honest chain ---")
    print(f"  env1 sig OK: {verify_envelope(env1, pk1)}")
    print(f"  env2 sig OK: {verify_envelope(env2, pk2)}")
    print(f"  env2.parent_envelope_hash == hash(env1): "
          f"{env2.parent_envelope_hash == compute_envelope_hash(env1)}")
    valid, idx = verify_chain([env1, env2])
    print(f"  verify_chain([env1, env2]) = ({valid}, {idx})")
    print()
    print(explain_chain_failure([env1, env2]))

    # ------------------------------------------------------------------
    # Tamper attack: someone flips the output_hash of env1 *after* it
    # was signed but *before* Agent 2 reads it.
    # ------------------------------------------------------------------
    print()
    print("--- Step 2: attacker mutates env1.output_hash ---")
    poisoned_output = blake3.blake3(b"poisoned-context-from-attacker").hexdigest()
    print(f"  attacker swaps output_hash → {poisoned_output[:16]}…")
    bad_env1 = replace(env1, output_hash=poisoned_output)

    print()
    print(f"  bad_env1 sig OK: {verify_envelope(bad_env1, pk1)}")
    print("    (the field changed, so the original Ed25519 signature no "
          "longer matches the recomputed payload hash)")

    print()
    print("--- Step 3: re-verify the chain with the tampered env1 ---")
    valid, idx = verify_chain([bad_env1, env2])
    print(f"  verify_chain([bad_env1, env2]) = ({valid}, {idx})")
    print()
    print(explain_chain_failure([bad_env1, env2]))

    print()
    print("--- Why the attack failed ---")
    print(
        "  Hop 0 (Agent 1's envelope) breaks first: the attacker mutated\n"
        "  output_hash, but the signature was bound to the original payload\n"
        "  via BLAKE3 → Ed25519. Without the agent's private seed there is\n"
        "  no way to re-sign, so verify_envelope returns False at index 0\n"
        "  and verify_chain reports (False, 0).\n"
        "\n"
        "  Even if the attacker somehow re-signed env1 (e.g. a stolen\n"
        "  key), env2.parent_envelope_hash still pins env1 to its\n"
        "  pre-tamper hash. Either the attacker fixes-up env2 too — for\n"
        "  which they'd need Agent 2's seed as well — or the chain breaks\n"
        "  at index 1 instead. There is no single-key tampering path that\n"
        "  leaves the chain whole."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
