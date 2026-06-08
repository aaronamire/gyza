"""
Tests for verify_dag — the multi-parent generalization of verify_chain.

Covers the four structural cases the linear verifier cannot express or
validate as a unit: fan-out, fan-in (diamond), the partition fork, and
a data-dependency cycle (reachable with perfectly valid signatures, so
the acyclicity guard is load-bearing). Plus determinism of the topo
order, and closed-DAG tamper/loss detection.
"""
from __future__ import annotations

import random

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.icp import (
    ICPEnvelope,
    compute_envelope_hash,
    sign_envelope,
    verify_chain,
    verify_dag,
)


def _seed(tag: int) -> bytes:
    return bytes([tag % 251 + 1]) * 32


def _pk(seed: bytes) -> str:
    return Ed25519PrivateKey.from_private_bytes(seed).public_key()\
        .public_bytes_raw().hex()


def _env(tag, *, action, inputs, output, parent):
    seed = _seed(tag)
    env = ICPEnvelope(
        intent_id="i", action_id=action, agent_pubkey=_pk(seed),
        capability_manifest_hash="00" * 32, input_hashes=list(inputs),
        output_hash=output, parent_envelope_hash=parent,
        timestamp_ns=0, inference_backend="mock", model_identifier="mock",
        duration_ms=0, tokens_in=0, tokens_out=0,
    )
    return sign_envelope(env, seed)


def test_linear_chain_is_a_valid_dag_one_root_one_leaf():
    a = _env(1, action="a", inputs=["00" * 32], output="0a" * 32, parent=None)
    b = _env(1, action="b", inputs=["0a" * 32], output="0b" * 32,
             parent=compute_envelope_hash(a))
    res = verify_dag([a, b], require_closed=True)
    assert res.valid, res.reason
    assert len(res.roots) == 1 and len(res.leaves) == 1
    assert res.roots[0] == compute_envelope_hash(a)
    assert res.leaves[0] == compute_envelope_hash(b)


def test_fan_out_one_root_two_leaves():
    root = _env(1, action="root", inputs=["00" * 32], output="0a" * 32,
                parent=None)
    rh = compute_envelope_hash(root)
    c1 = _env(2, action="c1", inputs=["0a" * 32], output="c1" * 32, parent=rh)
    c2 = _env(3, action="c2", inputs=["0a" * 32], output="c2" * 32, parent=rh)
    res = verify_dag([root, c1, c2], require_closed=True)
    assert res.valid, res.reason
    assert res.roots == [rh]
    assert set(res.leaves) == {compute_envelope_hash(c1),
                               compute_envelope_hash(c2)}


def test_diamond_fan_in_via_input_hashes():
    # root -> {left, right} -> sink (sink consumes BOTH outputs).
    root = _env(1, action="root", inputs=["00" * 32], output="0a" * 32,
                parent=None)
    rh = compute_envelope_hash(root)
    left = _env(2, action="left", inputs=["0a" * 32], output="1b" * 32,
                parent=rh)
    right = _env(3, action="right", inputs=["0a" * 32], output="2c" * 32,
                 parent=rh)
    sink = _env(2, action="sink", inputs=["1b" * 32, "2c" * 32],
                output="3d" * 32, parent=compute_envelope_hash(left))
    res = verify_dag([root, left, right, sink], require_closed=True)
    assert res.valid, res.reason
    assert res.roots == [rh]
    # fan-in: 'right' is consumed by the sink via a data edge, so the
    # ONLY leaf is the sink — something verify_chain could never see.
    assert res.leaves == [compute_envelope_hash(sink)]
    # topo order respects all edges: root first, sink last.
    order = [e.action_id for e in res.topo_order]
    assert order[0] == "root" and order[-1] == "sink"


def test_topo_order_is_input_order_independent():
    root = _env(1, action="root", inputs=["00" * 32], output="0a" * 32,
                parent=None)
    rh = compute_envelope_hash(root)
    a = _env(2, action="a", inputs=["0a" * 32], output="1b" * 32, parent=rh)
    b = _env(3, action="b", inputs=["0a" * 32], output="2c" * 32, parent=rh)
    sink = _env(2, action="sink", inputs=["1b" * 32, "2c" * 32],
                output="3d" * 32, parent=compute_envelope_hash(a))
    envs = [root, a, b, sink]
    canonical = None
    for seed in range(10):
        shuffled = list(envs)
        random.Random(seed).shuffle(shuffled)
        order = [compute_envelope_hash(e)
                 for e in verify_dag(shuffled).topo_order]
        canonical = canonical or order
        assert order == canonical


def test_data_dependency_cycle_rejected():
    # Two validly-signed envelopes that each consume the other's output:
    # A.output = X, A.input = [Y]; B.output = Y, B.input = [X].
    a = _env(1, action="a", inputs=["59" * 32], output="58" * 32, parent=None)
    b = _env(2, action="b", inputs=["58" * 32], output="59" * 32, parent=None)
    res = verify_dag([a, b])
    assert not res.valid
    assert "cycle" in res.reason


def test_closed_dag_detects_missing_predecessor():
    a = _env(1, action="a", inputs=["00" * 32], output="0a" * 32, parent=None)
    b = _env(1, action="b", inputs=["0a" * 32], output="0b" * 32,
             parent=compute_envelope_hash(a))
    # Drop the predecessor: closed verification must fail.
    res = verify_dag([b], require_closed=True)
    assert not res.valid
    assert "not held" in res.reason or "not closed" in res.reason
    # Lenient mode tolerates it (partial replica) and treats b as a root.
    lenient = verify_dag([b], require_closed=False)
    assert lenient.valid
    assert lenient.roots == [compute_envelope_hash(b)]


def test_tamper_breaks_signature():
    a = _env(1, action="a", inputs=["00" * 32], output="0a" * 32, parent=None)
    a.output_hash = "ff" * 32  # mutate after signing
    res = verify_dag([a])
    assert not res.valid
    assert "signature" in res.reason


def test_dag_agrees_with_verify_chain_on_linear_history():
    a = _env(1, action="a", inputs=["00" * 32], output="0a" * 32, parent=None)
    b = _env(1, action="b", inputs=["0a" * 32], output="0b" * 32,
             parent=compute_envelope_hash(a))
    c = _env(1, action="c", inputs=["0b" * 32], output="0c" * 32,
             parent=compute_envelope_hash(b))
    chain = [a, b, c]
    ok, _ = verify_chain(chain)
    assert ok
    res = verify_dag(chain, require_closed=True)
    assert res.valid
    # Same linear order both ways.
    assert [compute_envelope_hash(e) for e in res.topo_order] == \
           [compute_envelope_hash(e) for e in chain]
