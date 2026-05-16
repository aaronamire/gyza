"""
gyza-demo-agent — a long-running Python service that runs on the
bootstrap VPSes (and anyone else who wants to host a demo executor)
so that ``gyza submit "<task>"`` from a stranger's laptop actually
gets a result.

This is the "wow moment" companion to the protocol: a real,
always-on node somewhere on the network that claims free-text
work items, executes them with a deterministic local executor,
signs an ICP envelope, and gossips the result back. Settlement
runs but failures are non-fatal — the demo agent works for free.

Architecture:

    gyza-netd (already running as systemd unit)
        │
        │  gRPC over Unix socket
        ▼
    run_hosted_demo_agent()
        │
        ├─ LocalCompositor (~/.gyza/compositor.key)
        ├─ NetworkBlackboard (~/.gyza/blackboard.db, gossip-attached)
        ├─ GlobalCluster (re-uses the netd_client / gossip_client)
        │  └─ joins DEMO_PROJECT_ID
        └─ AgentRunner
           └─ executor: gyza.demo_executor.demo_response

The executor is deliberately deterministic in v0.1: it doesn't
make API calls or run untrusted code. The point of the demo is
the *protocol* — cryptographic provenance, peer-to-peer routing,
verifiable execution — not the answer quality. v0.1.1 will swap
in an Anthropic-backed executor gated behind a per-peer-ID rate
limit, so hosted agents can actually answer real questions for
strangers without burning the API budget.

Public CLI entrypoint: ``gyza demo-agent`` (added in
``gyza/cli.py``). systemd unit: ``gyza-demo-agent.service``,
installed by ``scripts/deploy-bootstrap.sh``.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
from pathlib import Path

import numpy as np

from gyza.config import load_config
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.network.global_cluster import GlobalCluster
from gyza.network.netd_client import GossipClient, NetdClient
from gyza.network.network_blackboard import NetworkBlackboard
from gyza.runner import AgentRunner, make_anthropic_executor
from gyza.schema import EMBEDDING_DIM

LOG = logging.getLogger("gyza.demo_agent")

# Well-known public demo project. Any node running ``gyza submit``
# or ``gyza demo-agent`` joins this topic; that's how submitters'
# work items reach hosted agents and how results gossip back.
#
# Bump the version suffix (``-v1``) only when the wire format on
# this topic changes in a way that breaks compatibility with old
# clients. Adding fields = same version (protobuf forward-compat).
DEMO_PROJECT_ID = "gyza-demo-public-v1"


def _demo_response(task: str) -> str:
    """
    Deterministic v0.1 response generator. Takes the task text,
    returns a structured "I received and processed this" message.
    No external calls, no shell exec, no LLM. The protocol path
    (claim → execute → sign → gossip → verify) is the demo, not
    the response content.

    v0.1.1 will replace this with an Anthropic-backed executor;
    callers should treat ``demo_response`` as a stable interface
    (input str → output str) so the swap is one-line.
    """
    import socket as _sock
    hostname = _sock.gethostname()
    return (
        f"[gyza-demo-agent on {hostname}]\n\n"
        f"Received task ({len(task)} chars):\n"
        f"  {task[:200]}{'...' if len(task) > 200 else ''}\n\n"
        f"This response is signed by a Tier-1 demo agent. The "
        f"protocol guarantees you (the submitter) can verify that "
        f"this node claimed your work item and produced this output "
        f"at the timestamp in the envelope. Real LLM-backed responses "
        f"land in v0.1.1 (Anthropic-gated behind per-peer-ID rate "
        f"limits).\n\n"
        f"Envelope chain root: see your local ledger after this "
        f"completes. Verify with `gyza credits statement` and "
        f"`gyza status`."
    )


def _build_deterministic_executor():
    """
    Fallback executor when no ANTHROPIC_API_KEY is set, or when the
    quota / spend cap is exhausted. Returns the deterministic
    "I received your task" response — same signed envelope path,
    just no real LLM behind it.
    """
    def executor(prompt: str, _context: dict) -> dict:
        return {
            "text": _demo_response(prompt),
            "tokens_in": len(prompt) // 4,        # rough char→token estimate
            "tokens_out": 200,                     # demo response is ~200 tokens
            "model_identifier": "gyza-demo-deterministic-v1",
            "inference_backend": "deterministic",
        }
    return executor


# ----------------------------------------------------------------------
# Rate limit + spend cap for the Anthropic-backed executor.
# ----------------------------------------------------------------------
#
# Why a SQLite table and not in-memory counters:
# the demo agent runs as a long-lived service. If we lose state on
# restart, a viral surge could trip the daily cap → systemd
# restarts the agent → quota resets → traffic resumes uncapped.
# SQLite is the simplest persistent store and the disk traffic is
# trivial (one upsert per query).
#
# Pricing constants below match Claude Sonnet 4.5 as of 2026-05.
# These are coarse — the goal is "approximately bounded spend", not
# precise billing reconciliation. Anthropic's invoice is authoritative.

CLAUDE_SONNET_USD_PER_M_INPUT = 3.0
CLAUDE_SONNET_USD_PER_M_OUTPUT = 15.0


def _query_cost_usd(tokens_in: int, tokens_out: int) -> float:
    return (
        (tokens_in / 1_000_000) * CLAUDE_SONNET_USD_PER_M_INPUT
        + (tokens_out / 1_000_000) * CLAUDE_SONNET_USD_PER_M_OUTPUT
    )


class QuotaTracker:
    """
    Daily counters per submitter pubkey + a ``__global__`` row for
    the agent-wide aggregate. Three gates checked before every
    LLM call:

      1. per-submitter daily query count (default 10)
      2. global daily query count (default 1000)
      3. global daily spend USD (default $5.00)

    After every successful LLM call, ``record(...)`` updates BOTH
    the per-submitter row AND the global row. So a 5-query batch
    from one submitter consumes 5 from their daily allotment AND
    5 from the global daily allotment.

    Thread-safe via a single mutex; the daemon's gossip ingress
    can in principle call the agent's executor concurrently
    (though AgentRunner currently serializes).
    """

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS quota (
        day_ymd          TEXT NOT NULL,
        submitter_pubkey TEXT NOT NULL,
        queries          INTEGER NOT NULL DEFAULT 0,
        tokens_in        INTEGER NOT NULL DEFAULT 0,
        tokens_out       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day_ymd, submitter_pubkey)
    );
    """

    GLOBAL_KEY = "__global__"

    def __init__(
        self,
        db_path: str,
        *,
        per_submitter_daily_queries: int = 10,
        global_daily_queries: int = 1000,
        global_daily_spend_usd: float = 5.0,
    ):
        self._db_path = db_path
        self._per_submitter_cap = per_submitter_daily_queries
        self._global_query_cap = global_daily_queries
        self._global_spend_cap = global_daily_spend_usd
        self._lock = threading.Lock()
        # Eager schema init — avoids a race between concurrent first
        # callers each trying to CREATE TABLE.
        conn = self._open()
        try:
            conn.executescript(self.SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def _open(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, timeout=5.0)
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        return c

    @staticmethod
    def _today() -> str:
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    def check(self, submitter_pubkey: str) -> tuple[bool, str]:
        """
        Returns ``(allowed, reason)``. If allowed=False, the caller
        should NOT call the real LLM; the reason string is a
        user-facing message safe to surface in the placeholder
        response.
        """
        today = self._today()
        with self._lock:
            conn = self._open()
            try:
                row = conn.execute(
                    "SELECT queries, tokens_in, tokens_out FROM quota "
                    "WHERE day_ymd=? AND submitter_pubkey=?",
                    (today, submitter_pubkey),
                ).fetchone()
                sub_queries = row[0] if row else 0

                g = conn.execute(
                    "SELECT queries, tokens_in, tokens_out FROM quota "
                    "WHERE day_ymd=? AND submitter_pubkey=?",
                    (today, self.GLOBAL_KEY),
                ).fetchone()
                g_queries = g[0] if g else 0
                g_tokens_in = g[1] if g else 0
                g_tokens_out = g[2] if g else 0
                g_spend = _query_cost_usd(g_tokens_in, g_tokens_out)
            finally:
                conn.close()

        if sub_queries >= self._per_submitter_cap:
            return False, (
                f"per-submitter daily quota ({self._per_submitter_cap} queries) "
                f"exhausted for compositor {submitter_pubkey[:16]}…. "
                f"resets daily at 00:00 UTC."
            )
        if g_queries >= self._global_query_cap:
            return False, (
                f"agent-wide daily query cap ({self._global_query_cap}) "
                f"reached. resets daily at 00:00 UTC."
            )
        if g_spend >= self._global_spend_cap:
            return False, (
                f"agent-wide daily spend cap (${self._global_spend_cap:.2f}) "
                f"reached. resets daily at 00:00 UTC."
            )
        return True, ""

    def record(self, submitter_pubkey: str, tokens_in: int, tokens_out: int) -> None:
        """Record one successful LLM call against both rows."""
        today = self._today()
        with self._lock:
            conn = self._open()
            try:
                for key in (submitter_pubkey, self.GLOBAL_KEY):
                    conn.execute(
                        "INSERT INTO quota (day_ymd, submitter_pubkey, queries, tokens_in, tokens_out) "
                        "VALUES (?, ?, 1, ?, ?) "
                        "ON CONFLICT(day_ymd, submitter_pubkey) DO UPDATE SET "
                        "  queries = queries + 1, "
                        "  tokens_in = tokens_in + excluded.tokens_in, "
                        "  tokens_out = tokens_out + excluded.tokens_out",
                        (today, key, tokens_in, tokens_out),
                    )
                conn.commit()
            finally:
                conn.close()


def _gated_anthropic_response(reason: str) -> str:
    """Placeholder returned when a quota gate is hit."""
    return (
        f"[demo-agent: real-LLM response gated]\n\n"
        f"{reason}\n\n"
        f"This response is signed by the demo agent but was NOT "
        f"generated by Claude — you've hit a rate limit / spend cap. "
        f"Run your own gyza node with your own ANTHROPIC_API_KEY for "
        f"unlimited real-LLM queries: see https://github.com/aaronamire/gyza"
    )


def _build_anthropic_executor_gated(quota: QuotaTracker, blackboard: NetworkBlackboard):
    """
    Returns an executor that wraps make_anthropic_executor with the
    three quota gates. Submitter identity is recovered from the work
    item's lineage_root → intent → compositor_pubkey when available;
    if the intent isn't in our blackboard (gossip race), the
    submitter is treated as anonymous (still subject to the global
    gates).
    """
    real_exec = make_anthropic_executor()

    def _lookup_submitter(lineage_root: str) -> str:
        """
        Read goal_spec_json from the human_intents row this work
        item descends from. The submitter's compositor_pubkey is
        embedded in that JSON by ``gyza submit``. If the intent
        hasn't gossipped to us yet (race) or the field is missing,
        we fall back to 'anonymous' — the global gates still apply.
        """
        import json as _json
        try:
            conn = blackboard._conn()  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT goal_spec_json FROM human_intents WHERE intent_id=?",
                (lineage_root,),
            ).fetchone()
            if row is None:
                return "anonymous"
            spec = _json.loads(row[0])
            return spec.get("compositor_pubkey") or "anonymous"
        except Exception:  # noqa: BLE001
            return "anonymous"

    def executor(prompt: str, context: dict) -> dict:
        item = context.get("item")
        submitter = "anonymous"
        if item is not None:
            submitter = _lookup_submitter(item.lineage_root)

        allowed, reason = quota.check(submitter)
        if not allowed:
            LOG.info("[quota] gated submitter=%s — %s", submitter[:16], reason)
            return {
                "text": _gated_anthropic_response(reason),
                "tokens_in": len(prompt) // 4,
                "tokens_out": 100,
                "model_identifier": "gyza-demo-gated-v1",
                "inference_backend": "deterministic",
            }

        try:
            result = real_exec(prompt, context)
        except Exception as e:  # noqa: BLE001
            # Surface API errors as a placeholder rather than blowing
            # up the runner. The signed envelope still chains; the
            # response text is honest about what went wrong.
            LOG.warning("[anthropic] call failed: %s", e)
            return {
                "text": f"[demo-agent: Anthropic API error] {e}",
                "tokens_in": len(prompt) // 4,
                "tokens_out": 100,
                "model_identifier": "gyza-demo-error-v1",
                "inference_backend": "deterministic",
            }

        quota.record(
            submitter,
            int(result.get("tokens_in", 0)),
            int(result.get("tokens_out", 0)),
        )
        return result

    return executor


