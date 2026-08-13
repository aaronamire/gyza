"""The claim ledger — the first end-to-end consumption of the governed registry.

WHAT THIS PINS. Before this, claims were emitted at two production sites and
read at zero. These tests exercise the whole path on REAL operations with REAL
verifiers: emit at the operation site -> route through the governed registry ->
recompute with the registered verifier -> tier the chain -> refuse.

EVERY POSITIVE HAS A NEGATIVE CONTROL. A ledger that has only ever said
"admissible" has demonstrated nothing.

Run:  ~/dev/marshal/.os/bin/python -m pytest tests/test_claim_ledger.py -q
"""
from __future__ import annotations

import secrets

import blake3

from gyza.icp import ICPEnvelope, sign_envelope
from gyza.verification.adapters import build_registries
from gyza.verification.ledger import (
    REFUTED, UNEVALUATED, VERIFIED, ClaimLedger,
)
from gyza.verification.migration import governed_router


def _envelope():
    """A real signed envelope — actual Ed25519, not a stub."""
    seed = secrets.token_bytes(32)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    pk = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()
    env = ICPEnvelope(
        intent_id="i1", action_id="a1", agent_pubkey=pk.hex(),
        capability_manifest_hash="c" * 64, input_hashes=["deadbeef"],
        output_hash="f" * 64, parent_envelope_hash=None, timestamp_ns=1,
        inference_backend="test", model_identifier="none",
        duration_ms=1, tokens_in=0, tokens_out=0,
    )
    return sign_envelope(env, seed), pk


def _honest_ledger():
    """Three REAL operations, each emitting its own type at its own site."""
    led = ClaimLedger()

    data = b"the bytes that were actually produced"
    led.emit("artifact_content_address", data, blake3.blake3(data).hexdigest(),
             note="hashed a real artifact")

    env, pk = _envelope()
    led.emit("envelope_signature", env, pk, note="signed a real envelope")

    led.emit("unit_test_execution", lambda x: x * 2, [(1, 2), (3, 6)],
             note="ran a finite case set")
    return led


def _run(led):
    verifiers, _specs = build_registries()
    return led.verify_all(governed_router(), verifiers)


# --------------------------------------------------------------------------- #
#  THE PATH RUNS END TO END                                                    #
# --------------------------------------------------------------------------- #
def test_the_whole_path_runs_on_real_operations():
    rep = _run(_honest_ledger())
    assert rep.n_claims == 3
    assert rep.counts.get(VERIFIED) == 3, rep.summary
    assert rep.admissible, rep.summary


def test_the_governed_registry_is_actually_consulted():
    """Not merely constructed — the verdicts must carry its attestation."""
    rep = _run(_honest_ledger())
    assert all(v.governed for v in rep.verdicts), \
        "a verdict came from the ungoverned fallback"


def test_a_TEST_carried_claim_sinks_the_whole_chain_to_tier_3():
    """SR-3, live rather than cited: PROOF composes at 1.000 and TEST at 0.000,
    so one sampled claim makes the chain tier 3 no matter what else verified."""
    rep = _run(_honest_ledger())
    assert rep.chain_tier == 3, rep.chain_reasons
    assert any("TEST-carried" in r for r in rep.chain_reasons), rep.chain_reasons
    # and it is genuinely the carrier doing it, not a tier-3 member
    assert all(v.tier in (1, 2) for v in rep.verdicts)


def test_dropping_the_TEST_claim_lifts_the_chain():
    """The counter-metric to the test above: without the sampled claim the same
    machinery reports tier 1. If it did not, the tier verdict would be inert."""
    led = ClaimLedger()
    data = b"only proof-carried work here"
    led.emit("artifact_content_address", data, blake3.blake3(data).hexdigest())
    env, pk = _envelope()
    led.emit("envelope_signature", env, pk)
    rep = _run(led)
    assert rep.admissible and rep.chain_tier == 1, rep.summary


# --------------------------------------------------------------------------- #
#  NEGATIVE CONTROLS — the ledger must REFUSE                                  #
# --------------------------------------------------------------------------- #
def test_negative_control_a_TAMPERED_artifact_is_REFUTED():
    """The bytes changed after the address was claimed."""
    led = ClaimLedger()
    led.emit("artifact_content_address", b"tampered bytes",
             blake3.blake3(b"the original bytes").hexdigest())
    rep = _run(led)
    assert rep.counts.get(REFUTED) == 1, rep.summary
    assert not rep.admissible, "a refuted claim must sink the set"
    assert "DIVERGED" in rep.verdicts[0].detail


def test_negative_control_a_FORGED_signature_is_REFUTED():
    """Signed with one key, presented against another."""
    env, _pk = _envelope()
    _other_env, other_pk = _envelope()
    led = ClaimLedger()
    led.emit("envelope_signature", env, other_pk)
    rep = _run(led)
    assert rep.counts.get(REFUTED) == 1, rep.summary
    assert not rep.admissible


