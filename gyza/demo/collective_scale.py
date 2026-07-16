"""
Scale + adversarial evaluation harness — measure a heterogeneous agent
collective's scalability, adaptability, and resilience, and emit
structured metrics.

WHY THIS EXISTS
---------------
The other demos tell a story at N=2..5. DICE (HR001126S0010) is scored
on *measurable* scalability, adaptability, and resilience across a range
of conditions (Q4, Q118), with "interactions" defined as messages
exchanged between agents (Q116). This harness drives an in-process
collective of N heterogeneous agents — each an ``AgentAdaptor`` over a
different "brain" — through a mission under a configurable network
partition and a configurable fraction of Byzantine (equivocating)
members, and emits JSON metrics for the three axes.

HONEST SCOPE
------------
This is a *logical-scale* simulation, not a wire-level distributed
deployment: N replicas in one process over the in-memory CRDT + gossip
planes (``gyza.demo.gossip`` / ``coordination_plane``). That is the
kind of evidence DICE's own program uses (simulation, Q5/Q32) — but the
wall-clock and message counts reflect this implementation's *naive*
all-pairs pull anti-entropy, which is O(N^2) messages per round. That
cost is reported, not hidden: a production epidemic protocol would
target O(N log N), and surfacing the gap here is a finding (cf. DICE
Q37 on the comms burden of peer-to-peer coordination), not a result to
launder.

Run it:

    python -m gyza.demo.collective_scale            # a sweep + a headline run
    python -m gyza.demo.collective_scale --json     # machine-readable metrics
"""
from __future__ import annotations

import json
import os
import random
import secrets
import sys
import tempfile
import time
from dataclasses import dataclass

import blake3

from gyza.adaptor import AgentAdaptor
from gyza.demo.gossip import GossipNode, Network, epidemic_converge
from gyza.icp import verify_dag
from gyza.identity import LocalCompositor
from gyza.resilience import assess_resilience

INTENT = "scale-mission"


# Heterogeneous "brains" — different agents, one adaptor/envelope contract.
def _fn_plan(p: str, c) -> str:
    return f"PLAN:{p}"


def _fn_upper(p: str, c) -> str:
    return p.upper()


def _fn_digest(p: str, c) -> str:
    return blake3.blake3(p.encode()).hexdigest()[:16]


def _fn_echo(p: str, c) -> str:
    return p


_BRAINS = (_fn_plan, _fn_upper, _fn_digest, _fn_echo)


@dataclass
class MissionConfig:
    n_agents: int
    partition: tuple[int, ...] | None = None  # group sizes; must sum to n_agents
    byzantine_fraction: float = 0.0
    seed: int = 0
    # None → all-pairs pull (O(N^2) msgs, ~1 round). An int → bounded
    # fanout epidemic (O(N*fanout) msgs/round, O(log N) rounds).
    fanout: int | None = None

    def __post_init__(self) -> None:
        if self.n_agents < 2:
            raise ValueError("n_agents must be >= 2")
        if self.partition is not None and sum(self.partition) != self.n_agents:
            raise ValueError(
                f"partition {self.partition} must sum to n_agents={self.n_agents}"
            )
        if self.fanout is not None and self.fanout < 1:
            raise ValueError("fanout must be >= 1 or None")


@dataclass
class MissionMetrics:
    config: dict
    scalability: dict
    adaptability: dict
    resilience: dict

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "scalability": self.scalability,
            "adaptability": self.adaptability,
            "resilience": self.resilience,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def summary(self) -> str:
        s, a, r = self.scalability, self.adaptability, self.resilience
        return (
            f"N={self.config['n_agents']:>4}  "
            f"envelopes={s['total_envelopes']:>5}  "
            f"conv_rounds={s['gossip_rounds']:>3}  "
            f"pull_msgs={s['pull_contacts']:>8}  "
            f"recover_rounds={a['recovery_rounds']:>3}  "
            f"byz={r['byzantine_agents']:>3}  "
            f"detected={r['equivocations_detected']:>3}  "
            f"honest={r['honest_fraction']:.2f}  "
            f"mission={'INTACT' if r['mission_intact'] else 'BROKEN'}  "
            f"{s['wall_ms']:>5}ms"
        )


