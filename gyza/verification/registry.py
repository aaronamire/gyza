"""
V-1 verifier registry and V-4 partial-spec registry.

Both live in the SIGNED GUARD CONFIGURATION's trust domain (C-8) and are
versioned with it. A verifier the constrained system can install for itself is
not a verifier, for the same reason a guard it can rewrite is not a guard: the
containment argument is an induction, and an agent that edits the checker
removes the inductive step.

V-4 additionally refuses MODEL-AUTHORED specs. This is not squeamishness, it is
R14's measured result (C11): asked to specify problems they could not solve,
models produced specs whose unconditional mutation kill rate was 0.1177 against
a TYPE-ONLY floor of 0.2864 -- **below a one-line isinstance check**. A spec
registry that accepts model-authored entries is a registry whose median entry is
worse than no spec at all. Specs are HUMAN-AUTHORED, ONE PER CLAIM TYPE, which
is the only thing that makes the cost bearable: types are few even when
instances are many.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from gyza.containment.invariants import InvariantClass, UntaggedInvariantError


class AuthorshipError(RuntimeError):
    """Raised when a spec lacks a human-authorship attestation."""


class RegistryVersionError(RuntimeError):
    """Raised on a downgrade. Same discipline as C-8's bounds."""


@dataclass(frozen=True)
class Verifier:
    """A NATIVE verifier: a mechanical postcondition that RECOMPUTES the
    property. Carrier = PROOF, which is what makes it compose (SR-3)."""
    claim_type: str
    fn: Callable[..., bool]
    witness: str                   # file:line of the production implementation


@dataclass(frozen=True)
class PartialSpec:
    """A human-authored partial property over a CLAIM TYPE."""
    claim_type: str
    fn: Callable[..., bool]
    cls: InvariantClass
    authored_by: str               # a human identifier
    human_attested: bool
    rationale: str


class VerifierRegistry:
    def __init__(self, version: int = 1):
        self._v: dict[str, Verifier] = {}
        self.version = version

    def register(self, v: Verifier) -> None:
        if v.claim_type in self._v:
            raise ValueError(f"verifier for {v.claim_type!r} already registered")
        if not v.witness:
            raise ValueError(
                f"verifier for {v.claim_type!r} cites no implementation; an "
                f"uncited verifier cannot be audited")
        self._v[v.claim_type] = v

    def __contains__(self, ct: str) -> bool:
        return ct in self._v

    def get(self, ct: str) -> Verifier:
        return self._v[ct]

    def claim_types(self) -> list[str]:
        return sorted(self._v)

    def load_version(self, version: int) -> None:
        if version <= self.version:
            raise RegistryVersionError(
                f"refusing version {version} over {self.version}: registry "
                f"versions are monotone (a downgrade reinstates removed checks)")
        self.version = version


class PartialSpecRegistry:
    def __init__(self, version: int = 1):
        self._s: dict[str, PartialSpec] = {}
        self.version = version

    def register(self, s: PartialSpec) -> None:
        if not s.human_attested:
            raise AuthorshipError(
                f"spec for {s.claim_type!r} carries no human-authorship "
                f"attestation and is REFUSED. Model-authored specs measured "
                f"BELOW a one-line type check (R14: unconditional kill 0.1177 "
                f"vs type-only floor 0.2864); a registry that accepts them is "
                f"worse than an empty one.")
        if not isinstance(s.cls, InvariantClass):
            raise UntaggedInvariantError(
                f"spec for {s.claim_type!r} carries no valid class tag; the "
                f"scheduler reads the tag to decide concurrency (C6/C7)")
        if not s.authored_by:
            raise AuthorshipError("a human attestation needs a human")
        self._s[s.claim_type] = s

    def __contains__(self, ct: str) -> bool:
        return ct in self._s

    def get(self, ct: str) -> PartialSpec:
        return self._s[ct]

    def claim_types(self) -> list[str]:
        return sorted(self._s)

    def load_version(self, version: int) -> None:
        if version <= self.version:
            raise RegistryVersionError(
                f"refusing version {version} over {self.version}: monotone")
        self.version = version
