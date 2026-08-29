"""How many runners can one host actually sustain, and what breaks first?

`research/scale/FINDINGS_COORDINATION_CEILING.md` measured the blackboard POLL
path at 209,000 reads/s and called the sandbox the binding constraint at 305
ms/action. Both are true and neither answers the deployment question, because
the poll path is the cheapest thing a runner does and the sandbox figure is
per-core rather than per-host.

WHAT ACTUALLY DECIDES THE FLEET SIZE is the CONTENDED path: N runners sharing
one blackboard, each claiming work, executing, and signing. Claims serialize on
SQLite's writer lock (BEGIN IMMEDIATE), so the interesting quantity is how
aggregate throughput moves with N -- and whether it moves at all.

This measures the SUBSTRATE, deliberately with a mock executor. Mixing in the
305 ms sandbox would make every configuration sandbox-bound and measure that
constant instead of the coordination it is supposed to isolate. The two compose
by the slower of the pair, and 4b reports the composition rather than hiding it.
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from gyza.blackboard import Blackboard                        # noqa: E402
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem          # noqa: E402


def _item(intent: str, i: int) -> WorkItem:
    emb = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    emb[i % EMBEDDING_DIM] = 1.0
    return WorkItem(
        id=str(uuid.uuid7()), lineage_root=intent, parent_id=None,
        description=f"item {i}", desc_embedding=emb, reward=0.5,
        reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
        output_spec={"kind": "test"}, streaming_ok=False, claimed_by=None,
        claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
        completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
        success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9)


def run_cell(n_runners: int, items_per_runner: int, db: str) -> dict:
    """N threads race for a shared pool, each claiming until the pool empties.

    THE POOL IS SHARED, NOT PARTITIONED. Giving each thread its own items would
    measure N independent writers and call the result contention -- the whole
    question is what happens when they collide.
    """
    bb = Blackboard(db)
    intent = f"concurrency-{n_runners}"
    bb.post_intent({"intent_id": intent, "natural_text": "concurrency",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [], "preview_required": False,
                                      "reversible": True}})
    total = n_runners * items_per_runner
    items = [_item(intent, i) for i in range(total)]
    for w in items:
        bb.post_work_item(w)

    ids = [w.id for w in items]
    won: dict[str, int] = {}
    latencies: list[float] = []
    lock = threading.Lock()
    start_barrier = threading.Barrier(n_runners)

    def worker(k: int) -> None:
        local = Blackboard(db)              # thread-local connection, as prod
        hlc = HLC(node_id=f"agent-{k}")
        mine = 0
        lat: list[float] = []
        start_barrier.wait(timeout=60)
        for wid in ids:
            t0 = time.perf_counter()
            got = local.try_claim(wid, f"agent-{k}", hlc)
            lat.append(time.perf_counter() - t0)
            if got:
                mine += 1
        with lock:
            won[f"agent-{k}"] = mine
            latencies.extend(lat)

    threads = [threading.Thread(target=worker, args=(k,), daemon=True)
               for k in range(n_runners)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300)
    elapsed = time.perf_counter() - t0

    claimed = sum(won.values())
    lat_sorted = sorted(latencies)
    return {
        "runners": n_runners,
        "items": total,
        "claimed": claimed,
        "double_claims": claimed - total if claimed > total else 0,
        "unclaimed": total - claimed,
        "wall_s": round(elapsed, 3),
        "claims_per_s": round(total / elapsed, 1) if elapsed else 0.0,
        "attempts": len(latencies),
        "claim_p50_ms": round(statistics.median(lat_sorted) * 1000, 3),
        "claim_p99_ms": round(lat_sorted[int(len(lat_sorted) * 0.99)] * 1000, 3),
        "distribution": dict(sorted(won.items())),
    }


def main() -> int:
    cells = []
    for n in (1, 2, 4, 8, 16, 32):
        with tempfile.TemporaryDirectory() as d:
            cells.append(run_cell(n, 25, str(Path(d) / "bb.db")))
            c = cells[-1]
            print(f"  runners={c['runners']:>3}  items={c['items']:>4}  "
                  f"wall={c['wall_s']:>7.2f}s  claims/s={c['claims_per_s']:>8.1f}  "
                  f"p50={c['claim_p50_ms']:>7.3f}ms  p99={c['claim_p99_ms']:>8.3f}ms  "
                  f"double={c['double_claims']}  unclaimed={c['unclaimed']}")

    base = cells[0]["claims_per_s"]
    print("\n  scaling vs 1 runner (throughput of the SHARED pool):")
    for c in cells:
        print(f"    {c['runners']:>3} runners: {c['claims_per_s'] / base:>6.2f}x")

    out = Path(__file__).parent / "concurrency.json"
    out.write_text(json.dumps({"cells": cells}, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