def test_negative_control_a_failing_unit_test_is_REFUTED():
    led = ClaimLedger()
    led.emit("unit_test_execution", lambda x: x * 3, [(1, 2)])
    rep = _run(led)
    assert rep.counts.get(REFUTED) == 1
    assert not rep.admissible


# --------------------------------------------------------------------------- #
#  THREE VERDICTS, NEVER TWO — an error is not a refutation                    #
# --------------------------------------------------------------------------- #
def test_a_verifier_that_RAISES_is_UNEVALUATED_not_REFUTED():
    """Artifact #16's species. 'It broke' and 'it is false' are opposite claims
    and must not share a channel."""
    led = ClaimLedger()
    led.emit("envelope_signature", None, None)      # AttributeError inside
    rep = _run(led)
    assert rep.counts.get(UNEVALUATED) == 1, rep.summary
    assert rep.counts.get(REFUTED, 0) == 0, "an error was recorded as a refutation"
    assert "raised" in rep.verdicts[0].detail
    assert not rep.admissible, "unevaluated must not read as passing"


# --------------------------------------------------------------------------- #
#  TWO DEFECTS THIS WIRING FOUND IN COMMITTED VERIFIERS                        #
#  Both are the program's recurring species: an ABSENT thing read as a VALUE.  #
# --------------------------------------------------------------------------- #
def test_ABSENT_content_does_not_verify_against_the_EMPTY_address():
    """FOUND BY THE LEDGER, not by review.

    `blake3.blake3(None)` does not raise -- it returns the digest of the empty
    string (af1349b9...). So before the guard, the claim "this absent content
    is at the empty address" VERIFIED, at tier 1, PROOF-carried. Absent content
    and empty content are different claims.
    """
    empty = blake3.blake3(b"").hexdigest()
    led = ClaimLedger()
    led.emit("artifact_content_address", None, empty)
    rep = _run(led)
    assert rep.counts.get(VERIFIED, 0) == 0, \
        "absent content verified against the empty address"
    assert rep.counts.get(UNEVALUATED) == 1, rep.summary
    assert not rep.admissible

    # POSITIVE CONTROL: genuinely empty bytes still verify. The guard must
    # reject ABSENCE, not empty content -- otherwise it is over-broad.
    led2 = ClaimLedger()
    led2.emit("artifact_content_address", b"", empty)
    assert _run(led2).counts.get(VERIFIED) == 1


def test_a_MALFORMED_case_set_is_UNEVALUATED_but_a_RAISING_case_is_REFUTED():
    """The other half of the same distinction, in `unit_test_execution`.

    A function that raises on a case has genuinely failed it -> REFUTED.
    A malformed `cases` is a broken harness -> must not read as a refutation.
    A blanket `except Exception` reported both as False.
    """
    led = ClaimLedger()
    led.emit("unit_test_execution", lambda x: 1 / 0, [(1, 1)])   # case raises
    assert _run(led).counts.get(REFUTED) == 1

    led2 = ClaimLedger()
    led2.emit("unit_test_execution", lambda x: x, "not a case set")
    rep2 = _run(led2)
    assert rep2.counts.get(UNEVALUATED) == 1, rep2.summary
    assert rep2.counts.get(REFUTED, 0) == 0, \
        "a malformed case set was reported as a refutation"


def test_an_unknown_claim_type_is_UNEVALUATED_not_passing():
    """An absent verifier is not a permissive one."""
    led = ClaimLedger()
    led.emit("no_such_claim_type_exists")
    rep = _run(led)
    assert rep.counts.get(UNEVALUATED) == 1
    assert not rep.admissible
    assert rep.verdicts[0].tier == 3, "an ungoverned type must route to tier 3"


def test_an_empty_ledger_is_NOT_admissible():
    """Vacuous truth is the easiest way to pass. Zero claims establishes
    nothing, so it must not report success."""
    rep = _run(ClaimLedger())
    assert rep.n_claims == 0
    assert not rep.admissible


# --------------------------------------------------------------------------- #
#  THE PRODUCTION PATH — a real emitter feeding a real consumer                #
#                                                                              #
#  Everything above builds its own ledger, which is exactly the trap artifact  #
#  #16 named: "a suite that builds its own fixtures never touches the          #
#  registered ones". These tests drive `EpisodicMemory.retrieve_similar` --    #
#  committed production code -- and read what IT emitted.                      #
# --------------------------------------------------------------------------- #
def _memory_with_ledger(tmp_path, monkeypatch):
    """Real EpisodicMemory over the SQLite backend, with a deterministic
    encoder so the test does not download sentence-transformers."""
    import time
    import uuid

    import numpy as np

    import gyza.memory as mem_mod
    from gyza.memory import Episode, EpisodicMemory

    agent = "11" * 32
    mem = EpisodicMemory(agent_id=agent, db_path=str(tmp_path / "m"))

    for i in range(6):
        v = np.zeros(384, dtype=np.float32)
        v[i] = 1.0
        mem.write(Episode(
            episode_id=str(uuid.uuid7()), agent_id=agent, task_embedding=v,
            intent_text=f"task {i}", input_hashes=["aa" * 32],
            output_hash="bb" * 32, action_types=["QUERY"], success=(i % 2 == 0),
            duration_ms=10, model_identifier="none",
            icp_envelope_hash="cc" * 32, timestamp_ns=time.time_ns(),
        ))
    mem.flush()

    q = np.zeros((1, 384), dtype=np.float32)
    q[0, 0] = 1.0
    monkeypatch.setattr(mem_mod, "_embed", lambda _t: q)

    mem.claim_ledger = ClaimLedger()
    return mem


