"""H5 storage growth — measuring h̄ and A for an EXTINGUISHES quantity.

R-D1b measured A for H1 (TRANSFERS, the only enforced bound) at < 1: a single
real-model action exceeds the declared bound. This measures the same thing for
the first EXTINGUISHES quantity, on a REAL `ArtifactStore` with REAL signed
envelopes.

THE SYSTEM-LEVEL COROLLARY, derived here and easy to miss: escalations from
different classes ADD, so actions-per-escalation is the harmonic combination

    A_system = 1 / Σ_i (1/A_i)

which is dominated by the WORST amortizer. Adding a well-amortized bound buys
nothing while a badly-amortized one is in force.

Run:  ~/dev/marshal/.os/bin/python research/planetary/r_b4_storage_amortization.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from dataclasses import asdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from gyza.identity import LocalCompositor                      # noqa: E402
from gyza.network.artifact_store import ArtifactStore          # noqa: E402
from tests.test_audit import _agent, _enforcement, _sign       # noqa: E402

#: R-D1: actions per human decision needed for 1e9/day at H=1e4 and today's p, c.
PLANETARY_A = 38_500

OUTPUT_SIZES = {"short (200 B)": 200, "typical (2 KB)": 2_000,
                "large (20 KB)": 20_000}
CANDIDATE_BOUNDS = {"1 GB": 1e9, "10 GB": 1e10, "100 GB": 1e11, "1 TB": 1e12}


def measure_h_bar() -> dict[str, int]:
    """Bytes retained per action: artifact on disk + envelope in the log."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    store = ArtifactStore(base_path=str(tmp / "cas"))
    worker = _agent(LocalCompositor(key_path=str(tmp / "k.key")), 512)
    out: dict[str, int] = {}
    for label, n in OUTPUT_SIZES.items():
        before = store.total_size_bytes()
        env, art = _sign(worker, f"a{n}", None, text="x" * n,
                         enforcement=_enforcement(512))
        store.store(art)
        env_bytes = len(json.dumps(asdict(env), sort_keys=True,
                                   separators=(",", ":")).encode())
        out[label] = (store.total_size_bytes() - before) + env_bytes
    return out


def a_system(*amortizations: float) -> float:
    """Escalations from different classes ADD; actions-per-escalation is their
    harmonic combination, so the worst class governs."""
    total = sum(1.0 / a for a in amortizations if a > 0)
    return float("inf") if total == 0 else 1.0 / total


def main() -> None:
    h = measure_h_bar()
    print("h̄ for H5 storage growth (real ArtifactStore, real signed envelopes)\n")
    print(f"{'agent output':22s} {'bytes/action':>13s}")
    for k, v in h.items():
        print(f"{k:22s} {v:13,d}")

    print(f"\nA = B/h̄ — actions per human decision  (planetary needs {PLANETARY_A:,})\n")
    print(f"{'bound':>10s} " + " ".join(f"{k:>16s}" for k in h))
    for label, B in CANDIDATE_BOUNDS.items():
        row = " ".join(f"{B/v:16,.0f}" for v in h.values())
        print(f"{label:>10s} {row}")

    print("\nAgainst H1, the only ENFORCED bound (R-D1b):")
    A_H1 = 0.0025          # claude-sonnet, 1k tokens, B = 100 credits
    A_H5 = 1e10 / h["typical (2 KB)"]
    print(f"  A(H1, sonnet)        = {A_H1:>18,.4f}   TRANSFERS")
    print(f"  A(H5, 10 GB, typical)= {A_H5:>18,.0f}   EXTINGUISHES")
    print(f"  ratio                = {A_H5/A_H1:>18,.0f}x")

    print("\nTHE COROLLARY — the system is governed by its WORST amortizer:")
    print(f"  A_system(H5 alone)   = {a_system(A_H5):>18,.0f}")
    print(f"  A_system(H1 + H5)    = {a_system(A_H1, A_H5):>18,.4f}")
    print("  -> adding a bound that amortizes 4 billion actions moves the system")
    print("     total by nothing. One miscalibrated class caps the whole system.")


if __name__ == "__main__":
    main()
