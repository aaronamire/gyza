"""
Runner release identity — the G1a partial closure of the
bounds-proof's host-integrity residual (ADR-0016 §A4, ADR-0017).

The problem this addresses
==========================

``__enforcement__`` is stamped by ``make_sandboxed_executor.
_wrapped`` running in the trusted parent. The sandboxed code can't
forge it. But *the parent binary itself is whoever runs the
daemon*. A hostile operator can patch the wrapper to stamp tighter
bounds than bwrap actually enforced. The submitter, given only the
signed envelope, has no way to tell which binary did the stamping.

What this module does
=====================

It computes a deterministic content hash of the gyza Python source
tree — the exact code that produces the enforcement stamp — and a
version string. The runner includes ``(runner_version,
runner_source_tree_hash)`` in the enforcement record. A submitter
checks that pair against a pinned, separately-distributed set of
trusted releases (``TRUSTED_RELEASES``).

What this buys (precisely)
==========================

It moves the trust anchor from "trust whoever runs the daemon" to
"trust whoever curates the trusted-release set, AND assume the
binary honestly self-reports its hash." The second clause is the
residual G1a does NOT close: a malicious binary can lie about its
own hash. Only reproducible builds + third-party verification, or
TEE remote attestation (vNext L8), closes that. G1a is the
cheapest, code-only step in that direction — it raises the bar
from "any operator" to "an operator running a binary that
self-reports a trusted-release hash."

Determinism contract
====================

``compute_source_tree_hash`` MUST be:

  * install-location independent (only paths *relative to the
    package root* feed the hash),
  * toolchain independent (generated protobuf is excluded — its
    bytes vary by protoc version even for identical .proto),
  * order independent of filesystem enumeration (paths sorted),
  * unambiguous under concatenation (every chunk length-prefixed).

A renamed file changes the hash (the relative path is hashed). A
``__pycache__`` artifact never changes it (excluded). These
properties are locked by ``tests/test_release.py``.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import blake3

from gyza import __version__

# Files whose bytes are not reproducible from source alone, or are
# pure build/runtime detritus. Excluded from the identity hash.
_EXCLUDE_SUFFIXES = ("_pb2.py", "_pb2_grpc.py")
_EXCLUDE_DIR_PARTS = ("__pycache__",)


def _package_root() -> Path:
    """The gyza/ directory — this file's parent."""
    return Path(__file__).resolve().parent


def _iter_source_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in _EXCLUDE_DIR_PARTS for part in p.parts):
            continue
        if any(p.name.endswith(suf) for suf in _EXCLUDE_SUFFIXES):
            continue
        out.append(p)
    # Sort by POSIX relative path so the order is filesystem- and
    # OS-independent.
    out.sort(key=lambda q: q.relative_to(root).as_posix())
    return out


def compute_source_tree_hash(root: Path | None = None) -> str:
    """
    Deterministic BLAKE3 over the gyza source tree.

    The wire is, for each file in sorted relative-path order:

        b"P" || u32(len(relpath))   || relpath_utf8
        b"D" || u32(len(filebytes)) || filebytes

    Length-prefixing every field makes the concatenation injective:
    no two distinct trees can produce the same byte stream, so no
    two distinct trees collide (modulo BLAKE3's own collision
    resistance).
    """
    root = root or _package_root()
    h = blake3.blake3()
    for p in _iter_source_files(root):
        rel = p.relative_to(root).as_posix().encode("utf-8")
        data = p.read_bytes()
        h.update(b"P")
        h.update(struct.pack(">I", len(rel)))
        h.update(rel)
        h.update(b"D")
        h.update(struct.pack(">I", len(data)))
        h.update(data)
    return h.hexdigest()


@dataclass(frozen=True)
class ReleaseIdentity:
    """The (version, source-tree-hash) pair a runner self-reports."""
    version: str
    source_tree_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "runner_version": self.version,
            "runner_source_tree_hash": self.source_tree_hash,
        }


# Computed once at module load — this is "the binary's identity at
# process start," matching the semantics a release hash should have.
# A daemon that hot-swaps source mid-process will (correctly) keep
# reporting the load-time hash, which then mismatches the on-disk
# tree — an honest signal that something is wrong.
CURRENT_RELEASE = ReleaseIdentity(
    version=__version__,
    source_tree_hash=compute_source_tree_hash(),
)


# ---------------------------------------------------------------------------
# Trusted-release set.
#
# This is the SECOND trust root (the first being honest self-report).
# It is intentionally a source-pinned literal: a submitter trusts the
# set that ships in *its own* installed gyza client, not a set fetched
# from the daemon it is querying. Same model as package signing — you
# trust the keyring your client was built with.
#
# Empty until the first tagged release. Until then every runner is
# honestly labeled "unknown build": the predicate (V4) still proves
# enforcement ⊆ manifest, but the runner that stamped it is not a
# verified release. Cutting a release = add its (version,
# source_tree_hash) here, in a signed commit, in the client people
# install. (Foundation-key signing of an out-of-band release
# manifest is the next step up; see ADR-0017 §"Path forward".)
# ---------------------------------------------------------------------------
TRUSTED_RELEASES: dict[tuple[str, str], dict[str, str]] = {
    # ("0.1.0", "<source_tree_hash of the 0.1.0 tag>"): {
    #     "released": "2026-..", "notes": "first public release",
    # },
}


def is_trusted_release(version: str, source_tree_hash: str) -> tuple[bool, str]:
    """
    Is this (version, source-tree-hash) a known trusted release?

    Returns ``(ok, reason)``. ``reason`` is human-readable and is
    surfaced in ``gyza submit`` output, so it must read well to a
    non-expert.
    """
    if not TRUSTED_RELEASES:
        return False, (
            "no releases have been published yet — this runner is a "
            "development build (enforcement still cryptographically "
            "checked; the binary that stamped it is just not a "
            "verified release)"
        )
    if (version, source_tree_hash) in TRUSTED_RELEASES:
        return True, ""
    return False, (
        f"runner {version!r} (tree {source_tree_hash[:12]}…) is not in "
        f"this client's trusted-release set"
    )


__all__ = [
    "CURRENT_RELEASE",
    "ReleaseIdentity",
    "TRUSTED_RELEASES",
    "compute_source_tree_hash",
    "is_trusted_release",
]
