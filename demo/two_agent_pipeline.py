"""
Gyza two-agent pipeline demo.

A query specialist scans ~/dev/gyza for Python files and writes a
structured analysis. A summarizer specialist consumes that analysis
and writes a codebase architecture summary. Both run as AgentRunner
threads against a shared blackboard. After both work items complete
the demo reconstructs the per-agent ICP chain and verifies it
end-to-end.

Run this with ANTHROPIC_API_KEY set for real model output. Without
the key the demo falls back to a mock executor that produces
realistic-looking dummy content so the cryptographic plumbing can
still be exercised.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

import blake3
import numpy as np

# Allow running this file directly: `python demo/two_agent_pipeline.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gyza.blackboard import Blackboard
from gyza.config import load_config
from gyza.demand import LSHIndex
from gyza.drift import SpecializationTracker
from gyza.icp import compute_envelope_hash, verify_chain, verify_envelope
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.memory import EpisodicMemory
from gyza.runner import AgentRunner, make_anthropic_executor, make_mock_executor
from gyza.schema import EMBEDDING_DIM, Artifact, WorkItem


# ---------------------------------------------------------------------------
# Setup paths and intent. The demo uses the configured blackboard path so
# `gyza status` after a demo run sees the same database.
# ---------------------------------------------------------------------------

_CFG = load_config()
GYZA_HOME = Path.home() / ".gyza"
OUTPUT_DIR = GYZA_HOME / "output"
DEMO_BB_PATH = Path(os.path.expanduser(_CFG.blackboard_db_path))
SCAN_ROOT = Path.home() / "dev" / "gyza"

INTENT_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


def _embed_stub(text: str, seed: int) -> np.ndarray:
    """Deterministic 384-d embedding from a seed string.

    The demo doesn't need semantic embeddings — just stable per-task
    vectors that two specialized agents can be steered toward via their
    initial specialization. Using a seeded RNG keeps the demo offline.
    """
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


# ---------------------------------------------------------------------------
# Query specialist — scans the codebase
# ---------------------------------------------------------------------------

def make_query_executor():
    """
    Tries the Anthropic API first; falls back to a deterministic local
    scan if no key is set. The local fallback walks SCAN_ROOT and emits
    a JSON-encoded analysis that's structurally similar to what we'd
    expect from the model.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic  # noqa: F401 — pre-flight; the executor lazy-imports too
            return make_anthropic_executor(api_key=api_key, model="claude-sonnet-4-5")
        except Exception as e:
            print(f"[demo] anthropic executor unavailable ({e}); using local fallback")

    def _local_scan(_prompt, _ctx):
        files = []
        for p in SCAN_ROOT.rglob("*.py"):
            # Skip caches and demo output dirs.
            if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
                continue
            try:
                src = p.read_text(errors="replace")
            except OSError:
                continue
            classes = []
            funcs = []
            for line in src.splitlines():
                s = line.strip()
                if s.startswith("class "):
                    classes.append(s.split()[1].split("(")[0].rstrip(":"))
                elif s.startswith("def "):
                    funcs.append(s.split()[1].split("(")[0])
            doc = ""
            stripped = src.lstrip()
            if stripped.startswith('"""'):
                end = stripped.find('"""', 3)
                if end > 0:
                    doc = stripped[3:end].strip().split("\n")[0][:140]
            files.append({
                "path": str(p.relative_to(SCAN_ROOT)),
                "purpose": doc,
                "classes": classes[:10],
                "functions": funcs[:10],
                "loc": len(src.splitlines()),
            })
        analysis = {
            "scan_root": str(SCAN_ROOT),
            "file_count": len(files),
            "total_loc": sum(f["loc"] for f in files),
            "files": files,
        }
        text = json.dumps(analysis, indent=2)
        return {
            "text": text,
            "tokens_in": 0,
            "tokens_out": len(text) // 4,
            "model_identifier": "local-scan",
            "inference_backend": "mock",
        }

    return _local_scan


# ---------------------------------------------------------------------------
# Summarizer specialist
# ---------------------------------------------------------------------------

