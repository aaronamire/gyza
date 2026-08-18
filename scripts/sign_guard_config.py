#!/usr/bin/env python3
"""Sign the guard configuration — C-8's authority half.

    python scripts/sign_guard_config.py --key <authority.key> \
        [--bounds gyza/containment/guard_bounds.json] \
        [--out gyza/containment/guard_bounds.signed.json]

THE KEY IS NOT THE SYSTEM'S, AND THAT IS THE ENTIRE POINT. C-8 says the guard
configuration lives in a separate trust domain: the constrained system verifies
the signature and does not hold the key that makes one. So this script is
deliberately NOT wired into the runtime, the CLI, or any test fixture — it is an
operator tool, run by whoever holds the authority key, on a machine of their
choosing.

Generate an authority key (once, and keep it off the machine that runs agents):

    python scripts/sign_guard_config.py --generate-key authority.key

Then sign. Loosening a bound requires the separate `install_loosening` path with
its own signed record — that is not this script, because a loosening must be
declared and read by a human, never slipped in behind an ordinary re-sign.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

from gyza.containment.guardconfig import config_hash, sign_config  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BOUNDS = REPO / "gyza" / "containment" / "guard_bounds.json"
DEFAULT_OUT = REPO / "gyza" / "containment" / "guard_bounds.signed.json"


def generate_key(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"refusing to overwrite an existing key at {path}")
    seed = secrets.token_bytes(32)
    path.write_bytes(seed)
    path.chmod(0o600)
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    print(f"authority key written to {path} (mode 0600)")
    print(f"authority pubkey: {pk.public_bytes_raw().hex()}")
    print("\nKeep this key OFF the machine that runs agents. A guard whose key "
          "the constrained system holds is not a guard.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generate-key", metavar="PATH")
    ap.add_argument("--key", metavar="PATH")
    ap.add_argument("--bounds", default=str(DEFAULT_BOUNDS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    if args.generate_key:
        generate_key(Path(args.generate_key))
        return 0
    if not args.key:
        ap.error("--key is required (or --generate-key to make one)")

    seed = Path(args.key).read_bytes()
    if len(seed) != 32:
        raise SystemExit(f"authority key must be a 32-byte seed, got {len(seed)}")
    raw = json.loads(Path(args.bounds).read_text())

    # Sign ONLY the policy-bearing fields. `_comment` and `declared` are prose
    # and must not be inside the signed bytes: a signature over commentary
    # invites re-signing for an edit that changes no policy, and every re-sign
    # is an opportunity to slip one in.
    config = {
        "version": int(raw.get("version", 1)),
        "bounds": raw["bounds"],
        "tier_assignments": raw.get("tier_assignments", {}),
    }
    doc = {"config": config, "signature": sign_config(config, seed)}
    Path(args.out).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    print(f"signed {len(config['bounds'])} bound(s) at version "
          f"{config['version']} -> {args.out}")
    print(f"config hash    : {config_hash(config)}")
    print(f"authority pubkey: {pk.public_bytes_raw().hex()}")
    print("\nLoad it with:")
    print("    build_registries(bounds_file=<out>, "
          "authority_pubkey=bytes.fromhex(<pubkey>))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
