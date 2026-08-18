"""
S1 — append-only event log, generalized beyond credits.

The ledger pattern already in production (gyza/economy/ledger.py:30-32
"entries are append-only, there is no update_entry"; gyza/economy/wallet.py:169-171
"pure projection over an iterable of LedgerEntry") is the right shape for ALL
staged state, not only for money. This is that pattern with the domain removed.

The representation rule it implements, and why each word is load-bearing:

  APPEND-ONLY        there is no update and no delete API. Not "discouraged" --
                     absent. If history can be rewritten the fold is no longer
                     a function of what happened (C9).
  PARTITIONED        every event carries a partition key, because a guard
                     scales in breadth only if its own state partitions along
                     the same axis as the actions (C8). A single global counter
                     serializes no matter how the underlying resource is split
                     -- that is R10's H-CONS refutation, and it is why the key
                     is mandatory rather than optional.
  DERIVED-NOT-STORED there is no stored aggregate. State is `fold()`, a pure
                     projection. Every path that changes a quantity must append
                     an event, so the gate that folds those events necessarily
                     sees it, and a blind channel has nowhere to hide (R12
                     Part C).

Tamper evidence comes free: events are hash-chained the way ICP envelopes are,
so an edited or excised event breaks the chain at that point and every point
after it.

THE COST, stated plainly and paid forever: NOTHING IS EVER FREED. Deletion
stops reclaiming anything and storage grows without bound. That is the whole
price of the guarantee and it is a bad trade for high-volume, low-stakes state.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

import blake3

# Control events. Domain folds skip these; the audit view does not.
KIND_PROMOTE = "__promote__"
KIND_ROLLBACK = "__rollback__"
# An ACCOUNTING WINDOW boundary. A cumulative bound stated "per window" needs a
# window that exists as a named thing; before this marker the boundary was
# implicit in whenever a caller happened to invoke promote(), which made the
# origin of every cumulative measurement caller-timed rather than fixed.
#
# It is a LOG EVENT, not a field on the staging area, and that is the whole
# design: the window's identity is its marker's `seq`, and an append-only log
# never rewrites a seq. So the origin cannot re-base for the lifetime of the
# window -- not by discipline, but because there is no operation that would do
# it. Derived-not-stored, applied to the frame itself.
KIND_WINDOW_OPEN = "__window_open__"
CONTROL_KINDS = frozenset({KIND_PROMOTE, KIND_ROLLBACK, KIND_WINDOW_OPEN})

GENESIS = "0" * 64


@dataclass(frozen=True)
class Event:
    seq: int
    partition: str
    kind: str
    payload: dict
    ts_ns: int
    prev_hash: str
    hash: str

    def canonical_bytes(self) -> bytes:
        """Everything except the hash itself, canonically ordered."""
        return json.dumps(
            {"seq": self.seq, "partition": self.partition, "kind": self.kind,
             "payload": self.payload, "ts_ns": self.ts_ns,
             "prev_hash": self.prev_hash},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")


def _hash(seq: int, partition: str, kind: str, payload: dict, ts_ns: int,
          prev_hash: str) -> str:
    return blake3.blake3(json.dumps(
        {"seq": seq, "partition": partition, "kind": kind, "payload": payload,
         "ts_ns": ts_ns, "prev_hash": prev_hash},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class AppendOnlyLog:
    """There is deliberately no ``update`` and no ``delete``. Adjustments are
    made by appending a compensating event, exactly as the credit ledger issues
    a counter-entry rather than editing one."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    # -- the only mutator --------------------------------------------------
    def append(self, partition: str, kind: str, payload: dict | None = None,
               ts_ns: int | None = None) -> Event:
        if not partition:
            raise ValueError(
                "every event must carry a partition key: a guard scales in "
                "breadth only if its state partitions along the action axis (C8)"
            )
        seq = len(self._events)
        prev = self._events[-1].hash if self._events else GENESIS
        ts = time.time_ns() if ts_ns is None else int(ts_ns)
        pl = dict(payload or {})
        e = Event(seq=seq, partition=partition, kind=kind, payload=pl,
                  ts_ns=ts, prev_hash=prev,
                  hash=_hash(seq, partition, kind, pl, ts, prev))
        self._events.append(e)
        return e

    # -- read-only projections --------------------------------------------
    def __iter__(self) -> Iterator[Event]:
        return iter(tuple(self._events))

    def __len__(self) -> int:
        return len(self._events)

    @property
    def last_seq(self) -> int:
        return len(self._events) - 1

    def get(self, seq: int) -> Event:
        return self._events[seq]

    def partitions(self) -> set[str]:
        return {e.partition for e in self._events}

    def events(self, *, partition: str | None = None,
               include_control: bool = False,
               skip: Callable[[Event], bool] | None = None) -> list[Event]:
        out = []
        for e in self._events:
            if not include_control and e.kind in CONTROL_KINDS:
                continue
            if partition is not None and e.partition != partition:
                continue
            if skip is not None and skip(e):
                continue
            out.append(e)
        return out

    def fold(self, reducer: Callable[[object, Event], object], initial: object,
             *, partition: str | None = None,
             skip: Callable[[Event], bool] | None = None) -> object:
        """Pure projection. The ONLY way to obtain state from this log."""
        acc = initial
        for e in self.events(partition=partition, skip=skip):
            acc = reducer(acc, e)
        return acc

    # -- integrity ---------------------------------------------------------
    def verify(self) -> tuple[bool, str]:
        """Recompute the chain. An edited or excised event breaks here and at
        every point after it."""
        prev = GENESIS
        for i, e in enumerate(self._events):
            if e.seq != i:
                return False, f"seq {e.seq} out of order at index {i}"
            if e.prev_hash != prev:
                return False, f"broken link at seq {e.seq}"
            if e.hash != _hash(e.seq, e.partition, e.kind, e.payload,
                               e.ts_ns, e.prev_hash):
                return False, f"tampered payload at seq {e.seq}"
            prev = e.hash
        return True, ""
