"""
Resolution layer — accountable, minimal ground-truth injection for the
bonded market.

THE DEPENDENCY THIS FILLS
-------------------------
The bonded market (``gyza.economy.market``) has exactly one theorem-
mandated dependency: without some ground-truth signal it cannot beat a
correlated-wrong majority (Gao-Wright-Leyton-Brown — no verification-free
free lunch). The consensus-lab experiments confirmed it: 0% resolution
leaves the market at chance; sparse resolution recovers it. This layer
supplies that signal — but in a way that is accountable and minimal:

  * **Accountable** — the truth used to settle is itself a SIGNED
    attestation (a ``Verdict``), attributable to the resolver's key.
    A corrupt oracle cannot settle arbitrarily without leaving evidence,
    and a high-stakes deployment can require a *quorum* of independent
    verdicts (the design leaves room; a single signed verdict is
    implemented here).
  * **Minimal** — resolution is SPARSE and TARGETED. Rather than
    resolving randomly, target the tasks with the highest *contested
    stake* (where the most capital would change hands), so the scarce
    ground-truth budget buys the most influence-reallocation per check.

HONEST FRAMING
--------------
This does not manufacture truth from nothing — that is impossible. It
makes the *required* truth-injection (a) accountable, (b) sample-
efficient, and (c) composable with Gyza's execution substrate: a
``Resolver``'s checker can be a human spot-check, a tool/oracle call, or
— the Gyza-native case — a bounded, bounds-proven sandbox re-execution
of a checkable claim, so the ground truth is itself a signed, auditable
computation.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Callable, Protocol

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gyza.economy.market import BondedMarket
from gyza.identity import AgentIdentity


# ======================================================================
# Signed verdict — the truth used to settle is itself accountable
# ======================================================================

@dataclass(frozen=True)
class Verdict:
    task_id: str
    truth: str
    resolver_pubkey: str
    method: str            # "oracle" | "reexecution" | "spot-check" | ...
    signature: str = ""


def _verdict_digest(task_id: str, truth: str, resolver_pubkey: str, method: str) -> bytes:
    payload = json.dumps(
        {
            "method": method,
            "resolver_pubkey": resolver_pubkey,
            "task_id": task_id,
            "truth": truth,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return blake3.blake3(payload).digest()


def sign_verdict(
    identity: AgentIdentity, task_id: str, truth: str, *, method: str,
) -> Verdict:
    digest = _verdict_digest(task_id, truth, identity.pubkey_hex, method)
    return Verdict(task_id, truth, identity.pubkey_hex, method,
                   identity.sign_bytes(digest))


def verify_verdict(v: Verdict) -> bool:
    if not v.signature:
        return False
    digest = _verdict_digest(v.task_id, v.truth, v.resolver_pubkey, v.method)
    try:
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(v.resolver_pubkey))
        pk.verify(bytes.fromhex(v.signature), digest)
        return True
    except (InvalidSignature, ValueError):
        return False


# ======================================================================
# Resolver — pluggable ground-truth source that signs what it attests
# ======================================================================

class Resolver(Protocol):
    def resolve(self, task_id: str, claims: set[str]) -> Verdict | None:
        """Return a signed Verdict for ``task_id``, or None if the truth
        is not (yet) checkable. ``claims`` is the set of asserted answers,
        so a checker can short-circuit when the truth isn't among them."""
        ...


class OracleResolver:
    """
    A resolver backed by a ``checker`` — a callable that returns the true
    claim for a task, or None if unknowable. The checker is where the
    ground truth actually comes from: a spot-check, a tool/oracle call,
    or a sandboxed re-execution of a checkable claim. Whatever it is, the
    verdict it produces is signed by this resolver's identity, so the
    truth is attributable.
    """

    def __init__(self, identity: AgentIdentity,
                 checker: Callable[[str], str | None], *, method: str = "oracle"):
        self._identity = identity
        self._checker = checker
        self._method = method

    def resolve(self, task_id: str, claims: set[str]) -> Verdict | None:
        truth = self._checker(task_id)
        if truth is None:
            return None
        return sign_verdict(self._identity, task_id, truth, method=self._method)


# ======================================================================
# Selection policy — spend the scarce resolution budget where it matters
# ======================================================================

def select_targeted(market: BondedMarket, budget: int) -> list[str]:
    """The ``budget`` open tasks with the highest contested stake."""
    tasks = market.open_task_ids()
    tasks.sort(key=lambda t: market.contested_stake(t), reverse=True)
    return tasks[:budget]


def select_random(market: BondedMarket, budget: int,
                  rng: random.Random) -> list[str]:
    tasks = market.open_task_ids()
    rng.shuffle(tasks)
    return tasks[:budget]


# ======================================================================
# Driver — settle what the resolver can verify, refund the rest
# ======================================================================

@dataclass
class ResolutionOutcome:
    verdicts: list[Verdict]
    settled: list[str]
    refunded: list[str]


def resolve_round(market: BondedMarket, resolver: Resolver,
                  task_ids: list[str]) -> ResolutionOutcome:
    """
    For each selected task, ask the resolver for a signed verdict; settle
    the market against a *verified* verdict, or refund (cancel) when the
    truth is not checkable. A verdict that fails signature verification is
    treated as no resolution — never trusted.
    """
    verdicts: list[Verdict] = []
    settled: list[str] = []
    refunded: list[str] = []
    for t in task_ids:
        claims = {a.claim for a in market.assertions_on(t)}
        v = resolver.resolve(t, claims)
        if v is not None and verify_verdict(v) and v.task_id == t:
            market.resolve(t, v.truth)
            verdicts.append(v)
            settled.append(t)
        else:
            market.cancel(t)
            refunded.append(t)
    return ResolutionOutcome(verdicts, settled, refunded)


__all__ = [
    "Verdict",
    "sign_verdict",
    "verify_verdict",
    "Resolver",
    "OracleResolver",
    "select_targeted",
    "select_random",
    "ResolutionOutcome",
    "resolve_round",
]