def test_PRODUCTION_retrieval_emits_a_claim_that_the_ledger_VERIFIES(
        tmp_path, monkeypatch):
    """THE GAP, CLOSED. `retrieve_similar` emits; the ledger reads; the
    governed registry recomputes. No step is a fixture."""
    mem = _memory_with_ledger(tmp_path, monkeypatch)
    got = mem.retrieve_similar("a task", k=3, min_similarity=-1.0,
                               success_only=True, emit_claim=True)

    assert mem.claim_ledger.claims, "production emitted nothing into the ledger"
    # NON-VACUITY. An empty result set verifies trivially, so the positive
    # result would mean nothing without this.
    emitted = mem.claim_ledger.claims[0]
    assert len(emitted.verify_args[0].returned_ids) == 3 == len(got)
    assert len(emitted.verify_args[1]) == 6, "the whole corpus must be carried"

    rep = _run(mem.claim_ledger)
    assert rep.n_claims == 1
    assert rep.counts.get(VERIFIED) == 1, rep.summary
    assert rep.verdicts[0].governed and rep.verdicts[0].carrier == "PROOF"
    assert rep.admissible, rep.summary


def test_emit_claim_FALSE_records_nothing(tmp_path, monkeypatch):
    """The counter-control: the ledger must reflect what happened, so an
    operation that emitted no claim must leave it empty rather than passing."""
    mem = _memory_with_ledger(tmp_path, monkeypatch)
    mem.retrieve_similar("a task", k=3, min_similarity=-1.0,
                         success_only=True, emit_claim=False)
    assert mem.claim_ledger.claims == []
    assert not _run(mem.claim_ledger).admissible


def test_NEGATIVE_CONTROL_a_tampered_production_claim_is_caught(
        tmp_path, monkeypatch):
    """The whole demonstration rests on this. Falsify the emitted claim's
    result set and the same ledger, unchanged, must refuse it."""
    import dataclasses

    mem = _memory_with_ledger(tmp_path, monkeypatch)
    mem.retrieve_similar("a task", k=3, min_similarity=-1.0,
                         success_only=True, emit_claim=True)
    assert _run(mem.claim_ledger).admissible          # honest baseline

    orig = mem.claim_ledger.claims[0]
    forged = dataclasses.replace(
        orig.verify_args[0], returned_ids=("an-id-that-was-never-returned",))

    tampered = ClaimLedger()
    tampered.emit("memory_retrieval_relevance", forged, *orig.verify_args[1:])
    rep = _run(tampered)
    assert rep.counts.get(REFUTED) == 1, rep.summary
    assert not rep.admissible


def test_the_REAL_runner_path_emits_and_verifies(tmp_path, monkeypatch):
    """`AgentRunner._execute` calls `build_enriched_prompt`, which is the only
    production caller of `retrieve_similar`. Driving THAT is what makes this a
    production consumer rather than a second fixture."""
    from gyza.memory import build_enriched_prompt

    mem = _memory_with_ledger(tmp_path, monkeypatch)
    prompt = build_enriched_prompt(base_prompt="do the thing", memory=mem,
                                   current_task="a task", max_episodes=3)
    assert "past experience" in prompt, "retrieval returned nothing to claim about"
    rep = _run(mem.claim_ledger)
    assert rep.n_claims == 1 and rep.counts.get(VERIFIED) == 1, rep.summary


def test_no_ledger_attached_leaves_the_hot_path_UNCHANGED(tmp_path, monkeypatch):
    """The cost control. `retrieve_similar` documents claim construction as
    O(corpus) and off the hot path; with no consumer attached, nothing is built."""
    from gyza.memory import build_enriched_prompt

    mem = _memory_with_ledger(tmp_path, monkeypatch)
    mem.claim_ledger = None
    build_enriched_prompt(base_prompt="x", memory=mem, current_task="a task")
    assert mem.last_retrieval_claim is None, \
        "the O(corpus) claim was built with no consumer to read it"


def test_an_untyped_claim_cannot_be_recorded():
    led = ClaimLedger()
    for bad in ("", None):
        try:
            led.emit(bad)                                # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"an untyped claim {bad!r} was accepted")
