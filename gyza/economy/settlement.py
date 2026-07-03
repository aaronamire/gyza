"""
Phase 3 Session 6 — bilateral settlement protocol.

The :class:`ComputeLedger` (in ``gyza.economy.ledger``) is the bookkeeping
primitive: it knows how to build, sign, verify, and persist entries. It
does not know how those entries cross the wire. The :class:`MessageService`
in gyza-netd (Go) is the wire primitive: it knows how to send a
(message_type, payload) frame to a peer over libp2p. It does not know
what payloads mean.

This module is the protocol layer that joins them. One instance per
local node owns the bilateral state machine:

    earner side                          payer side
    -----------                          -----------
    submit_earned(...)
    create_entry, sign_as_earner
    --- "ledger.entry.earner_signed" ─►  _handle_earner_signed
                                         verify earner sig
                                         verify icp envelope hash
                                         verify amount within ±20%
                                         acceptance policy (optional):
                                           ACCEPT / DEFER / DECLINE
                                         sign_as_payer  → settled
                                         _handle_earner_signed sends back
    _handle_payer_cosigned ◄── "ledger.entry.payer_cosigned"
    apply_cosigned_entry → settled

After the round trip, both ledgers hold the same fully-cosigned, settled
record. Re-delivery of either message is a no-op (entry_id is UUIDv7,
the ledger's UPSERT is idempotent, and we early-out if the entry is
already settled).

Why a separate class instead of folding into AgentRunner: the runner's
job is "claim → execute → sign envelope". Settlement is bookkeeping
that follows envelope signing but is conceptually orthogonal — a node
that runs no agents (a pure coordinator) still needs to participate in
settlement when its own agents have outsourced work. Keeping the
service standalone lets Session 7's GlobalCluster wire it up once and
have both runner-completed work and other emission paths (broadcast
ledger replay, dispute response) flow through the same handlers.

THREAT MODEL — what this layer trusts and verifies:

  Trusted:
    - The local ComputeLedger and its identity key.
    - libp2p transport-level Noise encryption + auth on the wire.
    - The daemon's stamping of ``sender_peer_id`` / ``sender_pubkey``
      on incoming messages (the daemon controls this; we verify only
      what's in the entry payload).

  Verified before payer-cosign:
    - Earner signature against the canonical entry bytes.
    - icp_envelope_hash matches a real completed work item we know
      about (via the caller-supplied resolver).
    - amount_credits is within ±20% of our independent recompute.
    - We are the entry's from_compositor (i.e. this entry is for us).
    - When an acceptance policy is wired: the payer's own judgment of
      the delivered work (AuditAcceptancePolicy = the unified audit run
      from the payer's own stores) — ACCEPT cosigns, DEFER waits without
      dispute (evidence lag), DECLINE refuses with a dispute (provable
      misbehavior).

  Verified before earner-apply:
    - Both signatures present and valid (verify_entry).
    - We are the entry's to_compositor (this is OUR earned entry).

Out of scope for Session 6: dispute resolution beyond rejection (a
mismatched amount or unknown envelope is silently rejected — production
will want a structured "dispute" reply); ledger gossip across all peers
in a project (Phase 4); rotation of the compositor key (a settled entry
references the key valid at the moment of signing).
"""
from __future__ import annotations

import enum
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

from gyza.economy.ledger import (
    ComputeLedger,
    LedgerEntry,
    compute_task_cost,
    verify_earner_signature,
    verify_payer_signature,
)


LOG = logging.getLogger("gyza.economy.settlement")


# Observability — fail-closed wrappers so a missing prometheus_client
# install never breaks settlement. The wrappers are zero-cost when the
# import succeeds (one attribute lookup); when it fails they're
# no-ops.
try:
    from gyza.observability import (
        DISPUTES_TOTAL as _DISPUTES_TOTAL,
        SETTLEMENTS_TOTAL as _SETTLEMENTS_TOTAL,
        observe_settlement_latency as _obs_settle_latency,
        record_settlement_start as _obs_settle_start,
    )

    def _obs_dispute(reason: str) -> None:
        _DISPUTES_TOTAL.labels(reason=reason).inc()

    def _obs_settled(role: str) -> None:
        _SETTLEMENTS_TOTAL.labels(role=role).inc()
except Exception:  # noqa: BLE001
    def _obs_dispute(reason: str) -> None:  # type: ignore[misc]
        pass

    def _obs_settled(role: str) -> None:  # type: ignore[misc]
        pass

    def _obs_settle_start(entry_id: str, t_monotonic: float) -> None:  # type: ignore[misc]
        pass

    def _obs_settle_latency(entry_id: str, t_monotonic_now: float) -> None:  # type: ignore[misc]
        pass


# Wire constants. Kept as class attributes so test code can reference
# them by name, not string literal.
EARNER_SIGNED_TYPE = "ledger.entry.earner_signed"
PAYER_COSIGNED_TYPE = "ledger.entry.payer_cosigned"
LEDGER_RECONCILE_REQUEST_TYPE = "ledger.reconcile.request"
LEDGER_RECONCILE_RESPONSE_TYPE = "ledger.reconcile.response"


