--------------------------- MODULE Attestation ---------------------------
(***************************************************************************)
(* Attestation.tla — formal spec of cert assembly + cosig verification.   *)
(*                                                                         *)
(* Third §C1 sub-spec (Settlement S19, Reconciliation S28). Ports the     *)
(* core quorum + applicant-proposed body + cosig verification logic from  *)
(* netd/internal/capability/capability.go's AssembleAttestation +         *)
(* VerifyAttestation + verifyProposedAttestationBody.                     *)
(*                                                                         *)
(* Scope (Session 29): the cert-assembly endpoint. Models cosigs being   *)
(* emitted by validators (honest or adversarial) and the applicant       *)
(* assembling a valid AttestationCert. Targets:                          *)
(*                                                                         *)
(*   INV-ATT-1  MinCoSignatures = 2: cert needs ≥ k distinct cosigs.    *)
(*   INV-ATT-2  IssuedTier = 3: body.tier must equal IssuedTier.         *)
(*   INV-ATT-3  Body lifetime ≤ MaxAttestationTTL.                       *)
(*   INV-ATT-6  Cosigs dedup by validator_pubkey.                        *)
(*   INV-ATT-7  All cosigs in a cert sign IDENTICAL canonical body bytes *)
(*              (applicant-proposed body).                               *)
(*   INV-ATT-8  Body fields satisfy plausibility (tier, lifetime).      *)
(*                                                                         *)
(* Deferred to companion sub-specs:                                      *)
(*   CapabilityStream.tla — wire protocol (3 frames, libp2p framing,    *)
(*                          challenge nonces, applicant identity from   *)
(*                          libp2p RemotePeer) — INV-ATT-9..14,         *)
(*                          INV-CAPSTREAM-*, INV-CAPBRIDGE-*.            *)
(*   AttestationDHT.tla   — DHT publish + fetch + verifier cache         *)
(*                          (INV-ATT-15..22).                            *)
(*   AttestationRecursive.tla — TrustedBootstrap + recursive cert       *)
(*                          verification (INV-ATT-23..28).               *)
(*                                                                         *)
(* By stripping the wire protocol from this spec we keep the state      *)
(* space tractable. The wire spec is a separate concern (different      *)
(* invariants, different abstraction level).                            *)
(***************************************************************************)

EXTENDS Naturals, FiniteSets, TLC

CONSTANTS
    Peers,                  \* Set of model-value peer identities
    Bodies,                 \* Set of model-value body identifiers
    Applicant,              \* The single applicant (model-value peer)
    CanonicalBody,          \* The body the applicant proposes
                            \* (one fixed canonical body per spec run)
    MinCoSignatures,        \* INV-ATT-1
    IssuedTier,             \* INV-ATT-2
    MaxAttestationTTL,      \* INV-ATT-3
    MalleableSigs           \* TRUE = enable adversarial cosig actions

ASSUME
    /\ Cardinality(Peers) >= MinCoSignatures + 1
        \* Applicant + at least MinCoSignatures distinct validators
    /\ Applicant \in Peers
    /\ MinCoSignatures \in Nat /\ MinCoSignatures >= 1
    /\ IssuedTier \in Nat /\ IssuedTier >= 1
    /\ MaxAttestationTTL \in Nat /\ MaxAttestationTTL >= 1
    /\ CanonicalBody \in Bodies

(***************************************************************************)
(* Domain                                                                 *)
(*                                                                         *)
(* A Body in this spec is identified by an opaque value (model-value     *)
(* from the Bodies constant). The body-shape attributes (applicant,     *)
(* tier, lifetime) are encoded via BodyAttrs functions that map a body  *)
(* identifier to its canonical representation.                          *)
(*                                                                         *)
(* For the canonical body of the spec run, BodyAttrs returns the        *)
(* applicant-proposed shape. For other bodies in the Bodies set, attrs  *)
(* may be ill-formed (used by adversarial actions to test that         *)
(* implausible bodies don't end up in certs).                          *)
(***************************************************************************)

\* Body attributes — pure functions from body identifier to fields.
\* CanonicalBody has: applicant=Applicant, tier=IssuedTier, lifetime ≤ TTL.
\* Other bodies are intentionally ill-formed (wrong tier).
BodyApplicant(b) == IF b = CanonicalBody THEN Applicant ELSE Applicant
BodyTier(b)      == IF b = CanonicalBody THEN IssuedTier ELSE 0
BodyLifetime(b)  == IF b = CanonicalBody THEN MaxAttestationTTL ELSE 0

\* "Plausible body" per INV-ATT-8 (structural form).
Plausible(b) ==
    /\ BodyTier(b) = IssuedTier
    /\ BodyLifetime(b) > 0
    /\ BodyLifetime(b) <= MaxAttestationTTL

(***************************************************************************)
(* A cosig is a (validator, body, sig_valid) triple. Honest cosigs have *)
(* sig_valid=TRUE over the canonical body. Adversarial cosigs have      *)
(* sig_valid=FALSE OR sign a non-canonical body. INV-ATT-7 demands that *)
(* a valid cert contains ONLY cosigs over the SAME body bytes; mismatched *)
(* bodies must be filtered.                                             *)
(***************************************************************************)
CoSigs == [validator : Peers, body : Bodies, sig_valid : BOOLEAN]

AttestationCerts == [body : Bodies, co_signatures : SUBSET CoSigs]

(***************************************************************************)
(* State variables                                                        *)
(***************************************************************************)
VARIABLES
    cosigs,        \* SUBSET CoSigs — accumulated over time
    certs          \* SUBSET AttestationCerts — committed by applicant

vars == <<cosigs, certs>>

TypeOK ==
    /\ cosigs \subseteq CoSigs
    /\ certs \subseteq AttestationCerts

(***************************************************************************)
(* Helpers                                                                *)
(***************************************************************************)

DistinctValidators(cs_set) ==
    Cardinality({ cs.validator : cs \in cs_set })

\* The set of cosigs that "count" toward a cert over body b: validator
\* sig is valid AND signs body b.
ValidCosigsFor(b) ==
    { cs \in cosigs : cs.sig_valid /\ cs.body = b }

(***************************************************************************)
(* Init                                                                   *)
(***************************************************************************)
Init ==
    /\ cosigs = {}
    /\ certs = {}

(***************************************************************************)
(* Action: HonestCosign — validator v emits a valid cosig over the       *)
(* applicant's canonical body. Mirrors the validator's path after        *)
(* successful VerifyResponse: emit cosig(v, body=CanonicalBody, sig=valid).*)
(***************************************************************************)
HonestCosign ==
    \E v \in Peers:
        /\ v /= Applicant
        /\ ~\E cs \in cosigs:
               /\ cs.validator = v
               /\ cs.body = CanonicalBody
        /\ cosigs' = cosigs \cup {[
               validator |-> v,
               body      |-> CanonicalBody,
               sig_valid |-> TRUE]}
        /\ UNCHANGED certs

(***************************************************************************)
(* Action: AssembleCert — applicant collects cosigs over CanonicalBody  *)
(* and builds an AttestationCert if ≥ MinCoSignatures DISTINCT validators *)
(* have emitted VALID cosigs. INV-ATT-1 enforced by the guard;           *)
(* INV-ATT-6 enforced by counting distinct validators; INV-ATT-7        *)
(* enforced by filtering on body = CanonicalBody.                        *)
(***************************************************************************)
AssembleCert ==
    LET matching == ValidCosigsFor(CanonicalBody)
    IN  /\ DistinctValidators(matching) >= MinCoSignatures
        /\ ~\E cert \in certs: cert.body = CanonicalBody
        /\ certs' = certs \cup {[
               body          |-> CanonicalBody,
               co_signatures |-> matching]}
        /\ UNCHANGED cosigs

