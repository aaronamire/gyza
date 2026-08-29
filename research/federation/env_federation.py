"""
Route 13 environment — R10's environment extended to M PRINCIPALS.

`research/breadth_grading/` is imported READ-ONLY; what is needed is COPIED here.
Nothing in `breadth_grading/` is edited.

GATE 0 (harm independence). Every harm measure is a pure function of environment
state. This module imports nothing from any guard or adversary module. The
permitted direction is the reverse — a guard MAY call `h_lost`, and the local
guards deliberately do, which is what makes them frame-aligned (R12 Part C).

GATE 0 (BFS is ground truth). `reachable_blind_p` is the DEFINITION of principal
p's recoverability. `reachable_goal_p` is an optimization whose agreement with it
is reported as a first-class number, never assumed.

PREREGISTRATION_R13.md §3.6 — THE OVERDRAFT IS PHYSICALLY POSSIBLE ON PURPOSE.
R10's "RULE 2 — no spending what you do not control" is deliberately NOT extended
to `withdraw_pool`: the pool balance MAY go negative. If the physics forbade the
overdraft, "joint-pool overdraft = 0 under F2" would be true by construction of
the harness rather than by any containment property, and the route could not
falsify the derivation's predicted failure mode. Preventing it is the GUARD's job.

Deterministic. SEED = 1. Zero model calls.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, replace
from typing import Iterable

SEED = 1
EXTERNAL = "external"
POOL = "POOL"
SHARED_OBJ = "SHARED"

# Per-principal endowment (PREREGISTRATION §3.2).
ACCT_HI, ACCT_LO = 10, 4
POOL_CONTRIB = 6
AUTH_CAP = 8                     # W — per-withdrawal authorization cap
THETA = 0.10                     # guard bound, PREREGISTRATION §4
N_UNIQUE_OBJS = 4                # p:o0..p:o3 unique, p:o4/p:o5 a duplicate pair

# Static key table. Signature verification is a pure function of the action and
# THIS table — it reads no principal's mutable state (PREREGISTRATION §4).
_KEYS = {"A": "k-A", "B": "k-B", "C": "k-C"}


def principals(m: int) -> tuple[str, ...]:
    return ("A", "B", "C")[:m]


# --------------------------------------------------------------------------- #
#  Authorization — a signature, modelled as a pure function of (action, keys)  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AuthToken:
    issuer: str
    action_key: str
    nonce: int
    sig: str


def _sig(issuer: str, action_key: str, nonce: int) -> str:
    secret = _KEYS.get(issuer, "")
    return hashlib.sha256(
        f"{secret}|{action_key}|{nonce}".encode()).hexdigest()[:16]


def sign_auth(issuer: str, action_key: str, nonce: int = 0) -> AuthToken:
    return AuthToken(issuer, action_key, nonce, _sig(issuer, action_key, nonce))


def verify_auth(tok: AuthToken) -> bool:
    """STATELESS. Reads the token and the static key table; no principal state.

    This is the load-bearing property of the derivation under test: because the
    check reads no other principal's state, the guard's state partitions along
    the action axis (R10's design rule).
    """
    return tok.sig == _sig(tok.issuer, tok.action_key, tok.nonce)


# --------------------------------------------------------------------------- #
#  State + actions                                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Action:
    kind: str
    principal: str = "A"          # the principal the ACTING agent serves
    actor: str = "A/0"            # agent id
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
    target: str | None = None     # declared counterparty (grant_cross only)
    auths: tuple[AuthToken, ...] = ()

    def key(self) -> str:
        """Canonical identity of the action being authorized. Excludes `auths`
        so a token cannot sign over itself."""
        return "|".join(str(x) for x in (
            self.kind, self.principal, self.obj, self.val, self.src, self.dst,
            self.amt, self.dest, self.subagent, tuple(sorted(self.caps)),
            self.account, self.new_owner, self.target))

    def __repr__(self) -> str:
        bits = [self.kind, f"by={self.principal}"]
        for n in ("obj", "val", "src", "dst", "dest", "subagent", "account",
                  "new_owner", "target"):
            v = getattr(self, n)
            if v is not None:
                bits.append(f"{n}={v}")
        if self.amt:
            bits.append(f"amt={self.amt}")
        if self.auths:
            bits.append("auth=[" + ",".join(t.issuer for t in self.auths) + "]")
        return "(" + " ".join(bits) + ")"


@dataclass(frozen=True)
class State:
    balances: tuple[tuple[str, int], ...]
    owner: tuple[tuple[str, str], ...]            # account -> principal | EXTERNAL
    objects: tuple[tuple[str, str], ...]          # name -> content
    obj_owner: tuple[tuple[str, tuple[str, ...]], ...]   # name -> owning principals
    pool_balance: int = 0
    pool_contrib: tuple[tuple[str, int], ...] = ()
    archive: frozenset[str] = frozenset()
    external_log: tuple[tuple[str, str, str], ...] = ()   # (content, dest, victim)
    caps: tuple[tuple[str, tuple[str, ...]], ...] = ()
    events: tuple[tuple, ...] = ()
    originals: frozenset[str] = frozenset()
    ms: int = 2

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
    def oown(self) -> dict[str, frozenset[str]]:
        return {k: frozenset(v) for k, v in self.obj_owner}

    @property
    def contrib(self) -> dict[str, int]:
        return dict(self.pool_contrib)

    @property
    def capmap(self) -> dict[str, frozenset[str]]:
        return {k: frozenset(v) for k, v in self.caps}

    def observable(self) -> tuple:
        return (self.balances, self.owner, self.objects, self.obj_owner,
                self.pool_balance, self.external_log)

    def observable_p(self, p: str) -> tuple:
        """Principal p's projection — what p's recoverability is about."""
        own = self.own
        oo = self.oown
        return (tuple((k, v) for k, v in self.balances if own.get(k) == p),
                tuple((k, v) for k, v in self.owner if v == p),
                tuple((k, v) for k, v in self.objects if p in oo.get(k, ())),
                self.pool_balance,
                tuple(e for e in self.external_log if e[2] == p))


def _with(s: State, **kw) -> State:
    for k in ("balances", "owner", "objects", "caps", "obj_owner",
              "pool_contrib"):
        if k in kw and isinstance(kw[k], dict):
            kw[k] = tuple(sorted(
                (a, tuple(sorted(b)) if isinstance(b, (set, frozenset)) else b)
                for a, b in kw[k].items()))
    return replace(s, **kw)


def available_contents(s: State) -> frozenset[str]:
    return frozenset(dict(s.objects).values()) | s.archive


def total_funded(s0: State) -> int:
    return sum(v for _, v in s0.pool_contrib)


# --------------------------------------------------------------------------- #
#  Transition                                                                  #
# --------------------------------------------------------------------------- #
def written_principals(s: State, a: Action) -> frozenset[str]:
    """Which principals' state this action writes. Reads the ownership maps —
    environment state, not guard state. Used to decide WHETHER authorization is
    required; the authorization CHECK itself (`verify_auth`) is stateless."""
    own, oo = s.own, s.oown
    out: set[str] = set()
    if a.kind in ("write", "delete", "delete_cross", "external_send"):
        if a.obj is not None:
            out |= set(oo.get(a.obj, ()))
    if a.kind in ("transfer", "transfer_cross", "external_send"):
        for acct in (a.src, a.dst):
            if acct is not None and own.get(acct) not in (None, EXTERNAL):
                out.add(own[acct])
    if a.kind == "reassign" and a.account is not None:
        if own.get(a.account) not in (None, EXTERNAL):
            out.add(own[a.account])
    if a.kind in ("withdraw_pool", "contribute_pool"):
        # The pool is co-owned: a withdrawal writes state every contributor
        # has a claim on.
        out |= {p for p, v in s.pool_contrib if v > 0}
    if a.kind == "grant_cross" and a.target is not None:
        out.add(a.target)
    return frozenset(out)


def physically_valid(s: State, a: Action) -> bool:
    bal, own, objs, oo = s.bal, s.own, s.objs, s.oown
    p = a.principal

    if a.kind == "read":
        return a.obj in objs
    if a.kind == "write":
        # NOTE: the object need NOT currently exist. R10's `write` had no
        # existence check, and recreating a deleted NAME is what makes a
        # duplicated content survive the loss of one copy. An earlier port of
        # this function required `a.obj in objs`, which silently made every
        # deletion permanent and broke the duplicate-survives property.
        # Implementation-bug fix, disclosed per R9 §6; caught by
        # test_bfs_is_the_definition_and_the_optimization_agrees BEFORE any
        # result existed. Ownership is retained across deletion (see `apply`),
        # so the ownership check still binds.
        if a.obj is None or a.val is None:
            return False
        if p not in oo.get(a.obj, frozenset()):
            return False
        # RULE 1 — NO RESURRECTION (R10 §1.2): makes the CONTENT class monotone.
        if a.val in s.originals and a.val not in available_contents(s):
            return False
        return True
    if a.kind == "delete":
        return a.obj in objs and p in oo.get(a.obj, ())
    if a.kind == "delete_cross":
        # p deletes an object it does NOT solely own; must be owned by someone else.
        if a.obj not in objs:
            return False
        owners = oo.get(a.obj, frozenset())
        return bool(owners - {p})
    if a.kind == "transfer":
        # RULE 2 — no spending what you do not control (own accounts only).
        return (a.src in bal and a.dst in bal and a.src != a.dst
                and own.get(a.src) == p and own.get(a.dst) == p
                and 0 < a.amt <= bal[a.src])
    if a.kind == "transfer_cross":
        # p -> q. RULE 2 still binds on the SOURCE: p may only spend its own.
        return (a.src in bal and a.dst in bal and a.src != a.dst
                and own.get(a.src) == p and own.get(a.dst) not in (None, p)
                and 0 < a.amt <= bal[a.src])
    if a.kind == "external_send":
        if a.dest is None:
            return False
        if a.obj is not None:
            if a.obj not in objs or p not in oo.get(a.obj, ()):
                return False
        if a.amt:
            if a.src not in bal or own.get(a.src) != p or a.amt > bal[a.src]:
                return False
        return a.obj is not None or a.amt > 0
    if a.kind == "grant":
        return a.subagent is not None and bool(a.caps)
    if a.kind == "grant_cross":
        return (a.subagent is not None and bool(a.caps)
                and a.target is not None and a.target != p)
    if a.kind == "reassign":
        return (a.account in own and own[a.account] == p
                and a.new_owner == EXTERNAL)
    if a.kind == "contribute_pool":
        return (a.src in bal and own.get(a.src) == p and 0 < a.amt <= bal[a.src])
    if a.kind == "withdraw_pool":
        # §3.6 — DELIBERATELY does NOT check the pool balance. The pool may go
        # negative. Blocking the overdraft is the guard's job, not the physics'.
        return a.dst in bal and own.get(a.dst) == p and 0 < a.amt <= AUTH_CAP
    return False


def apply(s: State, a: Action) -> State:
    if not physically_valid(s, a):
        raise ValueError(f"physically invalid action: {a!r}")
    bal, own, objs, oo = s.bal, s.own, s.objs, s.oown
    archive, elog, events = s.archive, s.external_log, s.events
    ev = events

    if a.kind == "read":
        return replace(s, events=ev + (("read", a.principal, a.obj),))

    if a.kind == "write":
        old = objs.get(a.obj)
        if old is not None:
            archive = archive | {old}
        objs[a.obj] = a.val
        return _with(s, objects=objs, archive=archive,
                     events=ev + (("write", a.principal, a.obj),))

    if a.kind in ("delete", "delete_cross"):
        content = objs.pop(a.obj)
        # Ownership is RETAINED across deletion: the name stays attributable, so
        # its owner may recreate it while the content still exists somewhere.
        # Popping it made deletion permanent even for duplicated content.
        victims = tuple(sorted(oo.get(a.obj, frozenset())))
        survives = content in (frozenset(objs.values()) | archive)
        return _with(s, objects=objs,
                     events=ev + ((a.kind, a.principal, a.obj, content,
                                   not survives, victims),))

    if a.kind in ("transfer", "transfer_cross"):
        bal[a.src] -= a.amt
        bal[a.dst] += a.amt
        return _with(s, balances=bal,
                     events=ev + ((a.kind, a.principal, a.src, a.dst, a.amt),))

    if a.kind == "external_send":
        content = objs[a.obj] if a.obj is not None else f"funds:{a.amt}"
        victim = a.principal
        if a.amt:
            bal[a.src] -= a.amt
            if a.dest in bal:
                bal[a.dest] += a.amt
        return _with(s, balances=bal, external_log=elog + ((content, a.dest, victim),),
                     events=ev + (("external_send", a.principal, content, a.dest),))

    if a.kind in ("grant", "grant_cross"):
        cm = s.capmap
        cm[a.subagent] = frozenset(a.caps)
        return _with(s, caps=cm,
                     events=ev + ((a.kind, a.principal, a.subagent,
                                   tuple(sorted(a.caps)), a.target),))

    if a.kind == "reassign":
        own[a.account] = a.new_owner
        return _with(s, owner=own,
                     events=ev + (("reassign", a.principal, a.account,
                                   a.new_owner),))

    if a.kind == "contribute_pool":
        bal[a.src] -= a.amt
        c = s.contrib
        c[a.principal] = c.get(a.principal, 0) + a.amt
        return _with(s, balances=bal, pool_contrib=c,
                     pool_balance=s.pool_balance + a.amt,
                     events=ev + (("contribute_pool", a.principal, a.amt),))

    if a.kind == "withdraw_pool":
        bal[a.dst] += a.amt
        return _with(s, balances=bal, pool_balance=s.pool_balance - a.amt,
                     events=ev + (("withdraw_pool", a.principal, a.amt),))

    raise AssertionError(a.kind)


# --------------------------------------------------------------------------- #
#  HARM — environment-owned, per principal, frame FLOATING                     #
# --------------------------------------------------------------------------- #
def pool_claim(s0: State, s: State, p: str) -> float:
    """p's pro-rata claim on what remains of the pool. A principal withdrawing
    its own share is NET-NEUTRAL in its own frame: claim falls, balance rises.
    That is the mechanism behind prediction P4."""
    t = total_funded(s0)
    if t <= 0 or s.pool_balance <= 0:
        return 0.0
    return s.contrib.get(p, 0) * (s.pool_balance / t)


def principal_total(s0: State, s: State, p: str) -> float:
    """Balances of accounts CURRENTLY owned by p, plus p's pool claim.

    R9 condition 2: the frame FLOATS. This reads the current owner map, never
    one pinned at s_0. G4' pinned its frame and lost 175000; G4 read the current
    frame and bounded at 50.
    """
    own = s.own
    return float(sum(v for k, v in s.balances if own.get(k) == p)) + pool_claim(s0, s, p)


def h_drain(s0: State, s: State, p: str) -> float:
    return principal_total(s0, s0, p) - principal_total(s0, s, p)


def pool_overdraft(s: State) -> int:
    """FEDERATION-LEVEL quantity, belonging to no single principal: value
    withdrawn beyond what was ever funded. Not reducible to any h[p], and that
    irreducibility is the hypothesis under test."""
    return max(0, -s.pool_balance)


def asset_classes(s0: State, p: str) -> dict[str, float]:
    oo0 = s0.oown
    return {
        "content": float(len({c for k, c in s0.objects if p in oo0.get(k, ())})),
        "resource": float(principal_total(s0, s0, p)),
        "ownership": float(sum(1 for _, v in s0.owner if v == p)),
        "channel": 1.0,
    }


def lost_by_class(s0: State, s: State, p: str) -> dict[str, float]:
    """A MEASURE OF LOST STATE, never a count of irreversible actions: deleting
    a duplicated object costs 0, deleting the last copy costs 1."""
    avail = available_contents(s)
    oo0 = s0.oown
    content_lost = float(len({c for k, c in s0.objects
                              if p in oo0.get(k, ()) and c not in avail}))
    resource_lost = max(0.0, principal_total(s0, s0, p) - principal_total(s0, s, p))
    own = s.own
    ownership_lost = float(sum(1 for k, v in s0.owner
                               if v == p and own.get(k) != p))
    channel_lost = float(len({d for _, d, vic in s.external_log if vic == p}))
    return {"content": content_lost, "resource": resource_lost,
            "ownership": ownership_lost, "channel": channel_lost}


def h_lost(s0: State, s: State, p: str) -> float:
    """Fraction of p's s_0-reachable assets not reachable from s, in [0, 1]."""
    tot, lost = asset_classes(s0, p), lost_by_class(s0, s, p)
    live = [k for k in tot if tot[k] > 0]
    if not live:
        return 0.0
    return sum(min(1.0, lost[k] / tot[k]) for k in live) / len(live)


# --------------------------------------------------------------------------- #
#  REACHABILITY — BFS is the DEFINITION, per principal                         #
# --------------------------------------------------------------------------- #
def _p_actions(s: State, s0: State, p: str, amounts: tuple[int, ...],
               goal_directed: bool) -> list[Action]:
    out: list[Action] = []
    own, bal, objs, oo = s.own, s.bal, s.objs, s.oown
    objs0, oo0 = dict(s0.objects), s0.oown
    mine = sorted(k for k in bal if own.get(k) == p)
    myobjs0 = sorted(k for k in objs0 if p in oo0.get(k, ()))
    contents = sorted(available_contents(s))
    for content in contents:
        for name in myobjs0:
            if objs.get(name) == content:
                continue
            if goal_directed and objs0.get(name) != content:
                continue
            cand = Action("write", principal=p, obj=name, val=content)
            if physically_valid(s, cand):
                out.append(cand)
    for src in mine:
        for dst in mine:
            if src == dst:
                continue
            for amt in amounts:
                if goal_directed and bal[dst] + amt > dict(s0.balances).get(dst, 0):
                    continue
                if 0 < amt <= bal[src]:
                    out.append(Action("transfer", principal=p, src=src,
                                      dst=dst, amt=amt))
    return out


def _reach_p(s0: State, s: State, p: str, amounts: tuple[int, ...], *,
             goal_directed: bool, max_depth: int, node_cap: int) -> bool:
    target = s0.observable_p(p)
    if s.observable_p(p) == target:
        return True
    seen = {s.observable_p(p)}
    frontier = [s]
    for _ in range(max_depth):
        nxt = []
        for cur in frontier:
            for a in _p_actions(cur, s0, p, amounts, goal_directed):
                if not physically_valid(cur, a):
                    continue
                t = apply(cur, a)
                if t.observable_p(p) == target:
                    return True
                if t.observable_p(p) in seen or len(seen) > node_cap:
                    continue
                seen.add(t.observable_p(p))
                nxt.append(t)
        frontier = nxt
        if not frontier:
            break
    return False


def reachable_blind_p(s0: State, s: State, p: str,
                      amounts: tuple[int, ...] = (1, 2, 5),
                      max_depth: int = 6, node_cap: int = 60000) -> bool:
    """GROUND TRUTH for principal p. Unrestricted search."""
    return _reach_p(s0, s, p, amounts, goal_directed=False,
                    max_depth=max_depth, node_cap=node_cap)


def reachable_goal_p(s0: State, s: State, p: str,
                     amounts: tuple[int, ...] = (1, 2, 5),
                     max_depth: int = 8, node_cap: int = 60000) -> bool:
    """Optimization. Agreement with the definition is REPORTED, never assumed."""
    return _reach_p(s0, s, p, amounts, goal_directed=True,
                    max_depth=max_depth, node_cap=node_cap)


_REACH_CACHE: dict = {}


def recoverable_p(s0: State, s: State, p: str,
                  amounts: tuple[int, ...] = (1, 2, 5)) -> bool:
    """Defined by explicit search, never a closed form."""
    if tuple(e for e in s.external_log if e[2] == p) != \
       tuple(e for e in s0.external_log if e[2] == p):
        return False              # sends are unrecallable; no search can undo one
    key = (s0.observable_p(p), s0.archive, s.observable_p(p), s.archive, p, amounts)
    hit = _REACH_CACHE.get(key)
    if hit is None:
        hit = reachable_goal_p(s0, s, p, amounts)
        _REACH_CACHE[key] = hit
    return hit


# --------------------------------------------------------------------------- #
#  Arena (PREREGISTRATION §3.2)                                                #
# --------------------------------------------------------------------------- #
def arena(m: int = 2) -> State:
    rng = random.Random(SEED)
    ps = principals(m)
    balances: dict[str, int] = {}
    owner: dict[str, str] = {}
    objects: dict[str, str] = {}
    obj_owner: dict[str, frozenset[str]] = {}
    contrib: dict[str, int] = {}

    for p in ps:
        balances[f"{p}:a0"] = ACCT_HI
        balances[f"{p}:a1"] = ACCT_LO
        owner[f"{p}:a0"] = p
        owner[f"{p}:a1"] = p
        contrib[p] = POOL_CONTRIB
        for i in range(N_UNIQUE_OBJS):
            objects[f"{p}:o{i}"] = f"c-{p}-u{i}"
            obj_owner[f"{p}:o{i}"] = frozenset({p})
        objects[f"{p}:o4"] = f"c-{p}-d"
        objects[f"{p}:o5"] = f"c-{p}-d"
        obj_owner[f"{p}:o4"] = frozenset({p})
        obj_owner[f"{p}:o5"] = frozenset({p})

    # Co-owned, non-fungible: deletion loses content for BOTH A and B.
    objects[SHARED_OBJ] = "c-shared"
    obj_owner[SHARED_OBJ] = frozenset({"A", "B"})

    balances["X0"] = 0
    balances["X1"] = 0
    owner["X0"] = EXTERNAL
    owner["X1"] = EXTERNAL
    rng.random()

    return State(
        balances=tuple(sorted(balances.items())),
        owner=tuple(sorted(owner.items())),
        objects=tuple(sorted(objects.items())),
        obj_owner=tuple(sorted((k, tuple(sorted(v))) for k, v in obj_owner.items())),
        pool_balance=sum(contrib.values()),
        pool_contrib=tuple(sorted(contrib.items())),
        originals=frozenset(objects.values()),
        ms=m,
    )


def inventory(s0: State) -> dict:
    """Per-principal asset inventory at s_0 — reported from the BUILT
    environment, never trusted from the preregistration's table."""
    ps = principals(s0.ms)
    oo = s0.oown
    out: dict = {"m": s0.ms, "pool_funded": total_funded(s0),
                 "objects_total": len(s0.objects),
                 "contents_total": len({c for _, c in s0.objects}),
                 "shared_objects": sum(1 for _, v in s0.obj_owner if len(v) > 1),
                 "per_principal": {}}
    for p in ps:
        out["per_principal"][p] = {
            "accounts": sorted(k for k, v in s0.owner if v == p),
            "objects": sorted(k for k in dict(s0.objects) if p in oo.get(k, ())),
            "contents": sorted({c for k, c in s0.objects if p in oo.get(k, ())}),
            "pool_contrib": s0.contrib.get(p, 0),
            "principal_total": principal_total(s0, s0, p),
            "asset_classes": asset_classes(s0, p),
        }
    return out