# Pagination defaults. The 4 MiB MessageBus payload cap (see
# netd/internal/message/message.go MaxPayloadLen) is the hard ceiling;
# 500 entries × ~250 bytes per dict-encoded entry leaves an order of
# magnitude of headroom even with field-name overhead. Operators with
# pathological histories can lower this through ``page_size`` on the
# outbound call, but the ceiling is fixed at MaxPayloadLen / safety
# margin.
_DEFAULT_RECONCILE_PAGE_SIZE = 500
_MAX_RECONCILE_PAGE_SIZE = 2000  # server cap
_DEFAULT_RECONCILE_PAGE_TIMEOUT_S = 5.0
_DEFAULT_RECONCILE_MAX_PAGES = 50  # bounds adversarial peers from looping us


class _MessageBus(Protocol):
    """
    Subset of ``NetdClient`` we depend on. Defining it as a Protocol
    lets the unit tests pass a fake without inheriting the gRPC channel
    machinery, and makes the dependency surface obvious.
    """

    def send_message(
        self, peer_id: str, message_type: str, payload: bytes,
    ) -> bool: ...

    def subscribe_messages(
        self, message_types: list[str] | None = None,
    ) -> Iterator: ...  # yields proto IncomingMessage-like objects


# Resolver: maps a work_item_id to the icp_envelope_hash we know for
# it locally (or None if we don't have one). The settlement service
# stays decoupled from the blackboard schema by accepting this as a
# callable. In practice it's:
#
#   lambda wid: (
#       (item := blackboard.get_work_item(wid))
#       and item.icp_envelope_hash
#   )
EnvelopeResolver = Callable[[str], "str | None"]


@dataclass
class _PendingReconcile:
    """
    State for one in-flight reconciliation page.

    The outbound caller registers one of these per page-request before
    sending, then ``event.wait``s on it. The receive thread populates
    ``entries`` / ``has_more`` / ``cursor`` and signals the event.

    Why per-page rather than per-reconciliation: pagination is a
    state-machine inside ``request_reconciliation``. Each page is its
    own request_id; the outbound loop builds them sequentially. This
    keeps the wire protocol stateless on the server side — the server
    handles each page request as an independent query.

    A single in-flight handle is matched against exactly one peer
    (``peer_pubkey``) so a hostile peer cannot inject a response into
    a reconciliation we initiated against someone else, even if it
    guesses the request_id.
    """
    request_id: str
    peer_pubkey: str
    event: threading.Event
    entries: list[dict[str, Any]] = field(default_factory=list)
    cursor_timestamp_ns: int = 0
    cursor_entry_id: str = ""
    has_more: bool = False
    error: str | None = None


@dataclass
class ReconcileResult:
    """
    What a successful (or partially-successful) reconciliation returns.

    ``error`` is None for clean reconciliations; populated when the
    pagination loop bailed early (timeout, malformed response, page
    cap hit). ``agreed/disputed/missing_ours/missing_theirs`` are
    bucketed entry_ids exactly as produced by
    ``ComputeLedger.reconcile_with_peer``. ``pages`` and
    ``entries_received`` are diagnostic.

    The convention "missing_theirs is not a dispute" lives in the
    caller logic that decides when to bump reputation — see
    ``LedgerSettlementService.request_reconciliation``. This dataclass
    is just the shape.
    """
    peer_compositor: str
    agreed: list[str]
    disputed: list[str]
    missing_ours: list[str]
    missing_theirs: list[str]
    pages: int
    entries_received: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_compositor": self.peer_compositor,
            "agreed": list(self.agreed),
            "disputed": list(self.disputed),
            "missing_ours": list(self.missing_ours),
            "missing_theirs": list(self.missing_theirs),
            "pages": self.pages,
            "entries_received": self.entries_received,
            "error": self.error,
        }


class AcceptanceVerdict(enum.Enum):
    """
    The payer's judgment on an earner-signed entry, distinct from the
    protocol checks (signature, envelope hash, amount) that precede it.

    ACCEPT   — cosign: the payer is satisfied with what was delivered.
    DEFER    — do not cosign, do NOT dispute: the payer cannot judge yet
               (evidence not held — gossip lag is not the peer's fault).
               The earner discovers the unsettled entry via
               reconciliation and may retry.
    DECLINE  — do not cosign, DO dispute: the payer holds the evidence
               and it is provably bad (tampered artifact, out-of-bounds
               execution). This is misbehavior, not lag.
    """
    ACCEPT = "accept"
    DEFER = "defer"
    DECLINE = "decline"


# entry -> (verdict, human-readable reason; empty when ACCEPT).
AcceptancePolicy = Callable[[LedgerEntry], "tuple[AcceptanceVerdict, str]"]


