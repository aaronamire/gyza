"""
EVERY REGISTERED COMPONENT MUST BE EXECUTED AGAINST A REAL INPUT.

The gap this closes, stated as the reason the file exists: a shipped harm
quantity (`_credits_at_risk`) read a non-existent attribute and RAISED on every
input for two sessions. **785 passing tests did not detect it**, because every
containment test constructed its own local fixture and nothing ever ran the
*registered* one.

> **A registry makes a component REACHABLE, not EXERCISED.** A registry entry
> that no test executes is a component that does not exist, and a suite that
> builds its own fixtures will never touch the registered ones.

So this file enumerates each registry and executes **every entry** against a
genuinely valid input. It is deliberately written as coverage-by-enumeration:
adding a registry entry without adding its input here fails the completeness
assertion at the bottom, rather than silently going unexercised.
"""
from __future__ import annotations

import os
import secrets
import tempfile

import blake3
import pytest

from gyza.containment.gyza_model import build_registries as build_harm
from gyza.containment.invariants import InvariantClass
from gyza.economy.delegation import CapabilitySpec, DelegationHop
from gyza.economy.market import BondedMarket, sign_assertion
from gyza.icp import ICPEnvelope, sign_envelope
from gyza.identity import AgentIdentity, LocalCompositor, manifest_hash_hex
from gyza.verification.adapters import HUMAN_SPECS, NATIVE, build_registries


