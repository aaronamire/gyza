"""
Build attestation — binding a SOURCE-TREE hash to a BINARY hash.

WHAT THIS DOES AND DOES NOT ADDRESS — read this before using anything here.

**S5 DOES NOT ADDRESS CORRECTNESS.** Correctness of natural-language reasoning
is closed across six mechanism families and the result is terminal (see
``research/COMPETENCE_BOUND.md``). A build attestation says *these bytes came
from that source*. It says nothing whatever about whether the computation those
bytes perform is right. A TEE running a wrong computation faithfully attests a
wrong result.

What S5 removes is one clause, and only one:

    BEFORE:  execution was bounded  GIVEN AN HONEST RUNNER
    AFTER:   execution was bounded  GIVEN A RUNNER WHOSE BINARY IS ATTESTED
             TO MATCH PUBLISHED SOURCE

Today the enforcement record is stamped by a runner that *self-reports its own
build* (``release.py`` says so in its own module docstring: "a malicious binary
can lie about its hash"). A modified runner can stamp a record describing a
sandbox it never entered. Binding source -> binary, and checking that binding at
verify time, is what closes that specific gap. Nothing else.

**ONE SIGNER IS A TRUSTED THIRD PARTY WITH EXTRA STEPS.** A single attestation
signed by whoever built the artifact proves only that that party asserts the
binding. The property becomes meaningful when >= 2 *independent* rebuilders
reproduce the same binary bytes from the same source and each sign it. The
second rebuilder is USER-OWNED work (a second machine, a second operator) and
cannot be produced from inside this repository. ``AttestationSet`` therefore
expresses N-of-M from the start rather than retrofitting it, and
``threshold=1`` is explicitly labelled as the degenerate case.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from gyza.canon import Failure, failed

ATTESTATION_SCHEMA = "gyza.build-attestation/1"


# --------------------------------------------------------------------------- #
#  The OUTPUT-side hash (release.py already handles the INPUT side)            #
# --------------------------------------------------------------------------- #
def compute_artifact_hash(root: Path) -> str:
    """Deterministic BLAKE3 over a built artifact tree (the onedir bundle).

    Same injective wire format as ``release.compute_source_tree_hash`` --
    length-prefixed path and data per file, sorted by relative POSIX path -- so
    no two distinct trees collide. Covers EVERY regular file, not a manifest:
    ``_internal/base_library.zip`` is exactly where this build's only
    non-determinism lived, and a manifest-level digest would have missed it.

    Symlinks are hashed by their TARGET STRING, not by following them, so a
    bundle cannot be altered by re-pointing a link at different content.
    """
    if not root.is_dir():
        raise NotADirectoryError(root)
    files = sorted((p for p in root.rglob("*") if p.is_file() or p.is_symlink()),
                   key=lambda p: p.relative_to(root).as_posix())
    h = blake3.blake3()
    for p in files:
        rel = p.relative_to(root).as_posix().encode("utf-8")
        if p.is_symlink():
            kind, data = b"L", str(p.readlink()).encode("utf-8")
        else:
            kind, data = b"D", p.read_bytes()
        h.update(b"P")
        h.update(struct.pack(">I", len(rel)))
        h.update(rel)
        h.update(kind)
        h.update(struct.pack(">I", len(data)))
        h.update(data)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
#  The signed statement                                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BuildAttestation:
    """One rebuilder's signed claim: this source produced these bytes.

    `builder_id` is descriptive only and is NOT a trust input -- trust is keyed
    on `builder_pubkey`. A name field that looked authoritative would invite
    exactly the confusion this program keeps catching.
    """
    schema: str
    version: str
    source_tree_hash: str
    artifact_hash: str
    toolchain: dict
    builder_id: str
    builder_pubkey: str
    signature: str = ""

    def payload(self) -> dict:
        """The signed content. Alphabetical by construction via sort_keys, and
        `signature` is excluded so a signature cannot sign over itself."""
        return {
            "artifact_hash": self.artifact_hash,
            "builder_id": self.builder_id,
            "builder_pubkey": self.builder_pubkey,
            "schema": self.schema,
            "source_tree_hash": self.source_tree_hash,
            "toolchain": self.toolchain,
            "version": self.version,
        }

    def signing_bytes(self) -> bytes:
        return json.dumps(self.payload(), sort_keys=True,
                          separators=(",", ":"),
                          allow_nan=False).encode("utf-8")

    def digest(self) -> str:
        return blake3.blake3(self.signing_bytes()).hexdigest()


def sign_attestation(att: BuildAttestation, seed: bytes) -> BuildAttestation:
    """Sign-the-hash, matching the ICP envelope discipline exactly."""
    if len(seed) != 32:
        raise ValueError(f"Ed25519 seed must be 32 bytes, got {len(seed)}")
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pub = sk.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw).hex()
    att = BuildAttestation(**{**att.__dict__, "builder_pubkey": pub,
                              "signature": ""})
    sig = sk.sign(bytes.fromhex(att.digest())).hex()
    return BuildAttestation(**{**att.__dict__, "signature": sig})


def verify_attestation(att: BuildAttestation) -> tuple[bool, str]:
    if not att.signature:
        return False, "unsigned"
    if att.schema != ATTESTATION_SCHEMA:
        return False, f"unknown schema {att.schema!r}"
    try:
        pk = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(att.builder_pubkey))
        pk.verify(bytes.fromhex(att.signature), bytes.fromhex(att.digest()))
    except (InvalidSignature, ValueError) as e:
        return False, f"bad signature: {type(e).__name__}"
    return True, ""


# --------------------------------------------------------------------------- #
#  N-of-M — expressible from the start, not retrofitted                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AttestationSet:
    """M attestations for one (version, source_tree_hash), needing N to agree.

    AGREEMENT IS ON `artifact_hash`, THE PROTECTED QUANTITY -- never on a count
    of signatures, never on builder names. Counting signatures without checking
    that they attest the SAME BYTES is the monotonicity-over-a-label error this
    program has now recorded three times.
    """
    version: str
    source_tree_hash: str
    threshold: int
    attestations: tuple[BuildAttestation, ...]

    def independent_agreement(self) -> tuple[str | None, int, str]:
        """-> (agreed_artifact_hash | None, n_distinct_valid_signers, reason)."""
        by_hash: dict[str, set[str]] = {}
        for a in self.attestations:
            ok, why = verify_attestation(a)
            if not ok:
                continue
            if a.version != self.version or \
                    a.source_tree_hash != self.source_tree_hash:
                continue
            by_hash.setdefault(a.artifact_hash, set()).add(a.builder_pubkey)
        if not by_hash:
            return None, 0, "no valid attestation for this (version, source)"
        best = max(by_hash.items(), key=lambda kv: len(kv[1]))
        ah, signers = best
        if len(by_hash) > 1:
            return None, len(signers), (
                "REBUILDERS DISAGREE on the artifact hash for identical source "
                f"({len(by_hash)} distinct binaries attested) — this is a "
                "reproducibility failure or a compromised builder, and it must "
                "not be resolved by majority vote")
        if len(signers) < self.threshold:
            return None, len(signers), (
                f"{len(signers)} independent signer(s), threshold is "
                f"{self.threshold}")
        return ah, len(signers), ""

    @property
    def is_degenerate(self) -> bool:
        """threshold == 1 means ONE SIGNER IS A TRUSTED THIRD PARTY WITH EXTRA
        STEPS. True is not an error; it is a disclosure."""
        return self.threshold <= 1


def load_attestation_set(path: Path) -> AttestationSet | Failure:
    """Failure, never a falsy default -- an unreadable trust file must not read
    as an empty trust file."""
    try:
        d = json.loads(path.read_text())
        return AttestationSet(
            version=d["version"],
            source_tree_hash=d["source_tree_hash"],
            threshold=int(d["threshold"]),
            attestations=tuple(
                BuildAttestation(**a) for a in d["attestations"]),
        )
    except Exception as e:                                    # noqa: BLE001
        return Failure(f"{type(e).__name__}: {e}", str(path))


__all__ = ["ATTESTATION_SCHEMA", "AttestationSet", "BuildAttestation",
           "compute_artifact_hash", "failed", "load_attestation_set",
           "sign_attestation", "verify_attestation"]
