"""
Gyza's own harm model, wired into C-1.

Quantities are taken from research/HARM_MODEL_DRAFT.md and computed with the
PRODUCTION folds, not reimplementations -- that is what makes the guard
frame-aligned rather than merely correct-looking (R12 Part C).

BOUNDS ARE NOT SET HERE. Every level in the draft is `TBD -- user decision`,
and inventing one would make the containment claim unfalsifiable. Call
`load_bounds({...})` with declared levels; until then `can_claim_containment`
is False and the engine refuses actions touching unbounded classes.

H3 is deliberately NOT registered as a bounded class: the draft records that no
function anywhere in gyza/ computes an irreversibility measure. Registering it
with an invented quantity would be exactly the circularity the discipline
forbids. It is listed in UNMODELLED so the gap is visible rather than absent.
"""
from __future__ import annotations

from pathlib import Path

from gyza.containment.harm import HarmClass, HarmModelRegistry
from gyza.containment.invariants import (
    Invariant, InvariantClass, InvariantRegistry,
)

# Harm classes named in the draft that have NO computable quantity in the
# codebase. Reported, never silently omitted.
UNMODELLED: dict[str, str] = {
    "H1_credits": (
        "RETIRED as a harm class 2026-08-15 (user decision). The quantity is "
        "computable and the ledger still records it, but credits are "
        "TOKEN_IS_FAKE -- 'internal, non-redeemable, no external value' -- so a "
        "bound denominated in them cannot be checked against anything: the "
        "declared 100 refused every real model's FIRST action (40,000 credits "
        "for Sonnet, 120,000 for Opus). R-B1 also classifies it TRANSFERS, so "
        "enforcing it relocated harm onto counterparties rather than removing "
        "it, while capping A_system harmonically. Autonomy is now bounded "
        "directly by H6 in actions. Re-register it when credits have an "
        "external referent and a real exposure limit can be declared."
    ),
    "H2_market_capital": (
        "RETIRED as a harm class 2026-08-17 (owner decision). The quantity is "
        "real and computable -- `fold_capital` over an append-only CapitalEntry "
        "log -- but it has NO PRODUCTION EXISTENCE: `BondedMarket` is "
        "constructed in tests only (zero production constructors), and the one "
        "production projection that feeds the harm model hardcodes "
        "`capital_entries=[]` (gates.py:114,122). So H2 measured exactly 0.0 in "
        "every production evaluation while being reported as a bounded class. "
        "Unlike H1 this is a WIRING gap rather than an unmeasurable quantity: "
        "re-register it the moment a production path constructs a market, and "
        "wire `capital_entries` through the projection at the same time."
    ),
    "H3_irreversible_change": (
        "no function in gyza/ computes an irreversibility measure "
        "(HARM_MODEL_DRAFT §H3). Sub-classes: signed envelopes emitted, "
        "external network sends (which leave modelled state entirely -- C15), "
        "deleted local state."
    ),
}


def _credits_at_risk(s0: object, s: object) -> float:
    """H1 -- settled net balance minus active holds, over the CURRENT frame.

    Uses the production fold (gyza.economy.wallet.Wallet, a pure projection
    over append-only LedgerEntry) rather than a private reimplementation, so
    the guard and the harm measure cannot disagree about what a balance is.
    The frame is the compositor pubkey and it FLOATS -- read from `s`, never
    pinned at `s0` (R9 condition 2).
    """
    from gyza.economy.wallet import Wallet
    before = Wallet(s0.entries).net_balance(s0.owner)
    after = Wallet(s.entries).net_balance(s.owner)
    holds = float(s.active_holds)
    # Fold in MICROS -- `Credits.value` is display-only and the class says so
    # explicitly ("Never fold with this"). An earlier version of this function
    # read a non-existent `.credits` attribute and therefore RAISED on every
    # input; it had never been executed, because no test exercised the
    # registered Gyza quantities against real state. Found by the unmeasured-
    # action audit, whose own harness had counted the resulting exception as a
    # harm movement and reported ZERO gaps -- an exact zero that was
    # definitional of two stacked bugs.
    return (before.micros - after.micros) / 1_000_000.0 + holds


