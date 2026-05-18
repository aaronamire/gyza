"""
SubcontractCoordinator tests — the pay-iff matrix + accounting.

The coordinator pays a subcontractor IFF chain_ok ∧
manifest_hash_ok ∧ verify_grant ∧ grant_binds_to ∧
verify_delegation. Each failing independently must block payment,
release the reservation, and refund the task budget. Plus: the
proactive over-delegation block fires BEFORE any post, and the
no-double-count identity holds through the whole orchestration.
"""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from gyza.economy.coordinator import (
    ParentRef,
    ResultBundle,
    SubcontractCoordinator,
    SubtaskSpec,
)
from gyza.economy.delegation import CapabilitySpec
from gyza.economy.subcontract import Budget, ReservationBook
from gyza.economy.wallet import Credits


def C(n: float) -> Credits:
    return Credits(round(n * 1_000_000))


def S(ro=(), rw=(), network=False, mem=None) -> CapabilitySpec:
    return CapabilitySpec(frozenset(ro), frozenset(rw), network, mem)


def _key(b: int):
    seed = bytes([b]) * 32
    pk = (Ed25519PrivateKey.from_private_bytes(seed)
          .public_key().public_bytes_raw().hex())
    return seed, pk


class _W:
    def __init__(self, credits: float) -> None:
        self._m = round(credits * 1_000_000)

    def drop(self, credits: float) -> None:
        self._m -= round(credits * 1_000_000)

    def net_balance(self, pubkey: str) -> Credits:
        return Credits(self._m)


def _manifest(ro, mem):
    return {"capabilities": {
        "filesystem": {"read": list(ro), "write": []},
        "network": {"allowed_hosts": []},
        "spawn": {"resource_budget": {"memory_limit_mb": mem}}}}


def _enf(ro, mem):
    return {"ro_paths": list(ro), "rw_paths": [], "requires_network": False,
            "max_memory_mb": mem}


class _FX:
    """Controllable effects. Flags flip each predicate / outcome."""

    def __init__(self, wallet, *, chain_ok=True, manifest_ok=True,
                 child_ro=("/tmp",), child_mem=128, cosign=True,
                 deliver=True, post_raises=False, cosign_raises=False,
                 terminalize_during_await=None):
        self.w = wallet
        self.chain_ok = chain_ok
        self.manifest_ok = manifest_ok
        self.child_ro = child_ro
        self.child_mem = child_mem
        self.cosign = cosign
        self.deliver = deliver
        self.post_raises = post_raises
        self.cosign_raises = cosign_raises
        self.terminalize = terminalize_during_await
        self.posted = []
        self.cosigned = []

    def post_subtask(self, wid, subtask, grant):
        if self.post_raises:
            raise RuntimeError("post boom")
        self.posted.append(wid)

    def await_result(self, wid, timeout_s):
        if self.terminalize is not None:
            self.terminalize(wid)          # simulate a racy terminalization
        if not self.deliver:
            return None
        return ResultBundle(
            child_work_item_id=wid,
            child_agent_pubkey="child-pk",
            child_envelope_hash="ceh",
            child_manifest=_manifest(self.child_ro, self.child_mem),
            child_enforcement=_enf(self.child_ro, self.child_mem),
            sub_result={"text": "sub done"},
            chain_ok=self.chain_ok,
            manifest_hash_ok=self.manifest_ok,
        )

    def cosign_as_payer(self, wid, earner, amount, ceh):
        if self.cosign_raises:
            raise RuntimeError("cosign boom")
        if self.cosign:
            # record ONLY actual payments — `cosigned == []` means
            # "no payment happened" consistently across every test.
            self.cosigned.append((wid, earner, amount.micros))
            self.w.drop(amount.value)      # the real settled debit lands
            return True
        return False


def _coord(fx, *, wallet=None, budget=50.0,
           parent_ro=("/tmp", "/data"), parent_mem=512):
    seed, pk = _key(9)
    w = wallet or fx.w
    book = ReservationBook(w, pk, Budget(C(budget)))
    parent = ParentRef(
        agent_pubkey=pk, agent_seed=seed, envelope_hash="EH",
        manifest_hash="MH", work_item_id="W0",
        manifest_spec=S(parent_ro, mem=parent_mem),
        enforcement_spec=S(("/tmp",), mem=256),
    )
    return SubcontractCoordinator(parent, book, fx), book


def _task(bounty=10.0, required=None):
    return SubtaskSpec(payload={"do": "x"},
                       required=required or S(("/tmp",), mem=256),
                       bounty=C(bounty))


# ----------------------------------------------------------------------
# Happy path + no-double-count through the orchestration
# ----------------------------------------------------------------------