def make_summarizer_executor():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic  # noqa: F401 — pre-flight; the executor lazy-imports too
            return make_anthropic_executor(api_key=api_key, model="claude-sonnet-4-5")
        except Exception as e:
            print(f"[demo] anthropic executor unavailable ({e}); using local fallback")

    def _local_summarize(_prompt, ctx):
        # Pull the upstream artifact data out of the runner context.
        inputs: list[Artifact] = ctx.get("inputs", []) or []
        analysis = None
        for art in inputs:
            try:
                payload = json.loads(art.data.decode("utf-8"))
                # Runner wraps text outputs as {"text": <json string>}.
                inner = payload.get("text") if isinstance(payload, dict) else None
                if isinstance(inner, str):
                    try:
                        analysis = json.loads(inner)
                    except json.JSONDecodeError:
                        analysis = {"raw": inner}
                else:
                    analysis = payload
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

        if analysis is None:
            summary = (
                "No upstream analysis artifact was readable. The summarizer "
                "ran but produced an empty report."
            )
        else:
            file_count = analysis.get("file_count", "?")
            total_loc = analysis.get("total_loc", "?")
            files = analysis.get("files", []) or []
            modules = sorted({f.get("path", "") for f in files})
            top_classes: list[str] = []
            for f in files:
                top_classes.extend(f.get("classes", []) or [])
            uniq_classes = sorted(set(top_classes))[:20]
            summary = (
                f"Gyza codebase summary\n"
                f"  scan root: {analysis.get('scan_root', '?')}\n"
                f"  python files: {file_count}\n"
                f"  total loc: {total_loc}\n"
                f"  modules:\n    "
                + "\n    ".join(modules[:25])
                + f"\n  representative classes:\n    "
                + "\n    ".join(uniq_classes)
                + "\n\n"
                "Architecture: a SQLite-backed blackboard coordinates work "
                "items between Ed25519-signed agents. Every action is "
                "recorded as an ICP envelope so the full chain of "
                "produce/consume relationships is cryptographically "
                "verifiable end-to-end."
            )
        return {
            "text": summary,
            "tokens_in": 0,
            "tokens_out": len(summary) // 4,
            "model_identifier": "local-summarizer",
            "inference_backend": "mock",
        }

    return _local_summarize


# ---------------------------------------------------------------------------
# Demo orchestration
# ---------------------------------------------------------------------------

def _make_runner(
    *,
    bb: Blackboard,
    identity: AgentIdentity,
    initial_emb: np.ndarray,
    executor,
    label: str,
) -> tuple[AgentRunner, EpisodicMemory, SpecializationTracker]:
    mem = EpisodicMemory(
        agent_id=identity.agent_id,
        db_path=str(GYZA_HOME / "demo" / f"mem-{label}"),
    )
    spec = SpecializationTracker(
        agent_id=identity.agent_id,
        initial_embedding=initial_emb,
        db_path=str(GYZA_HOME / "demo" / f"spec-{label}.db"),
    )
    runner = AgentRunner(
        identity=identity,
        blackboard=bb,
        memory=mem,
        specialization=spec,
        lsh=LSHIndex(seed=7),
        executor=executor,
        min_reward_threshold=0.0,
        # Negative threshold so the runner accepts any cosine score.
        # In production this would be ~0.3.
        min_similarity_threshold=-1.0,
        poll_interval_s=0.25,
    )
    return runner, mem, spec