class AuditAcceptancePolicy:
    """
    Cosign only what audits clean from the payer's OWN stores.

    The L0 gate of the settlement economics: before paying, run the real
    unified audit (``gyza.audit.audit_provenance``) over the envelope the
    entry settles, resolving the artifact and manifest from the payer's
    local content-addressed store. Nothing the earner sent is trusted —
    the judgment is a pure function of what the payer independently
    holds.

    Three-valued on purpose, and the split between DEFER and DECLINE is
    load-bearing: the payer must first hold every piece of evidence the
    audit will consult, THEN judge. Anything not yet held is DEFER
    (gossip/settlement lag is not the peer's fault — reconciliation
    retries); only a complete set of evidence that still fails the audit
    is DECLINE (provable misbehavior — tampered artifact, out-of-bounds
    execution).

      * envelope not held → DEFER;
      * output artifact not held → DEFER;
      * artifact is an *execution* (carries an ``__enforcement__``
        record) but its manifest isn't held → DEFER (a coordination
        artifact needs no manifest, so we only require one once we know
        the work claimed to run bounded);
      * everything the audit needs is held and it passes → ACCEPT;
      * everything is held and it fails → DECLINE.

    ``require_closed=False`` because settlement is per-work-item: the
    envelope's spine parent legitimately lives elsewhere in the DAG and
    its absence from this single-envelope audit is not evidence loss.
    """

    def __init__(self, blackboard, artifact_store):
        self._bb = blackboard
        self._store = artifact_store

    def __call__(self, entry: LedgerEntry) -> "tuple[AcceptanceVerdict, str]":
        from gyza.audit import audit_provenance

        env = self._bb.get_envelope(entry.icp_envelope_hash)
        if env is None:
            return AcceptanceVerdict.DEFER, "envelope not held locally yet"
        artifact = self._store.get(env.output_hash)
        if artifact is None:
            return AcceptanceVerdict.DEFER, "output artifact not held locally yet"

        # Only an execution (artifact carrying a folded __enforcement__
        # record) is bounds-checked against a manifest; a coordination
        # artifact is content-address-bound only. So require the manifest
        # to be held ONLY when this artifact is an execution — otherwise
        # a manifest we legitimately don't have would wrongly stall (or,
        # worse, decline) an honest coordination payment.
        is_execution = False
        try:
            obj = json.loads(artifact.decode("utf-8"))
            is_execution = isinstance(obj, dict) and isinstance(
                obj.get("__enforcement__"), dict
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            is_execution = False
        if is_execution and self._store.get(env.capability_manifest_hash) is None:
            return AcceptanceVerdict.DEFER, "agent manifest not held locally yet"

        def _manifest(h: str) -> "dict | None":
            raw = self._store.get(h)
            if raw is None:
                return None
            try:
                obj = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return obj if isinstance(obj, dict) else None

        report = audit_provenance(
            [env],
            resolve_artifact=self._store.get,
            resolve_manifest=_manifest,
            require_closed=False,
        )
        if not report.valid:
            bad = next((r for r in report.actions if not r.ok), None)
            why = bad.reason if bad is not None else report.summary
            return AcceptanceVerdict.DECLINE, f"audit INVALID: {why}"
        return AcceptanceVerdict.ACCEPT, ""


class LedgerSettlementService:
    """
    Bilateral ledger settlement. One instance per node.

    Lifecycle: ``start()`` spawns a daemon thread that calls
    ``netd.subscribe_messages([EARNER_SIGNED_TYPE, PAYER_COSIGNED_TYPE])``
    and dispatches each incoming message to the appropriate handler.
    ``stop()`` signals the thread to exit and joins. The subscription
    stream itself terminates when the gRPC channel closes — daemon
    shutdown, channel close, or context cancel.

    Thread-safety: handlers run sequentially on the receive thread.
    ``submit_earned`` is callable from any thread (the underlying
    NetdClient and ComputeLedger are thread-safe).
    """

    AMOUNT_TOLERANCE_RATIO = 0.20  # spec — payer rejects if claimed
                                   # diverges from independent recompute
                                   # by more than this fraction.

    def __init__(
        self,
        ledger: ComputeLedger,
        netd: _MessageBus,
        envelope_resolver: EnvelopeResolver,
        reputation_store=None,
        acceptance_policy: "AcceptancePolicy | None" = None,
        evidence_store=None,
    ):
        self._ledger = ledger
        self._netd = netd
        self._resolve_envelope = envelope_resolver
        # Optional acceptance judgment, run AFTER the protocol checks and
        # BEFORE sign_as_payer. None preserves the historical behavior
        # (protocol checks alone). Wire AuditAcceptancePolicy here to
        # refuse payment for work that doesn't audit clean from this
        # node's own stores.
        self._acceptance_policy = acceptance_policy
        # Optional content-addressed store (``.store(bytes)->hash``,
        # ``.get(hash)->bytes|None``). The earner reads it to attach the
        # evidence (output artifact + agent manifest) an entry settles;
        # the payer writes received evidence into it so the acceptance
        # policy can audit the work from bytes it now independently
        # holds. Content-addressing makes this safe: the store keys by
        # the true BLAKE3 of the bytes, and the audit re-derives the
        # binding, so a peer that sends bytes not matching the claimed
        # hash simply fails to satisfy the audit (unpaid), never
        # poisons anything.
        self._evidence_store = evidence_store
        # Optional reputation store. When provided, every protocol-level
        # rejection (forged signature, envelope-hash mismatch, amount
        # outside tolerance, misrouted entry) bumps DOWN the offending
        # peer's reputation as a DISPUTE — heavier weight than ordinary
        # failure because these signal deliberate misbehavior.
        # Successful settlements bump UP both the payer's and the
        # earner's reputation.
        self._reputation_store = reputation_store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # In-flight reconciliation page-requests. Keyed by request_id
        # (UUIDv7, globally unique). Mutated by both the receive thread
        # (response handler signals + populates) and outbound callers
        # (register before send, deregister on completion / timeout),
        # so guarded by its own dedicated lock — using ``self._lock``
        # would block the receive thread on a slow request_reconciliation
        # call.
        self._pending_reconciles: dict[str, _PendingReconcile] = {}
        self._pending_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="gyza-settlement",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Outbound — the earner submits a freshly-signed entry to the payer.
    # ------------------------------------------------------------------

    def submit_earned(
        self,
        *,
        payer_compositor: str,
        payer_peer_id: str,
        work_item_id: str,
        icp_envelope_hash: str,
        model_identifier: str,
        tokens_out: int,
        duration_ms: int,
        amount: float | None = None,
        evidence_hashes: "list[str] | None" = None,
    ) -> LedgerEntry:
        """
        Build, earner-sign, and send a ledger entry to ``payer_peer_id``.

        ``amount`` defaults to the cost computed via ``compute_task_cost``.
        Callers can override (e.g. to claim a smaller amount as
        goodwill); the payer applies the ±20% tolerance against its
        OWN recompute regardless of what we passed.

        ``evidence_hashes`` are content-addresses (the envelope's
        ``output_hash`` and ``capability_manifest_hash``) whose bytes
        this node holds in ``evidence_store``. When both are provided and
        resolvable, their bytes ride along with the entry so the payer
        can audit the work before paying — the loop's "pay only for
        verified bounded work" property. Gossip already carries the
        signed envelope to the payer; only these two blobs need to
        travel with settlement. Omitted (or unresolvable) evidence just
        means the payer's audit gate, if any, will defer — never a
        silent unaudited payment.

        Returns the unsettled entry — the to_signature is populated,
        from_signature is empty, settled is False. The full settlement
        completes asynchronously when the payer's "payer_cosigned"
        reply lands in our subscription stream and the corresponding
        handler calls apply_cosigned_entry.
        """
        if amount is None:
            amount = compute_task_cost(model_identifier, tokens_out, duration_ms)

        entry = self._ledger.create_entry(
            from_compositor=payer_compositor,
            to_compositor=self._ledger.compositor_pubkey,
            amount=amount,
            work_item_id=work_item_id,
            icp_envelope_hash=icp_envelope_hash,
            model_identifier=model_identifier,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
        )
        entry = self._ledger.sign_as_earner(entry)

        # Observability — stamp the moment we send so the receive
        # handler can observe end-to-end round-trip when the cosigned
        # echo lands. Time source is time.monotonic to avoid clock
        # skew artifacts; latency is intra-process so wall-clock
        # comparison would be a footgun.
        _obs_settle_start(entry.entry_id, time.monotonic())

        wire = entry.to_dict()
        evidence = self._collect_evidence(evidence_hashes)
        if evidence:
            # Sidecar key: LedgerEntry.from_dict tolerates extra keys, so
            # the signed entry bytes the payer verifies are unchanged.
            wire["__evidence__"] = evidence
        payload = json.dumps(wire).encode("utf-8")
        ok = self._netd.send_message(
            peer_id=payer_peer_id,
            message_type=EARNER_SIGNED_TYPE,
            payload=payload,
        )
        if not ok:
            # The entry stays in the local ledger un-cosigned; caller
            # may retry (with a fresh entry_id, so a partial first
            # delivery doesn't double-count) or surface it during
            # reconciliation. We log and return — the entry is the
            # source of truth.
            LOG.warning(
                "[settlement] failed to send earner_signed to %s "
                "for entry %s",
                payer_peer_id, entry.entry_id,
            )
        return entry

    # ------------------------------------------------------------------
    # Inbound — receive thread dispatches to the two handlers.
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        try:
            stream = self._netd.subscribe_messages([
                EARNER_SIGNED_TYPE,
                PAYER_COSIGNED_TYPE,
                LEDGER_RECONCILE_REQUEST_TYPE,
                LEDGER_RECONCILE_RESPONSE_TYPE,
            ])
        except Exception as e:  # noqa: BLE001
            LOG.error("[settlement] subscribe_messages failed at start: %s", e)
            return

        for incoming in stream:
            if self._stop.is_set():
                return
            try:
                if incoming.message_type == EARNER_SIGNED_TYPE:
                    self._handle_earner_signed(incoming)
                elif incoming.message_type == PAYER_COSIGNED_TYPE:
                    self._handle_payer_cosigned(incoming)
                elif incoming.message_type == LEDGER_RECONCILE_REQUEST_TYPE:
                    self._handle_reconcile_request(incoming)
                elif incoming.message_type == LEDGER_RECONCILE_RESPONSE_TYPE:
                    self._handle_reconcile_response(incoming)
                # Any other type slipped past the daemon-side filter:
                # ignore. We don't want to crash the whole settlement
                # thread for a stray frame.
            except Exception as e:  # noqa: BLE001
                LOG.warning(
                    "[settlement] handler raised on %s: %s",
                    getattr(incoming, "message_type", "?"), e,
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _collect_evidence(
        self, hashes: "list[str] | None"
    ) -> "dict[str, str]":
        """Read each hash's bytes from the local evidence store and
        base64-encode them for the wire. Missing store or missing bytes
        yield an empty map (the payer's gate then defers, never pays
        unaudited)."""
        import base64

        if not hashes or self._evidence_store is None:
            return {}
        out: dict[str, str] = {}
        for h in hashes:
            if not h or h in out:
                continue
            try:
                raw = self._evidence_store.get(h)
            except Exception:  # noqa: BLE001
                raw = None
            if raw is not None:
                out[h] = base64.b64encode(raw).decode("ascii")
        return out

    def _absorb_evidence(self, payload: bytes) -> None:
        """Store any evidence blobs an incoming earner_signed carried, so
        the acceptance policy can audit the work from bytes we now hold.
        Content-addressed: the store keys by the true hash of the bytes,
        so a mismatched claim simply isn't resolvable later (defer/decline),
        never a poisoned entry."""
        import base64

        if self._evidence_store is None:
            return
        try:
            d = json.loads(payload.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return
        evidence = d.get("__evidence__") if isinstance(d, dict) else None
        if not isinstance(evidence, dict):
            return
        for _claimed_hash, b64 in evidence.items():
            try:
                raw = base64.b64decode(b64, validate=True)
                self._evidence_store.store(raw)
            except Exception:  # noqa: BLE001
                continue

    def _decode_entry(self, payload: bytes) -> LedgerEntry | None:
        try:
            d = json.loads(payload.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            LOG.warning("[settlement] payload decode failed: %s", e)
            return None
        try:
            return LedgerEntry.from_dict(d)
        except Exception as e:  # noqa: BLE001
            LOG.warning("[settlement] entry construction failed: %s", e)
            return None

    def _bump_dispute(self, peer_pubkey: str) -> None:
        """Record a protocol-level rejection against the peer who sent
        the offending entry. No-op when no reputation store is wired."""
        if self._reputation_store is None or not peer_pubkey:
            return
        try:
            self._reputation_store.record_dispute(peer_pubkey)
        except Exception:  # noqa: BLE001
            pass

    def _bump_success(self, peer_pubkey: str) -> None:
        """Record a clean settlement. Counterparty's reputation goes up."""
        if self._reputation_store is None or not peer_pubkey:
            return
        try:
            self._reputation_store.record_success(peer_pubkey)
        except Exception:  # noqa: BLE001
            pass

    def _handle_earner_signed(self, incoming) -> None:
        entry = self._decode_entry(incoming.payload)
        if entry is None:
            return

        # We must be the payer; otherwise this entry is misrouted.
        if entry.from_compositor != self._ledger.compositor_pubkey:
            LOG.warning(
                "[settlement] earner_signed for from=%s, but we are %s",
                entry.from_compositor[:16], self._ledger.compositor_pubkey[:16],
            )
            # Misrouting from the *earner* is a protocol bug on their
            # side — they should know who the payer is. Mild dispute
            # against the to_compositor (the earner who sent this).
            self._bump_dispute(entry.to_compositor)
            _obs_dispute("misroute_payer")
            return

        with self._lock:
            # Idempotent: if we already cosigned this exact entry, do
            # nothing. Re-delivery via gossipsub re-mesh or peer retry
            # must not produce a second "payer_cosigned" reply.
            existing = self._ledger.get_entry(entry.entry_id)
            if existing is not None and existing.settled:
                return

            ok, reason = verify_earner_signature(entry)
            if not ok:
                LOG.warning(
                    "[settlement] earner sig invalid (%s) for entry %s",
                    reason, entry.entry_id,
                )
                self._bump_dispute(entry.to_compositor)
                _obs_dispute("forged_earner_sig")
                return

            # Earner signature is valid, so this entry really came from
            # the claimed earner: absorb any evidence it carried into our
            # local store so the acceptance policy below can audit the
            # work. Done after sig-verify (never store bytes from a
            # forged entry) and before the gate.
            self._absorb_evidence(incoming.payload)

            # Envelope hash must match a known completed work item.
            expected = self._resolve_envelope(entry.work_item_id)
            if expected is None:
                LOG.warning(
                    "[settlement] unknown work_item_id %s — "
                    "we have no completion record",
                    entry.work_item_id,
                )
                # NOT a dispute — we genuinely don't have the
                # work item; silently rejecting an entry against
                # work we never observed isn't a protocol violation
                # by the peer. Could be a gossip lag.
                return
            if expected != entry.icp_envelope_hash:
                LOG.warning(
                    "[settlement] envelope hash mismatch for %s: "
                    "expected %s, got %s",
                    entry.work_item_id,
                    expected[:16], entry.icp_envelope_hash[:16],
                )
                self._bump_dispute(entry.to_compositor)
                _obs_dispute("envelope_mismatch")
                return

            # Amount within tolerance.
            ours = compute_task_cost(
                entry.model_identifier,
                entry.tokens_out,
                entry.duration_ms,
            )
            if not _within_tolerance(
                entry.amount_credits, ours, self.AMOUNT_TOLERANCE_RATIO,
            ):
                LOG.warning(
                    "[settlement] amount %.6f outside ±%.0f%% of "
                    "our recompute %.6f for entry %s",
                    entry.amount_credits,
                    self.AMOUNT_TOLERANCE_RATIO * 100,
                    ours, entry.entry_id,
                )
                self._bump_dispute(entry.to_compositor)
                _obs_dispute("amount_tolerance")
                return

            # Acceptance judgment — the L0 gate. Protocol checks above
            # established the entry is well-formed and honestly priced;
            # this establishes the payer is willing to PAY for what was
            # actually delivered. DEFER mirrors the unknown-work-item
            # path (not the peer's fault; reconciliation retries);
            # DECLINE is provable misbehavior and disputes.
            if self._acceptance_policy is not None:
                verdict, why = self._acceptance_policy(entry)
                if verdict is AcceptanceVerdict.DEFER:
                    LOG.info(
                        "[settlement] acceptance deferred for entry %s: %s",
                        entry.entry_id, why,
                    )
                    return
                if verdict is AcceptanceVerdict.DECLINE:
                    LOG.warning(
                        "[settlement] acceptance DECLINED for entry %s: %s",
                        entry.entry_id, why,
                    )
                    self._bump_dispute(entry.to_compositor)
                    _obs_dispute("acceptance_declined")
                    return

            try:
                cosigned = self._ledger.sign_as_payer(entry)
            except ValueError as e:
                LOG.warning(
                    "[settlement] sign_as_payer rejected entry %s: %s",
                    entry.entry_id, e,
                )
                return

        # Successful settlement — bump the earner's reputation. The
        # peer produced verifiable work for an honest claim cost.
        self._bump_success(cosigned.to_compositor)
        _obs_settled("payer")

        # Echo cosigned entry back to the earner. Outside the lock so a
        # slow send_message doesn't block the next incoming frame.
        payload = json.dumps(cosigned.to_dict()).encode("utf-8")
        ok = self._netd.send_message(
            peer_id=incoming.sender_peer_id,
            message_type=PAYER_COSIGNED_TYPE,
            payload=payload,
        )
        if not ok:
            LOG.warning(
                "[settlement] failed to send payer_cosigned for entry %s; "
                "earner must reconcile to discover settlement",
                cosigned.entry_id,
            )

    def _handle_payer_cosigned(self, incoming) -> None:
        entry = self._decode_entry(incoming.payload)
        if entry is None:
            return

        # We must be the earner.
        if entry.to_compositor != self._ledger.compositor_pubkey:
            LOG.warning(
                "[settlement] payer_cosigned for to=%s, but we are %s",
                entry.to_compositor[:16], self._ledger.compositor_pubkey[:16],
            )
            self._bump_dispute(entry.from_compositor)
            _obs_dispute("misroute_earner")
            return

        with self._lock:
            existing = self._ledger.get_entry(entry.entry_id)
            if existing is not None and existing.settled:
                return

            # apply_cosigned_entry verifies BOTH signatures before
            # storing. A malformed echo (e.g. payer tampered with the
            # amount before re-signing) fails here.
            try:
                self._ledger.apply_cosigned_entry(entry)
                # Successful apply — payer honored their cosignature.
                self._bump_success(entry.from_compositor)
                _obs_settled("earner")
                # Round-trip latency: from our submit_earned send to
                # this apply. record_settlement_start stamped the entry
                # at submit; observe pops + observes here. No-op when
                # the entry arrived from somewhere we didn't submit
                # (gossip replay path).
                _obs_settle_latency(entry.entry_id, time.monotonic())
            except ValueError as e:
                LOG.warning(
                    "[settlement] apply_cosigned_entry rejected %s: %s",
                    entry.entry_id, e,
                )
                # Payer sent an invalid cosignature — protocol violation.
                self._bump_dispute(entry.from_compositor)
                _obs_dispute("apply_failed")

            # Sanity guard: defense-in-depth against a cosmic-ray flip
            # in apply_cosigned_entry's verify path. verify_payer_signature
            # is cheap enough to run again here.
            ok, reason = verify_payer_signature(entry)
            if not ok:
                LOG.warning(
                    "[settlement] post-apply payer sig recheck failed: %s",
                    reason,
                )
                _obs_dispute("forged_payer_sig")

    # ------------------------------------------------------------------
    # Reconciliation — Phase 3 §6 #25
    # ------------------------------------------------------------------

    def _handle_reconcile_request(self, incoming) -> None:
        """
        Reply to a paginated reconciliation request.

        Wire schema (request payload, JSON):
            {
              "request_id": str,           # UUIDv7, echoed in response
              "from_compositor": str,      # the requester (their pubkey)
              "for_peer": str,             # explicit "asking your view of US"
              "since_timestamp_ns": int,   # exclusive cursor (lex with id)
              "since_entry_id": str,       # tiebreak when ns ties
              "max_entries": int           # client preference; we cap at server max
            }

        The "for_peer" field guards against a confused or hostile peer
        asking us to dump someone else's pairwise ledger — cheap defense
        in depth on top of the bus-level peer authentication.
        """
        try:
            d = json.loads(incoming.payload.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            LOG.warning("[settlement.reconcile] request decode failed: %s", e)
            return

        request_id = str(d.get("request_id") or "")
        requester = str(d.get("from_compositor") or "")
        for_peer = str(d.get("for_peer") or "")
        since_t = int(d.get("since_timestamp_ns") or 0)
        since_id = str(d.get("since_entry_id") or "")
        max_entries = int(d.get("max_entries") or _DEFAULT_RECONCILE_PAGE_SIZE)

        if not request_id or not requester:
            LOG.warning("[settlement.reconcile] request missing id/requester")
            return

        # Misroute: we are not "for_peer". The peer sent a request asking
        # for OUR view of THEIR pairwise ledger with someone else. Reject
        # without replying — replying would leak a confirmation about
        # our key, and a benign confused peer should re-issue once they
        # discover their mistake.
        if for_peer and for_peer != self._ledger.compositor_pubkey:
            LOG.warning(
                "[settlement.reconcile] request for_peer=%s but we are %s",
                for_peer[:16], self._ledger.compositor_pubkey[:16],
            )
            return

        # Cap the page size at server max, even if the client asked for
        # more. Bounds adversarial response sizes (a hostile peer could
        # request 10M entries hoping to OOM us).
        max_entries = max(1, min(max_entries, _MAX_RECONCILE_PAGE_SIZE))

        # Read our pairwise view of the requester. export_statement
        # already returns entries ordered by created_at_ns ASC; we slice
        # in-memory to keep storage-layer changes off the path.
        all_entries = self._ledger.export_statement(requester)
        # Lex cursor filter: (created_at_ns, entry_id) > (since_t, since_id).
        # Strict > so a re-issue with the previous page's last cursor
        # doesn't replay that entry. The lex tie-break is essential — two
        # entries created in the same ns (rare but possible) would cause
        # one to be silently skipped if we only filtered on created_at_ns.
        after = [
            e for e in all_entries
            if (e["created_at_ns"], e["entry_id"]) > (since_t, since_id)
        ]
        # Fetch one extra to detect has_more without a separate count.
        page = after[: max_entries + 1]
        has_more = len(page) > max_entries
        page = page[:max_entries]

        # Cursor = the lex-max of this page. When the page is empty we
        # echo the request's cursor unchanged so the client's loop
        # terminates immediately without confusion.
        if page:
            cursor_t = int(page[-1]["created_at_ns"])
            cursor_id = str(page[-1]["entry_id"])
        else:
            cursor_t = since_t
            cursor_id = since_id

        payload = json.dumps({
            "request_id": request_id,
            "from_compositor": self._ledger.compositor_pubkey,
            "entries": page,
            "cursor_timestamp_ns": cursor_t,
            "cursor_entry_id": cursor_id,
            "has_more": has_more,
        }).encode("utf-8")

        ok = self._netd.send_message(
            peer_id=incoming.sender_peer_id,
            message_type=LEDGER_RECONCILE_RESPONSE_TYPE,
            payload=payload,
        )
        if not ok:
            LOG.warning(
                "[settlement.reconcile] failed to send response for request %s",
                request_id,
            )

    def _handle_reconcile_response(self, incoming) -> None:
        """
        Match an inbound response to a pending request and signal the
        waiter. Drops responses we never asked for (no pending entry) —
        that's either a misroute or a late retry after timeout cleanup.

        SECURITY: verify the response's ``from_compositor`` matches the
        peer we registered the pending request against. Without this,
        any peer could inject a response into a pending request_id (which
        could be guessable in adversarial conditions, despite UUIDv7's
        timestamp + randomness, if the attacker can observe wire traffic).
        """
        try:
            d = json.loads(incoming.payload.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            LOG.warning("[settlement.reconcile] response decode failed: %s", e)
            return

        request_id = str(d.get("request_id") or "")
        if not request_id:
            return

        with self._pending_lock:
            pending = self._pending_reconciles.get(request_id)
        if pending is None:
            # No matching pending request — late delivery after timeout,
            # misroute, or hostile injection. Either way drop.
            return

        expected_peer = pending.peer_pubkey
        actual_from = str(d.get("from_compositor") or "")
        if actual_from != expected_peer:
            LOG.warning(
                "[settlement.reconcile] response from=%s but pending peer was %s; "
                "dropping (possible injection)",
                actual_from[:16], expected_peer[:16],
            )
            # Don't signal the event — the outbound caller will time out
            # and the legitimate response (if it ever arrives) won't be
            # confused with the one we just dropped.
            return

        raw_entries = d.get("entries") or []
        if not isinstance(raw_entries, list):
            pending.error = "entries field is not a list"
            pending.event.set()
            return

        # Keep entries as plain dicts; reconcile_with_peer accepts dicts.
        pending.entries = [e for e in raw_entries if isinstance(e, dict)]
        pending.cursor_timestamp_ns = int(d.get("cursor_timestamp_ns") or 0)
        pending.cursor_entry_id = str(d.get("cursor_entry_id") or "")
        pending.has_more = bool(d.get("has_more"))
        pending.event.set()

    def request_reconciliation(
        self,
        *,
        peer_compositor: str,
        peer_id: str,
        page_size: int = _DEFAULT_RECONCILE_PAGE_SIZE,
        page_timeout_s: float = _DEFAULT_RECONCILE_PAGE_TIMEOUT_S,
        max_pages: int = _DEFAULT_RECONCILE_MAX_PAGES,
    ) -> ReconcileResult:
        """
        Drive a paginated reconciliation against ``peer_compositor`` reachable
        at ``peer_id``. Returns a ReconcileResult.

        Pagination loop. Each iteration:

          1. Generate a fresh request_id (UUIDv7).
          2. Register a _PendingReconcile under that id.
          3. Send the request (cursor advances per page).
          4. ``event.wait(page_timeout_s)``.
          5. If signaled cleanly: collect entries, advance cursor, repeat
             while ``has_more``.
          6. On timeout / decode error: bail with a partial result.

        Reputation policy (CLAUDE.md §6 #25 trip-wire):

          * ``disputed`` entries → record_dispute(peer) per entry. These
            signal a forged or mutated record — the only unambiguous
            protocol violation surfaced by this RPC.
          * ``missing_theirs`` and ``missing_ours`` → NO reputation hit.
            Pruning, gossip lag, or unsettled entries are all benign
            causes.

        Page cap (``max_pages``) bounds adversarial peers from looping
        us indefinitely with ``has_more=true`` and tiny pages. Hitting
        the cap returns a ``error="page_cap_exceeded"`` result.
        """
        if not peer_compositor or not peer_id:
            return ReconcileResult(
                peer_compositor=peer_compositor,
                agreed=[], disputed=[], missing_ours=[], missing_theirs=[],
                pages=0, entries_received=0,
                error="peer_compositor and peer_id are required",
            )
        if peer_compositor == self._ledger.compositor_pubkey:
            return ReconcileResult(
                peer_compositor=peer_compositor,
                agreed=[], disputed=[], missing_ours=[], missing_theirs=[],
                pages=0, entries_received=0,
                error="cannot reconcile with self",
            )
        page_size = max(1, min(page_size, _MAX_RECONCILE_PAGE_SIZE))

        cursor_t = 0
        cursor_id = ""
        accumulated: list[dict[str, Any]] = []
        pages = 0
        error: str | None = None

        while pages < max_pages:
            request_id = str(uuid.uuid7())
            pending = _PendingReconcile(
                request_id=request_id,
                peer_pubkey=peer_compositor,
                event=threading.Event(),
            )
            with self._pending_lock:
                self._pending_reconciles[request_id] = pending

            try:
                payload = json.dumps({
                    "request_id": request_id,
                    "from_compositor": self._ledger.compositor_pubkey,
                    "for_peer": peer_compositor,
                    "since_timestamp_ns": cursor_t,
                    "since_entry_id": cursor_id,
                    "max_entries": page_size,
                }).encode("utf-8")
                ok = self._netd.send_message(
                    peer_id=peer_id,
                    message_type=LEDGER_RECONCILE_REQUEST_TYPE,
                    payload=payload,
                )
                if not ok:
                    error = "send_failed"
                    break

                if not pending.event.wait(page_timeout_s):
                    error = "timeout"
                    break

                if pending.error is not None:
                    error = pending.error
                    break

                accumulated.extend(pending.entries)
                pages += 1

                if not pending.has_more:
                    break

                # Advance the cursor. The server enforces strict-greater
                # over the lex tuple (cursor_t, cursor_id), so re-issuing
                # with this cursor cannot replay the entry we just got.
                cursor_t = pending.cursor_timestamp_ns
                cursor_id = pending.cursor_entry_id
            finally:
                with self._pending_lock:
                    self._pending_reconciles.pop(request_id, None)
        else:
            # while-else: ran the full max_pages without breaking. Treat
            # as an error so the caller doesn't silently see a truncated
            # diff. The accumulated entries we DO have are still bucketed
            # below — operators may want partial diagnostics even on the
            # bail path.
            error = "page_cap_exceeded"

        # Bucket against our local pairwise view. reconcile_with_peer
        # uses set difference on entry_id + structural compare on shared
        # keys, so accumulated may be a STRICT SUBSET of the peer's full
        # ledger view (when we bailed early) and the diff still tells us
        # what disagrees about the entries we DID see. ``missing_theirs``
        # under partial pagination is a noisy signal — that's why error
        # is propagated to the caller.
        diff = self._ledger.reconcile_with_peer(peer_compositor, accumulated)

        # Reputation: only ``disputed`` is unambiguous. One bump per
        # disputed entry — multiple disputes against the same peer
        # accumulate at the rate the EWMA store dictates.
        if self._reputation_store is not None and diff.get("disputed"):
            for _eid in diff["disputed"]:
                try:
                    self._reputation_store.record_dispute(peer_compositor)
                except Exception:  # noqa: BLE001
                    pass

        return ReconcileResult(
            peer_compositor=peer_compositor,
            agreed=list(diff.get("agreed", [])),
            disputed=list(diff.get("disputed", [])),
            missing_ours=list(diff.get("missing_ours", [])),
            missing_theirs=list(diff.get("missing_theirs", [])),
            pages=pages,
            entries_received=len(accumulated),
            error=error,
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _within_tolerance(claimed: float, ours: float, ratio: float) -> bool:
    """
    Amount tolerance check. Two-sided (claimed can be too high OR too
    low). When ``ours`` is zero the only valid claim is also zero.
    """
    if ours == 0.0:
        return claimed == 0.0
    return abs(claimed - ours) <= abs(ours) * ratio


__all__ = [
    "LedgerSettlementService",
    "EARNER_SIGNED_TYPE",
    "PAYER_COSIGNED_TYPE",
]
