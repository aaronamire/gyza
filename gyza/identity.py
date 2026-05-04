"""
Agent identity issuance and capability manifests.

In production, the Wayland compositor mints agent keypairs and signs
capability manifests at spawn time. Phase 1 substitutes a `LocalCompositor`
that simulates this on disk:

  - Master seed at ~/.gyza/compositor.key (created on first run from
    secrets.token_bytes XOR os.urandom — paranoid entropy mixing so a
    single-source RNG bug doesn't sink the whole hierarchy).
  - Compositor Ed25519 keypair derived from the master seed via BLAKE3
    keyed hash (domain-separated by a fixed context string).
  - Agent keys derived per-spawn from the master seed keyed with
    (agent_type, spawn_counter, time_ns) — counter is monotonic and
    persisted next to the master seed so re-runs don't collide.

All compositor signatures are over BLAKE3(canonical_json(payload_minus_sig)),
matching the convention in icp.py — one canonicalization rule across the
whole project.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from gyza.icp import ICPSigner


# Domain-separation tags. Distinct contexts mean a leak of one derived
# key never lets you predict another (BLAKE3 keyed hash with different
# data is independent of every other derivation).
_CTX_COMPOSITOR_SEED = b"gyza.compositor.ed25519.v1"
_CTX_AGENT_SEED = b"gyza.agent.ed25519.v1"


CAPABILITY_MANIFEST_SCHEMA: dict[str, Any] = {
    "agent_id": str,            # = agent pubkey hex
    "model_hash": str,          # BLAKE3 hex of model bytes or model identifier
    "spawn_time": int,          # ns since epoch
    "spawn_counter": int,       # monotonic per compositor instance
    "parent_agent_id": (str, type(None)),
    "capabilities": {
        "filesystem": {
            "read": list,
            "write": list,
            "landlock_enforced": bool,
        },
        "network": {
            "allowed_hosts": list,
            "allowed_ports": list,
        },
        "spawn": {
            "permitted": list,           # e.g. ["replica"] or []
            "resource_budget": {
                "max_children": int,
                "cpu_quota_percent": int,
                "memory_limit_mb": int,
            },
        },
    },
    "attestation_tier": int,    # 0..3
    "compositor_pubkey": str,   # hex
    "signature": str,           # hex; covers BLAKE3 of manifest minus this field
}


def _canon_bytes(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _manifest_payload_hash(manifest: dict) -> bytes:
    m = dict(manifest)
    m.pop("signature", None)
    return blake3.blake3(_canon_bytes(m)).digest()


def manifest_hash_hex(manifest: dict) -> str:
    """Hash of the *full* manifest JSON, signature included.

    This is what ICPSigner.capability_manifest_hash binds to: the manifest
    as it was issued. Including the signature locks the manifest's identity
    to its compositor-attested form.
    """
    return blake3.blake3(_canon_bytes(manifest)).hexdigest()


def _derive_seed(master: bytes, context: bytes, info: bytes) -> bytes:
    return blake3.blake3(context + b"|" + info, key=master).digest()


def _resolve(p: str) -> Path:
    return Path(os.path.expanduser(p))


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


class LocalCompositor:
    def __init__(self, key_path: str = "~/.gyza/compositor.key"):
        self._key_path = _resolve(key_path)
        self._counter_path = self._key_path.parent / "spawn_counter"
        self._revoke_dir = self._key_path.parent / "revocations"

        self._master_seed = self._load_or_create_master()

        # Compositor Ed25519 keypair from master seed.
        comp_seed = _derive_seed(self._master_seed, _CTX_COMPOSITOR_SEED, b"")
        self._comp_sk = Ed25519PrivateKey.from_private_bytes(comp_seed)
        self._comp_pk_bytes = self._comp_sk.public_key().public_bytes_raw()

        self._spawn_counter = self._load_counter()

    # ------------------------------------------------------------------
    # Master seed lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_master(self) -> bytes:
        if self._key_path.exists():
            data = self._key_path.read_bytes()
            if len(data) != 32:
                raise ValueError(
                    f"compositor key at {self._key_path} is corrupt: "
                    f"expected 32 bytes, got {len(data)}"
                )
            return data

        # Paranoid mix: secrets.token_bytes is the standard CSPRNG; XORing
        # with os.urandom gives a second independent draw. Even if one
        # source had a hidden bias, the XOR remains uniformly random.
        a = secrets.token_bytes(32)
        b = os.urandom(32)
        master = bytes(x ^ y for x, y in zip(a, b))
        _atomic_write(self._key_path, master, mode=0o600)
        return master

    def _load_counter(self) -> int:
        if not self._counter_path.exists():
            return 0
        try:
            return int(self._counter_path.read_text().strip())
        except (ValueError, OSError):
            return 0

    def _persist_counter(self) -> None:
        _atomic_write(
            self._counter_path,
            str(self._spawn_counter).encode("utf-8"),
            mode=0o600,
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    @property
    def pubkey_hex(self) -> str:
        return self._comp_pk_bytes.hex()

    def _compute_model_hash(self, model_path: str) -> str:
        p = _resolve(model_path)
        if p.is_file():
            h = blake3.blake3()
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        # API-hosted model or unresolved path: hash the identifier itself.
        return blake3.blake3(model_path.encode("utf-8")).hexdigest()

    def issue_agent(
        self,
        agent_type: str,
        model_path: str,
        fs_read_paths: list[str],
        fs_write_paths: list[str],
        allowed_hosts: list[str] | None = None,
        spawn_permitted: list[str] | None = None,
        max_children: int = 0,
        memory_limit_mb: int = 512,
        parent_agent_id: str | None = None,
        attestation_tier: int = 1,
    ) -> tuple[bytes, dict]:
        if attestation_tier not in (0, 1, 2, 3):
            raise ValueError(
                f"attestation_tier must be 0..3, got {attestation_tier}"
            )

        spawn_counter = self._spawn_counter
        spawn_time = time.time_ns()

        # Per-agent seed: BLAKE3 keyed hash of (agent_type | counter | time).
        # The counter alone would be enough for uniqueness, but mixing in
        # time_ns means even a corrupted counter file still produces fresh
        # keys instead of reissuing an existing identity.
        info = f"{agent_type}|{spawn_counter}|{spawn_time}".encode("utf-8")
        agent_seed = _derive_seed(self._master_seed, _CTX_AGENT_SEED, info)
        agent_sk = Ed25519PrivateKey.from_private_bytes(agent_seed)
        agent_pk_hex = agent_sk.public_key().public_bytes_raw().hex()

        manifest: dict[str, Any] = {
            "agent_id": agent_pk_hex,
            "model_hash": self._compute_model_hash(model_path),
            "spawn_time": spawn_time,
            "spawn_counter": spawn_counter,
            "parent_agent_id": parent_agent_id,
            "capabilities": {
                "filesystem": {
                    "read": list(fs_read_paths),
                    "write": list(fs_write_paths),
                    "landlock_enforced": True,
                },
                "network": {
                    "allowed_hosts": list(allowed_hosts or []),
                    "allowed_ports": [],
                },
                "spawn": {
                    "permitted": list(spawn_permitted or []),
                    "resource_budget": {
                        "max_children": max_children,
                        "cpu_quota_percent": 50,
                        "memory_limit_mb": memory_limit_mb,
                    },
                },
            },
            "attestation_tier": attestation_tier,
            "compositor_pubkey": self.pubkey_hex,
        }

        signature = self._comp_sk.sign(_manifest_payload_hash(manifest))
        manifest["signature"] = signature.hex()

        # Bump and persist counter only after a successful issue, so a
        # crash mid-derive doesn't leak a counter value to nothing.
        self._spawn_counter += 1
        self._persist_counter()

        return agent_seed, manifest

    def verify_manifest(self, manifest: dict) -> bool:
        sig_hex = manifest.get("signature")
        if not isinstance(sig_hex, str) or not sig_hex:
            return False
        try:
            sig = bytes.fromhex(sig_hex)
        except ValueError:
            return False
        try:
            pk = Ed25519PublicKey.from_public_bytes(self._comp_pk_bytes)
            pk.verify(sig, _manifest_payload_hash(manifest))
            return True
        except (InvalidSignature, ValueError):
            return False

    def revoke_agent(self, agent_id: str, reason: str) -> dict:
        record: dict[str, Any] = {
            "agent_id": agent_id,
            "reason": reason,
            "timestamp_ns": time.time_ns(),
            "compositor_pubkey": self.pubkey_hex,
        }
        sig = self._comp_sk.sign(_manifest_payload_hash(record))
        record["signature"] = sig.hex()

        self._revoke_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._revoke_dir, 0o700)
        except OSError:
            pass
        out = self._revoke_dir / f"{agent_id}.json"
        _atomic_write(
            out,
            json.dumps(record, sort_keys=True, indent=2).encode("utf-8"),
            mode=0o600,
        )
        return record

    def verify_revocation(self, record: dict) -> bool:
        # Same envelope shape as manifest verification — payload is the
        # record minus its signature, hashed and Ed25519-verified.
        sig_hex = record.get("signature")
        if not isinstance(sig_hex, str) or not sig_hex:
            return False
        try:
            sig = bytes.fromhex(sig_hex)
            pk = Ed25519PublicKey.from_public_bytes(self._comp_pk_bytes)
            pk.verify(sig, _manifest_payload_hash(record))
            return True
        except (InvalidSignature, ValueError):
            return False


class AgentIdentity:
    def __init__(self, private_key_seed: bytes, manifest: dict):
        if len(private_key_seed) != 32:
            raise ValueError(
                f"private_key_seed must be 32 bytes, got {len(private_key_seed)}"
            )
        self._seed = private_key_seed
        self._manifest = manifest

        sk = Ed25519PrivateKey.from_private_bytes(private_key_seed)
        self._sk = sk
        self._pk_bytes = sk.public_key().public_bytes_raw()
        derived_pk = self._pk_bytes.hex()

        manifest_agent_id = manifest.get("agent_id")
        if manifest_agent_id != derived_pk:
            raise ValueError(
                "manifest.agent_id does not match the public key derived "
                "from private_key_seed"
            )

    @property
    def pubkey_hex(self) -> str:
        return self._pk_bytes.hex()

    @property
    def agent_id(self) -> str:
        return self.pubkey_hex

    @property
    def manifest_hash(self) -> str:
        return manifest_hash_hex(self._manifest)

    @property
    def manifest(self) -> dict:
        return self._manifest

    def get_icp_signer(self) -> ICPSigner:
        return ICPSigner(self._seed, self.pubkey_hex, self.manifest_hash)

    def sign_bytes(self, data: bytes) -> str:
        return self._sk.sign(data).hex()

    def verify_signature(self, data: bytes, sig_hex: str) -> bool:
        try:
            sig = bytes.fromhex(sig_hex)
        except ValueError:
            return False
        try:
            pk = Ed25519PublicKey.from_public_bytes(self._pk_bytes)
            pk.verify(sig, data)
            return True
        except (InvalidSignature, ValueError):
            return False


__all__ = [
    "CAPABILITY_MANIFEST_SCHEMA",
    "LocalCompositor",
    "AgentIdentity",
    "manifest_hash_hex",
]

# Silence unused-import warnings.
_ = stat
