"""The specification authority — the gate human authorship enters through.

WHY THIS IS AN AUTHORITY AND NOT A STORE. `VerifierRegistry` and
`PartialSpecRegistry` (`gyza/verification/registry.py`) already hold entries and
already refuse two things: an uncited verifier, and a partial spec with no
human attestation. What they do not do is refuse on the two conditions that
measured results say matter most, and they version on an integer rather than on
the property the version is supposed to protect. A store that accepts what it
is given is a filing cabinet; the difference is the refusals.

THE THREE REFUSALS, each traceable to a measured result:

  (i)   NO ATTESTATION -> REFUSED.  R14 (C11): asked to specify problems they
        could not solve, models produced specs whose unconditional kill rate was
        0.1177 against a TYPE-ONLY floor of 0.2864 -- below a one-line isinstance
        check. A registry that accepts model-authored entries has a median entry
        worse than no spec at all. READ §B: what the attestation establishes is
        ACCOUNTABILITY, not humanity, and this module does not pretend otherwise.

  (ii)  SAMPLING DECLARED AS PROOF -> REFUSED.  SR-3 measured composition at
        PROOF 1.000 / SPEC 1.000 / TEST 0.000. A TEST-carrier mislabelled PROOF
        poisons every chain containing it, and the mislabelling is invisible
        until depth -- which is precisely when it is expensive.

  (iii) MOVABLE REFERENCE SET WITH NO FRAME -> REFUSED.  The G4'/SR-5 species:
        a bound measured from an origin that can move is not a bound. The
        working precedent is in this package -- `corpus_snapshot_digest`
        (`gyza/verification/respec.py:62`) pins the exact candidate set a
        retrieval claim ranked, and `verify_retrieval_claim` (:134) refuses when
        the corpus it is handed does not digest to the pinned value. This module
        generalises that pattern from one claim type to the registration path.

WHAT IS A PROXY HERE, STATED UP FRONT RATHER THAN IN A FOOTNOTE. Conditions
(ii) and (iii) are decided from the verifier's SIGNATURE, not from its
semantics. Whether an arbitrary callable recomputes rather than samples is not
decidable, and this module does not claim to decide it. What it does is
mechanical and one-directional:

    a DECLARED sampling parameter is conclusive evidence of sampling;
    its absence is NOT evidence of recomputation.

So (ii) and (iii) are NECESSARY-condition screens. They catch the entry that
announces itself and they cannot catch one that does not. `check_carrier_claim`
returns that judgement explicitly rather than a bare bool, so a caller cannot
read "not refused" as "verified".
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import blake3

from gyza.canon import canonical_form, values_equal
from gyza.containment.invariants import InvariantClass

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Parameter names that DECLARE a caller-supplied finite case set. A verifier
# taking one of these is sampling by construction: it can only speak about the
# cases it was handed. The list is deliberately short and literal -- a longer
# heuristic list would produce refusals nobody can predict, and an authority
# whose refusals are unpredictable is worse than one that refuses less.
SAMPLING_PARAMS = frozenset({"cases", "samples", "examples", "test_cases"})

# Parameter names that DECLARE a reference set the caller supplies and that can
# grow or be reordered between the claim and its verification. These are the
# ones where a pinned frame is the difference between a bound and a number.
MOVABLE_REFERENCE_PARAMS = frozenset({
    "candidates", "corpus", "entries", "envelopes", "chain", "claims",
})

VALID_CARRIERS = ("PROOF", "SPEC", "TEST")
ATTESTATION_METHODS = ("SELF_ASSERTED", "KEY_BOUND")

# WHAT A REGISTERED CARRIER ACTUALLY RESTS ON. Recorded on every registration so
# a reader of the registry can tell whether PROOF was VERIFIED or DECLARED,
# without having to find a findings document. The registry must not imply a
# guarantee it does not provide.
#
# The screens are one-directional signature checks: they refuse a verifier that
# ANNOUNCES sampling (a finite case-set parameter) or that lets the CALLER pick
# the proposition (variadic or defaulted parameters). Neither decides whether an
# arbitrary callable recomputes, and a read-set analysis was measured
# (research/spec_authority/FINDINGS_CARRIER_ENFORCEMENT.md) to be
# SCREENING-ONLY -- it falsely flags a correct entry, so it is NOT a gate.
CARRIER_ASSURANCE = (
    "DECLARED-UNDER-ATTESTATION — screened one-directionally against the "
    "verifier's SIGNATURE (sampling parameters, variadic/defaulted policy). "
    "NOT verified to recompute; the attester takes responsibility for the "
    "carrier claim."
)


# --------------------------------------------------------------------------- #
#  Refusals — one type per condition, so a caller can catch precisely          #
# --------------------------------------------------------------------------- #
class SpecRefused(RuntimeError):
    """Base: the authority declined to register a specification."""


class MissingField(SpecRefused):
    """A required field was absent, empty, or None.

    THERE ARE NO DEFAULTS. The empty-record hole already in this codebase is
    the precedent: a content-free enforcement record passes `enforcement subset
    manifest` because empty sets are subsets of anything, so absence read as
    permission. Here absence reads as refusal.
    """


class AttestationRefused(SpecRefused):
    """(i) -- no human-authorship attestation, or one that does not verify."""


class CarrierRefused(SpecRefused):
    """(ii) -- a sampling verifier declared PROOF."""


class UnderdeterminedClaim(SpecRefused):
    """(iv) -- the verifier decides a proposition the CALLER chooses.

    Distinct from CarrierRefused on purpose. Sampling and underdetermination
    are different defects with different fixes, and the exception type is where
    that distinction has to survive: a caller catching CarrierRefused is
    handling "this samples", which no amount of parameter-naming repairs.
    """


class FrameRefused(SpecRefused):
    """(iii) -- a movable reference set with no immutable frame identifier."""


class WeakeningRefused(SpecRefused):
    """A2 -- a replacement drops obligations without an explicit acknowledgement."""


# --------------------------------------------------------------------------- #
#  Value types                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NotApplicable:
    """An EXPLICIT absence, carrying the reason it is absent.

    This exists so that "this field does not apply" and "nobody filled this
    field in" are different values. `None` is refused for both; only a
    NotApplicable with a stated reason passes, which makes every absence a
    decision somebody recorded rather than a gap nobody noticed.
    """
    reason: str

    def __post_init__(self):
        if not self.reason or not self.reason.strip():
            raise MissingField(
                "NotApplicable() requires a reason. An unexplained absence is "
                "the empty-record hole with a friendlier name.")


@dataclass(frozen=True)
class FrameRef:
    """An immutable identifier for a reference set that could otherwise move.

    `identifier` names the set; `digest` pins its contents. Both are required:
    a name without a digest cannot detect that the set moved, and a digest
    without a name cannot say what moved.
    """
    identifier: str
    digest: str

    def __post_init__(self):
        for f in ("identifier", "digest"):
            if not getattr(self, f) or not str(getattr(self, f)).strip():
                raise MissingField(f"FrameRef.{f} is required and was empty")


@dataclass(frozen=True)
class Attestation:
    """Who takes responsibility for this specification.

    READ THE MODULE HEADER AND §B OF THE WRITE-UP BEFORE TRUSTING THIS FIELD.

      SELF_ASSERTED  whoever constructs the record sets it. This is a
                     NON-REPUDIATION RECORD, not a prevention: it does not stop
                     a model-authored spec, it records who answered for one.
      KEY_BOUND      additionally signed by an Ed25519 key over the record's
                     canonical bytes. This raises the bar from "someone typed a
                     name" to "someone holding key K signed it" -- which is
                     ACCOUNTABILITY, still not proof of humanity. A model with
                     access to the key produces an identical signature.

    NOTHING HERE ESTABLISHES THAT A HUMAN WROTE THE TEXT, and no mechanism
    available in this codebase could.

    `basis` is REQUIRED and is the substance of the attestation: it says on what
    grounds the attester takes responsibility. "I re-derived every carrier" and
    "an agent classified these and I accepted them" are different
    responsibility records, and an attestation that does not distinguish them
    records less than it appears to. It is folded into the signed canonical
    bytes, so a KEY_BOUND attestation signs its own basis and the basis cannot
    be edited after signing.
    """
    author: str
    method: str
    basis: str
    pubkey_hex: str | None = None
    signature_hex: str | None = None

    def __post_init__(self):
        if not self.author or not self.author.strip():
            raise AttestationRefused("a human attestation needs a human")
        if not self.basis or not self.basis.strip():
            raise AttestationRefused(
                "an attestation must state its BASIS -- on what grounds the "
                "attester takes responsibility. An unstated basis lets a "
                "reader assume independent verification that may not have "
                "happened, which is the failure R14 makes expensive.")
        if self.method not in ATTESTATION_METHODS:
            raise AttestationRefused(
                f"attestation method {self.method!r} unknown; "
                f"must be one of {ATTESTATION_METHODS}")
        if self.method == "KEY_BOUND" and not (self.pubkey_hex and self.signature_hex):
            raise AttestationRefused(
                "KEY_BOUND attestation requires both pubkey_hex and "
                "signature_hex; a key binding with no signature is a "
                "SELF_ASSERTED attestation claiming to be more")


@dataclass(frozen=True)
class SupersedeAck:
    """An explicit acknowledgement that a replacement drops obligations.

    Required only when weakening is detected. It names what was dropped and who
    accepted the loss, so the weakening is a recorded decision rather than a
    version bump.
    """
    dropped: frozenset[str]
    accepted_by: str
    reason: str

    def __post_init__(self):
        if not self.accepted_by or not self.reason:
            raise MissingField(
                "SupersedeAck requires accepted_by and reason: an unattributed "
                "weakening is the defect this check exists to prevent")


@dataclass(frozen=True)
class SpecRecord:
    """A governed specification of one claim type.

    EVERY FIELD IS REQUIRED. There are no defaults, and `None` is never a
    permitted value: where a field genuinely does not apply, the author passes
    `NotApplicable(reason=...)`, which is a different thing from omission.
    """
    claim_type: str
    success_condition: str
    fn: Callable[..., Any]
    carrier: str
    invariant_class: InvariantClass | NotApplicable
    attestation: Attestation
    frame: FrameRef | NotApplicable
    obligations: frozenset[str]
    version: int
    witness: str

    def __post_init__(self):
        for f in ("claim_type", "success_condition", "witness"):
            v = getattr(self, f)
            if not isinstance(v, str) or not v.strip():
                raise MissingField(
                    f"SpecRecord.{f} is required and was {v!r}. A missing field "
                    f"is a refusal, never a silently-filled zero value.")
        if not callable(self.fn):
            raise MissingField("SpecRecord.fn must be callable")
        if self.carrier not in VALID_CARRIERS:
            raise CarrierRefused(
                f"carrier {self.carrier!r} unknown; must be one of "
                f"{VALID_CARRIERS} (SR-3). NONE is not registrable: an entry "
                f"carrying nothing is an absence, and absences are recorded by "
                f"NOT registering.")
        if not isinstance(self.invariant_class, (InvariantClass, NotApplicable)):
            raise MissingField(
                f"SpecRecord.invariant_class must be an InvariantClass or an "
                f"explicit NotApplicable(reason=...); got "
                f"{self.invariant_class!r}. The scheduler reads this tag to "
                f"decide concurrency (C6/C7).")
        if not isinstance(self.frame, (FrameRef, NotApplicable)):
            raise MissingField(
                f"SpecRecord.frame must be a FrameRef or an explicit "
                f"NotApplicable(reason=...); got {self.frame!r}")
        if not isinstance(self.attestation, Attestation):
            raise AttestationRefused(
                "SpecRecord.attestation must be an Attestation")
        if not isinstance(self.obligations, frozenset) or not self.obligations:
            raise MissingField(
                "SpecRecord.obligations must be a non-empty frozenset. It is "
                "the quantity versioning is checked over (A2); an empty set "
                "would make every replacement vacuously non-weakening.")
        if not isinstance(self.version, int) or self.version < 1:
            raise MissingField("SpecRecord.version must be an int >= 1")

    def canonical_bytes(self) -> bytes:
        """The bytes an attestation signs. Excludes the signature itself."""
        ic = self.invariant_class
        fr = self.frame
        return canonical_form({
            "claim_type": self.claim_type,
            "success_condition": self.success_condition,
            "carrier": self.carrier,
            "invariant_class": (ic.name if isinstance(ic, InvariantClass)
                                else f"N/A:{ic.reason}"),
            "frame": ({"identifier": fr.identifier, "digest": fr.digest}
                      if isinstance(fr, FrameRef) else f"N/A:{fr.reason}"),
            "obligations": sorted(self.obligations),
            "version": self.version,
            "witness": self.witness,
            "author": self.attestation.author,
            "attestation_basis": self.attestation.basis,
        }).encode()

    def digest(self) -> str:
        return blake3.blake3(self.canonical_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
#  The screens — each returns its own judgement, never a bare bool             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScreenResult:
    """The outcome of a necessary-condition screen.

    `refused` is conclusive. `passed` is NOT a verification -- it means the
    screen found no declared evidence of the defect, which is a strictly weaker
    statement. The field is named `no_declared_evidence` rather than `ok` so a
    caller cannot read it as a clean bill of health.
    """
    no_declared_evidence: bool
    detail: str


def _params(fn: Callable[..., Any]) -> frozenset[str]:
    try:
        return frozenset(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return frozenset()


def check_carrier_claim(fn: Callable[..., Any], carrier: str) -> ScreenResult:
    """(ii) — does a PROOF declaration contradict a declared sampling parameter?

    ONE-DIRECTIONAL BY CONSTRUCTION. A parameter named in `SAMPLING_PARAMS` is
    a caller-supplied finite case set, and a function that can only see the
    cases it was handed cannot be recomputing the property. The converse does
    not hold and is not claimed: plenty of samplers take no such parameter.
    """
    sampling = _params(fn) & SAMPLING_PARAMS
    if carrier == "PROOF" and sampling:
        return ScreenResult(False,
                            f"declares carrier PROOF but takes a finite case "
                            f"set {sorted(sampling)}: it can only be sound "
                            f"where it sampled (SR-3: TEST composes at 0.000)")
    return ScreenResult(True,
                        f"no declared sampling parameter"
                        + (f"; carrier {carrier} is not PROOF" if carrier != "PROOF" else ""))


def check_claim_determinacy(fn: Callable[..., Any], carrier: str) -> ScreenResult:
    """Does the verifier decide EXACTLY ONE proposition, or a caller-chosen one?

    THE DISTINCTION THIS ENFORCES, AND WHY IT IS NOT THE SAMPLING CHECK.
    Two different defects were being collapsed under "carrier", and they have
    different consequences:

      SAMPLING (fails TOTALITY) -- the verifier examines a proper subset of the
        claim's domain and generalises. `all(fn(x) == y for x, y in cases)` is
        about three points; the claim is about the function. SR-3 measured this
        composing at 0.000, because behaviour outside the sample is
        unconstrained. Naming a parameter does not fix it.

      UNDERDETERMINATION (fails DETERMINACY) -- the verifier TOTALLY decides
        some proposition, but the claim does not say WHICH. Every link is fully
        decided, so this does not compose at 0.000; what fails is that you
        cannot compose the MEANINGS. Naming the parameter fixes it completely.

    A verifier whose signature admits `**kwargs`, or carries a parameter with a
    default, lets the CALLER choose the proposition. That is mechanical and
    conclusive: `_envelope_dag(envelopes, **kw)` forwards `require_closed`,
    which production sets both ways (`audit.py:101` True,
    `resilience.py:202` False), so "the DAG verified" is two claims with two
    verdicts and records neither (RESPEC-4).

    ONE-DIRECTIONAL, like the other screens: a defaulted or variadic parameter
    is conclusive evidence of caller-chosen policy; its absence does not prove
    the claim names everything that moves the verdict. A parameter bound to a
    module constant deeper in the call graph is FIXED-UNNAMED -- it does not
    vary per call site, so it is not refused, but the success condition should
    still state it. That grade is not detectable from this signature alone.
    """
    if carrier == "TEST":
        return ScreenResult(True, "TEST carriers are not held to determinacy: "
                                  "they already claim only what they sampled")
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return ScreenResult(True, "signature unavailable; not checkable")
    variadic = [p.name for p in sig.parameters.values()
                if p.kind is inspect.Parameter.VAR_KEYWORD]
    defaulted = [p.name for p in sig.parameters.values()
                 if p.default is not inspect.Parameter.empty]
    if variadic or defaulted:
        return ScreenResult(
            False,
            f"the caller chooses the proposition: "
            f"{'**' + variadic[0] + ' forwards arbitrary policy' if variadic else ''}"
            f"{' and ' if variadic and defaulted else ''}"
            f"{'defaulted parameter(s) ' + str(sorted(defaulted)) if defaulted else ''}"
            f". A claim that does not name every verdict-changing parameter is "
            f"UNDERDETERMINED -- it is not sampling, and naming the parameter "
            f"fixes it (RESPEC-4)")
    return ScreenResult(True, "no variadic or defaulted parameter; one proposition")


def check_frame_requirement(fn: Callable[..., Any],
                            frame: FrameRef | NotApplicable) -> ScreenResult:
    """(iii) — does a declared movable reference set go unpinned?"""
    movable = _params(fn) & MOVABLE_REFERENCE_PARAMS
    if movable and isinstance(frame, NotApplicable):
        return ScreenResult(False,
                            f"takes a movable reference set {sorted(movable)} "
                            f"but names no immutable frame: a bound measured "
                            f"from an origin that can move is not a bound "
                            f"(G4'/SR-5)")
    if not movable:
        return ScreenResult(True, "no declared movable reference set")
    assert isinstance(frame, FrameRef)          # NotApplicable refused above
    return ScreenResult(
        True, f"movable set {sorted(movable)} pinned by {frame.identifier}")


def check_witness_resolves(witness: str) -> ScreenResult:
    """Does the cited implementation exist?

    The carrier declaration is a proxy; this is the one thing binding it to
    something real. A citation that does not resolve cannot be audited, and
    stale citations are not hypothetical here -- `NO_VERIFIER`'s two entries
    were both found stale by an earlier session.

    Advisory, not a refusal: witnesses legitimately include non-file references
    such as "V-3 adapter (finite sample)", and refusing those would force
    authors to fabricate a path.
    """
    if ":" not in witness:
        return ScreenResult(True, f"non-file witness {witness!r}; not checkable")
    path_part, _, line_part = witness.rpartition(":")
    p = _REPO_ROOT / path_part
    if not p.is_file():
        return ScreenResult(False, f"witness cites {path_part!r}: no such file")
    if line_part.isdigit():
        n = sum(1 for _ in p.open("rb"))
        if int(line_part) > n:
            return ScreenResult(False,
                                f"witness cites {witness!r} but the file has "
                                f"{n} lines")
    return ScreenResult(True, f"witness resolves to {path_part}")


def weakening(old: SpecRecord, new: SpecRecord) -> frozenset[str]:
    """Obligations present in `old` and absent from `new`.

    THIS IS THE PROTECTED QUANTITY, AND IT IS NOT THE VERSION INTEGER. The
    version is a label that correlates with strength; the obligation set is the
    strength. This program has now recorded three instances of checking a
    correlate instead of the quantity -- R9's G4' pinned the frame, SR-5's gate
    floated the origin, and GuardConfigStore tested the version integer so a
    correctly-signed HIGHER version could raise every bound and install
    cleanly. A monotone version check here would be the fourth.
    """
    return frozenset(old.obligations) - frozenset(new.obligations)


# --------------------------------------------------------------------------- #
#  The authority                                                               #
# --------------------------------------------------------------------------- #
class SpecAuthority:
    """Governs registration. Refuses (i), (ii), (iii) and unacknowledged weakening."""

    def __init__(self) -> None:
        self._records: dict[str, SpecRecord] = {}
        self._log: list[dict[str, Any]] = []

    # -- registration ------------------------------------------------------ #
    def register(self, rec: SpecRecord, *,
                 supersede: SupersedeAck | None = None) -> None:
        if not isinstance(rec, SpecRecord):
            raise MissingField("register() takes a SpecRecord")

        # (i) attestation. Attestation.__post_init__ has already refused an
        # anonymous or malformed one; what is left is verifying a KEY_BOUND
        # signature actually verifies, which is the only part that can lie.
        if rec.attestation.method == "KEY_BOUND":
            if not verify_attestation(rec):
                raise AttestationRefused(
                    f"spec for {rec.claim_type!r} declares a KEY_BOUND "
                    f"attestation whose signature does not verify against "
                    f"{rec.attestation.pubkey_hex!r}. A binding that does not "
                    f"bind is worse than none: it claims a property it lacks.")

        # (ii) carrier
        carrier_screen = check_carrier_claim(rec.fn, rec.carrier)
        if not carrier_screen.no_declared_evidence:
            raise CarrierRefused(
                f"spec for {rec.claim_type!r} REFUSED: {carrier_screen.detail}. "
                f"Register it as carrier=TEST, which is what it is.")

        # (iv) determinacy -- checked AFTER the carrier screen, because
        # "this samples" is the more fundamental defect and should be the
        # message a mislabelled sampler gets.
        det_screen = check_claim_determinacy(rec.fn, rec.carrier)
        if not det_screen.no_declared_evidence:
            raise UnderdeterminedClaim(
                f"spec for {rec.claim_type!r} REFUSED: {det_screen.detail}. "
                f"Bind the parameter at the adapter, or split the claim type "
                f"so each names its own policy.")

        # (iii) frame
        frame_screen = check_frame_requirement(rec.fn, rec.frame)
        if not frame_screen.no_declared_evidence:
            raise FrameRefused(
                f"spec for {rec.claim_type!r} REFUSED: {frame_screen.detail}. "
                f"Name a FrameRef pinning it -- the working precedent is "
                f"corpus_snapshot_digest in gyza/verification/respec.py.")

        # A2 -- weakening over the OBLIGATION SET, not over the version integer
        prior = self._records.get(rec.claim_type)
        if prior is not None:
            dropped = weakening(prior, rec)
            if dropped:
                if supersede is None:
                    raise WeakeningRefused(
                        f"spec for {rec.claim_type!r} v{rec.version} drops "
                        f"obligations {sorted(dropped)} held by v{prior.version} "
                        f"and carries no SupersedeAck. The version integer is "
                        f"NOT the protected quantity -- a higher version with "
                        f"fewer obligations is a downgrade wearing an upgrade's "
                        f"label.")
                if not values_equal(set(supersede.dropped), set(dropped)):
                    raise WeakeningRefused(
                        f"SupersedeAck for {rec.claim_type!r} names "
                        f"{sorted(supersede.dropped)} but the replacement "
                        f"actually drops {sorted(dropped)}. An acknowledgement "
                        f"that misdescribes what it accepts acknowledges "
                        f"nothing.")
            if rec.version <= prior.version:
                raise WeakeningRefused(
                    f"spec for {rec.claim_type!r} offers version {rec.version} "
                    f"over {prior.version}; versions must increase so the "
                    f"replacement is identifiable")

        self._records[rec.claim_type] = rec
        self._log.append({
            "claim_type": rec.claim_type, "version": rec.version,
            "digest": rec.digest(), "carrier": rec.carrier,
            "carrier_assurance": CARRIER_ASSURANCE,
            "author": rec.attestation.author,
            "attestation_method": rec.attestation.method,
            "attestation_basis": rec.attestation.basis,
            "witness_screen": check_witness_resolves(rec.witness).detail,
            "superseded": sorted(supersede.dropped) if supersede else [],
        })

    # -- reading ----------------------------------------------------------- #
    def __contains__(self, ct: str) -> bool:
        return ct in self._records

    def get(self, ct: str) -> SpecRecord:
        return self._records[ct]

    def claim_types(self) -> list[str]:
        return sorted(self._records)

    def registration_log(self) -> list[dict[str, Any]]:
        """Append-only record of what was admitted, and on whose attestation."""
        return list(self._log)

    def audit(self) -> dict[str, Any]:
        """Screens re-run over everything currently held.

        Registering a checker is not evidence that it runs; this is the call
        that runs it over real entries.
        """
        rows = []
        for ct in self.claim_types():
            r = self._records[ct]
            rows.append({
                "claim_type": ct,
                "carrier": check_carrier_claim(r.fn, r.carrier).detail,
                "determinacy": check_claim_determinacy(r.fn, r.carrier).detail,
                "frame": check_frame_requirement(r.fn, r.frame).detail,
                "witness": check_witness_resolves(r.witness).detail,
                "witness_resolves": check_witness_resolves(r.witness).no_declared_evidence,
                "attestation_method": r.attestation.method,
            })
        return {"n": len(rows), "entries": rows,
                "carrier_assurance": CARRIER_ASSURANCE,
                "unresolved_witnesses": [x["claim_type"] for x in rows
                                         if not x["witness_resolves"]],
                "self_asserted": [x["claim_type"] for x in rows
                                  if x["attestation_method"] == "SELF_ASSERTED"]}


# --------------------------------------------------------------------------- #
#  Key-bound attestation — reuses the existing Ed25519 surface                 #
# --------------------------------------------------------------------------- #
def sign_attestation(rec: SpecRecord, private_key) -> str:
    """Sign a record's canonical bytes. `private_key` is an Ed25519PrivateKey."""
    return private_key.sign(rec.canonical_bytes()).hex()


def verify_attestation(rec: SpecRecord) -> bool:
    """Verify a KEY_BOUND attestation. Returns False, never raises.

    ESTABLISHES ACCOUNTABILITY, NOT HUMANITY. See `Attestation`.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    att = rec.attestation
    if att.method != "KEY_BOUND" or not (att.pubkey_hex and att.signature_hex):
        return False
    try:
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(att.pubkey_hex))
        pk.verify(bytes.fromhex(att.signature_hex), rec.canonical_bytes())
        return True
    except (InvalidSignature, ValueError):
        return False


__all__ = [
    "SpecRefused", "MissingField", "AttestationRefused", "CarrierRefused",
    "FrameRefused", "WeakeningRefused", "UnderdeterminedClaim",
    "NotApplicable", "FrameRef", "Attestation", "SupersedeAck", "SpecRecord",
    "ScreenResult", "SpecAuthority",
    "check_carrier_claim", "check_claim_determinacy", "check_frame_requirement",
    "check_witness_resolves",
    "weakening", "sign_attestation", "verify_attestation",
    "SAMPLING_PARAMS", "MOVABLE_REFERENCE_PARAMS", "VALID_CARRIERS",
    "CARRIER_ASSURANCE",
]
