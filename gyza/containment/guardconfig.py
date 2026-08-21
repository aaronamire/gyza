"""
C-8 — guard configuration in a SEPARATE TRUST DOMAIN.

The guard configuration -- harm bounds, invariant class tags, tier assignments,
the reversibility table -- is signed by an authority key and verified before
use. The system it constrains does not hold that key.

This is structural, not a policy preference. Every containment argument in this
program is an INDUCTION: the invariant holds at s0, and every admitted
transition preserves it, therefore it holds throughout. If the agent can rewrite
the invariant, the induction has no base case and no inductive step -- there is
nothing left to prove and nothing being enforced. A guard an agent can edit is
not a guard.

Two properties, and the second is the one people forget:

  1. TAMPER EVIDENCE. A modified config fails signature verification.
  2. NO SELF-MODIFICATION PATH. Verification alone is not enough: if the runtime
     exposed a setter, an agent could install a config it signed with its OWN
     key and the check would pass against the wrong authority. The verified
     config is therefore frozen, and updates require a signature from the
     declared authority -- a key the constrained system does not possess.

`update_guard_config` is classified IRREVERSIBLE in C-3, so it cannot be staged
in the interior and must pass the promotion gate: the maximally-gated action.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)


@dataclass(frozen=True)
class BoundChange:
    bound_id: str
    old: float | None
    new: float | None
    direction: str          # UNCHANGED | TIGHTENED | LOOSENED


def diff_bounds(old: dict, new: dict) -> list[BoundChange]:
    """Classify each bound as UNCHANGED / TIGHTENED / LOOSENED.

    PERMISSIVENESS IS COMPUTED OVER THE ADMITTED SET, NOT OVER THE NUMBER.
    That distinction is the whole point and it is easy to get backwards:

      * an UNSET bound FAILS CLOSED -- `GuardEngine.evaluate` refuses every
        action touching a harm class with no declared bound
        (`engine.py:99-101`). So a class with no bound admits NOTHING.
      * therefore ADDING a bound is a LOOSENING (refuse-all -> admit-some), and
        REMOVING one is a TIGHTENING.

    Read off the magnitudes alone, both of those come out inverted. The bound
    *number* is a label that correlates with permissiveness; the admitted set is
    the quantity being protected.
    """
    out: list[BoundChange] = []
    for k in sorted(set(old) | set(new)):
        o, n = old.get(k), new.get(k)
        if o is None and n is None:
            continue
        if o is None:                       # unbounded (refuse-all) -> bounded
            out.append(BoundChange(k, None, float(n), "LOOSENED"))
        elif n is None:                     # bounded -> unbounded (refuse-all)
            out.append(BoundChange(k, float(o), None, "TIGHTENED"))
        elif float(n) > float(o):
            out.append(BoundChange(k, float(o), float(n), "LOOSENED"))
        elif float(n) < float(o):
            out.append(BoundChange(k, float(o), float(n), "TIGHTENED"))
        else:
            out.append(BoundChange(k, float(o), float(n), "UNCHANGED"))
    return out


@dataclass(frozen=True)
class LooseningRecord:
    """An explicit, separately-signed declaration that specific bounds loosen.

    Loosening is permitted, but it is a DISTINCT OPERATION from updating. The
    record must name every bound that moves, with its old and new value, and a
    reason. A record that UNDER-REPORTS is refused: a loosening you did not
    declare is worse than one you did, because the signature would then attest
    to a change nobody read.
    """
    #: See StagingArea.NON_ADOPTED for the convention.
    NON_ADOPTED = ("no production entry point exists BY DESIGN. Tightening "
                   "goes through scripts/sign_guard_config.py, which states "
                   "at line 19 that loosening is deliberately not that "
                   "script: raising a bound must be a separate, separately-"
                   "signed, human act and no tool automates it yet.")
    changes: tuple                          # ((bound_id, old, new), ...)
    reason: str

    def as_dict(self) -> dict:
        return {"changes": [list(c) for c in self.changes], "reason": self.reason}

    @property
    def named(self) -> set:
        return {c[0] for c in self.changes}


def sign_loosening(rec: LooseningRecord, authority_sk: bytes) -> str:
    return sign_config(rec.as_dict(), authority_sk)


class GuardConfigError(RuntimeError):
    """Verification or mutation failure. Always fails closed: an unverifiable
    configuration is not a permissive configuration."""


def canonical_bytes(config: dict) -> bytes:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def config_hash(config: dict) -> str:
    return blake3.blake3(canonical_bytes(config)).hexdigest()


def authority_key_is_colocated(pubkey_hex: str,
                               search: "list[str] | None" = None) -> str | None:
    """Return the path of a PRIVATE authority key on this host, or None.

    C-8'S BASE CASE, CHECKED RATHER THAN ASSUMED. The whole containment
    induction rests on one premise: *the constrained system does not hold the
    key that signs its bounds.* `scripts/sign_guard_config.py` states it in its
    header -- "keep it off the machine that runs agents" -- and **nothing
    verified it.** A host whose agent directory also contains the authority
    private key can re-sign any bounds it likes after a local compromise, so a
    bare `SIGNED` verdict there reads far stronger than it is.

    This does not weaken the signature: signed bounds are still strictly better
    than unsigned, because tampering without the key is detectable. What it
    weakens is the SEPARATION, and separation is what the induction needs.

    Returns the path so the report can name it. NEVER returns or logs key
    material -- only a public key is derived, and only to compare.
    """
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    # THE SEARCH IS BEST-EFFORT AND CANNOT PROVE ABSENCE, and that limit is the
    # reason this list is wide rather than tidy. The check answers "is the
    # signing key reachable by the constrained system?", and the honest answer
    # for any location it does not look in is "unknown", not "no".
    #
    # It listed exactly two paths until 2026-08-21, so RELOCATING THE KEY ONE
    # DIRECTORY SIDEWAYS SILENCED IT while changing nothing about the risk:
    # anything running as the agent's user could still read the file and re-sign
    # the policy it is constrained by. A check that a file move defeats is a
    # check that reports where the key ISN'T.
    #
    # Widening does not make it sound. Only removable media, another host, or
    # ownership the agent's user cannot read achieves separation; this makes the
    # common relocations visible instead of silently clearing them.
    candidates = search or [
        "~/.gyza/authority.key",
        "~/.gyza-authority/authority.key",
        "~/.config/gyza/authority.key",
        "~/authority.key",
        "./authority.key",
        "./authority/authority.key",
    ]
    for c in candidates:
        path = Path(c).expanduser()
        try:
            raw = path.read_bytes()
            if len(raw) < 32:
                continue
            derived = Ed25519PrivateKey.from_private_bytes(
                raw[:32]).public_key().public_bytes(
                    _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        except Exception:                                    # noqa: BLE001
            continue
        if derived == pubkey_hex:
            return str(path)
    return None


def _sign_payload(payload: dict, sk: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    return Ed25519PrivateKey.from_private_bytes(sk).sign(
        canonical_bytes(payload)).hex()


def _verify_payload(payload: dict, signature_hex: str, pubkey: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )
    try:
        Ed25519PublicKey.from_public_bytes(pubkey).verify(
            bytes.fromhex(signature_hex), canonical_bytes(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_config(config: dict, authority_sk: bytes) -> str:
    """Sign-the-hash, matching the ICP discipline (gyza/icp.py:67)."""
    sk = Ed25519PrivateKey.from_private_bytes(authority_sk)
    return sk.sign(blake3.blake3(canonical_bytes(config)).digest()).hex()


def verify_config(config: dict, signature_hex: str,
                  authority_pk: bytes) -> bool:
    try:
        pk = Ed25519PublicKey.from_public_bytes(authority_pk)
        pk.verify(bytes.fromhex(signature_hex),
                  blake3.blake3(canonical_bytes(config)).digest())
        return True
    except (InvalidSignature, ValueError):
        return False


@dataclass(frozen=True)
class VerifiedGuardConfig:
    """Frozen on purpose. There is no setter, so there is no in-process path by
    which the constrained system installs its own policy."""
    version: int
    bounds: dict
    #: POLICY IS NOT BOUNDS, and the separation is load-bearing.
    #:
    #: `bounds` are harm LEVELS -- each one claims that a quantity stays below
    #: a number, and `can_claim_containment` spends them. `policy` holds signed
    #: operating parameters that bound nothing: the review cadence is a TIMER
    #: BY DESIGN (it must fire periodically; that is its job), and carrying it
    #: in `bounds` made it a harm class whose "bound" of 10,000 asserted only
    #: that the agent had not yet run 10,000 actions.
    #:
    #: Both are signed by the same authority and covered by the same signature.
    #: What differs is what they license.
    policy: dict
    tier_assignments: dict
    signature: str
    authority_pubkey_hex: str
    config_hash: str

    @property
    def as_dict(self) -> dict:
        return {"version": self.version, "bounds": dict(self.bounds),
                "policy": dict(self.policy),
                "tier_assignments": dict(self.tier_assignments)}


@dataclass(frozen=True)
class KeySuccession:
    """An authority key naming its successor, SIGNED BY THE OUTGOING KEY.

    WHY THE OLD KEY SIGNS. Succession must be an act of the CURRENT authority,
    never of the constrained system. A record signed by the incoming key would
    let anyone who can generate a keypair appoint themselves -- the guard
    configuration is the trust root the whole induction rests on, so
    self-appointment would void every downstream containment claim.

    WHY THIS TYPE EXISTS AT ALL. `settlement.py` deferred "rotation of the
    compositor key (a settled entry references the key valid at the moment of
    signing)", and CLAUDE.md records that the deferral is a FRAME HAZARD:
    implemented naively it reproduces R9's `G4'` exactly -- history pinned to
    the old key, the live gate reading the new one, and the invariant checking
    against a frame the history is not in.

    THE SAFETY PROPERTY, which is the whole point:

        ROTATION CHANGES WHO SIGNS. IT CHANGES NOTHING ELSE.

    Version monotonicity and permissiveness monotonicity continue across a
    rotation UNBROKEN, because `_install` compares against `self._cfg` and
    succession deliberately leaves `_cfg` in place. Clearing it would make
    rotation a LOOSENING BYPASS: rotate, then install any bounds at any version
    with nothing to compare against. That bypass is the reason this class keeps
    the previous configuration rather than starting fresh.
    """

    old_pubkey_hex: str
    new_pubkey_hex: str
    at_ns: int
    reason: str

    def as_dict(self) -> dict:
        return {"old_pubkey": self.old_pubkey_hex,
                "new_pubkey": self.new_pubkey_hex,
                "at_ns": self.at_ns, "reason": self.reason}


def sign_succession(rec: KeySuccession, outgoing_sk: bytes) -> str:
    """Sign a succession with the OUTGOING key. See `KeySuccession`."""
    return _sign_payload(rec.as_dict(), outgoing_sk)


def verify_succession(rec: KeySuccession, signature_hex: str,
                      outgoing_pubkey: bytes) -> bool:
    return _verify_payload(rec.as_dict(), signature_hex, outgoing_pubkey)


class GuardConfigStore:
    """Holds the verified configuration and refuses to replace it except under
    the authority signature."""

    def __init__(self, authority_pubkey: bytes,
                 history_path: "str | Path | None" = None):
        self._authority = bytes(authority_pubkey)
        self._genesis_authority = bytes(authority_pubkey)
        self._cfg: VerifiedGuardConfig | None = None
        #: WHERE VERSION MONOTONICITY SURVIVES A RESTART.
        #:
        #: `_cfg` is None on every fresh store, and BOTH monotonicity checks
        #: compare against it -- so before 2026-08-21 a cold load accepted any
        #: validly-signed configuration, including an OLD one. Demonstrated
        #: against the real file shipped at v0.1.3: it installed cleanly over
        #: v3, no key required, because a rollback payload is just a file from
        #: git history.
        #:
        #: That is the one attack a signature cannot show you. Replacing code
        #: needs the same host write access and breaks integrity checks; a
        #: rollback leaves EVERY SIGNATURE VERIFYING, and `gyza status` would
        #: report "bounds: SIGNED (v1, authority ...)" and be telling the
        #: truth. The version integer was the only tell and nothing compared it
        #: against anything.
        #:
        #: WHAT THIS DOES AND DOES NOT CLOSE. It remembers the highest version
        #: ever installed and refuses anything below it, so a silent downgrade
        #: becomes a refusal. An attacker with write access to BOTH the config
        #: and this file can reset both and roll back anyway -- local storage
        #: cannot prevent that, only trusted storage or a remote witness can.
        #: This raises the bar and is not a closure, which is why the ceiling
        #: is written here rather than left for a reader to discover.
        self._history_path = (Path(history_path).expanduser()
                              if history_path else None)
        #: Every accepted succession, oldest first, so an offline verifier
        #: holding only the GENESIS pubkey can walk to the current one. A
        #: rotation nobody can reconstruct is indistinguishable from a key
        #: substitution.
        self._successions: list[tuple[KeySuccession, str]] = []
        # O-3 surface: every loosening lands here, always.
        self.alarms: list[str] = []

    @property
    def config(self) -> VerifiedGuardConfig:
        if self._cfg is None:
            raise GuardConfigError(
                "no verified guard configuration loaded; refusing to operate "
                "unconfigured (an absent policy is not a permissive policy)")
        return self._cfg

    @property
    def authority_pubkey_hex(self) -> str:
        return self._authority.hex()

    def load(self, config: dict, signature_hex: str) -> VerifiedGuardConfig:
        return self._install(config, signature_hex)

    def load_file(self, path: str | Path) -> VerifiedGuardConfig:
        doc = json.loads(Path(path).read_text())
        return self._install(doc["config"], doc["signature"])

    @property
    def genesis_authority_pubkey_hex(self) -> str:
        """The key this store was PINNED to. An auditor validates the chain
        from here, never from the current key -- validating from the current
        key would accept any substitution that arrived with its own history."""
        return self._genesis_authority.hex()

    @property
    def succession_chain(self) -> list[dict]:
        return [r.as_dict() for r, _ in self._successions]

    def rotate_authority(self, record: "KeySuccession", signature_hex: str
                         ) -> None:
        """Install a new authority key, named by the outgoing one.

        THREE REFUSALS, each closing a distinct attack:

        1. The signature must verify against the CURRENT authority. A record
           signed by the incoming key is SELF-APPOINTMENT and is refused.
        2. `old_pubkey_hex` must equal the current authority. A record naming
           some other predecessor is a chain that does not attach here, and
           accepting it would let a valid succession from an unrelated store be
           replayed into this one.
        3. The new key must differ from the old. A no-op rotation would append
           a chain entry that asserts a change that did not happen.

        WHAT IS DELIBERATELY NOT DONE: `self._cfg` IS NOT CLEARED. Version
        monotonicity and permissiveness monotonicity both compare against it,
        so clearing it would make rotation a LOOSENING BYPASS -- rotate, then
        install any bounds at any version against nothing. Rotation changes WHO
        SIGNS and nothing else; the invariant's frame follows the history's
        frame rather than the reverse (R9's `G4'`, which CLAUDE.md flags this
        deferral as reproducing if done naively).
        """
        if not verify_succession(record, signature_hex, self._authority):
            # NAME THE FAILURE, NOT A GUESS AT ITS CAUSE. An earlier version
            # asserted "self-appointment", which sent the first person to hit
            # it (a mismatched `at_ns` between the signed record and the passed
            # one) looking for the wrong bug entirely. The C-8 suite already
            # records why: 'these bounds are unsigned' and 'this signature is
            # wrong' have different remedies, and an operator handed the wrong
            # one debugs the wrong thing. Causes are listed as possibilities.
            raise GuardConfigError(
                "succession signature does not verify against the CURRENT "
                "authority key. Possible causes: it was signed by the INCOMING "
                "key (self-appointment, which is refused); it was signed by a "
                "third key; or the signed record differs from the one passed "
                "here -- every field is covered, including at_ns and reason.")
        if record.old_pubkey_hex != self._authority.hex():
            raise GuardConfigError(
                f"succession names predecessor {record.old_pubkey_hex[:16]}... "
                f"but this store's authority is "
                f"{self._authority.hex()[:16]}...; the chain does not attach "
                f"here and replaying another store's succession is refused")
        if record.new_pubkey_hex == self._authority.hex():
            raise GuardConfigError(
                "succession names the incumbent as its own successor; a no-op "
                "rotation would record a change that did not happen")
        self._successions.append((record, signature_hex))
        self._authority = bytes.fromhex(record.new_pubkey_hex)
        self.alarms.append(
            f"AUTHORITY ROTATED to {record.new_pubkey_hex[:16]}... "
            f"({record.reason})")

    def attempt_update(self, config: dict, signature_hex: str,
                       *, requested_by: str = "unknown") -> VerifiedGuardConfig:
        """The path an agent would have to take. It does not hold the authority
        key, so the signature check is what refuses it -- and the refusal names
        the requester so the attempt is auditable rather than silent."""
        try:
            return self._install(config, signature_hex)
        except GuardConfigError as e:
            raise GuardConfigError(
                f"guard configuration update REFUSED (requested by "
                f"{requested_by!r}): {e}. The guard configuration lives in a "
                f"separate trust domain; the constrained system does not hold "
                f"the authority key."
            ) from None

    def _version_floor(self) -> int:
        """Highest version ever installed, from the append-only history.

        FAILS CLOSED ON A BROKEN CHAIN. A history whose links do not verify has
        been edited, and an edited history is exactly what a rollback needs --
        so it raises rather than returning 0. "I cannot tell" must not read as
        "no floor", which is the reassuring direction.
        """
        if self._history_path is None or not self._history_path.exists():
            return 0
        floor, prev = 0, ""
        for i, line in enumerate(
                self._history_path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                link = blake3.blake3(
                    canonical_bytes({"version": rec["version"],
                                     "config_hash": rec["config_hash"],
                                     "at_ns": rec["at_ns"],
                                     "prev": rec["prev"]})).hexdigest()
            except Exception as exc:                         # noqa: BLE001
                raise GuardConfigError(
                    f"guard-config history is unreadable at line {i} ({exc}). "
                    f"An unreadable history cannot establish a version floor, "
                    f"and proceeding without one is what a rollback needs."
                ) from exc
            if rec["prev"] != prev:
                raise GuardConfigError(
                    f"guard-config history chain breaks at line {i}: entry "
                    f"names predecessor {rec['prev'][:16]!r} but the previous "
                    f"link hashes to {prev[:16]!r}. The history has been "
                    f"edited, which is what a rollback requires.")
            prev = link
            floor = max(floor, int(rec["version"]))
        return floor

    def _record_install(self, version: int, config_hash_hex: str) -> None:
        """Append one install to the chained history. Best-effort on I/O, but
        a failure is LOGGED -- an install nobody recorded lowers the floor for
        the next start."""
        if self._history_path is None:
            return
        prev = ""
        try:
            if self._history_path.exists():
                for line in self._history_path.read_text().splitlines():
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    prev = blake3.blake3(canonical_bytes(
                        {"version": r["version"], "config_hash": r["config_hash"],
                         "at_ns": r["at_ns"], "prev": r["prev"]})).hexdigest()
            rec = {"version": int(version), "config_hash": config_hash_hex,
                   "at_ns": time.time_ns(), "prev": prev}
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            with self._history_path.open("a") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        except OSError:
            logging.getLogger(__name__).warning(
                "[guardconfig] install of v%s was not recorded; the version "
                "floor will not rise", version, exc_info=True)

    def _install(self, config: dict, signature_hex: str,
                 _allow_loosening: bool = False) -> VerifiedGuardConfig:
        if not verify_config(config, signature_hex, self._authority):
            raise GuardConfigError(
                "signature does not verify against the declared authority key")
        version = int(config.get("version", 0))
        floor = self._version_floor()
        if self._cfg is None and version < floor:
            raise GuardConfigError(
                f"refusing to install version {version}: this host has "
                f"previously installed version {floor}. A validly-signed OLD "
                f"configuration is a ROLLBACK -- every signature verifies and "
                f"the bounds silently revert. Monotonicity is checked across "
                f"restarts, not only within one process.")
        if self._cfg is not None and version <= self._cfg.version:
            # Monotone versioning: a valid OLD config must not be replayable to
            # reinstate loosened bounds that were since tightened.
            raise GuardConfigError(
                f"refusing to install version {version} over "
                f"{self._cfg.version}: guard configuration versions are "
                f"monotone (rollback would be a downgrade attack)")

        # PERMISSIVENESS monotonicity -- computed over the admitted set, never
        # inferred from the version integer. A version bump is a LABEL that
        # correlates with intent; it says nothing about whether the guard got
        # weaker, and a correctly-signed v2 raising every bound would otherwise
        # install cleanly. The guard configuration is the immutable trust root
        # the whole induction rests on, so an undetected escalation here voids
        # every downstream containment claim without tripping a check.
        if self._cfg is not None and not _allow_loosening:
            loosened = [c for c in diff_bounds(self._cfg.bounds, config.get("bounds", {}))
                        if c.direction == "LOOSENED"]
            if loosened:
                detail = ", ".join(
                    f"{c.bound_id}: {c.old} -> {c.new}" for c in loosened)
                raise GuardConfigError(
                    f"refusing to install: {len(loosened)} bound(s) LOOSEN "
                    f"({detail}). Loosening is permitted but it is a DISTINCT "
                    f"OPERATION -- use install_loosening() with a separately "
                    f"signed LooseningRecord naming every bound that moves.")
        self._cfg = VerifiedGuardConfig(
            version=version,
            bounds=dict(config.get("bounds", {})),
            policy=dict(config.get("policy", {})),
            tier_assignments=dict(config.get("tier_assignments", {})),
            signature=signature_hex,
            authority_pubkey_hex=self._authority.hex(),
            config_hash=config_hash(config),
        )
        self._record_install(version, self._cfg.config_hash)
        return self._cfg

    def install_loosening(self, config: dict, signature_hex: str,
                          record: LooseningRecord, record_signature_hex: str,
                          *, requested_by: str = "unknown") -> VerifiedGuardConfig:
        """The ONLY path by which a bound may loosen.

        Requires a separately-signed record naming EXACTLY the bounds that
        actually move. Refuses on any mismatch in either direction:
        under-reporting hides an escalation behind an authorized signature, and
        over-reporting means the record does not describe the config it
        accompanies.

        Every successful loosening raises an O-3 alarm. Always -- a loosening
        that is authorized is still a loosening, and the alarm is how it becomes
        visible rather than merely permitted.
        """
        if self._cfg is None:
            raise GuardConfigError(
                "no configuration is installed; there is nothing to loosen")
        if not verify_config(record.as_dict(), record_signature_hex, self._authority):
            raise GuardConfigError(
                "the LOOSENING RECORD does not verify against the authority key")

        actual = {c.bound_id: (c.old, c.new)
                  for c in diff_bounds(self._cfg.bounds, config.get("bounds", {}))
                  if c.direction == "LOOSENED"}
        if not actual:
            raise GuardConfigError(
                "install_loosening called but no bound loosens; use the "
                "ordinary update path")

        if record.named != set(actual):
            missing = sorted(set(actual) - record.named)
            extra = sorted(record.named - set(actual))
            raise GuardConfigError(
                f"LOOSENING RECORD does not match the configuration. "
                f"Undeclared loosenings: {missing or 'none'}; "
                f"declared but not loosening: {extra or 'none'}. A record that "
                f"under-reports is worse than none -- the signature would "
                f"attest to a change nobody read.")
        for bid, old, new in record.changes:
            a_old, a_new = actual[bid]
            if (old, new) != (a_old, a_new):
                raise GuardConfigError(
                    f"LOOSENING RECORD misstates {bid}: says {old} -> {new}, "
                    f"actual {a_old} -> {a_new}")
        if not record.reason.strip():
            raise GuardConfigError("a loosening requires a reason")

        cfg = self._install(config, signature_hex, _allow_loosening=True)
        alarm = (f"GUARD-LOOSENED (requested by {requested_by!r}): "
                 + "; ".join(f"{b}: {o} -> {n}" for b, o, n in record.changes)
                 + f" — reason: {record.reason}")
        self.alarms.append(alarm)
        return cfg

    def apply_to(self, harm_registry) -> None:
        """Push verified bounds into C-1, stamped with their provenance.

        THE SENTENCE THIS USED TO CARRY -- "Bounds reach the harm registry ONLY
        through a verified configuration" -- WAS FALSE. `load_bounds` and
        `load_bounds_file` are public and `gyza_model.build_registries` called
        the file loader directly, so bounds reached C-1 without ever passing
        here. An unenforced invariant is an assumption.

        It is now checkable rather than asserted: this is the only call site
        that stamps SIGNED provenance, and `can_claim_containment` reads it. Any
        other route leaves the registry UNSIGNED and unable to claim
        containment.
        """
        from gyza.containment.harm import BoundsProvenance
        cfg = self.config
        harm_registry.load_bounds(cfg.bounds, BoundsProvenance(
            source="SIGNED",
            detail=f"verified against authority {self._authority.hex()[:16]}…",
            authority_pubkey_hex=cfg.authority_pubkey_hex,
            version=cfg.version,
            config_hash=cfg.config_hash,
        ))