def _build_executor(blackboard: NetworkBlackboard, quota_db_path: str):
    """
    Choose the executor based on environment:

      - ANTHROPIC_API_KEY set → real Claude calls, gated by QuotaTracker
      - otherwise            → deterministic fallback (no API spend)

    Both produce signed ICP envelopes; only ``model_identifier`` and
    ``inference_backend`` differ.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        per_sub = int(os.environ.get("GYZA_DEMO_PER_SUBMITTER_QUERIES", "10"))
        glob_q = int(os.environ.get("GYZA_DEMO_GLOBAL_QUERIES", "1000"))
        glob_s = float(os.environ.get("GYZA_DEMO_GLOBAL_SPEND_USD", "5.0"))
        LOG.info(
            "[exec] real-LLM mode (anthropic) — per_submitter=%d/day, "
            "global=%d/day, spend_cap=$%.2f/day",
            per_sub, glob_q, glob_s,
        )
        quota = QuotaTracker(
            db_path=quota_db_path,
            per_submitter_daily_queries=per_sub,
            global_daily_queries=glob_q,
            global_daily_spend_usd=glob_s,
        )
        return _build_anthropic_executor_gated(quota, blackboard)

    LOG.info("[exec] deterministic mode (no ANTHROPIC_API_KEY)")
    return _build_deterministic_executor()


def run_hosted_demo_agent(
    *,
    socket_path: str | None = None,
    poll_interval_s: float = 0.5,
    min_similarity_threshold: float = -1.0,
    stop_event: threading.Event | None = None,
) -> int:
    """
    Long-running service. Connects to the local gyza-netd via the
    given socket path, joins ``DEMO_PROJECT_ID``, spawns an
    AgentRunner with the deterministic demo executor, and blocks
    until SIGTERM/SIGINT or ``stop_event`` is set.

    Returns process exit code (0 on clean shutdown).

    ``min_similarity_threshold=-1.0`` means the runner accepts any
    work item posted to the demo project, regardless of how well
    the item's embedding matches the agent's specialization. That's
    deliberately broad: a public demo agent should answer anything
    posted to the demo topic.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    cfg = load_config()
    sock = socket_path or cfg.netd_socket_path
    sock = str(Path(sock).expanduser())

    LOG.info("daemon socket: %s", sock)
    LOG.info("demo project:  %s", DEMO_PROJECT_ID)

    # Use resolved (tilde-expanded) paths. cfg.* attributes are raw
    # config strings like "~/.gyza/blackboard.db"; resolved_paths()
    # expands them. Without this the agent creates a literal "~"
    # directory relative to CWD.
    rp = cfg.resolved_paths()
    resolved_bb = rp["blackboard_db_path"]
    state_dir = Path(resolved_bb).parent

    compositor = LocalCompositor(key_path=rp["compositor_key_path"])
    LOG.info("compositor:    %s", compositor.pubkey_hex)

    # Re-use the existing daemon. Both NetdClient and GossipClient
    # are thin Unix-socket clients; we own neither the daemon
    # subprocess nor its lifecycle.
    netd = NetdClient(sock)
    gossip = GossipClient(sock)

    bb = NetworkBlackboard(resolved_bb)

    cluster = GlobalCluster(
        compositor=compositor,
        config=cfg,
        blackboard=bb,
        netd_client=netd,
        gossip_client=gossip,
    )

    # Block on start() — it does the daemon handshake, identity
    # check, peer-cache warm-up. ``async`` in the source but we
    # wrap with run_until_complete for the synchronous service.
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(cluster.start())
    LOG.info("cluster started")

    # Join the demo project topic and attach our blackboard so that
    # gossipsub deltas (intents posted by submitters, completions
    # posted by us) flow through the network.
    gossip.join_project(DEMO_PROJECT_ID)
    bb.attach_gossip(
        gossip, DEMO_PROJECT_ID, node_id=compositor.pubkey_hex,
    )
    LOG.info("joined %s, blackboard attached", DEMO_PROJECT_ID)

    # Build a single agent specialized broadly — the description
    # is intentionally generic so cosine(spec, any_task) is
    # nonzero. Combined with min_similarity_threshold=-1.0 this
    # makes the agent willing to claim anything.
    seed, manifest = compositor.issue_agent(
        agent_type="demo.public-agent",
        model_path="deterministic",
        fs_read_paths=[],
        fs_write_paths=[],
        attestation_tier=1,
    )
    ident = AgentIdentity(seed, manifest)
    LOG.info("agent id: %s", ident.agent_id)

    # Stub specialization vector. The hosted demo agent uses
    # min_similarity_threshold=-1.0 (accepts any work regardless of
    # cosine score), so the specialization vector's *content* doesn't
    # matter — only its shape + dtype. Using a fixed-seed stub
    # vector here lets us avoid loading sentence-transformers on
    # 1 GB VPSes (which would push the daemon + agent over the RAM
    # budget). If a future demo-agent variant DOES want semantic
    # specialization (e.g. "I only do code tasks"), swap this for
    # embed_work_description("...") and accept the ST load.
    rng = np.random.default_rng(seed=0xDEC0DE)
    spec_seed = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    spec_seed /= np.linalg.norm(spec_seed)
    spec = SpecializationTracker(
        agent_id=ident.agent_id,
        initial_embedding=spec_seed,
        db_path=str(state_dir / "demo-spec.db"),
    )
    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(state_dir / "demo-mem"),
    )
    lsh = LSHIndex(seed=42)

    quota_db_path = str(state_dir / "demo-agent-quota.db")
    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=lsh,
        executor=_build_executor(bb, quota_db_path),
        min_reward_threshold=0.0,
        min_similarity_threshold=min_similarity_threshold,
        poll_interval_s=poll_interval_s,
        # settle=False: the public demo agent works for free. It
        # still delivers the signed result to the submitter (that's
        # the value); it just doesn't open a bilateral ledger entry,
        # so strangers running `gyza submit` don't accrue compute
        # debt. Settlement is demonstrated by demo/single_machine_global.
        on_envelope_signed=cluster.runner_envelope_hook(settle=False),
        hlc=cluster.shared_hlc(),
    )
    runner.start()
    LOG.info("agent runner started — ready to accept demo work")

    # Signal handling. SIGTERM (systemd stop) and SIGINT (Ctrl-C)
    # both trigger a clean shutdown. stop_event lets tests / Python
    # supervisors trigger the same path without sending a signal.
    stop = stop_event if stop_event is not None else threading.Event()

    def _handle_signal(signum, _frame):  # noqa: ANN001
        LOG.info("signal %d received; shutting down", signum)
        stop.set()

    if stop_event is None:
        # Only install signal handlers when we own the main thread
        # (i.e., running as a service, not embedded in a test).
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    # Lightweight liveness heartbeat — prints once a minute so
    # journalctl shows the service is alive even if no work
    # arrives. The runner itself logs every claim/sign at INFO,
    # so the heartbeat is a "did we crash silently" canary, not a
    # primary observability surface.
    last_heartbeat = time.monotonic()
    while not stop.is_set():
        stop.wait(timeout=5.0)
        now = time.monotonic()
        if now - last_heartbeat >= 60.0:
            LOG.info(
                "alive — agent=%s completed=%d",
                ident.agent_id[:16],
                runner.completed_count,
            )
            last_heartbeat = now

    LOG.info("shutting down runner")
    runner.stop()
    loop.run_until_complete(cluster.stop())
    loop.close()
    LOG.info("clean exit")
    return 0


def main() -> int:
    """CLI entrypoint registered under ``gyza demo-agent``."""
    return run_hosted_demo_agent()


if __name__ == "__main__":
    sys.exit(main())
