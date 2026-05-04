"""
Cross-machine trust registry.

In Phase 1, every agent ran under the same `LocalCompositor`, so
"verify this manifest" reduced to "verify the local compositor's
signature." Phase 2 is multi-machine: hop 1 of a chain may have been
signed by an agent whose compositor is on machine X, hop 2 by an
agent under machine Y's compositor.

`TrustRegistry` is the local pin-set. Compositors get added during
cluster formation, after the QUIC transport's challenge-response
already proved the peer controls the pubkey it claims. Before any
ICP envelope referencing a remote agent's manifest can be trusted,
its compositor's pubkey must be in this table — and not revoked.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


LOG = logging.getLogger("gyza.trust_registry")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trusted_compositors (
    pubkey               TEXT PRIMARY KEY,
    first_seen_ns        INTEGER NOT NULL,
    last_seen_ns         INTEGER NOT NULL,
    peer_ip              TEXT,
    gyza_version         TEXT,
    notes                TEXT,
    revoked              INTEGER NOT NULL DEFAULT 0,
    revoked_at_ns        INTEGER,
    revocation_reason    TEXT
);

CREATE TABLE IF NOT EXISTS cached_manifests (
    manifest_hash       TEXT PRIMARY KEY,
    compositor_pubkey   TEXT NOT NULL,
    manifest_json       TEXT NOT NULL,
    verified_at_ns      INTEGER NOT NULL,
    FOREIGN KEY (compositor_pubkey)
        REFERENCES trusted_compositors(pubkey)
);
"""


def _canon_bytes(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _manifest_payload_hash(manifest: dict) -> bytes:
    m = dict(manifest)
    m.pop("signature", None)
    return blake3.blake3(_canon_bytes(m)).digest()


def _manifest_full_hash(manifest: dict) -> str:
    return blake3.blake3(_canon_bytes(manifest)).hexdigest()


class TrustRegistry:
    def __init__(self, db_path: str = "~/.gyza/trust_registry.db"):
        self._db_path = Path(os.path.expanduser(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tls = threading.local()
        # Bootstrap schema.
        self._conn().executescript(_SCHEMA_SQL)

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is not None:
            return c
        c = sqlite3.connect(str(self._db_path))
        c.row_factory = sqlite3.Row
        c.isolation_level = None
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        self._tls.conn = c
        return c

    # ------------------------------------------------------------------
    # Trust management
    # ------------------------------------------------------------------

    def add_trusted_compositor(
        self,
        pubkey: str,
        peer_ip: str = "",
        gyza_version: str = "",
        notes: str = "",
    ) -> None:
        """Pin a compositor as trusted.

        Caller must have already verified the peer controls this pubkey
        — typically via the QUIC transport's hello/hello_ack handshake.
        Revoked entries are *un*-revoked when re-added so a compositor
        that was retired can come back online cleanly.
        """
        try:
            pk = bytes.fromhex(pubkey)
        except ValueError:
            raise ValueError(f"invalid pubkey hex: {pubkey!r}")
        if len(pk) != 32:
            raise ValueError(f"pubkey must be 32 bytes, got {len(pk)}")

        now_ns = time.time_ns()
        self._conn().execute(
            """
            INSERT INTO trusted_compositors
              (pubkey, first_seen_ns, last_seen_ns, peer_ip, gyza_version, notes,
               revoked, revoked_at_ns, revocation_reason)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, NULL)
            ON CONFLICT(pubkey) DO UPDATE SET
              last_seen_ns = excluded.last_seen_ns,
              peer_ip      = excluded.peer_ip,
              gyza_version = excluded.gyza_version,
              notes        = excluded.notes,
              revoked      = 0,
              revoked_at_ns = NULL,
              revocation_reason = NULL
            """,
            (pubkey, now_ns, now_ns, peer_ip, gyza_version, notes),
        )

    def is_trusted(self, compositor_pubkey: str) -> bool:
        row = self._conn().execute(
            "SELECT revoked FROM trusted_compositors WHERE pubkey=?",
            (compositor_pubkey,),
        ).fetchone()
        if row is None:
            return False
        return int(row["revoked"]) == 0

    def verify_manifest_from_trusted_compositor(
        self, manifest: dict,
    ) -> tuple[bool, str]:
        """Returns (valid, reason). Reason is "ok" iff valid is True."""
        compositor_pubkey = manifest.get("compositor_pubkey")
        if not compositor_pubkey or not isinstance(compositor_pubkey, str):
            return False, "missing compositor_pubkey field"
        if not self.is_trusted(compositor_pubkey):
            return False, (
                f"compositor {compositor_pubkey[:16]} not trusted"
            )

        sig_hex = manifest.get("signature")
        if not isinstance(sig_hex, str) or not sig_hex:
            return False, "manifest missing signature"
        try:
            pk_bytes = bytes.fromhex(compositor_pubkey)
            sig_bytes = bytes.fromhex(sig_hex)
        except ValueError:
            return False, "manifest signature/pubkey not hex"
        if len(pk_bytes) != 32:
            return False, "compositor pubkey wrong length"
        try:
            pk = Ed25519PublicKey.from_public_bytes(pk_bytes)
            pk.verify(sig_bytes, _manifest_payload_hash(manifest))
        except (InvalidSignature, ValueError) as e:
            return False, f"signature invalid: {e}"
        return True, "ok"

    # ------------------------------------------------------------------
    # Manifest cache
    # ------------------------------------------------------------------

    def cache_manifest(self, manifest: dict) -> None:
        compositor_pubkey = manifest.get("compositor_pubkey")
        if not isinstance(compositor_pubkey, str):
            return
        manifest_hash = _manifest_full_hash(manifest)
        self._conn().execute(
            """
            INSERT OR REPLACE INTO cached_manifests
              (manifest_hash, compositor_pubkey, manifest_json, verified_at_ns)
            VALUES (?, ?, ?, ?)
            """,
            (
                manifest_hash, compositor_pubkey,
                json.dumps(manifest, sort_keys=True),
                time.time_ns(),
            ),
        )

    def get_cached_manifest(self, manifest_hash: str) -> dict | None:
        row = self._conn().execute(
            "SELECT manifest_json FROM cached_manifests WHERE manifest_hash=?",
            (manifest_hash,),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["manifest_json"])
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # Listing & revocation
    # ------------------------------------------------------------------

    def list_trusted(self) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM trusted_compositors WHERE revoked=0 "
            "ORDER BY first_seen_ns ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def revoke_compositor(self, pubkey: str, reason: str) -> None:
        self._conn().execute(
            """
            UPDATE trusted_compositors
            SET revoked=1, revoked_at_ns=?, revocation_reason=?
            WHERE pubkey=?
            """,
            (time.time_ns(), reason, pubkey),
        )


__all__ = ["TrustRegistry"]