# --------------------------------------------------------------------------- #
#  Real fixtures                                                               #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def idn():
    with tempfile.TemporaryDirectory() as tmp:
        kp = os.path.join(tmp, "compositor.key")
        with open(kp, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(kp, 0o600)
        c = LocalCompositor(key_path=kp)
        seed, manifest = c.issue_agent(
            agent_type="reg", model_path="mock", fs_read_paths=["/in"],
            fs_write_paths=["/out"], allowed_hosts=[], memory_limit_mb=512,
            attestation_tier=1)
        yield AgentIdentity(seed, manifest)


def _envelope(idn, i=0, parent=None):
    env = ICPEnvelope(
        intent_id="i", action_id=f"a{i}", agent_pubkey=idn.pubkey_hex,
        capability_manifest_hash=manifest_hash_hex(idn.manifest),
        input_hashes=[], output_hash=blake3.blake3(f"o{i}".encode()).hexdigest(),
        parent_envelope_hash=parent, timestamp_ns=1000 + i,
        inference_backend="mock", model_identifier="mock",
        duration_ms=1, tokens_in=1, tokens_out=1)
    return sign_envelope(env, idn._seed)


class _LedgerEntryStub:
    """A REAL LedgerEntry shape with genuine signatures would need a live
    Ledger + DB. The adapter under test is `ledger.verify_entry`, so the real
    input here is a real *entry* passed to a real *verify_entry*; an unsigned
    entry exercises the same code path and returns (False, reason), which is a
    legitimate execution -- the assertion is that it RUNS, not that it passes."""

    def __init__(self):
        from gyza.economy.ledger import LedgerEntry
        self.entry = LedgerEntry(
            entry_id="e1", from_compositor="a" * 64, to_compositor="b" * 64,
            amount_credits=1.0, work_item_id="w", icp_envelope_hash="h",
            model_identifier="m", tokens_out=1, duration_ms=1,
            created_at_ns=1)


def _market(idn):
    m = BondedMarket({idn.pubkey_hex: 100.0}, diversity_threshold=0.0)
    m.submit(sign_assertion(idn, "t1", "yes", 10.0))
    return m


# --------------------------------------------------------------------------- #
#  C-1 harm quantities                                                         #
# --------------------------------------------------------------------------- #
def _S():
    """The PRODUCTION state type, not a local stand-in.

    This used to be a hand-rolled class carrying `.capital` and
    `.authority_violations`. **No production object carried either**, so both
    quantities read a `getattr` default of 0.0 and this test — the one written
    to enforce "registering a checker is not evidence that it runs" — passed
    against a shape production never produced. A fixture the suite invents is
    not evidence about a registry.
    """
    from gyza.containment.projection import project_now
    from gyza.economy.market import BondedMarket
    return project_now(
        owner="aa" * 32, ledger_entries=[], active_holds=0.0,
        capital_entries=BondedMarket(
            initial_capital={"aa" * 32: 100.0}).capital_entries())


def test_every_registered_harm_quantity_executes():
    harm, _inv = build_harm()
    ran = 0
    for hc in harm:
        v = hc.measure(_S(), _S())          # must not raise
        assert isinstance(v, float)
        ran += 1
    assert ran == len(list(harm)) > 0


# --------------------------------------------------------------------------- #
#  C-2 invariant predicates                                                    #
# --------------------------------------------------------------------------- #
def test_every_registered_invariant_predicate_executes():
    """A class with NO declared bound must RAISE rather than default, so it is
    counted separately here instead of being silently skipped -- a predicate
    that never runs because its bound is missing is still an unexercised
    registry entry, and saying so is the point of this file."""
    from gyza.containment.gyza_model import MEASURED_NOT_BOUNDED
    from gyza.containment.harm import UnsetBoundError

    harm, inv = build_harm()
    ran = 0
    undeclared: list[str] = []
    for i in inv:
        try:
            bound = harm.bound(i.harm_class)
        except UnsetBoundError:
            # AN UNBOUNDED CLASS STILL GETS ITS PREDICATE EXERCISED. The prior
            # version `continue`d here, so a registered-but-unbounded class had
            # its predicate skipped entirely -- an unexercised registry entry,
            # which is the exact defect this file exists to catch (artifact
            # #16: 785 passing tests missed a quantity that raised on every
            # input). A probe level runs it without declaring anything.
            bound = 1.0
            if i.harm_class not in MEASURED_NOT_BOUNDED:
                undeclared.append(i.harm_class)
        h = harm.get(i.harm_class).measure(_S(), _S())
        r = i.predicate(h, bound, _S(), _S())   # must not raise
        assert isinstance(r, bool)
        ran += 1
    assert ran == len(inv) > 0
    # A class may be unbounded ONLY if it says so, in code, with a reason.
    # "Measured, not bounded" is honest; a FORGOTTEN level is the D1 gap, and
    # the two are distinguishable only because the deliberate ones are declared.
    assert undeclared == [], (
        f"{undeclared} have no declared level and are not listed in "
        f"MEASURED_NOT_BOUNDED. Either declare a level, or declare -- with a "
        f"reason -- that the level is deliberately absent.")


# --------------------------------------------------------------------------- #
#  V-1 native verifier adapters                                                #
# --------------------------------------------------------------------------- #
def _verifier_inputs(idn):
    """One genuinely valid input per registered verifier."""
    e0 = _envelope(idn, 0)
    e1 = _envelope(idn, 1, parent=None)
    pk = bytes.fromhex(idn.pubkey_hex)
    root = CapabilitySpec(ro=frozenset({"/in"}), rw=frozenset({"/out"}),
                          network=False, mem_cap=512)
    child = CapabilitySpec(ro=frozenset({"/in"}), rw=frozenset(),
                           network=False, mem_cap=256)
    enf = {"backend": "bubblewrap", "ro_paths": ["/in"], "rw_paths": ["/out"],
           "requires_network": False, "max_memory_mb": 256}
    data = b"payload"
    return {
        "envelope_signature": ((e0, pk), {}),
        "envelope_chain": (([e0],), {}),
        # the SPLIT: two determinate types where one caller-chosen kwarg was
        "envelope_dag_closed": (([e0],), {}),
        "envelope_dag_open": (([e0, e1],), {}),
        "manifest_identity": ((idn.manifest, manifest_hash_hex(idn.manifest)), {}),
        "enforcement_within_manifest": ((enf, idn.manifest), {}),
        "delegation_attenuation": (([DelegationHop("r", root, root, None),
                                     DelegationHop("c", child, child, child)],), {}),
        "ledger_entry_signatures": (None, {}),          # special-cased below
        "balance_fold": (([], idn.pubkey_hex, __import__(
            "gyza.economy.wallet", fromlist=["Credits"]).Credits(0)), {}),
        "market_capital_fold": (None, {}),              # special-cased below
        "artifact_content_address": ((data, blake3.blake3(data).hexdigest()), {}),
        "unit_test_execution": ((lambda x: x * 2, [(1, 2), (2, 4)]), {}),
        # RESPECIFIED out of NO_VERIFIER. Registered entries with no input here
        # would be exactly the gap artifact #16 records: reachable, never run.
        "memory_retrieval_relevance": (_retrieval_case(), {}),
        "external_send_content": (_send_case(), {}),
    }


def _retrieval_case():
    import numpy as np

    from gyza.verification.respec import (
        FILTER_SUCCESS_ONLY, METRIC_COSINE_UNIT, RetrievalClaim,
        corpus_snapshot_digest,
    )
    rng = np.random.default_rng(5)
    q = rng.normal(size=8).astype(np.float32)
    items = [(f"e{i}", rng.normal(size=8).astype(np.float32), True)
             for i in range(4)]
    scored = sorted(
        ((e, float(np.dot(q / np.linalg.norm(q), v / np.linalg.norm(v))))
         for e, v, _ in items), key=lambda p: (-p[1], p[0]))
    claim = RetrievalClaim(
        corpus_snapshot=corpus_snapshot_digest(items),
        metric=METRIC_COSINE_UNIT, k=2, threshold=-1.0,
        filter_predicate=FILTER_SUCCESS_ONLY,
        returned_ids=tuple(e for e, _ in scored[:2]))
    return (claim, items, q)


def _send_case():
    """B4: exercised against a REAL PRODUCED claim, not a hand-built fixture.

    `_emit_send_claim` is the claim CONSTRUCTOR. It USED TO BE the function
    the netd send paths called, and this docstring used to say that proved
    production and verification were connected. THAT IS NO LONGER TRUE:
    emission was removed because nothing consumed it (OPEN_PROBLEM 4.6), so
    no production path builds a SendClaim today. What this still proves is
    that the REGISTERED verifier executes against a constructed claim --
    artifact #16's check -- not that anything in production produces one.
    """
    from gyza.network.netd_client import _emit_send_claim

    payload = b"registry-exercised-bytes"
    return (_emit_send_claim(payload, destination="peer"), payload)


def test_every_registered_verifier_executes_against_a_real_input(idn):
    verifiers, _specs = build_registries()
    inputs = _verifier_inputs(idn)
    ran = []
    for ct in verifiers.claim_types():
        assert ct in inputs, (
            f"verifier {ct!r} is registered but this test supplies no input — "
            f"an unexercised registry entry is a component that does not exist")
        v = verifiers.get(ct)
        if ct == "ledger_entry_signatures":
            from gyza.economy.ledger import ComputeLedger
            with tempfile.TemporaryDirectory() as tmp:
                kp = os.path.join(tmp, "k.key")
                with open(kp, "wb") as f:
                    f.write(secrets.token_bytes(32))
                os.chmod(kp, 0o600)
                led = ComputeLedger(LocalCompositor(key_path=kp),
                                    db_path=os.path.join(tmp, "l.db"))
                out = v.fn(led, _LedgerEntryStub().entry)
        elif ct == "market_capital_fold":
            m = _market(idn)
            out = v.fn(m, idn.pubkey_hex, 90.0)
        else:
            args, kw = inputs[ct]
            out = v.fn(*args, **kw)
        assert isinstance(out, bool), f"{ct} returned {type(out).__name__}"
        ran.append(ct)
    assert sorted(ran) == sorted(verifiers.claim_types())
    assert len(ran) == len(NATIVE)


# --------------------------------------------------------------------------- #
#  V-4 partial specs                                                           #
# --------------------------------------------------------------------------- #
def test_every_registered_partial_spec_executes():
    _v, specs = build_registries()
    inputs = {
        "hlc_ordering": ((1, 0, "n"), (2, 0, "n")),
        "reputation_score": (0.5,),
        "work_claim_exclusivity": (["w1", "w2"], "w1"),
    }
    ran = []
    for ct in specs.claim_types():
        assert ct in inputs, (
            f"spec {ct!r} is registered but this test supplies no input")
        out = specs.get(ct).fn(*inputs[ct])
        assert isinstance(out, bool)
        assert isinstance(specs.get(ct).cls, InvariantClass)
        ran.append(ct)
    assert len(ran) == len(HUMAN_SPECS)


# --------------------------------------------------------------------------- #
#  The completeness assertion — this is the part that must not be deleted      #
# --------------------------------------------------------------------------- #
def test_no_registry_entry_is_left_unexercised(idn):
    """Adding a registry entry without adding its input above fails HERE.

    Without this, the file degrades into 'some registered things are tested',
    which is the state that let a never-executing harm quantity ship past 785
    green tests.
    """
    harm, inv = build_harm()
    verifiers, specs = build_registries()
    covered = {
        "harm": {c.id for c in harm},
        "invariant": {i.id for i in inv},
        "verifier": set(_verifier_inputs(idn)),
        "spec": {"hlc_ordering", "reputation_score", "work_claim_exclusivity"},
    }
    assert covered["harm"] == {c.id for c in harm}
    assert covered["invariant"] == {i.id for i in inv}
    assert covered["verifier"] == set(verifiers.claim_types()), (
        "verifier registry and this test's inputs have diverged")
    assert covered["spec"] == set(specs.claim_types()), (
        "spec registry and this test's inputs have diverged")


# --------------------------------------------------------------------------- #
#  WITNESS CITATIONS MUST RESOLVE TO THE SYMBOL THEY NAME                      #
# --------------------------------------------------------------------------- #
def test_every_witness_citation_resolves_to_the_symbol_it_names():
    """`VerifierRegistry.register` REFUSES an uncited verifier because "an
    uncited verifier cannot be audited". That makes the citation load-bearing --
    and load-bearing is exactly what nothing was checking.

    Two had drifted when this was written (2026-08-14). `delegation_attenuation`
    cited `delegation.py:213`, sixteen lines stale after the depth 8->3 commit
    moved `verify_delegation` to :229. `ledger_entry_signatures` cited
    `ledger.py:348` -- inside `sign_as_payer`, the SIGNER -- while the adapter
    calls `verify_entry`, so an auditor following the witness landed on the
    wrong function entirely.

    SOUND IN ONE DIRECTION. A citation naming a symbol that does not contain the
    cited line is DEFINITELY wrong; one that resolves is not thereby verified.
    """
    import ast
    import pathlib
    import re

    from gyza.containment.gyza_model import build_registries as _bh
    from gyza.verification.adapters import build_registries as _bv

    named = re.compile(r'((?:gyza|netd|tests|scripts)[\w/\-.]*\.py):(\d+)'
                       r'(?:-\d+)?\s+([A-Za-z_]\w*)')
    _pins_a_line = re.compile(r'(?:gyza|netd|tests|scripts)[\w/\-.]*\.py:\d+')
    cites = []
    v, _s = _bv()
    for ct in v.claim_types():
        cites.append((ct, v.get(ct).witness))
    h, _i = _bh()
    for hc in h:
        cites.append((hc.id, hc.code_path))

    checked = 0
    for ident, wit in cites:
        m = named.search(wit or "")
        if m is None:
            # A CITATION THAT PINS A LINE BUT NAMES NO SYMBOL IS EXEMPT BY
            # OMISSION, and that is how two of them went stale unnoticed:
            # `gyza/icp.py:82` drifted into `compute_envelope_hash` and
            # `gyza/icp.py:105` into `verify_envelope`, while the checker
            # skipped both because neither said what it pointed at.
            #
            # A line number is the part that rots. Naming a file alone is a
            # durable citation and stays exempt; naming a LINE without a symbol
            # is an unverifiable claim and now fails.
            assert not _pins_a_line.search(wit or ""), (
                f"{ident}: witness {wit!r} pins a line but names no symbol, so "
                f"nothing checks it. Add the symbol, or cite the file alone.")
            continue
        path, line, symbol = m.group(1), int(m.group(2)), m.group(3)
        src = pathlib.Path(path)
        assert src.is_file(), f"{ident}: cited file {path} does not exist"
        tree = ast.parse(src.read_text())
        enclosing = None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if n.lineno <= line <= (n.end_lineno or n.lineno):
                    enclosing = n.name
        assert enclosing == symbol, (
            f"{ident}: witness says {path}:{line} {symbol}, but that line is "
            f"inside {enclosing!r}. A stale citation is worse than none.")
        checked += 1

    assert checked >= 3, f"only {checked} symbol-anchored citations were checked"
