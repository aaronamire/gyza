"""AR-1 harness: the chain must be real and must audit clean under the
production verifiers, or every number derived from it is meaningless."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "vocabulary_design"))

from gyza.audit import audit_provenance          # noqa: E402
from gyza.icp import verify_chain, verify_dag    # noqa: E402
from gyza.identity import manifest_hash_hex      # noqa: E402
from run_ar1 import _identity, build_real_chain  # noqa: E402


def test_ar1_chain_passes_the_production_verifiers():
    with tempfile.TemporaryDirectory() as tmp:
        idn = _identity(tmp)
        envs, arts = build_real_chain(idn, 4)
        ok, bad = verify_chain(envs)
        assert ok, f"verify_chain failed at {bad}"
        assert verify_dag(envs, require_closed=True).valid

        mh = manifest_hash_hex(idn.manifest)
        rep = audit_provenance(
            envs, resolve_artifact=lambda h: arts.get(h),
            resolve_manifest=lambda h: idn.manifest if h == mh else None,
            require_closed=True, require_all_artifacts=True)
        assert rep.valid, rep.summary
        assert len(list(rep.actions)) == 4


def test_empty_input_hashes_are_refused_by_production_and_would_void_the_route():
    """The disclosed harness correction: a chain with empty inputs is not a
    chain the production verifiers accept."""
    with tempfile.TemporaryDirectory() as tmp:
        idn = _identity(tmp)
        envs, _ = build_real_chain(idn, 3)
        from dataclasses import replace
        broken = [replace(e, input_hashes=[]) for e in envs]
        ok, _bad = verify_chain(broken)
        assert not ok, "empty input_hashes must be refused"