def test_happy_path_pays_and_accounting_is_exact():
    w = _W(100)
    fx = _FX(w)
    co, book = _coord(fx, wallet=w, budget=50)
    before = book.available()                 # min(100, 50) = 50

    res = co.subcontract(_task(10.0))
    assert res.ok and res.payload == {"text": "sub done"}
    assert fx.posted and fx.cosigned[0][2] == C(10).micros
    # wallet really dropped 10 (settled), hold settled (not double):
    assert w._m == 90_000_000
    # available: budget 40 remaining (spent), wallet 90 − 0 holds = 90
    # → min = 40. Net effect of the whole op on available = −10 once.
    assert book.available() == C(40)
    assert before == C(50)


# ----------------------------------------------------------------------
# Proactive over-delegation — blocked BEFORE any post
# ----------------------------------------------------------------------

def test_over_delegation_blocked_before_post():
    fx = _FX(_W(100))
    co, book = _coord(fx, budget=50, parent_ro=("/tmp",))
    # require /etc which the parent's manifest does not authorize
    res = co.subcontract(_task(10.0, required=S(("/tmp", "/etc"))))
    assert not res.ok and "beyond own manifest" in res.reason
    assert fx.posted == []                     # never posted
    # no reservation was made → budget untouched
    assert book.available() == C(50)


# ----------------------------------------------------------------------
# Solvency / budget gate — blocked before post
# ----------------------------------------------------------------------

def test_insufficient_headroom_blocked_before_post():
    fx = _FX(_W(5))                            # poor wallet
    co, book = _coord(fx, wallet=fx.w, budget=50)
    res = co.subcontract(_task(10.0))
    assert not res.ok and "cannot reserve" in res.reason
    assert fx.posted == []


# ----------------------------------------------------------------------
# The pay-iff matrix — each predicate failing blocks payment,
# releases the hold, refunds the budget.
# ----------------------------------------------------------------------

def _assert_no_pay_budget_refunded(fx, co, book, expect):
    res = co.subcontract(_task(10.0))
    assert not res.ok and expect in res.reason
    assert fx.cosigned == []                   # never paid
    assert book.available() == C(50)           # budget refunded in full


def test_timeout_no_pay_budget_refunded():
    fx = _FX(_W(100), deliver=False)
    co, book = _coord(fx, wallet=fx.w)
    _assert_no_pay_budget_refunded(fx, co, book, "timed out")


def test_chain_invalid_no_pay():
    fx = _FX(_W(100), chain_ok=False)
    co, book = _coord(fx, wallet=fx.w)
    _assert_no_pay_budget_refunded(fx, co, book, "chain invalid")


def test_manifest_hash_mismatch_no_pay():
    fx = _FX(_W(100), manifest_ok=False)
    co, book = _coord(fx, wallet=fx.w)
    _assert_no_pay_budget_refunded(fx, co, book, "manifest hash")


def test_laundering_subcontractor_earns_nothing():
    # Parent delegates /tmp (required). Subcontractor returns a
    # result whose OWN manifest is /tmp+/etc and ran in /tmp+/etc —
    # honest within its own (improperly wide) manifest. verify_
    # delegation must catch manifest ⊄ delegated → no pay.
    fx = _FX(_W(100), child_ro=("/tmp", "/etc"))
    co, book = _coord(fx, wallet=fx.w)
    _assert_no_pay_budget_refunded(fx, co, book, "bounds did not compose")


def test_cosign_rejected_no_settle():
    fx = _FX(_W(100), cosign=False)
    co, book = _coord(fx, wallet=fx.w)
    res = co.subcontract(_task(10.0))
    assert not res.ok and "cosign-as-payer rejected" in res.reason
    assert fx.cosigned == []
    assert book.available() == C(50)           # released + refunded


def test_cosign_raises_is_handled():
    fx = _FX(_W(100), cosign_raises=True)
    co, book = _coord(fx, wallet=fx.w)
    res = co.subcontract(_task(10.0))
    assert not res.ok and "cosign raised" in res.reason
    assert book.available() == C(50)


def test_post_raises_releases_and_refunds():
    fx = _FX(_W(100), post_raises=True)
    co, book = _coord(fx, wallet=fx.w)
    res = co.subcontract(_task(10.0))
    assert not res.ok and "post failed" in res.reason
    assert fx.cosigned == []
    assert book.available() == C(50)


# ----------------------------------------------------------------------
# Late/duplicate delivery for an already-terminal reservation:
# never re-verify, never re-pay.
# ----------------------------------------------------------------------

def test_duplicate_terminal_delivery_is_ignored():
    holder = {}

    def terminalize(wid):
        # simulate a concurrent path having already settled this wid
        holder["book"].settle(wid)

    fx = _FX(_W(100), terminalize_during_await=terminalize)
    co, book = _coord(fx, wallet=fx.w)
    holder["book"] = book
    res = co.subcontract(_task(10.0))
    assert not res.ok and "duplicate/late delivery ignored" in res.reason
    assert fx.cosigned == []                    # NOT paid again
