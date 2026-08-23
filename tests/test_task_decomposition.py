"""Agents create work for each other, and the decomposition is SIGNED.

Until 2026-08-23 nothing in `gyza/` ever wrote a non-None `parent_id`. The
work-DAG edge was schema'd, indexed, gossiped, carried in protobuf and
deserialized, and no producer existed -- so agents could not coordinate, only
drain a queue a human had filled.

Decomposition is deliberately NOT a new envelope type. The child ids are folded
into the output artifact, so the parent's existing `output_hash` commits to
them: who split this task, under which manifest, into exactly which children,
is signed and offline-verifiable.
"""
from __future__ import annotations

import json
import time
import uuid

import numpy as np
import pytest

from gyza.blackboard import Blackboard
from gyza.identity import AgentIdentity, LocalCompositor
from gyza.runner import MAX_TASK_DEPTH
from gyza.schema import EMBEDDING_DIM, HLC, WorkItem


def _agent(tmp_path, *, max_children=4, permitted=("worker",), name="d"):
    comp = LocalCompositor(key_path=str(tmp_path / f"{name}.key"))
    seed, manifest = comp.issue_agent(
        agent_type="decomp.worker", model_path="mock", fs_read_paths=[],
        fs_write_paths=[], allowed_hosts=[], memory_limit_mb=512,
        attestation_tier=0, spawn_permitted=list(permitted),
        max_children=max_children)
    return AgentIdentity(seed, manifest)


def _runner(tmp_path, ident, bb, executor, name="d"):
    from gyza.demand import LSHIndex
    from gyza.drift import SpecializationTracker
    from gyza.memory import EpisodicMemory
    from gyza.network.artifact_store import ArtifactStore
    from gyza.runner import AgentRunner

    # ONE store per blackboard, as production has. Attaching a fresh store per
    # runner orphaned every artifact the previous runner wrote, which made the
    # governed-claim tests fail for a harness reason that looked exactly like
    # "the claim was never emitted".
    bb.attach_artifact_store(ArtifactStore(base_path=str(tmp_path / "cas")))
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32); v[0] = 1.0
    return AgentRunner(
        identity=ident, blackboard=bb,
        memory=EpisodicMemory(agent_id=ident.agent_id,
                              db_path=str(tmp_path / f"{name}mem")),
        specialization=SpecializationTracker(
            agent_id=ident.agent_id, initial_embedding=v,
            db_path=str(tmp_path / f"{name}spec.db")),
        lsh=LSHIndex(seed=42), executor=executor,
        min_reward_threshold=0.0, min_similarity_threshold=-1.0,
        verify_chain_before_claim=False)


def _intent(bb, iid="dec"):
    try:
        bb.post_intent({"intent_id": iid, "natural_text": "d",
                        "category": "system_task", "actions": [],
                        "authorization": {"resources": [],
                                          "preview_required": False,
                                          "reversible": True}})
    except Exception:
        pass


def _item(bb, *, parent=None, iid="dec", claim_for=None, spec=None, tier=0):
    _intent(bb, iid)
    e = np.zeros(EMBEDDING_DIM, dtype=np.float32); e[0] = 1.0
    w = WorkItem(
        id=str(uuid.uuid7()), lineage_root=iid, parent_id=parent,
        description="task", desc_embedding=e, reward=0.9,
        reward_updated_ns=time.time_ns(), required_tier=tier, input_hashes=[],
        output_spec=spec or {"kind": "test"}, streaming_ok=False,
        claimed_by=None, claimed_at_ns=None, claim_hlc_l=0, claim_hlc_c=0,
        claim_hlc_node="", completed_at_ns=None, output_hash=None,
        icp_envelope_hash=None, success=None, created_at_ns=time.time_ns(),
        ttl_ns=3600 * 10**9)
    bb.post_work_item(w)
    if claim_for:
        assert bb.try_claim(w.id, claim_for, HLC(node_id="t"), claimant_tier=tier)
    return w


def _splitter(n, **extra):
    def _e(_p, _c):
        return {"text": "decomposed",
                "__subtasks__": [{"description": f"part {i}", **extra}
                                 for i in range(n)]}
    return _e


# --------------------------------------------------------------------------- #
#  THE CAPABILITY THAT DID NOT EXIST                                            #
# --------------------------------------------------------------------------- #
def test_an_agent_creates_work_with_parent_id_set(tmp_path):
    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path)
    r = _runner(tmp_path, ident, bb, _splitter(3))
    root = _item(bb, claim_for=ident.agent_id)

    r._complete(root, r._execute(root), success=True)

    kids = bb.children_of(root.id)
    assert len(kids) == 3, "no child work items were created"
    assert all(k.parent_id == root.id for k in kids)
    assert all(k.lineage_root == root.lineage_root for k in kids)