(***************************************************************************)
(* Adversarial actions — only enabled with MalleableSigs=TRUE.           *)
(*                                                                         *)
(* AdversarialBadSig: a peer X (possibly a real validator) emits a      *)
(*   cosig over CanonicalBody with sig_valid=FALSE. Models a Tier-3 key *)
(*   compromise where the attacker has the wrong private key, or a peer *)
(*   producing a malformed signature. AssembleCert's sig_valid filter   *)
(*   drops these; INV-ATT-1's count guards against quorum from forged   *)
(*   sigs alone.                                                        *)
(*                                                                         *)
(* AdversarialWrongBody: a peer X emits a cosig over a NON-canonical    *)
(*   body with sig_valid=TRUE. Models a validator who runs eval but    *)
(*   then signs a body with mutated fields (wrong tier, wrong lifetime).*)
(*   Mismatched bodies don't end up in certs because AssembleCert       *)
(*   filters by body=CanonicalBody. INV-ATT-7 catches.                  *)
(*                                                                         *)
(* AdversarialSelfDoubleSign: a peer X who has already emitted a cosig  *)
(*   for CanonicalBody re-emits — but the cosigs set's SET SEMANTICS   *)
(*   forbid duplicate (validator, body, sig_valid) tuples. INV-ATT-6   *)
(*   (dedup by validator_pubkey) is enforced at assembly time, since   *)
(*   DistinctValidators counts unique validator field values.          *)
(***************************************************************************)
AdversarialBadSig ==
    /\ MalleableSigs
    /\ \E v \in Peers:
        /\ v /= Applicant
        /\ ~\E cs \in cosigs:
               /\ cs.validator = v
               /\ cs.body = CanonicalBody
               /\ cs.sig_valid = FALSE
        /\ cosigs' = cosigs \cup {[
               validator |-> v,
               body      |-> CanonicalBody,
               sig_valid |-> FALSE]}
        /\ UNCHANGED certs

AdversarialWrongBody ==
    /\ MalleableSigs
    /\ \E v \in Peers:
       \E b \in Bodies:
        /\ v /= Applicant
        /\ b /= CanonicalBody
        /\ ~\E cs \in cosigs:
               /\ cs.validator = v
               /\ cs.body = b
        /\ cosigs' = cosigs \cup {[
               validator |-> v,
               body      |-> b,
               sig_valid |-> TRUE]}
        /\ UNCHANGED certs

