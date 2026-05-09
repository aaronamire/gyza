"""
Generate the canonical LSH hyperplane matrix used by Python and Go.

  shape:  (64, 384) float32
  RNG:    numpy.random.default_rng(seed=42).standard_normal
  norm:   per-row L2-normalized (unit vectors)
  layout: row-major, little-endian float32 (4 bytes/element, 98304 bytes total)

Both gyza/demand.py LSHIndex(seed=42) and netd/internal/dht.LSHIndex must
hash an embedding to the same uint64 bucket. To enforce that across two
unrelated RNGs (numpy.random.PCG64 in Python, math/rand or whatever in
Go) we make both sides agree on one matrix:

  - Python:  LSHIndex(seed=42) generates from this script's seed.
  - Go:      dht.LSHIndex loads this exact file via //go:embed.

A guard test on the Go side (TestLSHMatchesPython) hashes a small set of
reference vectors and asserts the result matches what Python computed
when this asset was last generated. If anyone bumps the seed/dim/RNG on
either side, that test breaks loudly.

Usage:
    PYTHONPATH=. python scripts/generate_lsh_planes.py [output_path]

Default output: netd/internal/dht/lsh_planes.bin
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


SEED = 42
N_PLANES = 64
DIM = 384


def main() -> int:
    out = Path(
        sys.argv[1] if len(sys.argv) > 1 else "netd/internal/dht/lsh_planes.bin"
    )

    rng = np.random.default_rng(seed=SEED)
    planes = rng.standard_normal((N_PLANES, DIM)).astype(np.float32)
    norms = np.linalg.norm(planes, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    planes = (planes / norms).astype(np.float32)

    # Explicit little-endian on disk so the asset is portable across
    # archs (no native-byte-order surprises on big-endian builds).
    data = planes.astype("<f4").tobytes(order="C")
    assert len(data) == N_PLANES * DIM * 4

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"[lsh] wrote {len(data)} bytes to {out}")

    # Sanity: gyza.demand.LSHIndex(seed=42) must produce the same matrix.
    # (If it doesn't, somebody changed the Python-side RNG and we'd ship
    # an asset that doesn't match Python's behavior — defeats the
    # whole purpose of cross-language byte-identity.)
    from gyza.demand import LSHIndex
    idx = LSHIndex(seed=SEED)
    if not np.allclose(idx.planes, planes):
        print("ERROR: LSHIndex(seed=42).planes diverged from generated asset")
        return 1
    print("[lsh] guard: LSHIndex(seed=42).planes matches asset ✓")

    # Reference buckets — paste these into the Go test fixture so any
    # asset regeneration also updates the Go-side expected values.
    print("\n[lsh] reference buckets — paste into TestLSHMatchesPython:")
    cases = {
        "zeros":       np.zeros(DIM, dtype=np.float32),
        "small_pos":   np.full(DIM, 0.1, dtype=np.float32),
        "small_neg":   np.full(DIM, -0.1, dtype=np.float32),
        "ramp":        np.array(
            [(i - DIM // 2) / float(DIM) for i in range(DIM)], dtype=np.float32),
        "alternating": np.array(
            [1.0 if i % 2 == 0 else -1.0 for i in range(DIM)], dtype=np.float32),
        "first_half":  np.array(
            [1.0 if i < DIM // 2 else 0.0 for i in range(DIM)], dtype=np.float32),
    }
    for name, v in cases.items():
        b = idx.hash(v)
        print(f"    {{name: {name!r:15s} bucket: 0x{b:016x}}}, // = {b}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
