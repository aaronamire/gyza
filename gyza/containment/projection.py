"""The production state projection — what the guard actually measures.

WHY THIS DID NOT EXIST, and why its absence was invisible. `StagingArea` takes
a caller-supplied `projector`, `GuardEngine.evaluate` takes `s0`/`s_next`, and
the three registered harm quantities read attributes off them. **No production
projector was ever written.** The only objects in the tree carrying the fields
those quantities read were test stubs, so:

  * `gyza/containment/gyza_model.py:build_registries` had ZERO production
    callers -- three importers, all tests or research;
  * `gyza/runner.py`, the real claim/execute/sign loop, referenced the
    containment package not at all;
  * and `test_every_registered_harm_quantity_executes` -- the test written to
    enforce "registering a checker is not evidence that it runs" -- built its
    own `_S` stub and therefore passed against a shape production never
    produced. The discipline test was defeated by the mechanism it existed to
    catch.

WHAT THIS IS. A frozen snapshot folded from the sources that are ALREADY
append-only: `LedgerEntry` (settlement), `CapitalEntry` (market), and the
authority-violation record. Nothing here stores a derived aggregate -- the
quantities fold these lists themselves, with the same functions production
uses, so guard and harm cannot drift (C3, frame alignment by construction).

EVERY FIELD IS REQUIRED. That is the whole point. The defect this module
repairs was two `getattr(..., default)` calls that turned "this state does not
carry the field" into "the measurement is zero, which is within bound". An
absent measurement must raise.

TWO SNAPSHOTS, ONE ORIGIN. A cumulative bound is measured from a named,
immutable origin (`at_origin`) to now (`now`) -- never from a moving
checkpoint, which is the frame-drift defect recorded as ledger artifact #13.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class AuthorityViolation:
    """One action whose enforcement record exceeded its manifest.

    Recorded at the point of detection (`gyza/runner.py`'s bounds gate) rather
    than inferred later. The runner REFUSES TO SIGN such an action, so this
    counts breaches that were caught, not breaches that got through -- and that
    is the right quantity: the sandboxed work already ran outside its declared
    bounds, which is the harm. H4's declared bound is 0, so any entry is a
    breach rather than consumed allowance.
    """
    action_id: str
    agent_pubkey: str
    reason: str
    at_ns: int


@dataclass(frozen=True)
class GyzaState:
    """A snapshot the registered harm quantities can measure.

    Field names are load-bearing: they are exactly what `gyza_model`'s three
    quantities read. Adding a harm class means adding a field here, and the
    quantity will RAISE until it is added -- which is the intended coupling.
    """
    owner: str                              # H1, H2 frame: the compositor key
    entries: Sequence[object]               # H1: append-only LedgerEntry
    active_holds: float                     # H1: credits held by reservations
    capital_entries: Sequence[object]       # H2: append-only CapitalEntry
    authority_violations: tuple[AuthorityViolation, ...] = field(
        default_factory=tuple)
    # H5: bytes retained by the content-addressed store. The architectural
    # principle's stated price -- "nothing is ever freed" -- made measurable.
    # Defaulted because it is the newest field and every existing caller
    # predates it; the quantity below reads it directly, so a state that
    # genuinely has no store measures zero growth rather than raising, which
    # is the correct reading for "no artifacts were stored".
    stored_bytes: int = 0
    # H6: signed envelopes since the origin — the cadence measurand. Folded
    # from the append-only envelope log, never an in-process counter.
    signed_envelope_count: int = 0
    # H3: sends that did NOT land on an attested peer — folded from the
    # append-only `egress_log`, for the same durability reason as H6. Excludes
    # ATTESTED_PEER by construction, which is what makes the quantity shrink as
    # the mesh grows (see `containment/egress.py`).
    mesh_exit_sends: int = 0
    # H3 AS A RATE: bytes that left via MESH_EXIT inside a TRAILING WALL-CLOCK
    # WINDOW, not since genesis. The count above is retained because it is what
    # `gyza status` reports and what the retired-shape record refers to, but it
    # carries no evidence -- a benign node and an exfiltrating one both emit
    # 1.000 sends per action (R-EVID Part B), so no level over it separates
    # them. Bytes do carry evidence, and a window is what keeps the fold from
    # being a timer.
    mesh_exit_bytes_in_window: int = 0
    mesh_exit_window_ns: int = 0
    #: C-2. Count of actions whose effects cannot be shown to be recoverable,
    #: folded from SIGNED enforcement records by
    #: `gyza.containment.irreversibility.fold_irreversible`. The caller folds;
    #: this module only projects.
    irreversible_actions: int = 0

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError(
                "GyzaState requires an owner: H1 and H2 are measured over a "
                "frame, and an unnamed frame is not a measurement")


@dataclass(frozen=True)
class WindowOrigin:
    """The named, immutable origin a cumulative bound is measured from.

    TWO COORDINATES, NOT ONE, and the reason is a defect this class exists to
    make unrepresentable. The two append-only logs are ordered by different
    keys: `LedgerEntry` by `created_at_ns` (what `Ledger.all_entries()` sorts
    by) and `CapitalEntry` by `seq` (an index assigned at append). A single
    origin value compared against both is a CATEGORY ERROR -- a nanosecond
    timestamp exceeds every plausible seq, so every capital entry would sort
    before the origin, `before` and `after` would be identical, and H2 would
    measure 0.0 and pass. That is the same silent zero this module was written
    to remove, reintroduced one layer up.

    Frozen, and captured when the window opens: the origin of a cumulative
    bound must be immutable for the lifetime of the bound (ledger artifact
    #13 -- a gate that measured from a moving checkpoint bought unlimited
    drain).
    """
    ledger_ns: int          # ledger entries with created_at_ns < this
    capital_seq: int        # capital entries with seq < this
    envelope_ns: int = 0    # signed envelopes with timestamp_ns >= this


def _ledger_before(entries: Sequence[object], origin: WindowOrigin):
    return [e for e in entries if getattr(e, "created_at_ns", 0) < origin.ledger_ns]


def _capital_before(entries: Sequence[object], origin: WindowOrigin):
    return [e for e in entries if getattr(e, "seq", 0) < origin.capital_seq]


def project_now(
    *,
    owner: str,
    ledger_entries: Sequence[object],
    active_holds: float,
    capital_entries: Sequence[object],
    authority_violations: Sequence[AuthorityViolation] = (),
    stored_bytes: int = 0,
    signed_envelope_count: int = 0,
    mesh_exit_sends: int = 0,
    mesh_exit_bytes_in_window: int = 0,
    mesh_exit_window_ns: int = 0,
    irreversible_actions: int = 0,
) -> GyzaState:
    """State as of now — the `s_next` of a guard evaluation."""
    return GyzaState(
        owner=owner,
        entries=list(ledger_entries),
        active_holds=float(active_holds),
        capital_entries=list(capital_entries),
        authority_violations=tuple(authority_violations),
        stored_bytes=int(stored_bytes),
        signed_envelope_count=int(signed_envelope_count),
        mesh_exit_sends=int(mesh_exit_sends),
        mesh_exit_bytes_in_window=int(mesh_exit_bytes_in_window),
        mesh_exit_window_ns=int(mesh_exit_window_ns),
        irreversible_actions=int(irreversible_actions),
    )


def project_at_origin(
    *,
    owner: str,
    ledger_entries: Sequence[object],
    capital_entries: Sequence[object],
    origin: WindowOrigin,
    authority_violations: Sequence[AuthorityViolation] = (),
    stored_bytes_at_origin: int = 0,
    mesh_exit_sends_at_origin: int = 0,
) -> GyzaState:
    """State as of the accounting window's origin — the `s0`.

    `active_holds` is 0.0 by construction and that is not a stub: a hold is a
    live reservation, so the origin snapshot has none outstanding. Holds enter
    the measurement through `s_next` only, which is what makes them count as
    credits *at risk* rather than credits *spent*.
    """
    return GyzaState(
        owner=owner,
        entries=_ledger_before(ledger_entries, origin),
        active_holds=0.0,
        capital_entries=_capital_before(capital_entries, origin),
        authority_violations=tuple(
            v for v in authority_violations if v.at_ns < origin.ledger_ns),
        # Storage is APPEND-ONLY and has no per-entry timestamp to filter on,
        # so the origin value must be CAPTURED when the window opens rather
        # than reconstructed. An origin that cannot be recomputed must be
        # recorded; inferring one would be the moving-frame defect again.
        stored_bytes=int(stored_bytes_at_origin),
        # H3, unlike H5, CAN be recomputed: `egress_log` carries a timestamp per
        # row, so `count_egress_since(origin_ns, MESH_EXIT)` reconstructs this
        # exactly. It is still passed in rather than derived here, because this
        # module must not learn what a blackboard is -- the caller folds, this
        # projects.
        mesh_exit_sends=int(mesh_exit_sends_at_origin),
    )


__all__ = ["GyzaState", "AuthorityViolation", "WindowOrigin", "project_now",
           "project_at_origin"]
