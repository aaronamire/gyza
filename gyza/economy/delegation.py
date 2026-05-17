"""
Compositional boundedness — the safety floor under subcontracting.

This is the central safety mechanism of the whole vision, made
real and testable BEFORE the stateful subcontract loop that will
depend on it (the same discipline that built the bounds predicate
before the brick-3 gate, and the wallet before any consumer).

THE CLAIM IT MAKES REAL
-----------------------
"Bounds compose upward." When agent A subcontracts a subtask to
A', and A' to A'', the *composite* must be no wider than A's own
declared manifest — otherwise A could launder capability it does
not itself possess through a chain of subcontractors. The
guarantee is: at every edge of the delegation DAG,

    enforcement(child) ⊆ manifest(child)
                       ⊆ delegated_authority(parent)
                       ⊆ manifest(parent)

Apply ONE subset predicate to EVERY edge and full transitive
boundedness falls out — including, for free, that a capped
ancestor forces every descendant capped no higher (the memory
asymmetry composes correctly: an `outer` with a hard cap forces
`inner` to declare a cap ≤ it, so cap-ness propagates strictly
downward along the chain).

RELATIONSHIP TO enforcement_satisfies_manifest
----------------------------------------------
Same idea, generalized. We do NOT refactor
``gyza.sandbox.config.enforcement_satisfies_manifest``: it is
security-critical, on the brick-3 signing hot path, and locked by
many tests; sharing code into it for elegance would risk it for no
functional gain. The ~15 lines of subset logic recur here
deliberately — the two call sites have different message
contracts, and coupling them would be the worse engineering.

SCOPE / PRECONDITION
--------------------
This module decides *only* "do the bounds compose, is there a
cycle, is the depth sane". It does NOT verify signatures or
envelope-hash linkage — that is ``gyza.icp.verify_chain``'s job and
is an orthogonal predicate over the same DAG. ``verify_delegation``
must be composed *after* a successful ``verify_chain``; it assumes
a cryptographically intact chain and reasons only about capability
containment. Conflating the two would be a modeling error.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# A delegation chain deeper than this is treated as a runaway
# (goal/agent self-replication without a decreasing budget — the §9
# ladder's dangerous rung). The subcontract loop will also enforce a
# strictly-decreasing credit budget; depth is the cheap structural
# backstop. Conservative on purpose; raise deliberately, never
# silently.
MAX_DELEGATION_DEPTH = 8


@dataclass(frozen=True)
class CapabilitySpec:
    """
    The common shape over which containment is decided. A manifest,
    an enforcement record, and a delegated-authority grant are all
    projected to this so ONE predicate covers every edge.

    ``network`` is a single bool: for a manifest it means "network
    is permitted at all" (allowed_hosts non-empty); for an
    enforcement record it means "the sandbox opened the network".
    ``mem_cap`` is None ⇔ "no hard cap declared" — the asymmetry
    below hangs on that distinction.
    """

    ro: frozenset[str] = field(default_factory=frozenset)
    rw: frozenset[str] = field(default_factory=frozenset)
    network: bool = False
    mem_cap: int | None = None

    def to_canonical(self) -> dict:
        """Deterministic dict for signing. Paths are SORTED LISTS —
        frozenset iteration order is not stable, so canonicalization
        MUST sort or the signature is non-reproducible."""
        return {
            "ro": sorted(self.ro),
            "rw": sorted(self.rw),
            "network": bool(self.network),
            "mem_cap": self.mem_cap,
        }

    @classmethod
    def from_canonical(cls, d: object) -> "CapabilitySpec":
        if not isinstance(d, dict):
            return cls()
        mem = d.get("mem_cap")
        return cls(
            ro=_strset(d.get("ro", [])),
            rw=_strset(d.get("rw", [])),
            network=bool(d.get("network")),
            mem_cap=mem if isinstance(mem, int) and mem > 0 else None,
        )


def _strset(xs) -> frozenset[str]:
    if not isinstance(xs, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(str(p) for p in xs if p)


def spec_from_manifest(manifest: dict) -> CapabilitySpec:
    caps = manifest.get("capabilities", {}) if isinstance(manifest, dict) else {}
    if not isinstance(caps, dict):
        caps = {}
    fs = caps.get("filesystem", {}) if isinstance(caps.get("filesystem"), dict) else {}
    net = caps.get("network", {}) if isinstance(caps.get("network"), dict) else {}
    spawn = caps.get("spawn", {}) if isinstance(caps.get("spawn"), dict) else {}
    budget = (
        spawn.get("resource_budget", {})
        if isinstance(spawn.get("resource_budget"), dict)
        else {}
    )
    mem = budget.get("memory_limit_mb")
    return CapabilitySpec(
        ro=_strset(fs.get("read", [])),
        rw=_strset(fs.get("write", [])),
        network=bool(net.get("allowed_hosts")),
        mem_cap=mem if isinstance(mem, int) and mem > 0 else None,
    )


def spec_from_enforcement(enf: dict) -> CapabilitySpec:
    if not isinstance(enf, dict):
        # No enforcement record ≙ the widest possible claim: model it
        # as a spec that fails containment against anything non-trivial
        # (huge — caller's subset check rejects). Represented as
        # network=True + a sentinel; simpler to let callers treat a
        # missing record as an explicit failure upstream. Here we
        # return the most-permissive spec so subset() is conservative.
        return CapabilitySpec(network=True, mem_cap=None)
    em = enf.get("max_memory_mb")
    return CapabilitySpec(
        ro=_strset(enf.get("ro_paths", [])),
        rw=_strset(enf.get("rw_paths", [])),
        network=bool(enf.get("requires_network")),
        mem_cap=em if isinstance(em, int) and em > 0 else None,
    )


def capability_subset(
    inner: CapabilitySpec, outer: CapabilitySpec
) -> tuple[bool, str]:
    """
    Is ``inner`` no wider than ``outer`` (inner ⊆ outer)? A tighter
    inner is always safe; a wider one — on ANY dimension — is a
    violation. Returns ``(ok, reason)``.

    Memory is asymmetric on purpose and this asymmetry is what makes
    boundedness compose: if ``outer`` declares a hard cap then
    ``inner`` MUST declare one too (refusing "unbounded under a
    declared cap" — otherwise omission would launder the bound) and
    it must be ≤ outer's. If ``outer`` declares no cap, inner is
    unconstrained on memory. Applied at every edge, a capped
    ancestor therefore forces every descendant capped ≤ it.
    """
    if not inner.ro <= outer.ro:
        return False, (
            f"read paths exceed the grant: {sorted(inner.ro - outer.ro)}"
        )
    if not inner.rw <= outer.rw:
        return False, (
            f"write paths exceed the grant: {sorted(inner.rw - outer.rw)}"
        )
    if inner.network and not outer.network:
        return False, "uses the network but the grant does not permit it"
    if outer.mem_cap is not None:
        if inner.mem_cap is None:
            return False, (
                f"grant caps memory at {outer.mem_cap} MB but the inner "
                f"spec declares no cap"
            )
        if inner.mem_cap > outer.mem_cap:
            return False, (
                f"memory {inner.mem_cap} MB exceeds the granted cap "
                f"{outer.mem_cap} MB"
            )
    return True, ""


@dataclass(frozen=True)
class DelegationHop:
    """
    One node of the delegation chain, root first. ``delegated`` is
    the authority THIS hop's parent granted to it (None for the
    root, which is bounded only by its own manifest). All three
    specs are already projected via spec_from_* by the caller, so
    this module stays a pure decision function.
    """

    agent_pubkey: str
    manifest: CapabilitySpec
    enforcement: CapabilitySpec
    delegated: CapabilitySpec | None = None


def verify_delegation(
    chain: list[DelegationHop],
    *,
    max_depth: int = MAX_DELEGATION_DEPTH,
) -> tuple[bool, str]:
    """
    Fold compositional boundedness over a delegation chain.

    Precondition: the underlying envelope chain has already passed
    ``gyza.icp.verify_chain`` (signatures + parent-hash linkage
    intact). This function reasons ONLY about capability
    containment, cycles, and depth.

    At every hop h:

      1. enforcement(h) ⊆ manifest(h)            — h stayed in its
         own bounds (the brick-3 property, recursively);
      2. manifest(h) ⊆ delegated(h)              — h was not handed,
         and did not assume, more than its parent granted (this is
         the step that defeats capability-laundering: a
         subcontractor honestly inside its OWN — improperly wide —
         manifest is still caught here);
      3. delegated(h) ⊆ manifest(parent)         — the parent could
         only delegate authority it actually held.

    Plus: no agent_pubkey may appear twice (a delegation cycle is a
    mutual-farm / infinite-recursion attack — same class as the
    RecursiveVerifier cycle guard), and depth ≤ max_depth (runaway
    backstop).
    """
    if not chain:
        return False, "empty delegation chain"
    if len(chain) > max_depth:
        return False, (
            f"delegation depth {len(chain)} exceeds max {max_depth} "
            f"(runaway / unbounded self-replication)"
        )

    seen: set[str] = set()
    prev: DelegationHop | None = None
    for i, h in enumerate(chain):
        if h.agent_pubkey in seen:
            return False, (
                f"delegation cycle: {h.agent_pubkey[:16]}… appears twice "
                f"(mutual-farm / infinite-recursion attack)"
            )
        seen.add(h.agent_pubkey)

        ok, why = capability_subset(h.enforcement, h.manifest)
        if not ok:
            return False, f"hop {i}: enforcement exceeds manifest — {why}"

        if i == 0:
            if h.delegated is not None:
                return False, "root hop must not carry a delegated grant"
            prev = h
            continue

        if h.delegated is None:
            return False, f"hop {i}: non-root hop missing its delegated grant"

        ok, why = capability_subset(h.manifest, h.delegated)
        if not ok:
            return False, (
                f"hop {i}: manifest exceeds what the parent delegated "
                f"— {why} (capability-laundering blocked)"
            )

        assert prev is not None
        ok, why = capability_subset(h.delegated, prev.manifest)
        if not ok:
            return False, (
                f"hop {i}: parent delegated more than it held — {why}"
            )
        prev = h

    return True, ""


# ---------------------------------------------------------------------------
# DelegationGrant — the signed wire record of a delegation.
#
# Chosen over a new ICPEnvelope field (the schema bump) and over
# overloading parent_envelope_hash (the modeling error): a separate
# signed artifact keeps the signed envelope schema UNTOUCHED (honors
# the §8 forward-compat commitment — no re-sign of existing
# envelopes) and keeps the two relationships distinct.
#
# Authenticity vs. soundness vs. integrity are three orthogonal
# predicates over the same DAG, deliberately not conflated:
#   * verify_chain (icp.py)  — the envelope chain is intact (sigs +
#     hash linkage);
#   * verify_grant (here)    — the parent really signed THIS grant
#     of THIS authority for THIS child work-item at THIS point in
#     its chain;
#   * verify_delegation      — given the above, the bounds compose
#     (child.manifest ⊆ delegated ⊆ parent.manifest), no cycle,
#     bounded depth.
#
# Design decision (subtle, deliberate): a grant delegates authority
# TO A WORK-ITEM, not to a specific agent. Whoever claims the child
# work-item operates under ≤ delegated_authority; bounds still
# compose because verify_delegation requires the claimer's manifest
# ⊆ delegated regardless of who they are. Binding to a fixed child
# pubkey would break the open subcontract market for no safety gain.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DelegationGrant:
    parent_envelope_hash: str      # anchors to a point in parent's chain
    parent_agent_pubkey: str       # the granter (sig key + cycle id)
    parent_manifest_hash: str      # must == parent envelope's manifest hash
    child_work_item_id: str        # binds the grant to THIS subtask
    delegated_authority: dict      # CapabilitySpec.to_canonical()
    created_at_ns: int
    schema_version: int = 1        # its OWN versioning; ICPEnvelope untouched
    signature: str = ""


def _grant_payload_bytes(g: DelegationGrant) -> bytes:
    """Canonical JSON of every field except `signature` — IDENTICAL
    convention to icp._payload_bytes (one canonicalization rule
    across the codebase)."""
    d = asdict(g)
    d.pop("signature", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def grant_hash(g: DelegationGrant) -> str:
    return blake3.blake3(_grant_payload_bytes(g)).hexdigest()


def sign_grant(g: DelegationGrant, parent_agent_seed: bytes) -> DelegationGrant:
    """
    Sign as the parent agent. Sign-the-hash (BLAKE3 digest), 32-byte
    Ed25519 seed — exactly icp.sign_envelope's contract. Returns a
    fresh instance so the caller's original stays unsigned.
    """
    if len(parent_agent_seed) != 32:
        raise ValueError(
            f"Ed25519 seed must be 32 bytes, got {len(parent_agent_seed)}"
        )
    sk = Ed25519PrivateKey.from_private_bytes(parent_agent_seed)
    sig = sk.sign(blake3.blake3(_grant_payload_bytes(g)).digest()).hex()
    fields = asdict(g)
    fields["signature"] = sig
    return DelegationGrant(**fields)


def verify_grant(g: DelegationGrant) -> tuple[bool, str]:
    """
    Authenticity only: the embedded ``parent_agent_pubkey`` really
    signed this exact grant. Does NOT check that the grant binds to a
    real parent envelope, nor that the bounds compose — those are
    ``grant_binds_to`` and ``verify_delegation`` respectively, kept
    separate on purpose.
    """
    if not isinstance(g.parent_agent_pubkey, str) or not g.parent_agent_pubkey:
        return False, "grant missing parent_agent_pubkey"
    if not isinstance(g.delegated_authority, dict):
        return False, "grant delegated_authority is not a dict"
    if not g.signature:
        return False, "grant is unsigned"
    try:
        sig = bytes.fromhex(g.signature)
        pk = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(g.parent_agent_pubkey)
        )
    except ValueError:
        return False, "grant signature or pubkey is not valid hex"
    try:
        pk.verify(sig, blake3.blake3(_grant_payload_bytes(g)).digest())
    except (InvalidSignature, ValueError):
        return False, "grant signature does not verify"
    return True, ""


def grant_binds_to(
    g: DelegationGrant,
    *,
    parent_envelope_hash: str,
    parent_agent_pubkey: str,
    parent_capability_manifest_hash: str,
    child_work_item_id: str,
) -> tuple[bool, str]:
    """
    Binding: this authenticated grant actually corresponds to the
    parent envelope / agent / manifest / subtask it claims. Caller
    passes the primitives off the *actual* parent envelope (kept as
    primitives so this module stays free of an icp.ICPEnvelope
    import). Defeats: replay onto another subtask, anchoring to a
    different parent point, and grant/manifest decoupling (a parent
    signing a grant referencing a manifest different from the one
    its envelope binds).
    """
    if g.parent_envelope_hash != parent_envelope_hash:
        return False, "grant is anchored to a different parent envelope"
    if g.parent_agent_pubkey != parent_agent_pubkey:
        return False, "grant granter ≠ parent envelope's agent"
    if g.parent_manifest_hash != parent_capability_manifest_hash:
        return False, (
            "grant's parent_manifest_hash ≠ parent envelope's "
            "capability_manifest_hash (grant/manifest decoupling)"
        )
    if g.child_work_item_id != child_work_item_id:
        return False, "grant is for a different child work-item (replay)"
    return True, ""


__all__ = [
    "MAX_DELEGATION_DEPTH",
    "CapabilitySpec",
    "DelegationGrant",
    "DelegationHop",
    "capability_subset",
    "grant_binds_to",
    "grant_hash",
    "sign_grant",
    "spec_from_enforcement",
    "spec_from_manifest",
    "verify_delegation",
    "verify_grant",
]