(***************************************************************************)
(* Next-state                                                           *)
(***************************************************************************)
Next ==
    \/ HonestCosign
    \/ AssembleCert
    \/ AdversarialBadSig
    \/ AdversarialWrongBody

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Safety invariants                                                     *)
(***************************************************************************)

\* INV-ATT-1: every cert has ≥ MinCoSignatures distinct valid cosigs.
INV_ATT_1_MinCoSignatures ==
    \A cert \in certs:
        LET valid_cs == { cs \in cert.co_signatures :
                              /\ cs.sig_valid
                              /\ cs.body = cert.body }
        IN DistinctValidators(valid_cs) >= MinCoSignatures

\* INV-ATT-2: every cert body has tier = IssuedTier.
INV_ATT_2_TierFixed ==
    \A cert \in certs: BodyTier(cert.body) = IssuedTier

\* INV-ATT-3: every cert body's lifetime ≤ MaxAttestationTTL.
INV_ATT_3_LifetimeBound ==
    \A cert \in certs:
        /\ BodyLifetime(cert.body) > 0
        /\ BodyLifetime(cert.body) <= MaxAttestationTTL

\* INV-ATT-6: every cert's valid cosigs have distinct validators.
INV_ATT_6_DistinctValidators ==
    \A cert \in certs:
        LET valid_cs == { cs \in cert.co_signatures :
                              /\ cs.sig_valid
                              /\ cs.body = cert.body }
        IN DistinctValidators(valid_cs) = Cardinality(valid_cs)

\* INV-ATT-7: every cosig in a cert signs the SAME body (= cert.body).
INV_ATT_7_AllCosignSameBody ==
    \A cert \in certs:
        \A cs \in cert.co_signatures:
            cs.sig_valid => cs.body = cert.body

\* INV-ATT-8: every cert body is structurally plausible.
INV_ATT_8_BodyPlausible ==
    \A cert \in certs: Plausible(cert.body)

\* INV-ATT-5 composite: every cert in certs verifies under the same
\* checks VerifyAttestation runs (capability.go::VerifyAttestation).
\* In this spec the checks are: tier=IssuedTier + lifetime bounded +
\* distinct-validator count ≥ MinCoSignatures + every cosig valid over
\* the cert body. This is the conjunction of INV-1/2/3/6/7/8.
INV_ATT_5_Verifiable ==
    /\ INV_ATT_1_MinCoSignatures
    /\ INV_ATT_2_TierFixed
    /\ INV_ATT_3_LifetimeBound
    /\ INV_ATT_6_DistinctValidators
    /\ INV_ATT_7_AllCosignSameBody
    /\ INV_ATT_8_BodyPlausible

AllSafety ==
    /\ TypeOK
    /\ INV_ATT_1_MinCoSignatures
    /\ INV_ATT_2_TierFixed
    /\ INV_ATT_3_LifetimeBound
    /\ INV_ATT_6_DistinctValidators
    /\ INV_ATT_7_AllCosignSameBody
    /\ INV_ATT_8_BodyPlausible

================================================================================
