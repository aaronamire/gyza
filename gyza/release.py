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

import json
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
# Trusted-release set — the SECOND trust root (the first being honest
# self-report). Loaded from trusted_releases.json, NOT a Python literal.
#
# Why a JSON data file and not a dict in this module (ADR-0018):
# compute_source_tree_hash globs only *.py. If the trusted set lived
# in release.py, pinning a release's own hash would be a
# non-convergent fixed point — writing the hash into release.py
# changes release.py, which changes the tree hash, ad infinitum —
# making `+ RUNNER ATTESTED` UNREACHABLE for any release. Putting the
# *data* in a non-.py file dissolves that: editing it cannot perturb
# the hash. The verification *logic* (this function,
# compute_source_tree_hash) stays in *.py and so stays hash-covered
# and tamper-evident. It is also semantically more correct: code
# identity should be invariant under trust-policy changes — adding a
# peer release to your trust list must not change your binary's hash.
#
# Trust model (unchanged from ADR-0017): a submitter trusts the
# trusted_releases.json that shipped in *its own* pip install, never
# one fetched from the daemon it is querying. Keyed by version with
# exactly one canonical source_tree_hash per version, so a build that
# claims a known version but presents a different tree is rejected as
# tampered, not merely "unknown".
#
# Fail-safe: a missing / unparseable / malformed file yields {} — the
# conservative direction (everything "unverified", never falsely
# trusted). NEVER fail open.
# ---------------------------------------------------------------------------
def _trusted_releases_path() -> Path:
    return _package_root() / "trusted_releases.json"


def _load_trusted_releases() -> dict[str, dict]:
    try:
        raw = json.loads(_trusted_releases_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  missing/corrupt → fail-safe to {}
        return {}
    if not isinstance(raw, dict):
        return {}
    releases = raw.get("releases")
    if not isinstance(releases, dict):
        return {}
    # Keep only well-formed entries: {version: {"source_tree_hash": hex,...}}
    out: dict[str, dict] = {}
    for ver, entry in releases.items():
        if (
            isinstance(ver, str)
            and isinstance(entry, dict)
            and isinstance(entry.get("source_tree_hash"), str)
            and entry["source_tree_hash"]
        ):
            out[ver] = entry
    return out


# Loaded once at import — the trust policy in effect for this client.
TRUSTED_RELEASES: dict[str, dict] = _load_trusted_releases()


def is_trusted_release(version: str, source_tree_hash: str) -> tuple[bool, str]:
    """
    Is this (version, source-tree-hash) a known trusted release?

    Returns ``(ok, reason)``. ``reason`` is human-readable and is
    surfaced in ``gyza submit`` output, so it must read well to a
    non-expert. Distinguishes three negatives: no releases published
    at all; this version unknown; version known but tree hash differs
    (the strongest negative — a build claiming to be a release it is
    not).
    """
    if not TRUSTED_RELEASES:
        return False, (
            "no releases have been published yet — this runner is a "
            "development build (enforcement still cryptographically "
            "checked; the binary that stamped it is just not a "
            "verified release)"
        )
    entry = TRUSTED_RELEASES.get(version)
    if entry is None:
        return False, (
            f"runner version {version!r} is not in this client's "
            f"trusted-release set"
        )
    if entry["source_tree_hash"] != source_tree_hash:
        return False, (
            f"runner claims version {version!r} but its source-tree "
            f"hash {source_tree_hash[:12]}… does not match the trusted "
            f"build for that version (tampered or rebuilt)"
        )
    return True, ""


__all__ = [
    "CURRENT_RELEASE",
    "ReleaseIdentity",
    "TRUSTED_RELEASES",
    "compute_source_tree_hash",
    "is_trusted_release",
]