def _market_capital_at_risk(s0: object, s: object) -> float:
    """H2 -- market capital drawdown over the accounting window.

    READS THE APPEND-ONLY ENTRIES AND FOLDS THEM WITH THE MARKET'S OWN
    FUNCTION, exactly as H1 folds `LedgerEntry` with the production `Wallet`.

    WHAT THIS REPLACED, because the defect is instructive. This used to read
    `getattr(s0, "capital", 0.0) - getattr(s, "capital", 0.0)`, a MUTABLE
    STORED SCALAR. H2 was then fixed representationally -- `_capital` became
    the append-only `CapitalEntry` fold -- and this quantity was never updated,
    so **no production object exposed `.capital` at all**. The two `getattr`
    defaults meant the class measured 0.0 against a bound of 100.0 and passed
    by measuring nothing. The only objects in the tree carrying `.capital` were
    two test stubs, so the suite could not see it either.

    Hence the direct attribute access: a missing field must RAISE. An absent
    measurement is UNEVALUATED, never a passing one.
    """
    from gyza.economy.market import fold_capital
    return (fold_capital(s0.capital_entries, s0.owner)
            - fold_capital(s.capital_entries, s.owner))


def _authority_exceedance(s0: object, s: object) -> float:
    """H4 -- authority. A MEASURE, not the draft's boolean (C5): the count of
    executed actions whose enforcement exceeded the delegation root's manifest.
    Zero is the intended operating point; a count gives the dial a boolean
    lacks.

    Same correction as H2: `getattr(s, "authority_violations", ()) or ()`
    defaulted to the empty tuple, so a state that recorded nothing measured 0
    against a bound of 0 and PASSED. Direct access now; an unrecorded field is
    an error, not a clean bill of health.
    """
    return float(len(s.authority_violations))


def _storage_growth(s0: object, s: object) -> float:
    """H5 -- bytes retained by the content-addressed store, since the origin.

    THE ARCHITECTURAL PRINCIPLE'S OWN PRICE, made measurable.
    `ARCHITECTURAL_PRINCIPLE.md` states the cost of append-only plainly --
    "nothing is ever freed" -- and until now no function anywhere computed it,
    so the one cost the architecture openly accepts was the one nobody could
    see.

    WHY THIS CLASS AND NOT ANOTHER (R-B1). Storage growth is NOT CONSERVED:
    appending CREATES bytes and no other frame loses them. So bounding it
    EXTINGUISHES the harm rather than transferring it -- unlike H1, which is the
    only bound currently enforced and which R-B1 classifies as TRANSFERS. This
    is the first declared quantity where a bound would actually remove harm.

    It reads the store's own fold (`ArtifactStore.total_size_bytes`) captured
    into the projection, never a private reimplementation -- the same
    frame-alignment discipline H1 gets from `Wallet` and H2 from
    `fold_capital`.
    """
    return float(s.stored_bytes - s0.stored_bytes)


def _unsupervised_actions(s0: object, s: object) -> float:
    """H6 -- signed envelopes since the accounting origin: THE CADENCE.

    This is the quantity the operator's review cadence is denominated in.
    "Look every 10,000 actions" is a statement about THIS number, and about
    nothing else -- which is why it is a separate class from H1 rather than a
    credit figure in disguise.

    WHY IT IS NOT DENOMINATED IN CREDITS. `TOKEN_IS_FAKE = True`: credits are
    "internal, non-redeemable, no external value", so a bound expressed in them
    cannot be checked against anything and 100 could be generous or absurd. An
    action count is interpretable without a conversion table, and it is what a
    human's attention is actually spent on.

    NOT CONSERVED, PREVENTABLE (R-B1) -- so bounding it EXTINGUISHES rather than
    transfers: signing CREATES a non-repudiable claim and no other party holds
    one fewer. Refusing to sign means the claim does not exist, not that someone
    else bears it.

    DERIVED FROM THE APPEND-ONLY ENVELOPE LOG via
    `Blackboard.count_envelopes_since`, never an in-process counter -- a counter
    resets on restart, and a cumulative bound whose origin moves is not a bound.
    """
    return float(s.signed_envelope_count - s0.signed_envelope_count)


#: Classes that are REGISTERED AND DELIBERATELY UNBOUNDED, with the reason.
#:
#: "Measured, not bounded" is a real and honest state, and it is strictly better
#: than `UNMODELLED`: the quantity is computed on every projection and reported
#: by `readiness()`, it just has no declared level yet. This map exists so that
#: state is DECLARED rather than inferred -- a class whose level was simply
#: FORGOTTEN must still fail `test_every_registered_invariant_predicate_executes`,
#: and it will, because it is absent here.
#:
#: Being listed here costs the containment claim: `can_claim_containment` stays
#: False while any class is unbounded, signed configuration or not. That price is
#: correct and is the point -- see research/H3_MESH_EXIT.md §6.
MEASURED_NOT_BOUNDED: dict[str, str] = {
    "H3_mesh_exit_sends": (
        "no level until the attainable range is measured. H1_credits was "
        "retired because 100 was declared without measuring and refused every "
        "real model's FIRST action; standing rule #4 (check a threshold "
        "against its feasibility ceiling BEFORE fixing it) has failed four "
        "times. Instrument, measure, then declare."
    ),
}


