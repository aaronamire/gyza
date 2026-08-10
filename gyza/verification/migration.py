"""Structural migration of the ungoverned registry into the authority.

WHAT THIS FILE IS, AND THE ONE THING IT DELIBERATELY DOES NOT CONTAIN.

Every entry below carries its STRUCTURE — claim type, success condition,
carrier with a stated basis, invariant class, and whether its reference set can
move. **None of them carries an attestation, and none was written by the agent
that classified them.**

That omission is the point. R14 (C11) measured that models asked to specify
problems they could not solve produced specs whose unconditional kill rate was
0.1177 against a TYPE-ONLY floor of 0.2864 — below a one-line isinstance check.
The attestation requirement exists because of that result. An agent supplying
the attestations would defeat the mechanism **at the moment of adoption**, and
would do so invisibly, because a self-asserted attestation is a non-repudiation
record and records whatever it is given.

So the split is: **the agent migrates structure, a human supplies attestation.**
`governed_registry()` admits only the drafts a human has signed off, and an
unattested draft stays out. Five governed entries and sixteen honestly
unmigrated is a better state than twenty-one with fictitious provenance.

CARRIER BASIS. `MEASURED` means the verifier's body plainly recomputes or
plainly samples and the reading is not arguable. `JUDGEMENT` means it is
arguable, and the reason says why. A4 of the authority already established that
no static analysis decides recompute-versus-sample — R12 measured that closing
that gap requires deciding the question the check was meant to replace — so this
column is authored, and its fraction is reported rather than hidden.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from gyza.containment.invariants import InvariantClass
from gyza.verification.authority import (
    Attestation, FrameRef, NotApplicable, SpecAuthority, SpecRecord,
)

MEASURED = "MEASURED"
JUDGEMENT = "JUDGEMENT"
UNCLASSIFIABLE = "UNCLASSIFIABLE"


@dataclass(frozen=True)
class SpecDraft:
    """A spec record with everything filled EXCEPT the attestation.

    `attestation` is not a field here. It cannot be defaulted, cannot be
    inherited, and cannot be supplied by this module — it is passed to
    `governed_registry()` by the caller, or the draft does not migrate.
    """
    claim_type: str
    success_condition: str
    fn: Callable[..., Any] | None
    carrier: str
    carrier_basis: str
    carrier_reason: str
    invariant_class: InvariantClass | NotApplicable
    frame: FrameRef | NotApplicable
    obligations: frozenset[str]
    witness: str
    blocked_reason: str | None = None      # non-attestation blockers only

    @property
    def structurally_ready(self) -> bool:
        return self.blocked_reason is None and self.fn is not None

    def to_record(self, attestation: Attestation, version: int = 1) -> SpecRecord:
        if self.fn is None:
            raise ValueError(
                f"{self.claim_type!r} has no verifier function; it cannot "
                f"become a SpecRecord (see blocked_reason)")
        return SpecRecord(
            claim_type=self.claim_type,
            success_condition=self.success_condition,
            fn=self.fn,
            carrier=self.carrier,
            invariant_class=self.invariant_class,
            attestation=attestation,
            frame=self.frame,
            obligations=self.obligations,
            version=version,
            witness=self.witness,
        )


def _na(reason: str) -> NotApplicable:
    return NotApplicable(reason)


def _drafts() -> list[SpecDraft]:
    """Built lazily so importing this module does not import every verifier."""
    from gyza.verification.adapters import HUMAN_SPECS, NATIVE, NO_VERIFIER

    by_ct = {v.claim_type: v for v in NATIVE}
    sp = {s.claim_type: s for s in HUMAN_SPECS}
    d: list[SpecDraft] = []

    def native(ct, success, carrier, basis, reason, inv, frame, obligations):
        v = by_ct[ct]
        d.append(SpecDraft(ct, success, v.fn, carrier, basis, reason, inv,
                           frame, frozenset(obligations), v.witness))

    # --- signature / identity: hash and Ed25519 recomputation --------------
    native("envelope_signature",
           "The envelope's Ed25519 signature verifies against the agent pubkey "
           "over the canonical payload hash.",
           "PROOF", MEASURED,
           "delegates to gyza.icp.verify_envelope, which recomputes the "
           "canonical bytes, re-hashes and re-verifies the signature; no "
           "caller-supplied case set exists",
           _na("a per-envelope postcondition, not a quantity that accumulates"),
           _na("both operands are passed by value; there is no set to move"),
           ["signature_verifies_over_canonical_payload"])

    native("manifest_identity",
           "The manifest's canonical hash equals the declared hash.",
           "PROOF", MEASURED,
           "recomputes manifest_hash_hex and compares; a pure function of the "
           "two arguments",
           _na("a per-manifest postcondition"),
           _na("both operands passed by value"),
           ["recomputed_hash_equals_declared"])

    native("artifact_content_address",
           "blake3(data) equals the declared content address.",
           "PROOF", MEASURED,
           "recomputes the digest over the supplied bytes and compares",
           _na("a per-artifact postcondition"),
           _na("the bytes are passed by value"),
           ["recomputed_digest_equals_address"])

    # --- structural verification over a caller-supplied sequence ----------
    native("envelope_chain",
           "Every envelope in the sequence links to its parent and each "
           "signature verifies, over the WHOLE sequence supplied.",
           "PROOF", MEASURED,
           "gyza.icp.verify_chain walks every element; it does not sample",
           _na("a structural postcondition over the sequence, not a budget"),
           FrameRef("chain_head_envelope_hash",
                    "PENDING — the hash of the head envelope pins which chain "
                    "was verified; not currently carried by the claim"),
           ["all_links_resolve", "all_signatures_verify"])

    native("envelope_dag",
           "Every envelope's parents resolve within the supplied set and each "
           "signature verifies. NOTE: closure is NOT checked unless the caller "
           "passes require_closed=True.",
           "PROOF", MEASURED,
           "gyza.icp.verify_dag traverses every node; no sampling",
           _na("a structural postcondition over the supplied set"),
           FrameRef("dag_root_set_digest",
                    "PENDING — nothing currently pins WHICH envelopes were "
                    "supplied; see blocked_reason"),
           ["all_parents_resolve", "all_signatures_verify"])
    d[-1] = SpecDraft(**{**d[-1].__dict__,
                         "blocked_reason":
                         "SUCCESS CONDITION IS NOT FIXED BY THE REGISTRY. The "
                         "adapter forwards **kw to verify_dag, whose "
                         "require_closed defaults to False (gyza/icp.py:220). "
                         "Production calls it BOTH ways -- audit.py:101 and "
                         "demo/ddil_partition.py:616 pass True, "
                         "resilience.py:202 and two demos pass False -- so the "
                         "registered entry proves a DIFFERENT PROPOSITION "
                         "depending on the call site. Split into two claim "
                         "types or bind the kwarg before attesting."})

    # --- capability / authority -------------------------------------------
    native("enforcement_within_manifest",
           "The enforcement record's read set, write set, network flag and "
           "memory cap are all within the signed manifest's.",
           "PROOF", MEASURED,
           "enforcement_satisfies_manifest compares the declared dimensions "
           "directly; a total check over four fields",
           _na("a per-work-item postcondition"),
           _na("both records passed by value"),
           ["read_set_subset", "write_set_subset", "network_not_widened",
            "memory_cap_not_raised"])

    native("delegation_attenuation",
           "For every hop i in the chain, manifest(h_i) is a subset of "
           "manifest(h_0); the chain is acyclic; and its depth is at most "
           "max_depth = 8 (MAX_DELEGATION_DEPTH, gyza/economy/delegation.py). "
           "THE VALUE 8 IS PART OF THE CLAIM: it is a defaulted parameter of "
           "verify_delegation that moves the verdict, and a claim that says "
           "only 'depth is bounded' does not say which bound was checked.",
           "PROOF", MEASURED,
           "verify_delegation iterates every hop; the bound is structural, "
           "not sampled. FIXED-UNNAMED under the carrier rule: max_depth has a "
           "default, but the adapter does not expose it, so the verdict cannot "
           "vary per call site -- PROOF stands, and the remedy is naming the "
           "value here rather than refusing the entry",
           InvariantClass.MONOTONE_NON_CUMULATIVE,
           FrameRef("delegation_root_manifest_hash",
                    "PENDING — the root manifest hash pins the origin the "
                    "attenuation is measured FROM"),
           ["authority_non_increasing_per_hop", "depth_at_most_8", "acyclic"])

    native("ledger_entry_signatures",
           "Every required role signature on the entry verifies over the "
           "entry's canonical sign-bytes.",
           "PROOF", MEASURED,
           "ledger.verify_entry recomputes canonical_sign_bytes per role and "
           "verifies each signature",
           _na("a per-entry postcondition"),
           _na("the entry is passed by value; the ledger supplies keys only"),
           ["all_role_signatures_verify"])

    # --- folds over append-only state --------------------------------------
    native("balance_fold",
           "The net balance derived by folding the supplied entries equals the "
           "declared balance.",
           "PROOF", MEASURED,
           "Wallet(entries).net_balance recomputes the fold over every entry",
           InvariantClass.CONSERVATION,
           FrameRef("ledger_entry_set_digest",
                    "PENDING — which entries were folded is not pinned; a "
                    "balance folded from a moving entry set is not a balance"),
           ["fold_over_all_entries_equals_declared"])

    native("market_capital_fold",
           "The capital derived by folding the market's capital entries for "
           "the pubkey equals the declared amount.",
           "PROOF", MEASURED,
           "sums market.capital_entries() in full; no sampling",
           InvariantClass.CONSERVATION,
           FrameRef("capital_entry_set_digest",
                    "PENDING — and note this set is reached THROUGH the market "
                    "object, so the authority's signature screen does not see "
                    "it (see FINDINGS)"),
           ["fold_over_all_capital_entries_equals_declared"])

    # --- the one that samples ----------------------------------------------
    native("unit_test_execution",
           "The function returns the expected output for every case in the "
           "SUPPLIED FINITE CASE SET, and for nothing else.",
           "TEST", MEASURED,
           "the body is all(fn(x) == y for x, y in cases) -- it is sound "
           "exactly where it sampled and says nothing elsewhere. SR-3 measured "
           "TEST-carriers composing at 0.000",
           _na("a per-case postcondition"),
           _na("the case set IS the claim's scope, not a moving reference"),
           ["all_supplied_cases_pass"])

    # --- respecified out of NO_VERIFIER ------------------------------------
    native("memory_retrieval_relevance",
           "The returned ids are exactly the first k candidates, in descending "
           "metric order, of the pinned corpus snapshot that satisfy the "
           "filter and score >= threshold.",
           "PROOF", MEASURED,
           "verify_retrieval_claim RECOMPUTES the whole neighbour set "
           "(respec.py:122-150) and refuses on corpus-digest mismatch; it does "
           "not sample the ranking",
           _na("a per-query postcondition"),
           FrameRef("corpus_snapshot",
                    "ALREADY CARRIED — RetrievalClaim.corpus_snapshot, checked "
                    "at respec.py:134. This is the working precedent the other "
                    "frames should follow."),
           ["corpus_digest_matches", "membership_exact", "order_exact"])

    native("external_send_content",
           "blake3 of the bytes that ACTUALLY left equals the claimed artifact "
           "hash, and the byte count matches.",
           "PROOF", MEASURED,
           "verify_send_claim recomputes wire_digest over the emitted bytes "
           "(respec.py:204); the hash is not taken from the sender",
           _na("containment ends at emission (C15); nothing accumulates after"),
           _na("the emitted bytes are passed by value"),
           ["wire_digest_matches", "byte_count_matches"])
    d[-1] = SpecDraft(**{**d[-1].__dict__,
                         "blocked_reason":
                         "SUCCESS CONDITION IS NOT FIXED BY THE REGISTRY. The "
                         "`policy` parameter defaults to None "
                         "(respec.py:195), and when it is None the policy "
                         "clause is SKIPPED. So the registered entry verifies "
                         "hash+length alone at some call sites and "
                         "hash+length+policy at others. Bind the policy or "
                         "split the claim type before attesting."})

    # --- human partial specs ------------------------------------------------
    def spec(ct, success, reason, frame, obligations, basis=MEASURED):
        s = sp[ct]
        d.append(SpecDraft(ct, success, s.fn, "SPEC", basis, reason, s.cls,
                           frame, frozenset(obligations),
                           f"[NO WITNESS FIELD] PartialSpec at "
                           f"gyza/verification/adapters.py, authored_by="
                           f"{s.authored_by!r}"))

    spec("hlc_ordering",
         "The successor HLC tuple is >= the predecessor's, componentwise.",
         "the body is a total tuple comparison; it recomputes the ordering "
         "rather than sampling it",
         _na("both timestamps passed by value"),
         ["successor_not_less_than_predecessor"])

    spec("reputation_score",
         "The score lies in the closed interval [0.0, 1.0].",
         "a total range check on one value",
         _na("a single scalar passed by value"),
         ["score_within_unit_interval"])

    spec("work_claim_exclusivity",
         "At most one claim in the supplied set names the given work item.",
         "counts every element of the supplied set; no sampling",
         FrameRef("claim_set_digest",
                  "PENDING — exclusivity counted over a set that can grow "
                  "between claim and check is not exclusivity"),
         ["at_most_one_claim_per_work_item"])

    # --- NO_VERIFIER: enumerated, and NOT registrable -----------------------
    for ct, why in zip(NO_VERIFIER, (
        "restating it as 'output hash = H, checkable by re-execution' "
        "verifies REPRODUCIBILITY and discards the property wanted: a "
        "deterministic wrong program passes every time.",
        "the mechanically checkable restatement (routed to argmax of declared "
        "capability overlap) is known not to deliver -- R11 ROUTER-DEAD "
        "measured failure even with an AUROC-1.000 oracle. Rule 3d: verifiable "
        "and known not to deliver is not a win.",
    )):
        d.append(SpecDraft(
            ct, f"NO MECHANICAL SUCCESS CONDITION EXISTS. {why}",
            None, "NONE", UNCLASSIFIABLE,
            "there is no verifier body to read; the carrier is not "
            "undetermined but ABSENT, which is a different claim",
            _na("no verifier"), _na("no verifier"),
            frozenset({"__none__"}),
            f"[NO VERIFIER] enumerated at gyza/verification/adapters.py "
            f"NO_VERIFIER",
            blocked_reason="IRREDUCIBLY SEMANTIC: no verifier exists to "
                           "govern. Not registrable, and recorded so it is "
                           "not proposed again."))

    return d


DRAFTS: list[SpecDraft] = _drafts()
BY_CLAIM_TYPE: dict[str, SpecDraft] = {x.claim_type: x for x in DRAFTS}


ATTESTATIONS_PATH = Path(__file__).resolve().parent / "attestations.json"


def load_attestations(path: Path | None = None) -> dict[str, Attestation]:
    """Load the OWNER-SUPPLIED attestations. Returns {} if none exist.

    NOT AUTHORED HERE, AND THAT IS THE DESIGN. This function reads a file the
    repository owner wrote; it cannot manufacture one. If the file is absent the
    governed registry is empty, which is the correct state for a standard nobody
    has signed -- an agent filling this in would defeat the mechanism at the
    moment of adoption (R14), and would do it invisibly, because a self-asserted
    attestation records whatever it is given.
    """
    p = path or ATTESTATIONS_PATH
    if not p.exists():
        return {}
    d = json.loads(p.read_text())
    att = Attestation(author=d["attester"], method=d["method"],
                      basis=d["basis"])
    return {ct: att for ct in d["claim_types"]}


def governed_registry(attestations: Mapping[str, Attestation],
                      *, versions: Mapping[str, int] | None = None
                      ) -> tuple[SpecAuthority, list[tuple[str, str]]]:
    """Build the governed registry from drafts a HUMAN has attested.

    Returns `(authority, skipped)` where `skipped` is
    `[(claim_type, reason), ...]`. An unattested draft is skipped, never
    admitted with a placeholder — that is the whole design.
    """
    auth = SpecAuthority()
    versions = versions or {}
    skipped: list[tuple[str, str]] = []
    for draft in DRAFTS:
        if draft.blocked_reason is not None:
            skipped.append((draft.claim_type,
                            f"BLOCKED: {draft.blocked_reason}"))
            continue
        att = attestations.get(draft.claim_type)
        if att is None:
            skipped.append((draft.claim_type, "AWAITING ATTESTATION"))
            continue
        try:
            auth.register(draft.to_record(att, versions.get(draft.claim_type, 1)))
        except Exception as e:                                  # noqa: BLE001
            skipped.append((draft.claim_type, f"{type(e).__name__}: {e}"))
    return auth, skipped


def fallback_scope() -> dict[str, str]:
    """The claim types the ungoverned fallback still covers, and WHY each.

    THE EXPIRY CONDITION, WHICH WAS NEVER ACTUALLY WRITTEN. The DUAL_READ
    policy shipped with marking (`UNGOVERNED FALLBACK` in the routing reason)
    and counting (`TierRouter.governance`), and the test that introduced it says
    "an unmarked fallback is a fallback that never expires" -- but NO expiry
    condition was ever specified. Marking and counting are visibility; they are
    not a termination condition. That is an unenforced invariant inside the
    mechanism built to enforce invariants, and this function is the fix: the
    fallback's scope is now ENUMERATED, so "is the migration finished" has an
    answer instead of a vibe.

    THE FALLBACK MAY BE REMOVED WHEN THIS RETURNS {}. Not before.
    """
    from gyza.verification.adapters import build_registries
    v, s = build_registries()
    ungoverned = set(v.claim_types()) | set(s.claim_types())
    governed = set(governed_registry(load_attestations())[0].claim_types())
    gap = {}
    for ct in sorted(ungoverned - governed):
        d = BY_CLAIM_TYPE.get(ct)
        gap[ct] = (d.blocked_reason if d and d.blocked_reason
                   else "AWAITING ATTESTATION")
    return gap


def governed_router(policy=None):
    """THE LIVE CONSTRUCTION POINT: a router reading the ATTESTED registry.

    This is the wiring. Before it, `TierRouter` could accept an authority and
    nothing ever passed one, so twenty attested records governed nothing.

    Default policy is FAIL_CLOSED, and the reasoning is not "safest by
    default": the two claim types outside the governed set are blocked because
    their SUCCESS CONDITION IS NOT FIXED BY THE REGISTRY -- the verifier proves
    a different proposition depending on the call site. Routing those to tier 3
    is the correct verdict, not a conservative one. Under DUAL_READ they would
    keep tier 1 on a carrier claim nobody attested, which is exactly the state
    the authority exists to end.

    DUAL_READ remains available and is NOT removed, because the gap is real
    (see `fallback_scope`). Selecting a policy is not the same as deleting the
    mechanism.
    """
    from gyza.verification.adapters import build_registries
    from gyza.verification.router import CutoverPolicy, TierRouter
    v, s = build_registries()
    auth, _ = governed_registry(load_attestations())
    return TierRouter(v, s, authority=auth,
                      policy=policy or CutoverPolicy.FAIL_CLOSED)


def manifest() -> dict[str, Any]:
    """The migration manifest: every entry, structure filled, attestation empty."""
    rows = []
    for x in DRAFTS:
        rows.append({
            "claim_type": x.claim_type,
            "success_condition": x.success_condition,
            "carrier": x.carrier,
            "carrier_basis": x.carrier_basis,
            "carrier_reason": x.carrier_reason,
            "invariant_class": (x.invariant_class.name
                                if isinstance(x.invariant_class, InvariantClass)
                                else f"N/A: {x.invariant_class.reason}"),
            "reference_set_can_move": isinstance(x.frame, FrameRef),
            "frame_identifier": (x.frame.identifier
                                 if isinstance(x.frame, FrameRef) else None),
            "frame_status": (x.frame.digest if isinstance(x.frame, FrameRef)
                             else f"N/A: {x.frame.reason}"),
            "obligations": sorted(x.obligations),
            "witness": x.witness,
            "structurally_ready": x.structurally_ready,
            "blocked_reason": x.blocked_reason,
            "attestation": None,                # THE SLOT THE USER FILLS
        })
    basis = [x.carrier_basis for x in DRAFTS]
    return {
        "n": len(rows),
        "structurally_ready": sum(1 for x in DRAFTS if x.structurally_ready),
        "blocked": sum(1 for x in DRAFTS if x.blocked_reason is not None),
        "carrier_basis_counts": {b: basis.count(b) for b in sorted(set(basis))},
        "judgement_fraction": round(basis.count(JUDGEMENT) / len(basis), 4),
        "entries": rows,
    }


__all__ = ["SpecDraft", "DRAFTS", "BY_CLAIM_TYPE", "governed_registry",
           "load_attestations", "ATTESTATIONS_PATH",
           "fallback_scope", "governed_router",
           "manifest", "MEASURED", "JUDGEMENT", "UNCLASSIFIABLE"]
