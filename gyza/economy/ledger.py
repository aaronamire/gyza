"""
Bilateral compute-credit ledger.

Phase 3 economic substrate. When agent B on node Y completes a work
item for node X's coordinator, X owes Y compute credits. Each owed
debt is recorded as a LedgerEntry that BOTH sides sign — payer
acknowledges the cost was incurred, earner acknowledges payment was
received. Once both signatures are in, the entry is `settled`. Net
balances per peer are computed from settled entries only.

There is no global consensus. Each node keeps its own SQLite ledger
of entries it cosigned. Two nodes converge on the same view via the
`reconcile_with_peer` exchange, which surfaces disputed entries
without resolving them — the application layer handles disputes via
the ICP chain.

Design points worth understanding:

  * Canonical sign bytes per entry are
        BLAKE3(entry_id ∥ amount ∥ work_item_id ∥ icp_envelope_hash ∥ role)
    where role is "payer" or "earner". Domain separation keeps a
    payer signature from being replayed as an earner signature on
    the same entry.

  * `amount` is canonicalized as ``f"{x:.6f}"`` UTF-8 — six decimal
    places (sub-microcredit precision) — so two parties signing the
    same entry produce byte-identical inputs regardless of float
    representation differences.

  * Entries are append-only. There is no `update_entry`. Adjustments
    are made by issuing a counter-entry (negative amount, parent
    referencing the original) — Phase 4 territory.

  * Free-rider score is purely local (computed from this node's view
    of one peer's debt history). Different nodes will compute
    different scores for the same peer. That's fine for routing /
    deprioritization — global consensus on who's a free-rider isn't
    required for individual nodes to refuse service.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import blake3

from gyza.identity import LocalCompositor


LOG = logging.getLogger("gyza.economy.ledger")

# =============================================================================
# Cost calibration
# =============================================================================
#
# Baseline = i5-7200U + Qwen2.5-3B Q4_K_M, ~8 tok/s. One CPU-second of
# baseline work = 1.0 credit. Per-model rates convert other backends
# to baseline-equivalent so a node billing in credits is independent
# of what backend produced the work.
#
# Rates are credit-per-token-out. For local models the time-based
# fallback dominates because token counts are noisy; for API models
# the token-based rate dominates because it's a direct cost proxy.

ONE_CREDIT_CPU_SECONDS = 1.0

CREDIT_RATES: dict[str, float] = {
    "llama.cpp:qwen2.5-3b-q4_k_m":  1.0 / 8,
    "llama.cpp:qwen2.5-7b-q4_k_m":  1.0 / 3,
    "anthropic:claude-sonnet-4-5":   40.0,
    "anthropic:claude-opus-4-5":     120.0,
    "openai:gpt-4o":                 50.0,
    "mock":                          0.1,
}


def compute_task_cost(
    model_identifier: str,
    tokens_out: int,
    duration_ms: int,
) -> float:
    """
    Convert a task's resource use into credits.

    Returns ``max(token_based, time_based / 2)`` — the time-based
    floor catches local backends where token counts are noisy or
    unavailable; the token-based ceiling catches API backends where
    duration_ms is dominated by network latency unrelated to compute.
    The factor of 1/2 on the time-based fallback is the spec value.
    """
    rate = CREDIT_RATES.get(model_identifier, 1.0)
    token_cost = max(0, tokens_out) * rate
    time_cost = max(0, duration_ms) / 1000.0 * ONE_CREDIT_CPU_SECONDS
    return max(token_cost, time_cost * 0.5)


# =============================================================================
# LedgerEntry
# =============================================================================

@dataclass
class LedgerEntry:
    entry_id: str
    from_compositor: str       # pubkey hex — payer
    to_compositor: str         # pubkey hex — earner
    amount_credits: float
    work_item_id: str
    icp_envelope_hash: str
    model_identifier: str
    tokens_out: int
    duration_ms: int
    created_at_ns: int
    from_signature: str = ""   # populated when payer signs
    to_signature: str = ""     # populated when earner signs
    settled: bool = False      # both signatures present + verified

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LedgerEntry":
        # Tolerate extra keys so cross-version exchange doesn't fail.
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


# =============================================================================
# Canonical bytes
# =============================================================================

def _amount_canonical(amount: float) -> bytes:
    """Six decimal places, UTF-8. Stable across float representations."""
    return f"{amount:.6f}".encode("utf-8")


def canonical_sign_bytes(entry: LedgerEntry, role: str) -> bytes:
    """
    Bytes BOTH parties hash and sign for the same role. ``role`` is
    ``"payer"`` or ``"earner"``. Pipe separator chosen because it
    cannot appear in any of the sub-fields (hex strings, UUIDs, role
    constants) — eliminates ambiguity attacks.
    """
    if role not in ("payer", "earner"):
        raise ValueError(f"role must be 'payer' or 'earner', got {role!r}")
    parts = [
        entry.entry_id.encode("utf-8"),
        _amount_canonical(entry.amount_credits),
        entry.work_item_id.encode("utf-8"),
        entry.icp_envelope_hash.encode("utf-8"),
        role.encode("utf-8"),
    ]
    return blake3.blake3(b"|".join(parts)).digest()


# =============================================================================
# ComputeLedger
# =============================================================================

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id          TEXT PRIMARY KEY,
    from_compositor   TEXT NOT NULL,
    to_compositor     TEXT NOT NULL,
    amount_credits    REAL NOT NULL,
    work_item_id      TEXT NOT NULL,
    icp_envelope_hash TEXT NOT NULL,
    model_identifier  TEXT NOT NULL,
    tokens_out        INTEGER NOT NULL,
    duration_ms       INTEGER NOT NULL,
    created_at_ns     INTEGER NOT NULL,
    from_signature    TEXT,
    to_signature      TEXT,
    settled           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ledger_from ON ledger_entries(from_compositor);
CREATE INDEX IF NOT EXISTS idx_ledger_to   ON ledger_entries(to_compositor);
CREATE INDEX IF NOT EXISTS idx_ledger_work ON ledger_entries(work_item_id);

CREATE TABLE IF NOT EXISTS balance_cache (
    peer_compositor TEXT PRIMARY KEY,
    net_credits     REAL NOT NULL,
    last_updated_ns INTEGER NOT NULL,
    last_entry_id   TEXT
);
"""


