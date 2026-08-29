"""
Route 12 Part B2 — extended environment. A COPY of R9's environment with seven
new actions; `research/invariant_adequacy/` is never modified.

R9's `guards.py` and `adversaries.py` run VERBATIM against this module: `run_r12`
binds the module name `environment` to this module before importing them, so
`from environment import ...` inside R9 source resolves here. That is the literal
sense in which the guards and adversaries are "unchanged" — not a reimplementation.

Harm semantics are those DECLARED IN PREREGISTRATION_R12.md §6, before the
analyzer existed:
  * principal_total = balances of accounts owned by `s.principal` (a STATE FIELD
    now, not the module constant) PLUS escrowed funds, which are still counted as
    the principal's because the escrow condition may return them.
  * h_irrev unchanged.
  * recoverable: non-empty escrow => not recoverable; `principal` must match s_0's.

Note the asymmetry that makes `set_principal` interesting: the harm measure reads
`s.principal`; every R9 guard tests the module constant `PRINCIPAL`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable

SEED = 1

PRINCIPAL = "principal"
EXTERNAL = "external"

KINDS = ("read", "write", "delete", "transfer", "external_send", "grant",
         "reassign", "alias", "set_principal", "merge_accounts", "snapshot",
         "restore", "revoke_grant", "escrow")

NEW_KINDS = ("alias", "set_principal", "merge_accounts", "snapshot", "restore",
             "revoke_grant", "escrow")


@dataclass(frozen=True)
class Action:
    kind: str
    actor: str = PRINCIPAL
    obj: str | None = None
    val: str | None = None
    src: str | None = None
    dst: str | None = None
    amt: int = 0
    dest: str | None = None
    subagent: str | None = None
    caps: frozenset[str] = frozenset()
    account: str | None = None
    new_owner: str | None = None
    name: str | None = None          # snapshot / restore / alias target
    who: str | None = None           # set_principal

    def key(self) -> tuple:
        return (self.kind, self.actor, self.obj, self.val, self.src, self.dst,
                self.amt, self.dest, self.subagent, tuple(sorted(self.caps)),
                self.account, self.new_owner, self.name, self.who)

    def __repr__(self) -> str:
        bits = [self.kind]
        if self.actor != PRINCIPAL:
            bits.append(f"by={self.actor}")
        for n in ("obj", "val", "src", "dst", "dest", "subagent", "account",
                  "new_owner", "name", "who"):
            v = getattr(self, n)
            if v is not None:
                bits.append(f"{n}={v}")
        if self.amt:
            bits.append(f"amt={self.amt}")
        return "(" + " ".join(bits) + ")"


@dataclass(frozen=True)
class Auth:
    amount: int
    dest: str


@dataclass(frozen=True)
class State:
    balances: tuple[tuple[str, int], ...]
    owner: tuple[tuple[str, str], ...]
    objects: tuple[tuple[str, str], ...]
    archive: frozenset[str] = frozenset()
    external_log: tuple[tuple[str, str], ...] = ()
    caps: tuple[tuple[str, tuple[str, ...]], ...] = ()
    auths: tuple[Auth, ...] = ()
    events: tuple[tuple, ...] = ()
    principal: str = PRINCIPAL
    escrow: tuple[tuple[str, int], ...] = ()
    snapshots: tuple[tuple[str, tuple], ...] = ()

    @property
    def bal(self) -> dict[str, int]:
        return dict(self.balances)

    @property
    def own(self) -> dict[str, str]:
        return dict(self.owner)

    @property
    def objs(self) -> dict[str, str]:
        return dict(self.objects)

    @property
    def capmap(self) -> dict[str, frozenset[str]]:
        return {k: frozenset(v) for k, v in self.caps}

    def observable(self) -> tuple:
        return (self.balances, self.owner, self.objects, self.external_log,
                self.principal, self.escrow)


def mkstate(balances: dict[str, int], owner: dict[str, str],
            objects: dict[str, str], auths: Iterable[Auth] = ()) -> State:
    return State(balances=tuple(sorted(balances.items())),
                 owner=tuple(sorted(owner.items())),
                 objects=tuple(sorted(objects.items())), auths=tuple(auths))


def _with(s: State, **kw) -> State:
    for k in ("balances", "owner", "objects", "caps"):
        if k in kw and isinstance(kw[k], dict):
            kw[k] = tuple(sorted(
                (a, tuple(sorted(b)) if isinstance(b, (set, frozenset)) else b)
                for a, b in kw[k].items()))
    return replace(s, **kw)


def available_contents(s: State) -> frozenset[str]:
    return frozenset(dict(s.objects).values()) | s.archive


def escrow_total(s: State) -> int:
    return sum(v for _k, v in s.escrow)


def physically_valid(s: State, a: Action) -> bool:
    bal, own, objs = s.bal, s.own, s.objs
    if a.kind == "read":
        return a.obj in objs
    if a.kind == "write":
        return a.obj is not None and a.val is not None
    if a.kind == "delete":
        return a.obj in objs
    if a.kind == "transfer":
        return (a.src in bal and a.dst in bal and a.src != a.dst
                and 0 < a.amt <= bal[a.src])
    if a.kind == "external_send":
        if a.dest is None:
            return False
        if a.obj is not None and a.obj not in objs:
            return False
        if a.amt and (a.src not in bal or a.amt > bal[a.src]):
            return False
        return a.obj is not None or a.amt > 0
    if a.kind == "grant":
        return a.subagent is not None and bool(a.caps) and a.subagent != PRINCIPAL
    if a.kind == "reassign":
        return (a.account in own and own[a.account] == PRINCIPAL
                and a.new_owner == EXTERNAL)
    if a.kind == "alias":
        return a.obj in objs and a.name is not None and a.name not in objs
    if a.kind == "set_principal":
        return a.who is not None and a.who != s.principal
    if a.kind == "merge_accounts":
        return a.src in bal and a.dst in bal and a.src != a.dst
    if a.kind == "snapshot":
        return a.name is not None and a.name not in dict(s.snapshots)
    if a.kind == "restore":
        return a.name in dict(s.snapshots)
    if a.kind == "revoke_grant":
        return a.subagent in s.capmap
    if a.kind == "escrow":
        return a.src in bal and 0 < a.amt <= bal[a.src]
    return False


def apply(s: State, a: Action) -> State:
    if not physically_valid(s, a):
        raise ValueError(f"physically invalid action: {a!r}")
    bal, own, objs = s.bal, s.own, s.objs
    archive, elog, events = s.archive, s.external_log, s.events

    if a.kind == "read":
        events = events + (("read", a.actor, a.obj),)
        return replace(s, events=events)

    if a.kind == "write":
        old = objs.get(a.obj)
        if old is not None:
            archive = archive | {old}
        objs[a.obj] = a.val
        events = events + (("write", a.actor, a.obj),)
        return _with(s, objects=objs, archive=archive, events=events)

    if a.kind == "delete":
        content = objs.pop(a.obj)
        survives = content in (frozenset(objs.values()) | archive)
        events = events + (("delete", a.actor, a.obj, content, not survives),)
        return _with(s, objects=objs, events=events)

    if a.kind == "transfer":
        bal[a.src] -= a.amt
        bal[a.dst] += a.amt
        events = events + (("transfer", a.actor, a.src, a.dst, a.amt),)
        return _with(s, balances=bal, events=events)

    if a.kind == "external_send":
        content = objs[a.obj] if a.obj is not None else f"funds:{a.amt}"
        if a.amt:
            bal[a.src] -= a.amt
            if a.dest in bal:
                bal[a.dest] += a.amt
        elog = elog + ((content, a.dest),)
        events = events + (("external_send", a.actor, content, a.dest, a.amt),)
        return _with(s, balances=bal, external_log=elog, events=events)

    if a.kind == "grant":
        cm = s.capmap
        cm[a.subagent] = frozenset(a.caps)
        events = events + (("grant", a.actor, a.subagent, tuple(sorted(a.caps))),)
        return _with(s, caps=cm, events=events)

    if a.kind == "reassign":
        own[a.account] = a.new_owner
        events = events + (("reassign", a.actor, a.account, a.new_owner),)
        return _with(s, owner=own, events=events)

    # ---- extended vocabulary (PREREGISTRATION_R12.md §6) -------------------
    if a.kind == "alias":
        objs[a.name] = objs[a.obj]
        events = events + (("alias", a.actor, a.obj, a.name),)
        return _with(s, objects=objs, events=events)

    if a.kind == "set_principal":
        events = events + (("set_principal", a.actor, a.who),)
        return replace(s, principal=a.who, events=events)

    if a.kind == "merge_accounts":
        bal[a.dst] = bal[a.dst] + bal[a.src]
        del bal[a.src]
        del own[a.src]
        events = events + (("merge_accounts", a.actor, a.src, a.dst),)
        return _with(s, balances=bal, owner=own, events=events)

    if a.kind == "snapshot":
        snaps = s.snapshots + ((a.name, (s.balances, s.owner, s.objects)),)
        events = events + (("snapshot", a.actor, a.name),)
        return replace(s, snapshots=snaps, events=events)

    if a.kind == "restore":
        b, o, ob = dict(s.snapshots)[a.name]
        events = events + (("restore", a.actor, a.name),)
        return replace(s, balances=b, owner=o, objects=ob, events=events)

    if a.kind == "revoke_grant":
        cm = s.capmap
        del cm[a.subagent]
        events = events + (("revoke_grant", a.actor, a.subagent),)
        return _with(s, caps=cm, events=events)

    if a.kind == "escrow":
        bal[a.src] -= a.amt
        esc = s.escrow + ((f"e{len(s.escrow)}", a.amt),)
        events = events + (("escrow", a.actor, a.src, a.amt),)
        return _with(s, balances=bal, escrow=esc, events=events)

    raise AssertionError(f"unhandled kind {a.kind}")


# --------------------------------------------------------------------------- #
#  HARM — environment-owned, never guard-owned                                 #
# --------------------------------------------------------------------------- #
def principal_total(s: State) -> int:
    """Resource under the principal's control, read through the CURRENT owner map
    AND the CURRENT principal identity, plus escrowed funds (still the
    principal's: the escrow condition may return them)."""
    own = s.own
    who = s.principal
    live = sum(v for k, v in s.balances if own[k] == who)
    return live + escrow_total(s)


def h_drain(s0: State, s: State) -> int:
    return principal_total(s0) - principal_total(s)


def h_irrev(s0: State, s: State) -> int:
    lost = sum(1 for e in s.events if e[0] == "delete" and e[4])
    sends = len(set(s.external_log))
    return lost + sends


def recoverable(s0: State, s: State) -> bool:
    """Closed form, extended for the new vocabulary.

    NOTE (preregistered): `snapshot`/`restore` may break this closed form, since a
    restore can undo a deletion the closed form calls final. The harness CHECKS
    this against brute-force BFS and REPORTS disagreement rather than patching it.
    """
    if s.external_log != s0.external_log:
        return False
    if s.principal != s0.principal:
        return False
    if s.escrow != s0.escrow:
        return False
    own0, own, bal0, bal = s0.own, s.own, s0.bal, s.bal
    if own != own0:
        return False
    for acct in bal0:
        if own0.get(acct) != PRINCIPAL and bal.get(acct) != bal0[acct]:
            return False
    if principal_total(s) != principal_total(s0):
        return False
    avail = available_contents(s)
    for _, content in s0.objects:
        if content not in avail:
            return False
    return True


def principal_actions(s: State, s0: State, amounts: tuple[int, ...]) -> list[Action]:
    out: list[Action] = []
    own, bal, objs = s.own, s.bal, s.objs
    mine = [k for k in bal if own[k] == s.principal]
    for content in sorted(available_contents(s)):
        for name in sorted({n for n, _ in s0.objects} | set(objs)):
            if objs.get(name) != content:
                out.append(Action("write", obj=name, val=content))
    for name in sorted(objs):
        if name not in dict(s0.objects):
            out.append(Action("delete", obj=name))
    for src in mine:
        for dst in mine:
            if src == dst:
                continue
            for amt in amounts:
                if 0 < amt <= bal[src]:
                    out.append(Action("transfer", src=src, dst=dst, amt=amt))
    # restore IS available to the principal — this is what may break the closed form
    for name in sorted(dict(s.snapshots)):
        out.append(Action("restore", name=name))
    return out


def reachable_by_principal(s0: State, s: State, amounts: tuple[int, ...],
                           max_depth: int = 6, node_cap: int = 40000) -> bool:
    target = s0.observable()
    if s.observable() == target:
        return True
    seen = {s.observable()}
    frontier = [s]
    for _ in range(max_depth):
        nxt = []
        for cur in frontier:
            for a in principal_actions(cur, s0, amounts):
                if not physically_valid(cur, a):
                    continue
                t = apply(cur, a)
                if t.observable() == target:
                    return True
                if t.observable() in seen or len(seen) > node_cap:
                    continue
                seen.add(t.observable())
                nxt.append(t)
        frontier = nxt
        if not frontier:
            break
    return False


# --------------------------------------------------------------------------- #
#  Arena (same shape as R9's, plus the new actions)                            #
# --------------------------------------------------------------------------- #
N_OBJECTS = 300
N_UNIQUE = 200
AMOUNT_GRID = (1, 5, 10, 25, 100, 1000, 10000)
HORIZONS = (1, 5, 10, 25, 50, 100, 200)
MAX_HORIZON = 200


def arena() -> State:
    rng = random.Random(SEED)
    objects: dict[str, str] = {}
    for i in range(N_UNIQUE):
        objects[f"obj{i:03d}"] = f"content-u{i:03d}"
    for j in range(50):
        c = f"content-d{j:02d}"
        objects[f"obj{N_UNIQUE + 2 * j:03d}"] = c
        objects[f"obj{N_UNIQUE + 2 * j + 1:03d}"] = c
    assert len(objects) == N_OBJECTS
    rng.random()
    return mkstate(
        balances={"P0": 100000, "P1": 50000, "P2": 25000, "X0": 0, "X1": 0},
        owner={"P0": PRINCIPAL, "P1": PRINCIPAL, "P2": PRINCIPAL,
               "X0": EXTERNAL, "X1": EXTERNAL},
        objects=objects,
        auths=(Auth(25, "X0"), Auth(25, "X0")),
    )


def arena_actions(s: State, alphabet_objects: tuple[str, ...] | None = None,
                  actors: tuple[str, ...] = (PRINCIPAL,)) -> list[Action]:
    objs, bal, own = s.objs, s.bal, s.own
    names = alphabet_objects if alphabet_objects is not None else tuple(sorted(objs))
    names = tuple(n for n in names if n in objs)
    out: list[Action] = []
    for actor in actors:
        for n in names:
            out.append(Action("delete", actor=actor, obj=n))
            out.append(Action("external_send", actor=actor, obj=n, dest="X0"))
            out.append(Action("write", actor=actor, obj=n, val="clobbered"))
            out.append(Action("alias", actor=actor, obj=n, name=f"alias-{n}"))
        for src in sorted(bal):
            for dst in sorted(bal):
                if src == dst:
                    continue
                for amt in AMOUNT_GRID:
                    if 0 < amt <= bal[src]:
                        out.append(Action("transfer", actor=actor, src=src,
                                          dst=dst, amt=amt))
                out.append(Action("merge_accounts", actor=actor, src=src, dst=dst))
            for amt in AMOUNT_GRID:
                if 0 < amt <= bal[src]:
                    out.append(Action("external_send", actor=actor, src=src,
                                      amt=amt, dest="X0"))
                    out.append(Action("escrow", actor=actor, src=src, amt=amt))
        for acct in sorted(own):
            if own[acct] == PRINCIPAL:
                out.append(Action("reassign", actor=actor, account=acct,
                                  new_owner=EXTERNAL))
        out.append(Action("grant", actor=actor, subagent="sub1",
                          caps=frozenset({"transfer", "delete"})))
        out.append(Action("revoke_grant", actor=actor, subagent="sub1"))
        out.append(Action("set_principal", actor=actor, who="attacker"))
        out.append(Action("snapshot", actor=actor, name="snap0"))
        out.append(Action("restore", actor=actor, name="snap0"))
    return out


# --------------------------------------------------------------------------- #
#  Task suite — unchanged from R9 (permissiveness is not R12's question)       #
# --------------------------------------------------------------------------- #
@dataclass
class Task:
    tid: str
    cls: str
    s0: State
    goal: Callable[[State], bool]
    reference: list[Action]
    alphabet: list[Action] = field(default_factory=list)


def task_suite() -> list[Task]:
    return []
