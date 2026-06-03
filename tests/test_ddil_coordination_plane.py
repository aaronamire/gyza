"""
CRDT laws and deterministic-reconstruction tests for the DDIL
coordination plane.

The three merge laws asserted here — idempotence, commutativity,
associativity — are not incidental: they are the *definition* of a
join-semilattice, and Strong Eventual Consistency holds for this CRDT
precisely because ``merge`` satisfies them. If any one fails, the
"both sides converge after heal" claim of the whole demo is false.

Two layers, by design:

  * a dependency-free deterministic floor (``random`` + many fixed
    seeds) that ALWAYS runs, so the laws are never silently unguarded;
  * a Hypothesis layer (skipped if Hypothesis isn't installed) for
    stronger search and minimal-counterexample shrinking.
"""
from __future__ import annotations

import random

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gyza.demo.coordination_plane import CoordinationState
from gyza.icp import ICPSigner, compute_envelope_hash, verify_chain


# ----------------------------------------------------------------------
# Envelope builders
# ----------------------------------------------------------------------

def _signer(tag: int) -> ICPSigner:
    seed = bytes([tag % 251 + 1]) * 32
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key().public_bytes_raw().hex()
    return ICPSigner(seed, pk, "00" * 32)


def _mk_root(i: int):
    """A standalone signed envelope (parent=None) with a unique action."""
    return _signer(i).sign_action(
        intent_id="intent",
        action_id=f"action-{i}",
        input_hashes=["00" * 32],
        output_hash=f"{i:064x}",
        parent_envelope=None,
        inference_backend="mock",
        model_identifier="mock",
        duration_ms=0,
        tokens_in=0,
        tokens_out=0,
    )


def _mk_chain(prefix: str, n: int):
    """A linear signed chain of length ``n`` rooted at parent=None."""
    s = _signer(hash(prefix) & 0xFF)
    chain = []
    parent = None
    for k in range(n):
        env = s.sign_action(
            intent_id="intent",
            action_id=f"{prefix}-{k}",
            input_hashes=["00" * 32] if parent is None
            else [compute_envelope_hash(parent)],
            output_hash=f"{k:064x}",
            parent_envelope=parent,
            inference_backend="mock",
            model_identifier="mock",
            duration_ms=0,
            tokens_in=0,
            tokens_out=0,
        )
        chain.append(env)
        parent = env
    return chain


def _state_from(envs) -> CoordinationState:
    s = CoordinationState()
    s.add_all(list(envs))
    return s


# ----------------------------------------------------------------------
# Deterministic floor — always runs, no third-party dependency.
# ----------------------------------------------------------------------

_POOL = [_mk_root(i) for i in range(40)]


def _random_state(rng: random.Random) -> CoordinationState:
    k = rng.randint(0, len(_POOL))
    return _state_from(rng.sample(_POOL, k))


def test_merge_idempotent_floor():
    for seed in range(200):
        rng = random.Random(seed)
        s = _random_state(rng)
        merged = CoordinationState.merge(s, s)
        assert merged.canonical_bytes() == s.canonical_bytes()


def test_merge_commutative_floor():
    for seed in range(200):
        rng = random.Random(seed)
        a, b = _random_state(rng), _random_state(rng)
        ab = CoordinationState.merge(a, b)
        ba = CoordinationState.merge(b, a)
        assert ab.canonical_bytes() == ba.canonical_bytes()


def test_merge_associative_floor():
    for seed in range(200):
        rng = random.Random(seed)
        a, b, c = (_random_state(rng) for _ in range(3))
        left = CoordinationState.merge(CoordinationState.merge(a, b), c)
        right = CoordinationState.merge(a, CoordinationState.merge(b, c))
        assert left.canonical_bytes() == right.canonical_bytes()


def test_merge_is_set_union_floor():
    for seed in range(100):
        rng = random.Random(seed)
        a, b = _random_state(rng), _random_state(rng)
        merged = CoordinationState.merge(a, b)
        assert merged.event_hashes() == a.event_hashes() | b.event_hashes()


# ----------------------------------------------------------------------
# Hypothesis layer — stronger search; skipped if not installed.
# ----------------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

