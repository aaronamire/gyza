"""
Phase 3 Session 8.5+ — observability primitives.

Two concerns live here:

  1. Prometheus metrics — counters, histograms, gauges that the rest of
     the codebase imports and increments at well-known points
     (settlement, runner completion, gossip apply, supervisor spawn).
     A scrape endpoint is exposed via ``start_metrics_server``.

  2. Structured logging — a one-shot configurator that wires
     ``structlog`` into the standard library's ``logging`` so every
     existing ``LOG.warning(...)`` call gets either JSON-on-stderr or
     human-readable console output, depending on whether this is
     production (operator wants machine-parseable) or interactive (a
     human is reading).

Why both in one module: they're imported together at process startup
and share no state. Splitting them adds a file without information
hiding benefit. Imports are lazy where possible so a stripped-down
install missing prometheus_client / structlog can still load
``gyza.observability`` for its symbol references.

Why a single module-level registry: prometheus_client's default
registry is process-global and re-importing the module twice in the
same process raises ``Duplicated timeseries``. Test code that needs
clean state should reset individual metric values rather than rebuild
the registry — the helper ``reset_for_tests`` handles this.

Default bind address is 127.0.0.1, NOT 0.0.0.0. Metrics endpoints
expose internal state and binding to all interfaces by default would
leak that state to anything on the network. Operators who want
external scraping must pass ``addr="0.0.0.0"`` (or a specific NIC)
explicitly.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prometheus_client import Counter, Gauge, Histogram


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------
#
# Each metric is registered exactly once at import time, against the
# default global registry. The names are chosen to be searchable in
# Grafana / promql without any prefix juggling — ``gyza_*`` is the
# convention.
#
# Histograms use log-spaced buckets calibrated to the latency regimes
# we actually expect:
#
#   * settlement_latency:  network round-trip + signature verify, so
#       50ms low end (LAN) up to 30s upper bound (we'd treat anything
#       past that as a stuck handshake worth alerting on).
#   * claim_to_complete_latency: dominated by executor wall-clock —
#       seconds to a few minutes for LLM calls, longer if the
#       executor wraps a multi-stage tool.
#
# Don't pick uniform buckets here — uniform buckets in a domain that
# spans 4+ orders of magnitude waste 80% of the resolution.

from prometheus_client import Counter, Gauge, Histogram, start_http_server


SETTLEMENTS_TOTAL: "Counter" = Counter(
    "gyza_settlements_total",
    "Bilateral settlements completed",
    ["role"],  # "payer" | "earner"
)

DISPUTES_TOTAL: "Counter" = Counter(
    "gyza_disputes_total",
    "Protocol-level rejections during settlement",
    # reason classifications match the rejection sites in
    # gyza.economy.settlement; keep this list in sync when adding new
    # rejection paths so dashboards don't suddenly grow blank slices.
    ["reason"],  # "amount_tolerance" | "envelope_mismatch"
                 # | "forged_earner_sig" | "forged_payer_sig"
                 # | "misroute_payer"   | "misroute_earner"
                 # | "apply_failed"
)

AGENT_COMPLETIONS_TOTAL: "Counter" = Counter(
    "gyza_agent_completions_total",
    "Work items processed by local agent runners",
    ["outcome"],  # "success" | "failure" | "released"
)

GOSSIP_DELTAS_TOTAL: "Counter" = Counter(
    "gyza_gossip_deltas_total",
    "Blackboard deltas exchanged via gossipsub",
    ["direction"],  # "in" | "out"
)

SUPERVISOR_SPAWNS_TOTAL: "Counter" = Counter(
    "gyza_supervisor_spawns_total",
    "Replica agents spawned by the demand-driven supervisor",
)


SETTLEMENT_LATENCY: "Histogram" = Histogram(
    "gyza_settlement_latency_seconds",
    "Time from earner_signed send to payer_cosigned apply",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

CLAIM_TO_COMPLETE_LATENCY: "Histogram" = Histogram(
    "gyza_claim_to_complete_latency_seconds",
    "Wall time from claim to completion (or release) by a local agent",
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0),
)


ROSTER_SIZE: "Gauge" = Gauge(
    "gyza_roster_size",
    "Local agent runners currently tracked by the supervisor",
)

DHT_PEER_COUNT: "Gauge" = Gauge(
    "gyza_dht_peer_count",
    "DHT routing table size as reported by the daemon",
)

CONNECTED_PEERS: "Gauge" = Gauge(
    "gyza_connected_peers",
    "Live libp2p peer connections as reported by the daemon",
)

LEDGER_NET_CREDITS: "Gauge" = Gauge(
    "gyza_ledger_net_credits",
    "Net credits earned minus spent across the local ledger",
)


# ---------------------------------------------------------------------------
# Settlement latency tracking
# ---------------------------------------------------------------------------
#
# The earner stamps wall-clock at submit_earned; the same node observes
# elapsed time when its handler for payer_cosigned applies the entry.
# This map is the cross-call carrier. It's keyed by entry_id (UUIDv7,
# globally unique) so concurrent settlements don't collide.
#
# Memory: the map purges on observation. If a settlement never returns
# (peer goes dark), the entry leaks until process exit. That's
# acceptable at Phase 3 scale (max hundreds per session). If retention
# becomes a concern, swap for a TTL cache.

_settle_lock = threading.Lock()
_settle_starts: dict[str, float] = {}


def record_settlement_start(entry_id: str, t_monotonic: float) -> None:
    """Earner side: stamp the moment we sent earner_signed. Called from
    LedgerSettlementService.submit_earned."""
    with _settle_lock:
        _settle_starts[entry_id] = t_monotonic


def observe_settlement_latency(entry_id: str, t_monotonic_now: float) -> None:
    """Earner side: when payer_cosigned lands and we apply, observe the
    full round-trip. No-op if we never recorded a start (e.g. the entry
    arrived from elsewhere — gossip replay)."""
    with _settle_lock:
        t0 = _settle_starts.pop(entry_id, None)
    if t0 is None:
        return
    SETTLEMENT_LATENCY.observe(max(0.0, t_monotonic_now - t0))


# ---------------------------------------------------------------------------
# HTTP scrape endpoint
# ---------------------------------------------------------------------------

_server_lock = threading.Lock()
_server_started = False


def start_metrics_server(port: int = 9100, addr: str = "127.0.0.1") -> None:
    """
    Start the Prometheus scrape HTTP server on (addr, port).

    Idempotent: a second call within the same process is a no-op. The
    underlying ``prometheus_client.start_http_server`` spawns a daemon
    thread that lives for the rest of the process — it has no
    public stop API, so re-binding requires a process restart.

    Default ``addr="127.0.0.1"`` matches the operator-safe default. To
    expose externally, pass ``addr="0.0.0.0"`` and put a real reverse
    proxy in front.
    """
    global _server_started
    with _server_lock:
        if _server_started:
            return
        start_http_server(port, addr=addr)
        _server_started = True


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

_logging_configured = False


def configure_structlog(json: bool = True, level: int = logging.INFO) -> None:
    """
    Wire structlog over stdlib logging. Idempotent — the first call
    sticks; re-calls are no-ops to avoid dropping log lines mid-flight
    (structlog's docs warn against reconfiguring once handlers have
    been bound to loggers).

    ``json=True`` emits one JSON document per line on stderr (fits
    journald, Loki, Datadog). ``json=False`` emits the colorized
    "console" renderer for interactive runs.
    """
    global _logging_configured
    if _logging_configured:
        return

    import structlog
    from structlog.contextvars import merge_contextvars
    from structlog.processors import JSONRenderer, TimeStamper, add_log_level
    from structlog.dev import ConsoleRenderer

    # The stdlib root logger gets a basic config so that LOG.info(...)
    # calls in code that hasn't been migrated to structlog still
    # surface. structlog inherits the level via the WriteLoggerFactory
    # by default, so setting the root level is the simplest way to
    # gate verbosity uniformly.
    logging.basicConfig(level=level, format="%(message)s")

    structlog.configure(
        processors=[
            merge_contextvars,
            add_log_level,
            TimeStamper(fmt="iso"),
            JSONRenderer() if json else ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    _logging_configured = True


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------

def get_counter_value(name: str, labels: dict[str, str] | None = None) -> float:
    """
    Read a counter (or any sample) from the default registry by name.

    Test helper. Equivalent to scraping ``/metrics`` and parsing one
    sample. Returns 0.0 if the metric/labels combo has never been
    incremented (this matches Prometheus's ``absent`` semantics — the
    series is just missing, not zero).
    """
    from prometheus_client import REGISTRY
    v = REGISTRY.get_sample_value(name, labels or {})
    return float(v) if v is not None else 0.0


def reset_settlement_starts_for_tests() -> None:
    """
    Drop any in-flight settlement-start timestamps. Useful between
    tests that share the module-global ``_settle_starts`` map.
    Production code must NEVER call this — it would silently lose
    latency measurements for any in-flight settlement.
    """
    with _settle_lock:
        _settle_starts.clear()


__all__ = [
    # counters
    "SETTLEMENTS_TOTAL",
    "DISPUTES_TOTAL",
    "AGENT_COMPLETIONS_TOTAL",
    "GOSSIP_DELTAS_TOTAL",
    "SUPERVISOR_SPAWNS_TOTAL",
    # histograms
    "SETTLEMENT_LATENCY",
    "CLAIM_TO_COMPLETE_LATENCY",
    # gauges
    "ROSTER_SIZE",
    "DHT_PEER_COUNT",
    "CONNECTED_PEERS",
    "LEDGER_NET_CREDITS",
    # settlement helpers
    "record_settlement_start",
    "observe_settlement_latency",
    # lifecycle
    "start_metrics_server",
    "configure_structlog",
    # test helpers
    "get_counter_value",
    "reset_settlement_starts_for_tests",
]