class ComputeLedger:
    """
    SQLite-backed bilateral ledger. One instance per local compositor.

    Thread-safe: each thread gets its own sqlite3 connection via
    ``threading.local``. SQLite WAL allows concurrent reads with one
    writer; the bilateral signing flow doesn't generate write
    contention because each entry is touched at most twice (once when
    earner-signs, once when payer-cosigns).
    """

    def __init__(
        self,
        compositor: LocalCompositor,
        db_path: str = "~/.gyza/ledger.db",
    ):
        self._compositor = compositor
        self._db_path = Path(os.path.expanduser(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tls = threading.local()
        # Initialize schema on the constructing-thread connection.
        self._conn().executescript(_SCHEMA_SQL)
        self._conn().commit()

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tls, "conn", None)
        if c is not None:
            return c
        c = sqlite3.connect(str(self._db_path), isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        self._tls.conn = c
        return c

    @property
    def compositor_pubkey(self) -> str:
        return self._compositor.pubkey_hex

    # ------------------------------------------------------------------
    # Entry construction + signing
    # ------------------------------------------------------------------

    def create_entry(
        self,
        from_compositor: str,
        to_compositor: str,
        amount: float,
        work_item_id: str,
        icp_envelope_hash: str,
        model_identifier: str,
        tokens_out: int,
        duration_ms: int,
    ) -> LedgerEntry:
        """
        Build an unsigned entry. Caller decides whether they sign as
        payer (we are ``from_compositor``) or as earner (we are
        ``to_compositor``).
        """
        if amount < 0:
            raise ValueError(f"negative amount {amount}")
        if from_compositor == to_compositor:
            raise ValueError(
                "from_compositor == to_compositor — "
                "self-pay entries are not allowed"
            )
        return LedgerEntry(
            entry_id=str(uuid.uuid7()),
            from_compositor=from_compositor,
            to_compositor=to_compositor,
            amount_credits=amount,
            work_item_id=work_item_id,
            icp_envelope_hash=icp_envelope_hash,
            model_identifier=model_identifier,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
            created_at_ns=time.time_ns(),
        )

    def sign_as_earner(self, entry: LedgerEntry) -> LedgerEntry:
        """
        Earner signs first: "I claim payment for this work."

        Order: the earner produces the work, knows the cost, builds
        the entry, signs first, then sends to the payer for
        countersignature. A payer is unwilling to sign first because
        they want to verify the earner did the work (via the embedded
        ICP envelope hash) before acknowledging the debt.
        """
        if self._compositor.pubkey_hex != entry.to_compositor:
            raise ValueError(
                f"sign_as_earner called by {self._compositor.pubkey_hex[:16]}.. "
                f"but entry.to_compositor is {entry.to_compositor[:16]}.."
            )
        digest = canonical_sign_bytes(entry, "earner")
        sig = self._compositor.sign(digest)
        entry.to_signature = sig
        self._save_entry(entry)
        return entry

    def sign_as_payer(self, entry: LedgerEntry) -> LedgerEntry:
        """
        Payer countersigns: "I acknowledge this cost was incurred."

        Required AFTER the earner signs — without an earner signature,
        a payer would just be promising payment to someone who hasn't
        committed to having done the work. Verifies the earner's
        signature before adding the payer signature; once both are
        present, the entry is settled and the balance cache updates.
        """
        if self._compositor.pubkey_hex != entry.from_compositor:
            raise ValueError(
                f"sign_as_payer called by {self._compositor.pubkey_hex[:16]}.. "
                f"but entry.from_compositor is {entry.from_compositor[:16]}.."
            )
        if not entry.to_signature:
            raise ValueError("earner must sign before payer countersigns")
        ok, reason = verify_earner_signature(entry)
        if not ok:
            raise ValueError(f"earner signature invalid: {reason}")
        digest = canonical_sign_bytes(entry, "payer")
        sig = self._compositor.sign(digest)
        entry.from_signature = sig
        entry.settled = True
        self._save_entry(entry)
        self._update_balance_cache(entry)
        return entry

    def apply_cosigned_entry(self, entry: LedgerEntry) -> LedgerEntry:
        """
        Receive a fully-cosigned entry from the network and store it
        locally. Used at the end of the bilateral protocol when the
        payer echoes the settled entry back to the earner so both
        sides hold the same canonical record.

        Verifies both signatures before saving — refuses to mark an
        entry settled on this node if either signature is invalid.
        """
        valid, reason = self.verify_entry(entry)
        if not valid:
            raise ValueError(f"refusing to apply unverifiable entry: {reason}")
        entry.settled = True
        self._save_entry(entry)
        self._update_balance_cache(entry)
        return entry

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_entry(self, entry: LedgerEntry) -> tuple[bool, str]:
        """
        Validate both signatures on a settled entry. Returns
        (valid, reason) — reason is empty on valid.
        """
        if not entry.from_signature:
            return False, "missing payer signature"
        if not entry.to_signature:
            return False, "missing earner signature"
        ok, reason = verify_payer_signature(entry)
        if not ok:
            return False, f"payer: {reason}"
        ok, reason = verify_earner_signature(entry)
        if not ok:
            return False, f"earner: {reason}"
        return True, ""

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_entry(self, entry: LedgerEntry) -> None:
        # UPSERT — entry signed in two passes (earner-only first, then
        # payer-cosigned), and we want the second pass to update rather
        # than fail on PRIMARY KEY conflict.
        self._conn().execute(
            """
            INSERT INTO ledger_entries (
                entry_id, from_compositor, to_compositor, amount_credits,
                work_item_id, icp_envelope_hash, model_identifier,
                tokens_out, duration_ms, created_at_ns,
                from_signature, to_signature, settled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entry_id) DO UPDATE SET
                from_signature = excluded.from_signature,
                to_signature   = excluded.to_signature,
                settled        = excluded.settled
            """,
            (
                entry.entry_id, entry.from_compositor, entry.to_compositor,
                entry.amount_credits, entry.work_item_id,
                entry.icp_envelope_hash, entry.model_identifier,
                entry.tokens_out, entry.duration_ms, entry.created_at_ns,
                entry.from_signature, entry.to_signature, int(entry.settled),
            ),
        )

    def get_entry(self, entry_id: str) -> LedgerEntry | None:
        row = self._conn().execute(
            "SELECT * FROM ledger_entries WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
        return _row_to_entry(row) if row else None

    def all_entries(self) -> list[LedgerEntry]:
        rows = self._conn().execute(
            "SELECT * FROM ledger_entries ORDER BY created_at_ns ASC"
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    # ------------------------------------------------------------------
    # Balances
    # ------------------------------------------------------------------

    def get_balance(self, peer_compositor: str) -> float:
        """
        Net credits with this peer. Positive = they owe us. Negative
        = we owe them. Computed from settled entries only — unsettled
        entries are aspirational and don't affect economic decisions.
        """
        if peer_compositor == self.compositor_pubkey:
            return 0.0
        # earned_from_peer = settled entries where to=us, from=peer
        earned = self._conn().execute(
            "SELECT COALESCE(SUM(amount_credits), 0) FROM ledger_entries "
            "WHERE settled=1 AND to_compositor=? AND from_compositor=?",
            (self.compositor_pubkey, peer_compositor),
        ).fetchone()[0]
        spent = self._conn().execute(
            "SELECT COALESCE(SUM(amount_credits), 0) FROM ledger_entries "
            "WHERE settled=1 AND from_compositor=? AND to_compositor=?",
            (self.compositor_pubkey, peer_compositor),
        ).fetchone()[0]
        return float(earned) - float(spent)

    def get_total_earned(self) -> float:
        row = self._conn().execute(
            "SELECT COALESCE(SUM(amount_credits), 0) FROM ledger_entries "
            "WHERE settled=1 AND to_compositor=?",
            (self.compositor_pubkey,),
        ).fetchone()
        return float(row[0])

    def get_total_spent(self) -> float:
        row = self._conn().execute(
            "SELECT COALESCE(SUM(amount_credits), 0) FROM ledger_entries "
            "WHERE settled=1 AND from_compositor=?",
            (self.compositor_pubkey,),
        ).fetchone()
        return float(row[0])

    def get_total_transacted_with(self, peer_compositor: str) -> float:
        """Sum of |amount| across settled entries between us and peer."""
        row = self._conn().execute(
            "SELECT COALESCE(SUM(amount_credits), 0) FROM ledger_entries "
            "WHERE settled=1 "
            "AND ( (from_compositor=? AND to_compositor=?) "
            "  OR  (from_compositor=? AND to_compositor=?) )",
            (
                self.compositor_pubkey, peer_compositor,
                peer_compositor, self.compositor_pubkey,
            ),
        ).fetchone()
        return float(row[0])

    def _update_balance_cache(self, entry: LedgerEntry) -> None:
        # The balance cache is a per-peer rolling sum kept consistent
        # with the truth (sum over settled entries). We update on each
        # settle so callers reading the cache see fresh data; callers
        # that need authoritative numbers should use get_balance().
        peer = (
            entry.from_compositor
            if entry.to_compositor == self.compositor_pubkey
            else entry.to_compositor
        )
        if peer == self.compositor_pubkey:
            return
        balance = self.get_balance(peer)
        self._conn().execute(
            """
            INSERT INTO balance_cache (peer_compositor, net_credits, last_updated_ns, last_entry_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(peer_compositor) DO UPDATE SET
                net_credits     = excluded.net_credits,
                last_updated_ns = excluded.last_updated_ns,
                last_entry_id   = excluded.last_entry_id
            """,
            (peer, balance, time.time_ns(), entry.entry_id),
        )

    # ------------------------------------------------------------------
    # Statements + reconciliation
    # ------------------------------------------------------------------

    def export_statement(
        self, peer_compositor: str | None = None,
    ) -> list[dict[str, Any]]:
        if peer_compositor is None:
            rows = self._conn().execute(
                "SELECT * FROM ledger_entries ORDER BY created_at_ns ASC"
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM ledger_entries "
                "WHERE from_compositor=? OR to_compositor=? "
                "ORDER BY created_at_ns ASC",
                (peer_compositor, peer_compositor),
            ).fetchall()
        return [_row_to_entry(r).to_dict() for r in rows]

    def reconcile_with_peer(
        self,
        peer_compositor: str,
        their_entries: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """
        Compare our view of a peer relationship with theirs. Returns
        bucketed entry_ids:

          * agreed         — we both have the same entry (sigs match)
          * disputed       — same entry_id but different fields/sigs
          * missing_ours   — they have it; we don't
          * missing_theirs — we have it; they don't

        Doesn't resolve disputes — that's the application layer's call
        (typically: re-fetch the ICP chain, retry settlement). This
        method just identifies the mismatches.
        """
        ours = {e["entry_id"]: e for e in self.export_statement(peer_compositor)}
        theirs = {e["entry_id"]: e for e in their_entries}

        agreed: list[str] = []
        disputed: list[str] = []
        for eid in ours.keys() & theirs.keys():
            if _entries_equivalent(ours[eid], theirs[eid]):
                agreed.append(eid)
            else:
                disputed.append(eid)
        missing_ours = sorted(theirs.keys() - ours.keys())
        missing_theirs = sorted(ours.keys() - theirs.keys())

        return {
            "agreed": sorted(agreed),
            "disputed": sorted(disputed),
            "missing_ours": missing_ours,
            "missing_theirs": missing_theirs,
        }

    # ------------------------------------------------------------------
    # Free-rider detection
    # ------------------------------------------------------------------

    def free_rider_score(self, peer_compositor: str) -> float:
        """
        Local heuristic in [0, 1]. > 0.7 deprioritizes the peer's
        work items in the unclaimed queue.

        Score = clamp(debt_ratio * 1.5, 0, 1) where
            debt_ratio = max(0, -balance) / total_transacted

        Why 1.5×: a peer who owes us 67% of total transacted hits
        score 1.0 — heavy disincentive for genuine takers. Lower
        debt ratios scale linearly, so a peer with 20% debt ratio
        ends up at score 0.3 (still acceptable).

        Edge: a brand-new peer with zero transactions returns 0.0.
        Free-rider detection requires history.
        """
        if peer_compositor == self.compositor_pubkey:
            return 0.0
        balance = self.get_balance(peer_compositor)
        total = self.get_total_transacted_with(peer_compositor)
        if total <= 0:
            return 0.0
        debt = max(0.0, -balance)  # positive iff we owe them less than they owe us... wait
        # We want: positive debt_ratio when THEY owe US too much.
        # balance > 0 → they owe us (this IS the free-rider indicator).
        # So debt_amount_owed_to_us = max(0, balance).
        owed_to_us = max(0.0, balance)
        if owed_to_us <= 0:
            return 0.0
        debt_ratio = owed_to_us / total
        return min(debt_ratio * 1.5, 1.0)


# =============================================================================
# Standalone signature verification (no ledger instance required)
# =============================================================================

def verify_payer_signature(entry: LedgerEntry) -> tuple[bool, str]:
    if not entry.from_signature:
        return False, "no signature"
    return _verify_role_signature(entry, "payer", entry.from_signature, entry.from_compositor)


def verify_earner_signature(entry: LedgerEntry) -> tuple[bool, str]:
    if not entry.to_signature:
        return False, "no signature"
    return _verify_role_signature(entry, "earner", entry.to_signature, entry.to_compositor)


def _verify_role_signature(
    entry: LedgerEntry,
    role: str,
    sig_hex: str,
    pubkey_hex: str,
) -> tuple[bool, str]:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    try:
        pubkey_bytes = bytes.fromhex(pubkey_hex)
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError as e:
        return False, f"hex decode: {e}"
    if len(pubkey_bytes) != 32:
        return False, f"pubkey len {len(pubkey_bytes)} (want 32)"
    if len(sig_bytes) != 64:
        return False, f"sig len {len(sig_bytes)} (want 64)"
    digest = canonical_sign_bytes(entry, role)
    try:
        Ed25519PublicKey.from_public_bytes(pubkey_bytes).verify(sig_bytes, digest)
        return True, ""
    except InvalidSignature:
        return False, "signature mismatch"
    except ValueError as e:
        return False, str(e)


# =============================================================================
# helpers
# =============================================================================

def _row_to_entry(row) -> LedgerEntry:
    return LedgerEntry(
        entry_id=row["entry_id"],
        from_compositor=row["from_compositor"],
        to_compositor=row["to_compositor"],
        amount_credits=row["amount_credits"],
        work_item_id=row["work_item_id"],
        icp_envelope_hash=row["icp_envelope_hash"],
        model_identifier=row["model_identifier"],
        tokens_out=row["tokens_out"],
        duration_ms=row["duration_ms"],
        created_at_ns=row["created_at_ns"],
        from_signature=row["from_signature"] or "",
        to_signature=row["to_signature"] or "",
        settled=bool(row["settled"]),
    )


# Fields that must match for two views of the same entry to be
# considered "agreed" during reconciliation. We compare on signed
# fields plus the signatures themselves — matching signatures means
# both parties signed the same canonical bytes.
_RECONCILE_FIELDS = (
    "entry_id",
    "from_compositor",
    "to_compositor",
    "amount_credits",
    "work_item_id",
    "icp_envelope_hash",
    "from_signature",
    "to_signature",
)


def _entries_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    for f in _RECONCILE_FIELDS:
        if a.get(f) != b.get(f):
            return False
    return True


__all__ = [
    "LedgerEntry",
    "ComputeLedger",
    "compute_task_cost",
    "canonical_sign_bytes",
    "verify_payer_signature",
    "verify_earner_signature",
    "CREDIT_RATES",
    "ONE_CREDIT_CPU_SECONDS",
]