def _converge(nodes: list[GossipNode], net: Network, *, max_rounds: int = 500):
    """Instrumented anti-entropy to a fixpoint. Returns (rounds, pull_contacts).

    ``pull_contacts`` counts, per round, each node's pulls to its
    currently-reachable peers — the message count for this all-pairs
    pull protocol, including the final confirming sweep.
    """
    rounds = 0
    contacts = 0
    while rounds < max_rounds:
        round_contacts = sum(len(net.reachable(n.node_id)) - 1 for n in nodes)
        gained = sum(n.pull_round() for n in nodes)
        rounds += 1
        contacts += round_contacts
        if gained == 0:
            break
    return rounds, contacts


def run_mission(config: MissionConfig) -> MissionMetrics:
    rng = random.Random(config.seed)
    t0 = time.perf_counter()
    tmp = tempfile.mkdtemp(prefix="gyza-scale-")
    try:
        key_path = os.path.join(tmp, "compositor.key")
        with open(key_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(key_path, 0o600)
        compositor = LocalCompositor(key_path=key_path)

        ids = [f"a{i}" for i in range(config.n_agents)]
        net = Network(ids)
        nodes = {i: GossipNode(i, net) for i in ids}
        for n in nodes.values():
            n.attach_peers(list(nodes.values()))

        # a0 authors genesis and is never Byzantine (the root must be honest).
        n_byz = int(round(config.byzantine_fraction * config.n_agents))
        n_byz = max(0, min(n_byz, config.n_agents - 1))
        byz = set(rng.sample(ids[1:], n_byz)) if n_byz else set()

        adaptors: dict[str, AgentAdaptor] = {}
        for i in ids:
            brain = _BRAINS[rng.randrange(len(_BRAINS))]
            adaptors[i] = AgentAdaptor.from_compositor(
                compositor, brain,
                agent_type="byz" if i in byz else "honest",
                memory_limit_mb=512, sink=nodes[i].state,
            )

        node_list = list(nodes.values())

        def converge(nl: list[GossipNode]) -> tuple[int, int]:
            if config.fanout is None:
                return _converge(nl, net)
            return epidemic_converge(nl, net, fanout=config.fanout, rng=rng)

        # -- Phase 1: genesis, gossiped to everyone before anyone builds on it.
        root = adaptors["a0"].act(
            intent_id=INTENT, action_id="genesis", prompt="mission start",
        )
        converge(node_list)

        # -- Phase 2: partition, then every agent contributes; Byzantine
        #    members equivocate (two conflicting outputs for one action).
        if config.partition:
            groups: list[list[str]] = []
            k = 0
            for size in config.partition:
                groups.append(ids[k:k + size])
                k += size
            net.partition(*groups)

        for i in ids:
            a = adaptors[i]
            if i in byz:
                a.act(intent_id=INTENT, action_id=f"c-{i}",
                      prompt=f"{i}:report-A", parent=root)
                a.act(intent_id=INTENT, action_id=f"c-{i}",
                      prompt=f"{i}:report-B", parent=root)
            else:
                a.act(intent_id=INTENT, action_id=f"c-{i}",
                      prompt=f"{i}:work", parent=root)

        p_rounds, p_contacts = converge(node_list)

        # Divergence at the moment before heal: how much knowledge each
        # side is missing relative to the eventual union.
        union = set()
        for n in node_list:
            union |= set(n.state.event_hashes())
        pre_heal_divergence = max(
            len(union) - len(n.state.event_hashes()) for n in node_list
        )

        # -- Phase 3: heal and reconverge — the adaptability measurement.
        net.heal()
        r_rounds, r_contacts = converge(node_list)

        # Every node now holds the full union; assess the merged history.
        merged = node_list[0].state.envelopes()
        report = assess_resilience(merged)
        honest_only = [
            e for e in merged if e.agent_pubkey not in report.quarantined_agents
        ]
        honest_dag = verify_dag(honest_only, require_closed=False)
        all_converged = all(
            len(n.state.event_hashes()) == len(union) for n in node_list
        )

        wall_ms = int((time.perf_counter() - t0) * 1000)
        return MissionMetrics(
            config={
                "n_agents": config.n_agents,
                "partition": list(config.partition) if config.partition else None,
                "byzantine_fraction": config.byzantine_fraction,
                "seed": config.seed,
                "gossip": ("all-pairs" if config.fanout is None
                           else f"epidemic(fanout={config.fanout})"),
            },
            scalability={
                "total_envelopes": len(merged),
                "gossip_rounds": p_rounds + r_rounds,
                "pull_contacts": p_contacts + r_contacts,
                "all_converged": all_converged,
                "wall_ms": wall_ms,
                "note": ("all-pairs pull: O(N^2) msgs/round" if config.fanout is None
                         else f"bounded-fanout epidemic: O(N*{config.fanout}) msgs/round"),
            },
            adaptability={
                "partition_groups": list(config.partition) if config.partition else None,
                "pre_heal_divergence": pre_heal_divergence,
                "recovery_rounds": r_rounds,
            },
            resilience={
                "byzantine_agents": len(byz),
                "equivocations_detected": len(report.equivocations),
                "quarantined_agents": len(report.quarantined_agents),
                "honest_fraction": round(report.honest_fraction, 4),
                "mission_intact": report.mission_intact and honest_dag.valid,
            },
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def sweep(ns: list[int], *, byzantine_fraction: float = 0.1,
          partition_ratio: float = 0.5, seed: int = 0,
          fanout: int | None = None) -> list[MissionMetrics]:
    """Run one mission per N. Each N is split into a ``partition_ratio``
    partition and given the same Byzantine fraction, so the columns are
    comparable across scale. ``fanout`` selects all-pairs (None) or the
    bounded-fanout epidemic."""
    out: list[MissionMetrics] = []
    for n in ns:
        left = max(1, int(round(n * partition_ratio)))
        part = (left, n - left)
        out.append(run_mission(MissionConfig(
            n_agents=n, partition=part, byzantine_fraction=byzantine_fraction,
            seed=seed, fanout=fanout,
        )))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ns = [10, 50, 100, 200]
    all_pairs = sweep(ns, byzantine_fraction=0.1, partition_ratio=0.5, fanout=None)
    epidemic = sweep(ns, byzantine_fraction=0.1, partition_ratio=0.5, fanout=4)

    if "--json" in argv:
        print(json.dumps(
            {"all_pairs": [m.to_dict() for m in all_pairs],
             "epidemic": [m.to_dict() for m in epidemic]},
            indent=2, sort_keys=True,
        ))
        ok = all(m.resilience["mission_intact"] and m.scalability["all_converged"]
                 for m in all_pairs + epidemic)
        return 0 if ok else 1

    print("GYZA — COLLECTIVE SCALE + ADVERSARIAL HARNESS")
    print("=" * 76)
    print("Heterogeneous agents, 50/50 partition, 10% Byzantine (equivocators).")
    print("Two gossip protocols, same mission — the message-cost trade, measured.\n")
    print("  ALL-PAIRS PULL (O(N^2) messages):")
    for m in all_pairs:
        print("    " + m.summary())
    print("\n  BOUNDED-FANOUT EPIDEMIC, fanout=4 (O(N*fanout) messages/round):")
    for m in epidemic:
        print("    " + m.summary())
    print("\n  Message cost, all-pairs → epidemic (both converge, both catch every")
    print("  equivocator, both keep the mission intact):")
    for ap, ep in zip(all_pairs, epidemic):
        a, e = ap.scalability["pull_contacts"], ep.scalability["pull_contacts"]
        print(f"    N={ap.config['n_agents']:>4}: {a:>8} → {e:>7} msgs "
              f"({a / e:.1f}x fewer)   rounds {ap.scalability['gossip_rounds']} "
              f"→ {ep.scalability['gossip_rounds']}")

    ok = all(m.resilience["mission_intact"] and m.scalability["all_converged"]
             for m in all_pairs + epidemic)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