_indices = st.lists(st.integers(min_value=0, max_value=len(_POOL) - 1), unique=True)


@settings(max_examples=300)
@given(_indices, _indices)
def test_merge_commutative_hypothesis(xs, ys):
    a = _state_from(_POOL[i] for i in xs)
    b = _state_from(_POOL[i] for i in ys)
    assert (CoordinationState.merge(a, b).canonical_bytes()
            == CoordinationState.merge(b, a).canonical_bytes())


@settings(max_examples=300)
@given(_indices, _indices, _indices)
def test_merge_associative_hypothesis(xs, ys, zs):
    a = _state_from(_POOL[i] for i in xs)
    b = _state_from(_POOL[i] for i in ys)
    c = _state_from(_POOL[i] for i in zs)
    left = CoordinationState.merge(CoordinationState.merge(a, b), c)
    right = CoordinationState.merge(a, CoordinationState.merge(b, c))
    assert left.canonical_bytes() == right.canonical_bytes()


@settings(max_examples=300)
@given(_indices)
def test_merge_idempotent_hypothesis(xs):
    a = _state_from(_POOL[i] for i in xs)
    assert CoordinationState.merge(a, a).canonical_bytes() == a.canonical_bytes()


# ----------------------------------------------------------------------
# Deterministic reconstruction — ordering from ICP linkage, not arrival.
# ----------------------------------------------------------------------

def test_linearization_is_arrival_order_independent():
    chain = _mk_chain("L", 6)
    forward = _state_from(chain)
    rng = random.Random(7)
    shuffled = list(chain)
    rng.shuffle(shuffled)
    backward = _state_from(shuffled)
    # Same envelope set, opposite insertion orders → identical content.
    assert forward.canonical_bytes() == backward.canonical_bytes()
    # And the reconstructed linear chain is byte-identical.
    fa = forward.linear_chains()
    ba = backward.linear_chains()
    assert [compute_envelope_hash(e) for c in fa for e in c] == \
           [compute_envelope_hash(e) for c in ba for e in c]


def test_linear_chain_verifies_after_merge():
    chain = _mk_chain("V", 5)
    # Split the chain across two replicas, then merge — simulating gossip.
    left = _state_from(chain[:2])
    right = _state_from(chain[2:])
    merged = CoordinationState.merge(left, right)
    chains = merged.linear_chains()
    assert len(chains) == 1
    ok, bad = verify_chain(chains[0])
    assert ok, f"verify_chain failed at index {bad}"
    assert len(chains[0]) == 5


def test_fork_yields_two_verifiable_paths_sharing_a_prefix():
    # Shared prefix E0 -> E1, then a partition fork: two children of E1.
    s = _signer(3)
    e0 = s.sign_action("i", "E0", ["00" * 32], "00" * 32, None,
                       "mock", "mock", 0, 0, 0)
    e1 = s.sign_action("i", "E1", [compute_envelope_hash(e0)], "11" * 32, e0,
                       "mock", "mock", 0, 0, 0)
    branch_a = s.sign_action("i", "A", [compute_envelope_hash(e1)], "aa" * 32,
                             e1, "mock", "mock", 0, 0, 0)
    branch_b = s.sign_action("i", "B", [compute_envelope_hash(e1)], "bb" * 32,
                             e1, "mock", "mock", 0, 0, 0)

    # Two replicas each saw one branch; merge keeps BOTH (zero loss).
    left = _state_from([e0, e1, branch_a])
    right = _state_from([e0, e1, branch_b])
    merged = CoordinationState.merge(left, right)

    assert len(merged) == 4  # nothing discarded
    chains = merged.linear_chains()
    assert len(chains) == 2
    for c in chains:
        ok, bad = verify_chain(c)
        assert ok, f"branch failed verify_chain at {bad}"
    # Both branches share the E0 -> E1 prefix.
    for c in chains:
        assert compute_envelope_hash(c[0]) == compute_envelope_hash(e0)
        assert compute_envelope_hash(c[1]) == compute_envelope_hash(e1)
    # Convergence is order-independent for the forked case too.
    assert (CoordinationState.merge(left, right).canonical_bytes()
            == CoordinationState.merge(right, left).canonical_bytes())
