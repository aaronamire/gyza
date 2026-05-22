"""
Self-contained bounds-proof demonstration.

Shows — with zero external dependencies (no daemon, no network, no API
key) — that a valid signed Gyza envelope cryptographically IMPLIES the
work ran inside declared, kernel-enforced bounds, and that an
independent party can verify this with no trust in the runner.

Three acts:
  1. Honest bounded execution → independent verification (INDEPENDENTLY VERIFIED).
  2. Tamper detection: rewrite the enforcement record post-signing → caught.
  3. Refuse-to-sign: a sandbox wider than the manifest → no envelope is produced.

Every cryptographic / predicate operation calls the SAME production
function `gyza submit` uses:
  - sandboxed_mock_executor          (real bubblewrap sandbox)
  - enforcement_satisfies_manifest   (the refuse-to-sign / verify predicate)
  - manifest_hash_hex, ICPSigner.sign_action, verify_envelope,
    compute_envelope_hash            (real ICP crypto)

The only orchestration replicated here is the ~10-line artifact fold
from runner._execute/_complete; it is cited inline so it can't drift
silently from the production path.

Usage:
    python demo/bounds_proof_demo.py
    gyza demo bounds
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

import blake3

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gyza.icp import verify_envelope  # noqa: E402
from gyza.identity import (  # noqa: E402
    AgentIdentity,
    LocalCompositor,
    manifest_hash_hex,
)
from gyza.sandbox.config import (  # noqa: E402
    SandboxConfig,
    enforcement_satisfies_manifest,
    sandbox_config_from_manifest,
)
from gyza.sandbox.executor import sandboxed_mock_executor  # noqa: E402

BAR = "─" * 64


def _fold_artifact(text: str, enforcement: dict | None) -> tuple[bytes, str]:
    """Mirror of runner._execute's artifact construction.

    The enforcement record is folded INTO the hashed artifact, so the
    envelope's output_hash — and therefore its signature — commits to
    it. That is what makes the bounds tamper-evident rather than a side
    claim. Source of truth: gyza/runner.py::AgentRunner._execute. Kept
    deliberately tiny so divergence is obvious on review.
    """
    artifact_obj: dict = {"text": text}
    if enforcement is not None:
        artifact_obj["__enforcement__"] = enforcement
    canonical = json.dumps(
        artifact_obj, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return canonical, blake3.blake3(canonical).hexdigest()


def _issue_bounded_agent(compositor: LocalCompositor):
    """No filesystem, no network, 512 MB memory budget."""
    seed, manifest = compositor.issue_agent(
        agent_type="demo.bounds",
        model_path="mock",
        fs_read_paths=[],
        fs_write_paths=[],
        allowed_hosts=[],
        memory_limit_mb=512,
        attestation_tier=1,
    )
    return AgentIdentity(seed, manifest), manifest


def _print_manifest_bounds(manifest: dict) -> None:
    caps = manifest["capabilities"]
    budget = caps["spawn"]["resource_budget"]
    print(f"  filesystem read:   {caps['filesystem']['read'] or 'NONE'}")
    print(f"  filesystem write:  {caps['filesystem']['write'] or 'NONE'}")
    print(f"  network hosts:     {caps['network']['allowed_hosts'] or 'NONE'}")
    print(f"  memory budget:     {budget['memory_limit_mb']} MB")


def _print_enforcement(enf: dict) -> None:
    tree = str(enf.get("runner_source_tree_hash"))[:12]
    print(f"  sandbox backend:   {enf.get('backend')}  (kernel-enforced)")
    print(f"  ro_paths:          {enf.get('ro_paths') or 'NONE'}")
    print(f"  rw_paths:          {enf.get('rw_paths') or 'NONE'}")
    print(f"  network:           {'OPEN' if enf.get('requires_network') else 'NONE'}")
    print(f"  memory cap:        {enf.get('max_memory_mb')} MB (RLIMIT_AS)")
    print(f"  cpu cap:           {enf.get('max_cpu_seconds')} s (RLIMIT_CPU)")
    print(f"  runner build:      {enf.get('runner_version')} (tree {tree}…)")


def main() -> int:
    print()
    print("GYZA — BOUNDS-PROOF DEMO   (no daemon, no network, no API key)")
    print("=" * 64)
    print("Proves: a valid signed envelope IMPLIES the work ran inside")
    print("declared, kernel-enforced bounds — re-verifiable by anyone,")
    print("with zero trust in the machine that produced it.")
    print()

    # Ephemeral identity — never touches ~/.gyza/compositor.key.
    tmpdir = tempfile.mkdtemp(prefix="gyza-bounds-demo-")
    try:
        key_path = os.path.join(tmpdir, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        compositor = LocalCompositor(key_path=key_path)

        # ========= ACT 1 — honest bounded execution, verified =========
        print(BAR)
        print("ACT 1 — bounded execution, independently verified")
        print(BAR)
        identity, manifest = _issue_bounded_agent(compositor)
        print("Agent issued. Declared capability manifest:")
        _print_manifest_bounds(manifest)
        print()

        print("Executing a task in a bubblewrap sandbox derived FROM the")
        print("manifest (sandbox_config_from_manifest — the manifest is the")
        print("single source of truth for what the sandbox grants):")
        ex = sandboxed_mock_executor(
            response="bounded compute result",
            config=sandbox_config_from_manifest(manifest),
        )
        raw = ex("demo task", {})
        enforcement = raw.get("__enforcement__")
        if not isinstance(enforcement, dict):
            print("  ✗ no enforcement record — is bubblewrap installed?")
            return 1
        print("Host stamped this enforcement record (what bwrap ACTUALLY did):")
        _print_enforcement(enforcement)
        print()

        # Producer gate — the runner refuses to sign unless the sandbox
        # was no wider than the manifest. Source: runner._execute.
        gate_ok, gate_why = enforcement_satisfies_manifest(enforcement, manifest)
        print(
            "REFUSE-TO-SIGN GATE  (enforcement_satisfies_manifest): "
            + ("PASS — proceeding to sign" if gate_ok else f"FAIL — {gate_why}")
        )
        if not gate_ok:
            return 1
        print()

        _, output_hash = _fold_artifact(raw.get("text", ""), enforcement)
        env = identity.get_icp_signer().sign_action(
            intent_id="demo-intent",
            action_id="demo-work-item",
            input_hashes=["00" * 32],
            output_hash=output_hash,
            parent_envelope=None,
            inference_backend=raw.get("inference_backend", "mock"),
            model_identifier=raw.get("model_identifier", "mock"),
            duration_ms=int(raw.get("duration_ms", 0)),
            tokens_in=int(raw.get("tokens_in", 0)),
            tokens_out=int(raw.get("tokens_out", 0)),
        )
        print("Envelope signed. INDEPENDENT VERIFICATION (zero trust in the")
        print("runner — every line is recomputed here from the signed bytes):")
        sig_ok = verify_envelope(env, bytes.fromhex(env.agent_pubkey))
        _, recomputed = _fold_artifact(raw.get("text", ""), enforcement)
        artifact_ok = recomputed == env.output_hash
        manifest_ok = manifest_hash_hex(manifest) == env.capability_manifest_hash
        bounds_ok, bounds_why = enforcement_satisfies_manifest(enforcement, manifest)
        print(f"  signature:         {'✓ VALID' if sig_ok else '✗ INVALID'}")
        print(f"  artifact hash:     {'✓ MATCHES envelope' if artifact_ok else '✗ MISMATCH'}")
        print(f"  manifest hash:     {'✓ MATCHES envelope' if manifest_ok else '✗ MISMATCH'}")
        print(
            f"  bounds check:      "
            + ("✓ enforcement ⊆ manifest (re-verified here)"
               if bounds_ok else f"✗ {bounds_why}")
        )

        runner_trusted = None
        try:
            from gyza.release import is_trusted_release
            rv = enforcement.get("runner_version")
            rh = enforcement.get("runner_source_tree_hash")
            if isinstance(rv, str) and isinstance(rh, str):
                runner_trusted, _ = is_trusted_release(rv, rh)
        except Exception:  # noqa: BLE001
            runner_trusted = None
        if runner_trusted is True:
            print("  runner build:      ✓ trusted release")
        elif runner_trusted is False:
            print("  runner build:      ⚠ unverified (dev tree, not a tagged release)")
        print()

        verified = sig_ok and artifact_ok and manifest_ok and bounds_ok
        if verified and runner_trusted is True:
            print("  ✓ bounded (INDEPENDENTLY VERIFIED + RUNNER ATTESTED)")
            print("    — the strongest claim the protocol makes.")
        elif verified:
            print("  ✓ bounded (INDEPENDENTLY VERIFIED)")
            print("    — manifest re-hashed and bounds predicate re-run here.")
            print("    (+ RUNNER ATTESTED additionally requires a tagged release;")
            print("     this is a dev build, so that half is honestly withheld.)")
        else:
            print("  ✗ verification failed (unexpected)")
            return 1
        print()

        # ========= ACT 2 — tamper detection =========
        print(BAR)
        print("ACT 2 — tamper detection (the proof is not just a label)")
        print(BAR)
        print("An adversary rewrites the enforcement record inside the")
        print("artifact — claiming the agent read /etc/shadow — to forge a")
        print("different history of what the computation touched:")
        tampered = dict(enforcement)
        tampered["ro_paths"] = ["/etc/shadow"]
        _, tampered_hash = _fold_artifact(raw.get("text", ""), tampered)
        print(f"  envelope's committed output_hash: {env.output_hash[:28]}…")
        print(f"  hash of the tampered artifact:    {tampered_hash[:28]}…")
        if tampered_hash != env.output_hash:
            print("  ✗ artifact hash MISMATCH — TAMPER DETECTED.")
            print("    The signature commits to the original artifact; a forged")
            print("    enforcement record cannot be substituted without breaking")
            print("    verification. The bounds are immutable post-signing.")
        else:
            print("  (unexpected: hashes matched)")
            return 1
        print()

        # ========= ACT 3 — refuse-to-sign =========
        print(BAR)
        print("ACT 3 — refuse-to-sign: out-of-bounds work never gets signed")
        print(BAR)
        print("A runner executes the SAME agent but in a sandbox WIDER than the")
        print("manifest — a 4096 MB cap where the manifest authorized 512 MB:")
        wide_cfg = SandboxConfig(
            ro_paths=[], rw_paths=[], requires_network=False,
            max_memory_mb=4096,  # wider than the manifest's 512 MB
        )
        raw_wide = sandboxed_mock_executor(
            response="over-budget", config=wide_cfg,
        )("demo task", {})
        enf_wide = raw_wide.get("__enforcement__")
        print(f"  sandbox enforced memory cap: {enf_wide.get('max_memory_mb')} MB")
        ok2, why2 = enforcement_satisfies_manifest(enf_wide, manifest)
        if not ok2:
            print(f"  ✗ runner REFUSES TO SIGN — {why2}")
            print("    No envelope is produced. A valid signed envelope can")
            print("    therefore never attest execution that exceeded its bounds.")
        else:
            print("  (unexpected: gate passed)")
            return 1
        print()

        print(BAR)
        print("Signed → INDEPENDENTLY VERIFIED.  Tampered → caught.")
        print("Out-of-bounds → never signed.  The bounds-proof is real.")
        print(BAR)
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