def test_the_decomposition_is_COMMITTED_in_the_signed_envelope(tmp_path):
    """The point of doing it this way. A third party can verify which children
    a task was split into, without trusting the splitter."""
    import blake3

    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path)
    r = _runner(tmp_path, ident, bb, _splitter(2))
    root = _item(bb, claim_for=ident.agent_id)
    r._complete(root, r._execute(root), success=True)

    row = bb._conn().execute(
        "SELECT output_hash, icp_envelope_hash FROM work_items WHERE id=?",
        (root.id,)).fetchone()
    assert row["icp_envelope_hash"] is not None, "the parent never signed"

    blob = bb._artifact_store.get(row["output_hash"])
    assert blake3.blake3(blob).hexdigest() == row["output_hash"]
    body = json.loads(blob)
    assert "__subtasks__" in body
    assert sorted(body["__subtasks__"]) == sorted(
        k.id for k in bb.children_of(root.id))


def test_another_agent_can_claim_and_execute_the_children(tmp_path):
    """Coordination, minimally: agent A's decision becomes agent B's work."""
    bb = Blackboard(str(tmp_path / "b.db"))
    a = _agent(tmp_path, name="a")
    ra = _runner(tmp_path, a, bb, _splitter(3), name="a")
    root = _item(bb, claim_for=a.agent_id)
    ra._complete(root, ra._execute(root), success=True)

    b = _agent(tmp_path, name="b")
    rb = _runner(tmp_path, b, bb, lambda p, c: {"text": "did it"}, name="b")
    done = 0
    for w in bb.get_unclaimed(min_reward=0.0, tier=0):
        if bb.try_claim(w.id, b.agent_id, HLC(node_id="b"), claimant_tier=0):
            rb._complete(w, rb._execute(w), success=True)
            done += 1
    assert done == 3, f"agent B executed {done} of A's 3 subtasks"


# --------------------------------------------------------------------------- #
#  BOUNDED BY THE SIGNED MANIFEST                                               #
# --------------------------------------------------------------------------- #
def test_fanout_beyond_max_children_is_REFUSED(tmp_path):
    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path, max_children=2)
    r = _runner(tmp_path, ident, bb, _splitter(5))
    root = _item(bb, claim_for=ident.agent_id)
    with pytest.raises(RuntimeError, match="caps children at 2"):
        r._execute(root)
    assert bb.children_of(root.id) == []


def test_an_agent_with_NO_spawn_authority_is_REFUSED(tmp_path):
    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path, permitted=(), max_children=0)
    r = _runner(tmp_path, ident, bb, _splitter(2))
    root = _item(bb, claim_for=ident.agent_id)
    with pytest.raises(RuntimeError, match="no spawn authority"):
        r._execute(root)


def test_a_refused_decomposition_produces_NO_envelope(tmp_path):
    """The refusal reaches the same place a bounds violation does."""
    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path, max_children=1)
    r = _runner(tmp_path, ident, bb, _splitter(4))
    root = _item(bb, claim_for=ident.agent_id)
    with pytest.raises(RuntimeError):
        r._complete(root, r._execute(root), success=True)
    row = bb._conn().execute(
        "SELECT icp_envelope_hash FROM work_items WHERE id=?",
        (root.id,)).fetchone()
    assert row["icp_envelope_hash"] is None


def test_depth_is_capped(tmp_path):
    """DEPTH_CAP_REACHED -- an explicit reason, never a timeout."""
    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path)
    r = _runner(tmp_path, ident, bb, _splitter(1))
    cur = _item(bb, claim_for=ident.agent_id)
    for _ in range(MAX_TASK_DEPTH):
        r._complete(cur, r._execute(cur), success=True)
        kid = bb.children_of(cur.id)[0]
        assert bb.try_claim(kid.id, ident.agent_id, HLC(node_id="t"),
                            claimant_tier=0)
        cur = kid
    with pytest.raises(RuntimeError, match="DEPTH_CAP_REACHED"):
        r._execute(cur)


def test_a_child_may_not_require_a_HIGHER_tier_than_its_parent(tmp_path):
    """Otherwise a low-tier decomposer mints work only better-attested agents
    may take -- manufacturing demand for authority it does not hold."""
    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path)
    r = _runner(tmp_path, ident, bb, _splitter(1, required_tier=3))
    root = _item(bb, claim_for=ident.agent_id, tier=0)
    r._complete(root, r._execute(root), success=True)
    assert bb.children_of(root.id)[0].required_tier == 0