def storage_cap_bytes(bounds_file: "str | Path | None" = None) -> int | None:
    """The DECLARED H5 level, in bytes — the single source for the store's cap.

    TWO SOURCES FOR ONE BOUND is what this removes. `guard_bounds.json` declared
    `H5_storage_growth = 1e10`, while `ArtifactStore.max_bytes` was wired from
    `GyzaConfig.max_artifact_store_gb` at three CLI sites. They agree today at
    10 GB by coincidence of transcription -- H5's level was copied FROM the
    config -- and nothing kept them in step. Editing either alone would leave
    the enforced cap and the declared bound describing different systems, which
    is the frame-drift species this program has recorded three times.

    The DECLARED bound wins, because it is the one that becomes tamper-evident
    under C-8: a signed guard configuration that the store then ignored would be
    ceremony. Returns None when H5 has no declared level, which `ArtifactStore`
    reads as unlimited -- and that is the honest reading of "no bound declared",
    not a silent default.
    """
    from gyza.containment.harm import UnsetBoundError
    harm, _inv = build_registries(
        bounds_file=DEFAULT_BOUNDS_FILE if bounds_file is None else bounds_file)
    try:
        return int(harm.bound("H5_storage_growth"))
    except (UnsetBoundError, KeyError):
        return None


def _mesh_exit_sends(s0: object, s: object) -> float:
    """H3 -- sends since the origin that did NOT land on an attested peer.

    THE SUB-CLASS THE DRAFT MIS-CLASSIFIED. `HARM_MODEL_DRAFT` §H3 cites
    `publish_agent`, `send_message`, `publish_delta` and `publish_attestation`
    as "external network sends" that "leave the modeled system entirely". All
    four land on another `gyza-netd`: a libp2p peer, a DHT key under `/gyza/`,
    a gossipsub topic. They are FEDERATION, not exit.

    So C15's boundary is a property of deployment topology rather than a law,
    and this is the ONLY declared quantity here that improves with scale -- the
    set of destinations that lack a model shrinks as the mesh grows, while
    margin, aggregates and A_system all worsen.

    NOT CONSERVED, PREVENTABLE (R-B1): refusing to emit means the message does
    not exist, not that another party bears it. So a bound here EXTINGUISHES.

    NO BOUND IS DECLARED, DELIBERATELY. H1 was retired because 100 credits was
    fixed without measuring the attainable range and refused every real model's
    first action; standing rule #4 has failed four times. `readiness()` will
    report this class as unbounded, which is the honest state: measured, not
    bounded. The level comes after the measurement.
    """
    return float(s.mesh_exit_sends - s0.mesh_exit_sends)


DEFAULT_BOUNDS_FILE = Path(__file__).with_name("guard_bounds.json")


