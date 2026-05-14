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

import logging
import signal
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
from gyza.runner import AgentRunner
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


def _build_demo_executor():
    """
    Factory: produces an executor compatible with AgentRunner. The
    runner calls ``executor(prompt: str, context: dict) -> dict``
    and expects a dict with at least a ``"text"`` key. We adapt
    _demo_response to that shape.
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

    compositor = LocalCompositor(key_path=cfg.compositor_key_path)
    LOG.info("compositor:    %s", compositor.pubkey_hex)

    # Re-use the existing daemon. Both NetdClient and GossipClient
    # are thin Unix-socket clients; we own neither the daemon
    # subprocess nor its lifecycle.
    netd = NetdClient(sock)
    gossip = GossipClient(sock)

    bb = NetworkBlackboard(cfg.blackboard_db_path)

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
        db_path=str(Path(cfg.blackboard_db_path).parent / "demo-spec.db"),
    )
    mem = EpisodicMemory(
        agent_id=ident.agent_id,
        db_path=str(Path(cfg.blackboard_db_path).parent / "demo-mem"),
    )
    lsh = LSHIndex(seed=42)

    runner = AgentRunner(
        identity=ident,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=lsh,
        executor=_build_demo_executor(),
        min_reward_threshold=0.0,
        min_similarity_threshold=min_similarity_threshold,
        poll_interval_s=poll_interval_s,
        on_envelope_signed=cluster.runner_envelope_hook(),
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
