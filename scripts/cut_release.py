#!/usr/bin/env python3
"""
cut_release.py — pin a gyza release into the runner-attestation
trusted set (G1a / ADR-0017 / ADR-0018).

Lives OUTSIDE gyza/ on purpose: compute_source_tree_hash roots at
the gyza package dir, so this script is not in the hashed tree and
editing it never perturbs a release hash.

Correct ordering (the footgun this script removes):

  1. set gyza.__version__ to the release version  (a *.py change —
     IN the hash; the released version string is part of code
     identity);
  2. freeze: no further *.py edits;
  3. H = compute_source_tree_hash()  over the frozen tree;
  4. write {"releases": {version: {"source_tree_hash": H, ...}}}
     into gyza/trusted_releases.json  — a non-*.py file, so this
     write does NOT change H. Self-consistent.

The script refuses to proceed unless it can PROVE step 4 doesn't
move the hash (recompute after the write and assert equality). If
that invariant is ever broken — someone renamed the json to .py,
or changed compute_source_tree_hash to include it — cutting a
release would reintroduce the non-convergent fixed point, so we
hard-fail instead.

Usage:

    python scripts/cut_release.py 0.1.0 --dry-run
    python scripts/cut_release.py 0.1.0 --notes "first public release"

The script does NOT git-commit, git-tag, or upload to PyPI. Those
are deliberate human steps (a public tag is an irreversible release
signal). It prints the exact next commands.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INIT_PY = REPO / "gyza" / "__init__.py"
TRUSTED_JSON = REPO / "gyza" / "trusted_releases.json"
PYPROJECT = REPO / "pyproject.toml"

_VERSION_RE = re.compile(r'^(__version__\s*=\s*")([^"]*)(")', re.MULTILINE)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def set_init_version(version: str) -> None:
    txt = _read(INIT_PY)
    if not _VERSION_RE.search(txt):
        sys.exit("FATAL: no __version__ assignment found in gyza/__init__.py")
    new = _VERSION_RE.sub(rf'\g<1>{version}\g<3>', txt)
    INIT_PY.write_text(new, encoding="utf-8")


def current_init_version() -> str:
    m = _VERSION_RE.search(_read(INIT_PY))
    return m.group(2) if m else ""


def compute_hash() -> str:
    # Import lazily and from source on disk (compute_source_tree_hash
    # reads file bytes, not the already-imported module), so a
    # just-written __version__ is reflected.
    sys.path.insert(0, str(REPO))
    import importlib

    rel = importlib.import_module("gyza.release")
    importlib.reload(rel)  # pick up a freshly-edited __init__ if any
    return rel.compute_source_tree_hash()


def load_releases() -> dict:
    try:
        raw = json.loads(_read(TRUSTED_JSON))
    except Exception:  # noqa: BLE001
        return {"releases": {}}
    if not isinstance(raw, dict):
        return {"releases": {}}
    raw.setdefault("releases", {})
    if not isinstance(raw["releases"], dict):
        raw["releases"] = {}
    return raw


def main() -> int:
    ap = argparse.ArgumentParser(description="Pin a gyza release.")
    ap.add_argument("version", help="release version, e.g. 0.1.0")
    ap.add_argument("--notes", default="", help="freeform release notes")
    ap.add_argument("--dry-run", action="store_true",
                    help="prove the mechanism without mutating tracked files")
    args = ap.parse_args()
    version = args.version.strip()

    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"FATAL: version {version!r} must be X.Y.Z (no -dev suffix "
                 f"— a release is a clean version)")

    init_before = current_init_version()

    # Step 1: set the version (in-memory plan; only written on real run).
    if not args.dry_run:
        set_init_version(version)
    else:
        # Dry-run still needs the hash AS IF the version were set, so
        # temporarily set, compute, restore.
        set_init_version(version)

    try:
        # Steps 2-3: freeze + hash.
        h1 = compute_hash()

        # Step 4 + the invariant proof: simulate the json write and
        # recompute. If the hash moves, the fixed point is NOT
        # dissolved — refuse to cut.
        doc = load_releases()
        doc["releases"][version] = {
            "source_tree_hash": h1,
            "released": _dt.datetime.now(_dt.timezone.utc)
            .strftime("%Y-%m-%d"),
            "notes": args.notes,
        }
        TRUSTED_JSON.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        h2 = compute_hash()
        if h1 != h2:
            # Restore json + version; this is a hard design failure.
            sys.exit(
                "FATAL: writing trusted_releases.json CHANGED the source "
                f"tree hash ({h1[:12]}… -> {h2[:12]}…). The fixed point "
                "is not dissolved — trusted_releases.json must be a "
                "non-*.py file and compute_source_tree_hash must exclude "
                "it. Refusing to cut a release (see ADR-0018)."
            )

        # Prove the pinned entry is now self-trusted.
        sys.path.insert(0, str(REPO))
        import importlib

        rel = importlib.import_module("gyza.release")
        importlib.reload(rel)
        ok, why = rel.is_trusted_release(version, h1)
        if not ok:
            sys.exit(f"FATAL: post-pin self-check failed: {why}")

        print(f"version           : {version}")
        print(f"source_tree_hash  : {h1}")
        print(f"is_trusted_release: ✓ (self-consistent — hash invariant "
              f"under the json write)")

        if args.dry_run:
            # Roll everything back — dry-run mutates nothing tracked.
            set_init_version(init_before)
            # Restore the json to its pre-run content.
            doc["releases"].pop(version, None)
            TRUSTED_JSON.write_text(
                json.dumps(doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print("\n[dry-run] mechanism proven; no tracked files changed.")
            return 0

        # Real run: also bump pyproject version to match.
        pp = _read(PYPROJECT)
        pp2 = re.sub(r'(?m)^(version\s*=\s*")[^"]*(")',
                     rf'\g<1>{version}\g<2>', pp, count=1)
        PYPROJECT.write_text(pp2, encoding="utf-8")

        print("\nWrote:")
        print(f"  gyza/__init__.py            __version__ = {version}")
        print(f"  gyza/trusted_releases.json  + {version} -> {h1[:16]}…")
        print(f"  pyproject.toml              version = {version}")
        print("\nNEXT (human steps — intentionally NOT automated):")
        print(f"  git add -A && git commit -m 'release: {version}'")
        print(f"  git tag v{version} && git push origin main v{version}")
        print(f"  python -m build && twine upload dist/*   # when ready")
        print("\nThen flip main back to dev:")
        print("  edit gyza/__init__.py __version__ = "
              "'<next>-dev'  (dev builds stay honestly 'unverified')")
        return 0
    except SystemExit:
        # On any fatal abort, leave a clean tree on dry-run.
        if args.dry_run:
            set_init_version(init_before)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
