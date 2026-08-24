"""How many THREADED agents doing REAL sandboxed work can one box sustain?

Measures rather than asserts. The arithmetic says 500 agents x 20 actions is
~13 minutes on four cores; arithmetic of exactly this kind has been wrong twice
this week (a 4-core laptop reported as an architectural ceiling; 9.6 MB/runner
that was really 0.27). So this runs the ladder and reports where it breaks.

Every action is a real bubblewrap execution of /usr/bin/uname -a. Agents are
THREADS in one process, which the subprocess-scaling measurement says is the
right topology: threads scale 29.89x at 32 for subprocess-bound work and 0.66x
for CPU-bound, because the GIL is released across the ~305 ms bwrap call.

Usage:  python research/scale/threaded_scale.py <outdir> [max_n] [actions]
"""
from __future__ import annotations

import json, os, sys, threading, time, traceback, uuid
from pathlib import Path

import numpy as np
sys.path.insert(0, "/home/xan/dev/gyza")

from gyza.blackboard import Blackboard
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.network.artifact_store import ArtifactStore
from gyza.runner import AgentRunner
from gyza.sandbox.config import SandboxConfig
from gyza.sandbox.executor import ADMISSION, make_sandboxed_executor
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


def rss_mb() -> int:
    return int(open(f"/proc/{os.getpid()}/status").read()
               .split("VmRSS:")[1].split()[0]) // 1024


def seed_items(bb, intent, n):
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32); e[0] = 1.0
    bb.post_intent({"intent_id": intent, "natural_text": "scale probe",
                    "category": "system_task", "actions": [],
                    "authorization": {"resources": [], "preview_required": False,
                                      "reversible": True}})
    for _ in range(n):
        bb.post_work_item(WorkItem(
            id=str(uuid.uuid7()), lineage_root=intent, parent_id=None,
            description="sandboxed uname", desc_embedding=e, reward=0.9,
            reward_updated_ns=time.time_ns(), required_tier=0, input_hashes=[],
            output_spec={"kind": "text"}, streaming_ok=False, claimed_by=None,
            claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0, claim_hlc_node="",
            completed_at_ns=None, output_hash=None, icp_envelope_hash=None,
            success=None, created_at_ns=time.time_ns(), ttl_ns=3600 * 10**9))


def run(out: Path, n_agents: int, per_agent: int) -> dict:
    d = out / f"n{n_agents}"; d.mkdir(parents=True, exist_ok=True)
    intent = f"scale-{n_agents}"
    store = ArtifactStore(base_path=str(d / "cas"))
    bb = Blackboard(str(d / "b.db")); bb.attach_artifact_store(store)
    total = n_agents * per_agent
    seed_items(bb, intent, total)

    comp = LocalCompositor(key_path=str(d / "k.key"))
    lsh = LSHIndex(seed=42)                       # SHARED: 0.27 MB/runner
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32); v[0] = 1.0
    cfg = SandboxConfig(ro_paths=[], rw_paths=[], requires_network=False,
                        max_memory_mb=512)
    execu = make_sandboxed_executor(
        "gyza.runner:make_command_executor",
        init_kwargs={"argv": ["/usr/bin/uname", "-a"]}, config=cfg)

    a0 = ADMISSION.stats()
    rss0 = rss_mb()
    t_build = time.monotonic()
    runners = []
    for i in range(n_agents):
        seed, man = comp.issue_agent(
            agent_type=f"s{i}", model_path="mock", fs_read_paths=[],
            fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
            attestation_tier=0)
        ident = AgentIdentity(seed, man)
        runners.append((ident, AgentRunner(
            identity=ident, blackboard=bb,
            memory=EpisodicMemory(agent_id=ident.agent_id,
                                  db_path=str(d / f"m{i}")),
            specialization=SpecializationTracker(
                agent_id=ident.agent_id, initial_embedding=v,
                db_path=str(d / f"s{i}.db")),
            lsh=lsh, executor=execu, min_reward_threshold=0.0,
            min_similarity_threshold=-1.0, verify_chain_before_claim=False,
            require_enforcement=True)))
    build_s = time.monotonic() - t_build
    rss_built = rss_mb()

    done = {"ok": 0, "fail": 0}
    errs: list[str] = []
    lk = threading.Lock()

    def worker(ident, r):
        hlc = HLC(node_id=ident.agent_id[:8])
        for _ in range(per_agent):
            try:
                avail = bb.get_unclaimed(0.0, 0, limit=64)
                if not avail:
                    return
                got = None
                for w in avail:
                    if bb.try_claim(w.id, ident.agent_id, hlc, claimant_tier=0):
                        got = w; break
                if got is None:
                    continue
                r._complete(got, r._execute(got), success=True)
                with lk: done["ok"] += 1
            except Exception as e:                              # noqa: BLE001
                with lk:
                    done["fail"] += 1
                    if len(errs) < 5:
                        errs.append(f"{type(e).__name__}: {e}"[:160])

    t0 = time.monotonic()
    ths = [threading.Thread(target=worker, args=(i, r)) for i, r in runners]
    for t in ths: t.start()
    for t in ths: t.join()
    dt = time.monotonic() - t0
    peak = rss_mb()

    signed = bb._conn().execute(
        "SELECT COUNT(*) c FROM work_items WHERE lineage_root=? "
        "AND icp_envelope_hash IS NOT NULL", (intent,)).fetchone()["c"]
    a1 = ADMISSION.stats()
    n_adm = a1["admitted"] - a0["admitted"]
    waited = a1["total_wait_s"] - a0["total_wait_s"]
    a = {"limit": a1["limit"], "admitted": n_adm,
         "mean_wait_ms": round(waited / n_adm * 1000, 1) if n_adm else 0.0,
         "peak_waiting": a1["peak_waiting"]}
    return {"agents": n_agents, "per_agent": per_agent, "posted": total,
            "signed": signed, "ok": done["ok"], "failed": done["fail"],
            "wall_s": round(dt, 1),
            "actions_per_s": round(signed / dt, 2) if dt else 0,
            "build_s": round(build_s, 1),
            "rss_built_mb": rss_built, "rss_peak_mb": peak,
            "rss_per_agent_mb": round((rss_built - rss0) / n_agents, 3),
            "admission": a, "errors": errs}


def main() -> int:
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    max_n = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    ladder = [n for n in (10, 50, 100, 250, 500) if n <= max_n]
    print(f"cores={os.cpu_count()}  sandbox admission limit={ADMISSION.limit}  "
          f"{per} action(s)/agent\n")
    print(f"{'agents':>7} {'signed':>7} {'fail':>5} {'wall_s':>7} "
          f"{'act/s':>7} {'RSS_MB':>7} {'MB/agent':>9} {'q_ms':>7}")
    rows = []
    for n in ladder:
        try:
            r = run(out, n, per)
        except Exception as e:                                  # noqa: BLE001
            traceback.print_exc()
            print(f"{n:>7}  RUN FAILED: {type(e).__name__}: {e}")
            rows.append({"agents": n, "RUN_FAILED": f"{type(e).__name__}: {e}"})
            break
        rows.append(r)
        print(f"{r['agents']:>7} {r['signed']:>7} {r['failed']:>5} "
              f"{r['wall_s']:>7} {r['actions_per_s']:>7} {r['rss_peak_mb']:>7} "
              f"{r['rss_per_agent_mb']:>9} "
              f"{r['admission']['mean_wait_ms']:>7}")
        if r["failed"]:
            print(f"         first errors: {r['errors'][:2]}")
    (out / "ladder.json").write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {out/'ladder.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