# --------------------------------------------------------------------------- #
#  THE DEPENDENCY GATE                                                          #
# --------------------------------------------------------------------------- #
def test_a_combiner_is_not_served_until_its_siblings_finish(tmp_path):
    bb = Blackboard(str(tmp_path / "b.db"))
    root = _item(bb)
    leaf = _item(bb, parent=root.id)
    comb = _item(bb, parent=root.id,
                 spec={"kind": Blackboard.COMBINE_KIND, "of": root.id})

    served = {w.id for w in bb.get_unclaimed(min_reward=0.0, tier=0)}
    assert leaf.id in served
    assert comb.id not in served, "combiner served with work outstanding"
    assert bb.pending_siblings(comb) == [leaf.id]

    bb.try_claim(leaf.id, "x", HLC(node_id="t"), claimant_tier=0)
    bb.complete_work_item(leaf.id, "aa" * 32, "bb" * 32, True,
                          HLC(node_id="t"), expected_owner="x")
    assert comb.id in {w.id for w in bb.get_unclaimed(min_reward=0.0, tier=0)}
    assert bb.pending_siblings(comb) == []


def test_lineage_depth_survives_a_cycle(tmp_path):
    """`parent_id` is written by agents now, so a malformed graph must not
    hang the walk."""
    bb = Blackboard(str(tmp_path / "b.db"))
    a = _item(bb)
    b = _item(bb, parent=a.id)
    bb._conn().execute("UPDATE work_items SET parent_id=? WHERE id=?",
                       (b.id, a.id))
    assert bb.lineage_depth(b.id) < 64


# --------------------------------------------------------------------------- #
#  THE FULL LOOP: decompose -> execute in parallel -> COMBINE -> audit          #
# --------------------------------------------------------------------------- #
def _plan(n):
    """An executor that splits into n subtasks plus a combiner."""
    def _e(_p, _c):
        subs = [{"description": f"part {i}"} for i in range(n)]
        subs.append({"description": "combine",
                     "output_spec": {"kind": Blackboard.COMBINE_KIND}})
        return {"text": "planned", "__subtasks__": subs}
    return _e


def test_the_whole_loop_decompose_execute_combine(tmp_path):
    bb = Blackboard(str(tmp_path / "b.db"))
    planner = _agent(tmp_path, max_children=4, name="p")
    rp = _runner(tmp_path, planner, bb, _plan(2), name="p")
    root = _item(bb, claim_for=planner.agent_id)
    rp._complete(root, rp._execute(root), success=True)

    kids = bb.children_of(root.id)
    assert len(kids) == 3
    comb = [k for k in kids
            if k.output_spec.get("kind") == Blackboard.COMBINE_KIND][0]
    assert comb.output_spec["of"] == root.id, "the runner must set `of`"

    # The combiner is NOT servable while leaves are outstanding.
    assert comb.id not in {w.id for w in bb.get_unclaimed(0.0, 0)}

    # Two workers drain the leaves.
    w1 = _agent(tmp_path, name="w")
    rw = _runner(tmp_path, w1, bb, lambda p, c: {"text": "leaf done"}, name="w")
    for k in kids:
        if k.id == comb.id:
            continue
        assert bb.try_claim(k.id, w1.agent_id, HLC(node_id="w"), claimant_tier=0)
        rw._complete(k, rw._execute(k), success=True)

    # Now it IS servable.
    assert comb.id in {w.id for w in bb.get_unclaimed(0.0, 0)}

    seen = {}
    def _combine(_prompt, ctx):
        seen["inputs"] = [a.hash for a in ctx["inputs"]]
        return {"text": "combined " + str(len(ctx["inputs"]))}

    rc = _runner(tmp_path, w1, bb, _combine, name="w")
    assert bb.try_claim(comb.id, w1.agent_id, HLC(node_id="w"), claimant_tier=0)
    rc._complete(comb, rc._execute(comb), success=True)

    # The combiner SAW both child outputs...
    leaf_hashes = {bb.get_work_item(k.id).output_hash
                   for k in kids if k.id != comb.id}
    assert set(seen["inputs"]) == leaf_hashes

    # ...and its ENVELOPE COMMITS to exactly those child outputs.
    env_hash = bb.get_work_item(comb.id).icp_envelope_hash
    assert env_hash is not None
    env = bb.get_envelope(env_hash)
    assert set(env.input_hashes) >= leaf_hashes, (
        "the combine envelope does not commit to the children it consumed")


def test_a_combiner_reached_OUTSIDE_the_poll_path_still_refuses(tmp_path):
    """The gate protects polling. An item reached by gossip, a direct id or a
    reclaim has not passed through it, so the check is repeated at execute."""
    bb = Blackboard(str(tmp_path / "b.db"))
    planner = _agent(tmp_path, max_children=4, name="p")
    rp = _runner(tmp_path, planner, bb, _plan(2), name="p")
    root = _item(bb, claim_for=planner.agent_id)
    rp._complete(root, rp._execute(root), success=True)
    comb = [k for k in bb.children_of(root.id)
            if k.output_spec.get("kind") == Blackboard.COMBINE_KIND][0]

    # Bypass get_unclaimed entirely, as gossip or a direct id would.
    assert bb.try_claim(comb.id, planner.agent_id, HLC(node_id="p"),
                        claimant_tier=0)
    with pytest.raises(RuntimeError, match="have not completed"):
        rp._execute(comb)


