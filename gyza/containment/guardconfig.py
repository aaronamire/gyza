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
    tier_assignments: dict
    signature: str
    authority_pubkey_hex: str
    config_hash: str

    @property
    def as_dict(self) -> dict:
        return {"version": self.version, "bounds": dict(self.bounds),
                "tier_assignments": dict(self.tier_assignments)}


class GuardConfigStore:
    """Holds the verified configuration and refuses to replace it except under
    the authority signature."""

    def __init__(self, authority_pubkey: bytes):
        self._authority = bytes(authority_pubkey)
        self._cfg: VerifiedGuardConfig | None = None
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

    def _install(self, config: dict, signature_hex: str,
                 _allow_loosening: bool = False) -> VerifiedGuardConfig:
        if not verify_config(config, signature_hex, self._authority):
            raise GuardConfigError(
                "signature does not verify against the declared authority key")
        version = int(config.get("version", 0))
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
            tier_assignments=dict(config.get("tier_assignments", {})),
            signature=signature_hex,
            authority_pubkey_hex=self._authority.hex(),
            config_hash=config_hash(config),
        )
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
