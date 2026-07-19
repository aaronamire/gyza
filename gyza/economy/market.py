"""
Bonded-assertion market — settlement-primary truth maintenance for a
decentralized agent collective.

WHY THIS EXISTS
---------------
The consensus-lab experiments (``gyza.demo.consensus_lab``) showed that
every *detection*-primary mechanism — majority, confidence-weighting,
trimmed aggregation, receiver-side scoring, peer-prediction — collapses
(and peer-prediction actively inverts) once honest agents share a
correlated blind spot that is a majority. The one mechanism that
recovered truth in that regime was a *settlement*-primary bonded market:
agents stake capital on their claims, a sparse ground-truth oracle
settles, and capital — hence decision influence — flows to the agents
who are repeatedly right. With even 5% of rounds resolved, a
confidently-wrong majority is bankrupted and accuracy recovers; with 0%
resolution it stays at chance (Gao-Wright-Leyton-Brown: no
verification-free free lunch).

Gyza is unusually well-suited to build this because it already has a
bilateral settlement rail and self-sovereign signed identities. This
module is the *multilateral* settlement layer (vNext §8 layer 6's L1)
that the bilateral L0 does not cover.

DESIGN — REAL, NOT A TOY
------------------------
- An ``Assertion`` is a genuinely signed object: canonical JSON → BLAKE3
  → Ed25519, the same discipline as ICP envelopes, verifiable from the
  agent's public key alone.
- Settlement is a **deterministic pure function** of the set of verified
  assertions plus the oracle's truth. Every node that holds the same
  signed assertions computes byte-identical P&L — the same determinism
  the CRDT reconciliation and the bilateral ledger rely on. There is no
  privileged settler to trust.
- Settlement is **conservative** (zero-sum): total capital is invariant
  across a resolve. Winners recover their stake plus a pro-rata share of
  the losers' stakes; losers forfeit their stake.
- A **diversity gate** implements the invariant the experiments proved
  necessary: a capital-weighted decision drawn from a low-diversity
  (monoculture) pool is flagged untrusted, because no scoring survives
  that regime.

HONEST LIMITS
-------------
This mechanism needs an occasional ground-truth signal (an oracle, a
spot-check, a deferred verification); with none, it cannot beat a
correlated majority — that is a theorem, not an implementation gap.
Influence follows capital (plutocratic by construction): that is the
reallocation mechanism *and* a risk (capital requirements, bribery); it
is a backstop-and-diversity design, not a standalone guarantee.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gyza.identity import AgentIdentity


# ======================================================================
# Signed assertion
# ======================================================================

@dataclass(frozen=True)
class Assertion:
    agent_pubkey: str
    task_id: str
    claim: str
    stake: float
    nonce: str
    signature: str = ""


def _assertion_digest(
    agent_pubkey: str, task_id: str, claim: str, stake: float, nonce: str,
) -> bytes:
    payload = json.dumps(
        {
            "agent_pubkey": agent_pubkey,
            "claim": claim,
            "nonce": nonce,
            "stake": stake,
            "task_id": task_id,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return blake3.blake3(payload).digest()


def sign_assertion(
    identity: AgentIdentity, task_id: str, claim: str, stake: float,
    *, nonce: str | None = None,
) -> Assertion:
    """Bond ``stake`` on ``claim`` for ``task_id``, signed by ``identity``."""
    if stake <= 0:
        raise ValueError("stake must be positive")
    nonce = nonce or secrets.token_hex(8)
    digest = _assertion_digest(identity.pubkey_hex, task_id, claim, stake, nonce)
    sig = identity.sign_bytes(digest)
    return Assertion(identity.pubkey_hex, task_id, claim, stake, nonce, sig)


def verify_assertion(a: Assertion) -> bool:
    """True iff ``a``'s signature verifies under its own agent_pubkey and
    the stake is positive. Verifiable by anyone, no trust in the market."""
    if a.stake <= 0 or not a.signature:
        return False
    digest = _assertion_digest(a.agent_pubkey, a.task_id, a.claim, a.stake, a.nonce)
    try:
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(a.agent_pubkey))
        pk.verify(bytes.fromhex(a.signature), digest)
        return True
    except (InvalidSignature, ValueError):
        return False


# ======================================================================
# Settlement — a deterministic pure function of assertions + truth
# ======================================================================

@dataclass(frozen=True)
class Settlement:
    task_id: str
    truth: str
    pnl: dict[str, float]          # agent_pubkey -> net change (stake basis)
    pot: float                     # total forfeited by losers
    winners: tuple[str, ...]
    losers: tuple[str, ...]
    refunded: bool                 # True when nobody was correct (all refunded)


def settle(assertions: list[Assertion], truth: str) -> Settlement:
    """
    Deterministically settle a task. Pure: no capital state, no signing
    authority — any holder of the same verified assertions and the same
    ``truth`` computes the identical result.

    Winners (claim == truth) recover their stake and split the losers'
    pot pro-rata to stake; losers forfeit their stake. If no assertion
    was correct, everyone is refunded (nothing to settle against),
    keeping capital conserved.
    """
    # One assertion per agent per task counts (last-wins is a policy
    # choice; equivocation across assertions is caught upstream by
    # gyza.resilience.detect_equivocation over the signed envelopes).
    verified = [a for a in assertions if verify_assertion(a)]
    winners = [a for a in verified if a.claim == truth]
    losers = [a for a in verified if a.claim != truth]

    pnl: dict[str, float] = {a.agent_pubkey: 0.0 for a in verified}
    if not winners:
        # No correct participant → refund all (net zero).
        return Settlement(
            task_id=verified[0].task_id if verified else "",
            truth=truth, pnl=pnl, pot=0.0, winners=(), losers=(),
            refunded=True,
        )

    pot = sum(a.stake for a in losers)
    win_stake = sum(a.stake for a in winners)
    for a in losers:
        pnl[a.agent_pubkey] -= a.stake
    for a in winners:
        pnl[a.agent_pubkey] += pot * (a.stake / win_stake)

    return Settlement(
        task_id=verified[0].task_id,
        truth=truth, pnl=pnl, pot=pot,
        winners=tuple(a.agent_pubkey for a in winners),
        losers=tuple(a.agent_pubkey for a in losers),
        refunded=False,
    )


# ======================================================================
# Diversity gate — the invariant the experiments proved necessary
# ======================================================================

def pairwise_diversity(answer_history: dict[str, dict[str, str]]) -> float:
    """
    Average pairwise disagreement across the agents' answer history.

    ``answer_history[agent][task] = claim``. For each pair of agents the
    fraction of commonly-answered tasks on which they disagreed; averaged
    over all pairs. 0.0 = perfect monoculture, higher = more diverse.
    """
    agents = list(answer_history)
    if len(agents) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(len(agents)):
        for j in range(i + 1, len(agents)):
            a, b = answer_history[agents[i]], answer_history[agents[j]]
            shared = set(a) & set(b)
            if not shared:
                continue
            disagree = sum(1 for t in shared if a[t] != b[t]) / len(shared)
            total += disagree
            pairs += 1
    return total / pairs if pairs else 0.0


@dataclass(frozen=True)
class Decision:
    claim: str | None          # capital-weighted winner, None if no assertions
    capital_weight: dict[str, float]  # claim -> summed capital behind it
    diversity: float
    trusted: bool              # False when diversity is below the gate


# ======================================================================
# The market
# ======================================================================

class BondedMarket:
    """
    A capital ledger plus per-task escrow. Influence follows capital;
    settlement reallocates it toward agents who are repeatedly right.
    """

    def __init__(
        self, initial_capital: dict[str, float], *,
        diversity_threshold: float = 0.1,
    ) -> None:
        self._capital: dict[str, float] = dict(initial_capital)
        self._threshold = diversity_threshold
        self._open: dict[str, list[Assertion]] = {}
        self._escrow: dict[str, dict[str, float]] = {}
        # agent -> {task -> claim}, for the diversity gate
        self._history: dict[str, dict[str, str]] = {}

    # -- capital views -------------------------------------------------------

    def capital_of(self, pubkey: str) -> float:
        return self._capital.get(pubkey, 0.0)

    def total_capital(self) -> float:
        return sum(self._capital.values())

    # -- open-task introspection (for the resolution layer) ------------------

    def open_task_ids(self) -> list[str]:
        return list(self._open)

    def assertions_on(self, task_id: str) -> list[Assertion]:
        return list(self._open.get(task_id, []))

    def contested_stake(self, task_id: str) -> float:
        """
        Stake that would *change hands* if this task settled — the total
        escrowed minus the stake on the plurality claim. High when a lot
        of capital is bet against the leading answer; zero when unanimous.
        The resolution layer targets high-contested-stake tasks so the
        scarce ground-truth budget is spent where it moves the most.
        """
        escrow = self._escrow.get(task_id, {})
        if not escrow:
            return 0.0
        by_claim: dict[str, float] = {}
        for a in self._open.get(task_id, []):
            by_claim[a.claim] = by_claim.get(a.claim, 0.0) + escrow.get(
                a.agent_pubkey, 0.0
            )
        total = sum(by_claim.values())
        return total - max(by_claim.values()) if by_claim else 0.0

    # -- submission ----------------------------------------------------------

    def submit(self, a: Assertion) -> bool:
        """
        Accept an assertion iff it verifies and the agent can cover the
        stake; escrow the stake from the agent's capital. Returns False
        (no state change) otherwise.
        """
        if not verify_assertion(a):
            return False
        if a.agent_pubkey in self._escrow.get(a.task_id, {}):
            return False  # one bonded assertion per agent per task
        if self._capital.get(a.agent_pubkey, 0.0) < a.stake:
            return False
        self._capital[a.agent_pubkey] -= a.stake
        self._open.setdefault(a.task_id, []).append(a)
        self._escrow.setdefault(a.task_id, {})[a.agent_pubkey] = (
            self._escrow.get(a.task_id, {}).get(a.agent_pubkey, 0.0) + a.stake
        )
        self._history.setdefault(a.agent_pubkey, {})[a.task_id] = a.claim
        return True

    # -- decision ------------------------------------------------------------

    def decide(self, task_id: str) -> Decision:
        """
        Capital-weighted collective claim for a task, plus a diversity
        verdict. Weight is each asserting agent's *current* capital, so a
        bankrupted (repeatedly-wrong) agent loses decision influence.
        """
        weight: dict[str, float] = {}
        for a in self._open.get(task_id, []):
            weight[a.claim] = weight.get(a.claim, 0.0) + self._capital.get(
                a.agent_pubkey, 0.0
            ) + self._escrow.get(task_id, {}).get(a.agent_pubkey, 0.0)
        claim = max(weight, key=lambda k: weight[k]) if weight else None
        div = pairwise_diversity(self._history)
        return Decision(claim, weight, div, div >= self._threshold)

    # -- resolution ----------------------------------------------------------

    def resolve(self, task_id: str, truth: str) -> Settlement:
        """
        Settle a task against ``truth``: release escrow and apply the
        deterministic ``settle`` P&L to capital. Conservative — total
        capital is unchanged.
        """
        assertions = self._open.pop(task_id, [])
        escrow = self._escrow.pop(task_id, {})
        s = settle(assertions, truth)
        if s.refunded:
            for pk, amt in escrow.items():
                self._capital[pk] = self._capital.get(pk, 0.0) + amt
            return s
        # Return each agent's own stake, then apply net P&L (which is
        # measured on a stake basis: winners += share of pot, losers -=
        # stake). Returning stake + pnl nets to: winners keep stake+share,
        # losers keep 0 — capital conserved.
        for pk, amt in escrow.items():
            self._capital[pk] = self._capital.get(pk, 0.0) + amt + s.pnl.get(pk, 0.0)
        return s

    def cancel(self, task_id: str) -> None:
        """
        Refund all escrow for an unsettled task — the honest behaviour
        when no ground-truth signal ever arrives (the market cannot
        settle a claim it can never check, so it must not confiscate the
        bond). Conservative: capital is restored exactly.
        """
        escrow = self._escrow.pop(task_id, {})
        self._open.pop(task_id, None)
        for pk, amt in escrow.items():
            self._capital[pk] = self._capital.get(pk, 0.0) + amt


__all__ = [
    "Assertion",
    "sign_assertion",
    "verify_assertion",
    "Settlement",
    "settle",
    "pairwise_diversity",
    "Decision",
    "BondedMarket",
]
# (cancel is a method of BondedMarket)