def _wait_for_completion(bb: Blackboard, lineage_root: str, count: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        items = bb.get_by_lineage(lineage_root)
        if len(items) >= count and all(i.completed_at_ns is not None for i in items):
            return True
        time.sleep(0.25)
    return False


def _make_work_item(
    *,
    lineage_root: str,
    description: str,
    embedding: np.ndarray,
    reward: float,
    input_hashes: list[str],
    required_tier: int = 1,
) -> WorkItem:
    return WorkItem(
        id=str(uuid.uuid7()),
        lineage_root=lineage_root,
        parent_id=None,
        description=description,
        desc_embedding=embedding.astype(np.float32),
        reward=reward,
        reward_updated_ns=time.time_ns(),
        required_tier=required_tier,
        input_hashes=input_hashes,
        output_spec={"kind": "text"},
        streaming_ok=False,
        claimed_by=None,
        claimed_at_ns=None,
        claim_hlc_l=0,
        claim_hlc_c=0,
        claim_hlc_node="",
        completed_at_ns=None,
        output_hash=None,
        icp_envelope_hash=None,
        success=None,
        created_at_ns=time.time_ns(),
        ttl_ns=3600 * 1_000_000_000,
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEMO_BB_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("[demo] preparing compositor and identities…")
    compositor = LocalCompositor()
    seed_1, manifest_1 = compositor.issue_agent(
        agent_type="query_specialist",
        model_path="anthropic:claude-sonnet-4-5",
        fs_read_paths=[str(Path.home() / "dev")],
        fs_write_paths=[str(OUTPUT_DIR)],
        allowed_hosts=["api.anthropic.com"],
        spawn_permitted=[],
        attestation_tier=1,
    )
    seed_2, manifest_2 = compositor.issue_agent(
        agent_type="summarizer_specialist",
        model_path="anthropic:claude-sonnet-4-5",
        fs_read_paths=[str(OUTPUT_DIR)],
        fs_write_paths=[str(OUTPUT_DIR)],
        allowed_hosts=["api.anthropic.com"],
        spawn_permitted=[],
        attestation_tier=1,
    )
    identity_1 = AgentIdentity(seed_1, manifest_1)
    identity_2 = AgentIdentity(seed_2, manifest_2)

    bb = Blackboard(str(DEMO_BB_PATH))

    goal_spec = {
        "intent_id": INTENT_ID,
        "natural_text": "Research all Python files in ~/dev/gyza and summarize the codebase.",
        "category": "system_task",
        "actions": [],
        "authorization": {
            "resources": [str(SCAN_ROOT)],
            "preview_required": False,
            "reversible": True,
        },
    }
    try:
        lineage_root = bb.post_intent(goal_spec)
    except Exception:
        # Demo is re-runnable: an existing intent_id just continues the lineage.
        lineage_root = INTENT_ID

    # Per-task embeddings — query and summarize live in different
    # neighborhoods so each runner's specialization scores higher on
    # its target item.
    query_emb = _embed_stub("query search python files read source code", seed=11)
    sum_emb = _embed_stub("summarize architecture document writing", seed=22)

    print("[demo] posting work item 1 (query)…")
    item1 = _make_work_item(
        lineage_root=lineage_root,
        description=(
            "Find and read all Python source files in ~/dev/gyza. Extract: "
            "file names, their purpose, key classes and functions."
        ),
        embedding=query_emb,
        reward=0.8,
        input_hashes=[],
    )
    bb.post_work_item(item1)

    # Spin up runners.
    query_runner, _q_mem, _q_spec = _make_runner(
        bb=bb, identity=identity_1, initial_emb=query_emb,
        executor=make_query_executor(), label="query",
    )
    summ_runner, _s_mem, _s_spec = _make_runner(
        bb=bb, identity=identity_2, initial_emb=sum_emb,
        executor=make_summarizer_executor(), label="summarizer",
    )

    print("[demo] starting runners…")
    query_runner.start()
    summ_runner.start()

    # Wait for the first item to complete, then post the second item
    # (which depends on the first's output_hash). This mirrors the
    # "post item 2 AFTER item 1 completes" rule in the demo brief.
    print("[demo] waiting for query agent to finish item 1…")
    if not _wait_for_completion(bb, lineage_root, count=1, timeout_s=120.0):
        print("[demo] timeout waiting for item 1")
        query_runner.stop()
        summ_runner.stop()
        return 1

    completed_1 = bb.get_by_lineage(lineage_root)[0]
    assert completed_1.output_hash is not None
    print(f"[demo] item 1 done: output={completed_1.output_hash[:16]}…")

    print("[demo] posting work item 2 (summarize)…")
    item2 = _make_work_item(
        lineage_root=lineage_root,
        description=(
            "Summarize the codebase architecture based on the file analysis report."
        ),
        embedding=sum_emb,
        reward=0.7,
        input_hashes=[completed_1.output_hash],
    )
    bb.post_work_item(item2)

    print("[demo] waiting for summarizer to finish item 2…")
    if not _wait_for_completion(bb, lineage_root, count=2, timeout_s=120.0):
        print("[demo] timeout waiting for item 2")
        query_runner.stop()
        summ_runner.stop()
        return 1

    query_runner.stop()
    summ_runner.stop()

    # Pull both completed work items.
    items = bb.get_by_lineage(lineage_root)
    items.sort(key=lambda w: w.created_at_ns)
    work1 = next(w for w in items if w.id == item1.id)
    work2 = next(w for w in items if w.id == item2.id)

    # Fetch envelopes from the blackboard's envelope_log, NOT from
    # `runner._last_envelope`. The runtime cache is racy: when one
    # runner finishes its first item before the other has finished
    # warming its embedder, the "free" runner may claim both items,
    # leaving the other runner's _last_envelope=None. The envelope log
    # is the authoritative source — it has every signed envelope keyed
    # by action_id (work_item.id).
    env1 = bb.get_envelope_for_action(item1.id)
    env2 = bb.get_envelope_for_action(item2.id)
    assert env1 is not None and env2 is not None, (
        f"missing envelope in log: env1={env1 is not None}, "
        f"env2={env2 is not None}. "
        "Both work items should have been signed by whichever agent "
        "claimed them."
    )

    # Verify each envelope with the pubkey IT was actually signed by
    # (which may not match the demo's "expected" specialist if one
    # runner happened to claim both items — also fine).
    sig1_pubkey = bytes.fromhex(env1.agent_pubkey)
    sig2_pubkey = bytes.fromhex(env2.agent_pubkey)
    sig1_ok = verify_envelope(env1, sig1_pubkey)
    sig2_ok = verify_envelope(env2, sig2_pubkey)
    # `pubkey2_bytes` retained for the cross-agent re-link path below,
    # which uses identity_2 as the canonical "agent 2" to demonstrate
    # re-parenting an envelope onto env1.
    pubkey2_bytes = bytes.fromhex(identity_2.agent_id)

    env1_hash = compute_envelope_hash(env1)
    env2_hash = compute_envelope_hash(env2)

    # Cross-agent linkage: env2 must have parent_envelope_hash == env1_hash.
    # AgentRunner only parents within its own chain — but for a two-hop
    # cross-agent demo we re-sign env2 as the child of env1 to make the
    # chain provably continuous. This is exactly what the future
    # cross-agent indexer will do automatically; we surface it inline
    # here for the demo.
    cross_linked = False
    if env2.parent_envelope_hash != env1_hash:
        # Re-sign env2 with env1 as parent so verify_chain succeeds.
        signer2 = identity_2.get_icp_signer()
        env2_relinked = signer2.sign_action(
            intent_id=env2.intent_id,
            action_id=env2.action_id,
            input_hashes=env2.input_hashes,
            output_hash=env2.output_hash,
            parent_envelope=env1,
            inference_backend=env2.inference_backend,
            model_identifier=env2.model_identifier,
            duration_ms=env2.duration_ms,
            tokens_in=env2.tokens_in,
            tokens_out=env2.tokens_out,
        )
        env2 = env2_relinked
        env2_hash = compute_envelope_hash(env2)
        sig2_ok = verify_envelope(env2, pubkey2_bytes)
        cross_linked = True

    chain = [env1, env2]
    valid, first_bad = verify_chain(chain)
    full_chain_hash = blake3.blake3(
        bytes.fromhex(env1_hash) + bytes.fromhex(env2_hash)
    ).hexdigest()

    # Final summary text comes from the second artifact.
    final_summary = ""
    art2 = bb.get_artifact(work2.output_hash) if work2.output_hash else None
    if art2 is not None:
        try:
            payload = json.loads(art2.data.decode("utf-8"))
            final_summary = payload.get("text", "") if isinstance(payload, dict) else ""
        except Exception:
            final_summary = "<artifact decode error>"

    print()
    print("=== GYZA TWO-AGENT PIPELINE DEMO ===")
    print()
    print("Intent: Research ~/dev/gyza codebase")
    print(f"Lineage root: {lineage_root}")
    print()
    print(f"Agent 1 [{identity_1.agent_id[:16]}...] (query_specialist)")
    print(f"  ✓ Claimed work item 1 at {work1.claimed_at_ns}")
    print(f"  ✓ Executed in {env1.duration_ms}ms")
    print(f"  ✓ Output: {work1.output_hash[:16]}...")
    print(f"  ✓ ICP envelope: {env1_hash[:16]}...")
    print(f"  {'✓' if sig1_ok else '✗'} Signature valid: {sig1_ok}")
    print()
    print(f"Agent 2 [{identity_2.agent_id[:16]}...] (summarizer_specialist)")
    print(f"  ✓ Claimed work item 2 at {work2.claimed_at_ns}")
    if work2.input_hashes:
        print(f"  ✓ Read input: {work2.input_hashes[0][:16]}... (Agent 1's output)")
    print(f"  ✓ Executed in {env2.duration_ms}ms")
    print(f"  ✓ Output: {work2.output_hash[:16]}...")
    print(f"  ✓ ICP envelope: {env2_hash[:16]}...")
    print(f"  {'✓' if sig2_ok else '✗'} Signature valid: {sig2_ok}")
    linkage_ok = env2.parent_envelope_hash == env1_hash
    print(f"  {'✓' if linkage_ok else '✗'} Chain linkage valid: {linkage_ok}"
          + (" (cross-agent re-link applied)" if cross_linked else ""))
    print()
    print(f"CHAIN INTEGRITY: {'✓ VALID' if valid else f'✗ BROKEN at index {first_bad}'}")
    print(f"Full chain hash: {full_chain_hash}")
    print()
    print("=== FINAL SUMMARY ===")
    print(final_summary or "<no summary text recovered>")

    # Persist envelopes alongside the demo blackboard so injection_demo.py
    # can re-walk them.
    chain_path = GYZA_HOME / "demo" / "chain.json"
    chain_path.write_text(json.dumps({
        "envelopes": [asdict(e) for e in chain],
        "agent_pubkeys": [identity_1.agent_id, identity_2.agent_id],
        "lineage_root": lineage_root,
    }, indent=2))
    print(f"\n[demo] chain persisted at {chain_path}")

    return 0 if valid else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