# --------------------------------------------------------------------------- #
#  THE DECOMPOSITION IS GOVERNED, not merely signed                             #
# --------------------------------------------------------------------------- #
def _audit_decomposed(tmp_path, n=2, tamper=None):
    import json as _json

    from gyza.audit import audit_provenance
    from gyza.identity import manifest_canonical_bytes

    bb = Blackboard(str(tmp_path / "b.db"))
    planner = _agent(tmp_path, max_children=4, name="p")
    rp = _runner(tmp_path, planner, bb, _plan(n), name="p")
    root = _item(bb, claim_for=planner.agent_id)
    rp._complete(root, rp._execute(root), success=True)

    kids = bb.children_of(root.id)
    comb = [k for k in kids
            if k.output_spec.get("kind") == Blackboard.COMBINE_KIND][0]
    w = _agent(tmp_path, name="w")
    rw = _runner(tmp_path, w, bb, lambda p, c: {"text": "leaf"}, name="w")
    for k in kids:
        if k.id == comb.id:
            continue
        bb.try_claim(k.id, w.agent_id, HLC(node_id="w"), claimant_tier=0)
        rw._complete(k, rw._execute(k), success=True)
    rc = _runner(tmp_path, w, bb, lambda p, c: {"text": "combined"}, name="w")
    bb.try_claim(comb.id, w.agent_id, HLC(node_id="w"), claimant_tier=0)
    rc._complete(comb, rc._execute(comb), success=True)

    store = bb._artifact_store
    for m in (planner.manifest, w.manifest):
        store.store(manifest_canonical_bytes(m))
    envs = bb.reconstruct_dag(root.lineage_root)
    if tamper:
        envs = tamper(envs, root, comb)
    return audit_provenance(
        envs, resolve_artifact=lambda h: store.get(h),
        resolve_manifest=lambda h: (_json.loads(store.get(h))
                                    if store.get(h) else None),
        require_closed=False, require_all_artifacts=False, governed=True)


def test_a_decomposition_emits_GOVERNED_coordination_claims(tmp_path):
    rep = _audit_decomposed(tmp_path)
    assert rep.governance is not None
    types = {c.claim_type for c in rep.governance.verdicts}
    assert "decomposition_within_manifest" in types
    assert "combine_covers_siblings" in types
    bad = [c for c in rep.governance.verdicts
           if c.claim_type in ("decomposition_within_manifest",
                               "combine_covers_siblings")
           and c.status != "VERIFIED"]
    assert not bad, [(c.claim_type, c.status, c.detail) for c in bad]


def test_an_action_that_did_NOT_decompose_emits_nothing(tmp_path):
    """Negative control. A claim that is trivially true on every input
    measures nothing and would inflate the governed count with checks that
    never had a chance to fail."""
    from gyza.audit import audit_provenance
    import json as _json
    from gyza.identity import manifest_canonical_bytes

    bb = Blackboard(str(tmp_path / "b.db"))
    ident = _agent(tmp_path)
    r = _runner(tmp_path, ident, bb, lambda p, c: {"text": "plain"})
    w = _item(bb, claim_for=ident.agent_id)
    r._complete(w, r._execute(w), success=True)
    store = bb._artifact_store
    store.store(manifest_canonical_bytes(ident.manifest))
    rep = audit_provenance(
        bb.reconstruct_dag(w.lineage_root),
        resolve_artifact=lambda h: store.get(h),
        resolve_manifest=lambda h: (_json.loads(store.get(h))
                                    if store.get(h) else None),
        require_closed=False, require_all_artifacts=False, governed=True)
    types = {c.claim_type for c in rep.governance.verdicts}
    assert "decomposition_within_manifest" not in types
    assert "combine_covers_siblings" not in types


def test_a_DROPPED_sibling_is_caught_by_combine_covers_siblings(tmp_path):
    """The check earns its place: remove one child's envelope and the
    combination is no longer covered."""
    def _drop(envs, root, comb):
        drop = {k for k in {e.action_id for e in envs}
                if k not in (root.id, comb.id)}
        victim = sorted(drop)[0]
        return [e for e in envs if e.action_id != victim]

    rep = _audit_decomposed(tmp_path, n=2, tamper=_drop)
    ccs = [c for c in rep.governance.verdicts
           if c.claim_type == "combine_covers_siblings"]
    assert ccs, "the claim was not emitted"
    assert all(c.status == "REFUTED" for c in ccs), [c.status for c in ccs]
