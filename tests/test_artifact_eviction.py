"""H5 becomes a BOUND when the store can evict, and not before.

R-EVID Part C (`research/evidence/THEOREMS_C.md`) proves that a level on an
accumulating quantity is a bound only when the fold has non-positive benign
drift and reflects at zero. `ArtifactStore.max_bytes` supplied neither: it
REFUSED writes once full and kept refusing, so a node stopped permanently at
the declared level. A refusal is not a reversal.

Theorem 6 is the part that decides the design: adding a delete button is not
enough, because a reversal slower than the creation rate leaves a timer. Evicting
exactly enough to fit the incoming write satisfies `r >= b` at every step, so
the capacity condition holds BY CONSTRUCTION rather than by measurement.
"""
from __future__ import annotations

import json

import pytest

from gyza.network.artifact_store import ArtifactStore, ArtifactStoreFull


def _store(tmp_path, **kw):
    return ArtifactStore(base_path=str(tmp_path / "cas"), **kw)


def test_WITHOUT_eviction_the_store_is_a_timer(tmp_path):
    """The behaviour being replaced, asserted so the contrast is not rhetoric.

    Writes succeed until the cap, then fail forever. Nothing the node does
    afterwards makes it work again.
    """
    st = _store(tmp_path, max_bytes=300)
    for i in range(3):
        st.store(bytes([i]) * 100)
    for i in range(3, 8):
        with pytest.raises(ArtifactStoreFull):
            st.store(bytes([i]) * 100)
    assert st.total_size_bytes() == 300


def test_WITH_eviction_the_node_runs_indefinitely_within_the_cap(tmp_path):
    st = _store(tmp_path, max_bytes=300, evict_when_full=True)
    for i in range(50):
        st.store(bytes([i % 251]) * 100)
    assert st.total_size_bytes() <= 300, "the cap was exceeded"
    assert st.evicted_bytes() > 0, "nothing was evicted; this was not a test"
    # And the store is still usable, which is the whole point.
    h = st.store(b"still working" * 5)
    assert st.get(h) is not None


def test_theorem_6_the_reversal_rate_MATCHES_the_creation_rate(tmp_path):
    """`r >= b` at every step, checked as an invariant over the whole run
    rather than at the end. A store that stayed under the cap only because the
    test stopped writing would pass an end-state check."""
    st = _store(tmp_path, max_bytes=500, evict_when_full=True)
    written = 0
    for i in range(60):
        payload = bytes([i % 251]) * 100
        st.store(payload)
        written += len(payload)
        assert st.total_size_bytes() <= 500, f"cap exceeded at write {i}"
    # Everything written beyond the cap must have been reversed, not lost
    # track of: bytes on disk + bytes evicted accounts for the whole stream.
    assert st.total_size_bytes() + st.evicted_bytes() == written


def test_every_eviction_is_an_APPENDED_FACT_not_an_absence(tmp_path):
    """The architectural principle's requirement. A deleted file is an absence
    -- unattributable, and inferable only by noticing something is missing. A
    tombstone is append-only, which is what `Wallet.net_balance` already does:
    a fold that may decrease, where every decrement is an appended entry.
    """
    st = _store(tmp_path, max_bytes=250, evict_when_full=True)
    for i in range(10):
        st.store(bytes([i]) * 100)

    log = st.base_path / ArtifactStore.TOMBSTONE_LOG
    assert log.exists(), "evictions left no record"
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert rows, "tombstone log is empty despite evictions"
    for r in rows:
        assert set(r) == {"hash", "bytes", "evicted_at_ns"}
        assert r["bytes"] > 0 and r["evicted_at_ns"] > 0
    assert sum(r["bytes"] for r in rows) == st.evicted_bytes()


def test_the_tombstone_log_is_NOT_counted_as_stored_bytes(tmp_path):
    """Otherwise the record of freeing space would itself consume the budget,
    and the quantity would creep upward on every eviction."""
    st = _store(tmp_path, max_bytes=250, evict_when_full=True)
    for i in range(20):
        st.store(bytes([i]) * 100)
    on_disk = sum(p.stat().st_size for p in st.base_path.rglob("*")
                  if p.is_file())
    assert on_disk > st.total_size_bytes(), (
        "the tombstone log is being counted as stored artifact bytes")
    assert st.total_size_bytes() <= 250


def test_an_artifact_larger_than_the_WHOLE_CAP_still_raises(tmp_path):
    """No eviction rate can fit it, so failing is correct. Silently storing it
    would break the cap; silently dropping it would lose the write."""
    st = _store(tmp_path, max_bytes=100, evict_when_full=True)
    with pytest.raises(ArtifactStoreFull, match="cannot be stored"):
        st.store(b"x" * 500)


def test_eviction_does_NOT_break_chain_verification(tmp_path):
    """What an eviction costs is CONTENT INSPECTION, not PROVENANCE.

    `verify_chain` checks signatures over hashes carried in the envelopes, so a
    chain still verifies after its inputs are evicted. If this ever fails, the
    eviction design is wrong and H5 must go back to being a timer.
    """
    import time

    from gyza.icp import ICPEnvelope, sign_envelope, verify_chain
    from gyza.identity import AgentIdentity, LocalCompositor

    comp = LocalCompositor(key_path=str(tmp_path / "k.key"))
    seed, manifest = comp.issue_agent(
        agent_type="evict.test", model_path="mock", fs_read_paths=[],
        fs_write_paths=[], allowed_hosts=[], memory_limit_mb=64,
        attestation_tier=0)
    ident = AgentIdentity(seed, manifest)
    manifest_hash = ident.manifest_hash

    st = _store(tmp_path, max_bytes=200, evict_when_full=True)
    payload = b"the artifact that will be evicted" * 2
    h = st.store(payload)

    env = sign_envelope(ICPEnvelope(
        intent_id="i", action_id="a1", agent_pubkey=ident.pubkey_hex,
        capability_manifest_hash=manifest_hash,
        input_hashes=[h], output_hash=h, parent_envelope_hash=None,
        timestamp_ns=time.time_ns(), inference_backend="mock",
        model_identifier="mock", duration_ms=1, tokens_in=0, tokens_out=0,
    ), seed)

    # Evict it by writing past the cap.
    for i in range(10):
        st.store(bytes([i]) * 100)
    assert st.get(h) is None, "the artifact was not actually evicted"

    ok, _idx = verify_chain([env])
    assert ok, "chain failed to verify after its input artifact was evicted"
