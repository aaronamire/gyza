"""
C-8 — guard configuration in a SEPARATE TRUST DOMAIN.

The guard configuration -- harm bounds, invariant class tags, tier assignments,
the reversibility table -- is signed by an authority key and verified before
use. The system it constrains does not hold that key.

This is structural, not a policy preference. Every containment argument in this
program is an INDUCTION: the invariant holds at s0, and every admitted
transition preserves it, therefore it holds throughout. If the agent can rewrite
the invariant, the induction has no base case and no inductive step -- there is
nothing left to prove and nothing being enforced. A guard an agent can edit is
not a guard.

Two properties, and the second is the one people forget:

  1. TAMPER EVIDENCE. A modified config fails signature verification.
  2. NO SELF-MODIFICATION PATH. Verification alone is not enough: if the runtime
     exposed a setter, an agent could install a config it signed with its OWN
     key and the check would pass against the wrong authority. The verified
     config is therefore frozen, and updates require a signature from the
     declared authority -- a key the constrained system does not possess.

`update_guard_config` is classified IRREVERSIBLE in C-3, so it cannot be staged
in the interior and must pass the promotion gate: the maximally-gated action.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)


class GuardConfigError(RuntimeError):
    """Verification or mutation failure. Always fails closed: an unverifiable
    configuration is not a permissive configuration."""


def canonical_bytes(config: dict) -> bytes:
    return json.dumps(config, sort_keys=True, separators=(",", ":")).encode()


def config_hash(config: dict) -> str:
    return blake3.blake3(canonical_bytes(config)).hexdigest()


def sign_config(config: dict, authority_sk: bytes) -> str:
    """Sign-the-hash, matching the ICP discipline (gyza/icp.py:67)."""
    sk = Ed25519PrivateKey.from_private_bytes(authority_sk)
    return sk.sign(blake3.blake3(canonical_bytes(config)).digest()).hex()


def verify_config(config: dict, signature_hex: str,
                  authority_pk: bytes) -> bool:
    try:
        pk = Ed25519PublicKey.from_public_bytes(authority_pk)
        pk.verify(bytes.fromhex(signature_hex),
                  blake3.blake3(canonical_bytes(config)).digest())
        return True
    except (InvalidSignature, ValueError):
        return False


@dataclass(frozen=True)
class VerifiedGuardConfig:
    """Frozen on purpose. There is no setter, so there is no in-process path by
    which the constrained system installs its own policy."""
    version: int
    bounds: dict
    tier_assignments: dict
    signature: str
    authority_pubkey_hex: str
    config_hash: str

    @property
    def as_dict(self) -> dict:
        return {"version": self.version, "bounds": dict(self.bounds),
                "tier_assignments": dict(self.tier_assignments)}


class GuardConfigStore:
    """Holds the verified configuration and refuses to replace it except under
    the authority signature."""

    def __init__(self, authority_pubkey: bytes):
        self._authority = bytes(authority_pubkey)
        self._cfg: VerifiedGuardConfig | None = None

    @property
    def config(self) -> VerifiedGuardConfig:
        if self._cfg is None:
            raise GuardConfigError(
                "no verified guard configuration loaded; refusing to operate "
                "unconfigured (an absent policy is not a permissive policy)")
        return self._cfg

    @property
    def authority_pubkey_hex(self) -> str:
        return self._authority.hex()

    def load(self, config: dict, signature_hex: str) -> VerifiedGuardConfig:
        return self._install(config, signature_hex)

    def load_file(self, path: str | Path) -> VerifiedGuardConfig:
        doc = json.loads(Path(path).read_text())
        return self._install(doc["config"], doc["signature"])

    def attempt_update(self, config: dict, signature_hex: str,
                       *, requested_by: str = "unknown") -> VerifiedGuardConfig:
        """The path an agent would have to take. It does not hold the authority
        key, so the signature check is what refuses it -- and the refusal names
        the requester so the attempt is auditable rather than silent."""
        try:
            return self._install(config, signature_hex)
        except GuardConfigError as e:
            raise GuardConfigError(
                f"guard configuration update REFUSED (requested by "
                f"{requested_by!r}): {e}. The guard configuration lives in a "
                f"separate trust domain; the constrained system does not hold "
                f"the authority key."
            ) from None

    def _install(self, config: dict, signature_hex: str) -> VerifiedGuardConfig:
        if not verify_config(config, signature_hex, self._authority):
            raise GuardConfigError(
                "signature does not verify against the declared authority key")
        version = int(config.get("version", 0))
        if self._cfg is not None and version <= self._cfg.version:
            # Monotone versioning: a valid OLD config must not be replayable to
            # reinstate loosened bounds that were since tightened.
            raise GuardConfigError(
                f"refusing to install version {version} over "
                f"{self._cfg.version}: guard configuration versions are "
                f"monotone (rollback would be a downgrade attack)")
        self._cfg = VerifiedGuardConfig(
            version=version,
            bounds=dict(config.get("bounds", {})),
            tier_assignments=dict(config.get("tier_assignments", {})),
            signature=signature_hex,
            authority_pubkey_hex=self._authority.hex(),
            config_hash=config_hash(config),
        )
        return self._cfg

    def apply_to(self, harm_registry) -> None:
        """Push verified bounds into C-1. Bounds reach the harm registry ONLY
        through a verified configuration."""
        harm_registry.load_bounds(self.config.bounds)