def build_registries(
    bounds_file: str | Path | None = DEFAULT_BOUNDS_FILE,
    authority_pubkey: bytes | None = None,
) -> tuple[HarmModelRegistry, InvariantRegistry]:
    harm = HarmModelRegistry()
    harm.register(HarmClass(
        id="H4_authority",
        description="count of actions exceeding the delegation root's manifest",
        quantity=_authority_exceedance,
        frame="delegation chain root manifest",
        frame_mutable=False,
        code_path="gyza/economy/delegation.py:264 verify_delegation",
    ))

    harm.register(HarmClass(
        id="H5_storage_growth",
        description="bytes retained by the content-addressed store since the "
                    "accounting origin (the append-only principle's own price)",
        quantity=_storage_growth,
        frame="the local artifact store",
        frame_mutable=False,
        code_path="gyza/network/artifact_store.py:115 total_size_bytes",
    ))

    harm.register(HarmClass(
        id="H6_unsupervised_actions",
        description="signed envelopes since the accounting origin — the review "
                    "cadence, in the unit a human's attention is spent in",
        quantity=_unsupervised_actions,
        frame="the local envelope log",
        frame_mutable=False,
        code_path="gyza/blackboard.py count_envelopes_since",
    ))

    harm.register(HarmClass(
        id="H3_mesh_exit_sends",
        description="sends since the accounting origin that did NOT land on an "
                    "attested peer — the only declared quantity that shrinks "
                    "as the mesh grows",
        quantity=_mesh_exit_sends,
        frame="the local egress log",
        frame_mutable=False,
        code_path="gyza/blackboard.py count_egress_since; "
                  "classification in gyza/containment/egress.py",
    ))

    inv = InvariantRegistry()
    inv.register(Invariant(
        id="INV-H3-mesh-exit",
        harm_class="H3_mesh_exit_sends",
        cls=InvariantClass.CUMULATIVE,
        description=(
            "sends leaving the attested mesh stay within the declared bound. "
            "CUMULATIVE: a monotone total over one append-only log, so like H5 "
            "and H6 it is valid only at a serialization point (C7). Registered "
            "WITHOUT a declared bound on purpose — E2 established that a harm "
            "class with no invariant makes the engine refuse every action "
            "through the same channel as a bound breach, so the invariant must "
            "exist even while the level does not."),
    ))
    inv.register(Invariant(
        id="INV-H4-attenuation",
        harm_class="H4_authority",
        cls=InvariantClass.MONOTONE_NON_CUMULATIVE,
        description=(
            "authority is monotone non-increasing down a delegation chain "
            "(the attenuation theorem). Once exceeded it cannot be un-exceeded, "
            "and the property is per-action and stateless, so it composes "
            "concurrently in the interior (C6)."),
    ))
    inv.register(Invariant(
        id="INV-H5-storage",
        harm_class="H5_storage_growth",
        cls=InvariantClass.CUMULATIVE,
        description=(
            "retained bytes stay within the declared bound. CUMULATIVE: a "
            "monotone total over one store, so like H1 it is valid only at a "
            "serialization point and does not compose concurrently (C6/C7)."),
    ))
    inv.register(Invariant(
        id="INV-H6-cadence",
        harm_class="H6_unsupervised_actions",
        cls=InvariantClass.CUMULATIVE,
        description=(
            "actions since the origin stay within the declared review cadence. "
            "CUMULATIVE: a running count over one log, so it is valid only at a "
            "serialization point and does not compose concurrently (C6/C7)."),
    ))
    # H5 HAS NO DECLARED BOUND, DELIBERATELY. `guard_bounds.json` carries no
    # level for it, so `harm.bound("H5_storage_growth")` raises UnsetBoundError
    # and the engine refuses any action touching the class. That is the correct
    # state: how many bytes an operator is willing to retain is a USER DECISION
    # (BUILD_PLAN D1), and inventing one here would make the containment claim
    # unfalsifiable -- the exact circularity this module's docstring forbids.
    #
    # Registering it UNBOUNDED is not an oversight either. It moves the gap from
    # invisible to reported: `readiness()` now lists H5 under `unbounded`, and
    # `gyza status` prints it. `HARM_MODEL_GAP.md` had storage growth as
    # "declarable, existing code: none" -- this is the code.
    #
    # D1 — bounds are LOADED, never invented here. Passing bounds_file=None
    # yields an unbounded registry that refuses everything, which is the
    # correct behaviour before a model is declared.
    #
    # C-8 — WHICH LOADER RUNS IS THE WHOLE QUESTION. With an authority key the
    # bounds must arrive through a VERIFIED configuration, and an unsigned file
    # is refused outright: a guard whose bounds the constrained system can edit
    # has no base case for its induction. Without one they still load, but the
    # registry records UNSIGNED and `readiness()` will not claim containment.
    if authority_pubkey is not None:
        from gyza.containment.guardconfig import GuardConfigError, GuardConfigStore
        from gyza.containment.harm import UnsignedBoundsError
        if bounds_file is None or not Path(bounds_file).exists():
            raise UnsignedBoundsError(
                f"an authority key was supplied but no configuration exists at "
                f"{bounds_file!r}. Refusing to run unconfigured: an absent "
                f"policy is not a permissive policy")
        store = GuardConfigStore(authority_pubkey)
        try:
            store.load_file(bounds_file)
        except (KeyError, TypeError) as e:
            # A PLAIN bounds file has no "config"/"signature" envelope. Naming
            # that specifically matters: the failure is "these bounds are
            # unsigned", not "the signature is wrong", and the remedies differ.
            raise UnsignedBoundsError(
                f"{Path(bounds_file).name} is not a SIGNED configuration "
                f"({type(e).__name__}: {e}). Sign it with "
                f"scripts/sign_guard_config.py, or omit authority_pubkey to "
                f"run with unsigned bounds and no containment claim") from None
        except GuardConfigError as e:
            raise UnsignedBoundsError(
                f"the guard configuration did not verify: {e}") from None
        store.apply_to(harm)
        return harm, inv

    if bounds_file is not None and Path(bounds_file).exists():
        harm.load_bounds_file(bounds_file)
    return harm, inv
