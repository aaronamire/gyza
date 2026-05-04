"""
Demand oracle — measures unclaimed-work pressure per LSH bucket.

Background thread polls the blackboard every few seconds, groups
unclaimed work items by their description-embedding LSH bucket, and
publishes a `DemandSignal` per bucket. Agents query the oracle to
decide whether their semantic neighborhood has surplus work — the
cue for spawning replicas or drifting their specialization.

LSH choice: random-hyperplane (sign of dot product) over L2-normalized
planes, 64 bits. That's small enough to enumerate Hamming-radius-2
neighbors (2080 candidates) cheaply and big enough to keep collisions
between unrelated topics rare.

Concurrency: one writer (the poll thread) and many readers. A single
lock around the signals dict is enough — reads are dict lookups, the
write is a wholesale dict swap. The blackboard is already thread-safe
via per-thread sqlite3 connections.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from gyza.blackboard import Blackboard


_LSH_BITS = 64


class LSHIndex:
    def __init__(self, n_planes: int = 64, dim: int = 384, seed: int = 42):
        if n_planes != _LSH_BITS:
            # Hamming-radius enumeration in neighbor_buckets assumes 64 bits.
            # Allow other widths but make the assumption explicit.
            raise ValueError(
                f"n_planes must be {_LSH_BITS}; got {n_planes}. The bucket "
                f"id is packed into a 64-bit int."
            )
        rng = np.random.default_rng(seed)
        planes = rng.standard_normal((n_planes, dim)).astype(np.float32)
        # L2-normalize each plane — keeps projection magnitudes comparable
        # and makes the sign-of-dot-product geometric (a half-space test).
        norms = np.linalg.norm(planes, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self.planes = (planes / norms).astype(np.float32)
        self.n_planes = n_planes
        self.dim = dim

    def hash(self, embedding: np.ndarray) -> int:
        if embedding.shape != (self.dim,):
            raise ValueError(
                f"embedding shape must be ({self.dim},), got {embedding.shape}"
            )
        if embedding.dtype != np.float32:
            embedding = embedding.astype(np.float32)
        projections = self.planes @ embedding
        bits = (projections > 0).astype(np.uint8)
        # np.packbits packs 8 bits per byte big-endian; convert to int.
        packed = np.packbits(bits)
        return int.from_bytes(packed.tobytes(), byteorder="big")

    def neighbor_buckets(self, bucket: int, radius: int) -> list[int]:
        if radius < 0:
            raise ValueError(f"radius must be >= 0, got {radius}")
        if radius > self.n_planes:
            radius = self.n_planes
        out: list[int] = [bucket]
        for r in range(1, radius + 1):
            for positions in combinations(range(self.n_planes), r):
                mask = 0
                for p in positions:
                    mask |= 1 << p
                out.append(bucket ^ mask)
        return out


@dataclass
class DemandSignal:
    bucket: int
    unclaimed_count: int
    avg_reward: float
    max_reward: float
    oldest_item_age_ns: int
    centroid_embedding: np.ndarray | None


class DemandOracle:
    def __init__(
        self,
        blackboard: Blackboard,
        lsh: LSHIndex,
        poll_interval_s: float = 5.0,
    ):
        self._bb = blackboard
        self._lsh = lsh
        self._interval = poll_interval_s
        self._signals: dict[int, DemandSignal] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # Poll once synchronously so callers don't race the first tick —
        # otherwise compute_deficit() returns 0 for up to poll_interval_s
        # seconds after start(), which trips up tests and makes startup
        # behavior depend on timing.
        self._poll()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="gyza-demand-oracle", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._poll()
            except Exception:
                # Oracle outages must never bring down the agents that
                # depend on it. Swallow and retry next tick.
                continue

    def _poll(self) -> None:
        # Anything-tier, anything-reward: the oracle measures total demand,
        # not per-tier. Filtering happens in compute_deficit and at the
        # agent's own policy layer.
        items = self._bb.get_unclaimed(min_reward=0.0, tier=3)
        now_ns = time.time_ns()

        # Group items by bucket id.
        by_bucket: dict[int, list] = {}
        for w in items:
            b = self._lsh.hash(w.desc_embedding)
            by_bucket.setdefault(b, []).append(w)

        new_signals: dict[int, DemandSignal] = {}
        for bucket, witems in by_bucket.items():
            rewards = [w.reward for w in witems]
            ages = [now_ns - w.created_at_ns for w in witems]
            embs = np.stack([w.desc_embedding for w in witems], axis=0)
            centroid = embs.mean(axis=0).astype(np.float32)
            new_signals[bucket] = DemandSignal(
                bucket=bucket,
                unclaimed_count=len(witems),
                avg_reward=float(sum(rewards) / len(rewards)),
                max_reward=float(max(rewards)),
                oldest_item_age_ns=int(max(ages)),
                centroid_embedding=centroid,
            )

        with self._lock:
            self._signals = new_signals

    def get_signal(self, bucket: int) -> DemandSignal | None:
        with self._lock:
            return self._signals.get(bucket)

    def all_signals(self) -> dict[int, DemandSignal]:
        with self._lock:
            return dict(self._signals)

    def compute_deficit(self, agent_embedding: np.ndarray) -> float:
        bucket = self._lsh.hash(agent_embedding)
        deficit = 0.0
        for nb in self._lsh.neighbor_buckets(bucket, radius=2):
            sig = self.get_signal(nb)
            if sig is None:
                continue
            # Age factor: doubles roughly every 30s, capped at 3x. Keeps
            # demand monotonically growing for items that nobody picked
            # up, mirroring the reward-inflation halflife in reward.py.
            age_factor = min(sig.oldest_item_age_ns / 30e9, 3.0)
            deficit += sig.unclaimed_count * sig.avg_reward * age_factor
        return float(deficit)

    def should_spawn_replica(
        self,
        agent_embedding: np.ndarray,
        SPAWN_THRESHOLD: float = 5.0,
    ) -> bool:
        if self.compute_deficit(agent_embedding) <= SPAWN_THRESHOLD:
            return False
        own_bucket = self._lsh.hash(agent_embedding)
        own = self.get_signal(own_bucket)
        # Spawn only when *this* agent's own bucket isn't already saturated
        # — otherwise the agent itself should be working those items, not
        # cloning. <2 unclaimed in own bucket means it's near-idle locally.
        own_count = own.unclaimed_count if own is not None else 0
        return own_count < 2


__all__ = ["LSHIndex", "DemandSignal", "DemandOracle"]
