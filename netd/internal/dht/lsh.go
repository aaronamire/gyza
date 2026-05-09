package dht

// Cross-language LSH (locality-sensitive hashing) — random-hyperplane
// projection where the hyperplane matrix is shared with Python via an
// embedded binary asset. See scripts/generate_lsh_planes.py for the
// authoritative generation routine; the resulting bytes are committed
// at lsh_planes.bin in this directory and loaded into the Go process at
// init() time via //go:embed.
//
// Why an asset and not a Go-side RNG: Python uses
// numpy.random.default_rng(42) (PCG64) and Go's math/rand uses a
// different generator. To get *byte-identical* hashes from the same
// embedding, both runtimes must read from the same matrix. The asset
// approach trades a 96 KiB binary for absolute determinism.
//
// Bit-packing convention — must match np.packbits + int.from_bytes(big):
//   plane i ∈ {0..63} has its sign bit placed at position (63-i) of
//   the resulting uint64. Plane 0 → MSB; plane 63 → LSB.

import (
	_ "embed"
	"encoding/binary"
	"fmt"
	"math"
	"sync"
)

// lshPlanesBin is the canonical hyperplane matrix produced by
// scripts/generate_lsh_planes.py: 64 rows × 384 cols × 4 bytes/float32
// (98304 bytes total), row-major, little-endian.
//
//go:embed lsh_planes.bin
var lshPlanesBin []byte

// lshPlaneAssetSize is the expected byte length of the embedded asset.
// A wrong-sized asset is an immediate panic at init() time — easier to
// catch in CI than a subtle runtime LSH divergence.
const lshPlaneAssetSize = LSHBits * EmbeddingDim * 4 // 98304

// LSHIndex holds 64 unit-norm hyperplanes in R^EmbeddingDim, loaded
// once from the embedded asset. Identical bytes across processes →
// identical hash output for identical input.
type LSHIndex struct {
	Planes [LSHBits][EmbeddingDim]float32
}

var (
	defaultIndex     *LSHIndex
	defaultIndexErr  error
	defaultIndexOnce sync.Once
)

// DefaultLSHIndex returns the process-wide singleton index loaded from
// the embedded plane asset. All packages should use this rather than
// constructing their own — that's the entire point of the shared asset.
func DefaultLSHIndex() (*LSHIndex, error) {
	defaultIndexOnce.Do(func() {
		defaultIndex, defaultIndexErr = loadLSHIndex(lshPlanesBin)
	})
	return defaultIndex, defaultIndexErr
}

// MustDefaultLSHIndex is the convenience wrapper for callers that have
// no sensible recovery path if the asset is malformed (i.e. essentially
// all of them). Panics on error so the failure is loud.
func MustDefaultLSHIndex() *LSHIndex {
	idx, err := DefaultLSHIndex()
	if err != nil {
		panic(err)
	}
	return idx
}

func loadLSHIndex(data []byte) (*LSHIndex, error) {
	if len(data) != lshPlaneAssetSize {
		return nil, fmt.Errorf(
			"lsh asset has wrong size: got %d, want %d (regenerate with scripts/generate_lsh_planes.py)",
			len(data), lshPlaneAssetSize,
		)
	}
	idx := &LSHIndex{}
	off := 0
	for i := 0; i < LSHBits; i++ {
		for j := 0; j < EmbeddingDim; j++ {
			bits := binary.LittleEndian.Uint32(data[off : off+4])
			idx.Planes[i][j] = math.Float32frombits(bits)
			off += 4
		}
	}
	return idx, nil
}

// Hash projects embedding onto each plane, takes the sign of each dot
// product (>0 → 1, ≤0 → 0), then packs the 64 bits into a uint64. Bit
// for plane i sits at position (63-i) of the uint64 — see the package
// comment for why.
//
// Wrong-length input is a programming error; callers should validate
// upstream. We tolerate it by returning 0 (Python raises in the
// equivalent path; the discrepancy doesn't matter because the gRPC
// boundary will already have type-checked the embedding length).
func (l *LSHIndex) Hash(embedding []float32) uint64 {
	if len(embedding) != EmbeddingDim {
		return 0
	}
	var bucket uint64
	for i := 0; i < LSHBits; i++ {
		var dot float32
		row := &l.Planes[i]
		for j := 0; j < EmbeddingDim; j++ {
			dot += row[j] * embedding[j]
		}
		if dot > 0 {
			bucket |= uint64(1) << uint(63-i)
		}
	}
	return bucket
}

// HammingNeighbors returns every uint64 within Hamming distance ≤
// radius of `bucket`. The bucket itself is included at index 0. Order
// of the rest is lex over (k, combination), which matches the Python
// neighbor_buckets enumeration in gyza/demand.py exactly — convenient
// for cross-language tests that compare ordered slices.
//
//	radius=0 → 1 entry
//	radius=1 → 1 + 64 = 65
//	radius=2 → 1 + 64 + 2016 = 2081
func HammingNeighbors(bucket uint64, radius int) []uint64 {
	if radius < 0 {
		return nil
	}
	if radius > LSHBits {
		radius = LSHBits
	}
	cap := 1
	if radius >= 1 {
		cap += LSHBits
	}
	if radius >= 2 {
		cap += LSHBits * (LSHBits - 1) / 2
	}
	if radius >= 3 {
		cap *= radius + 1 // coarse upper bound; rare path
	}
	out := make([]uint64, 0, cap)
	out = append(out, bucket)
	if radius == 0 {
		return out
	}

	// Mirror gyza/demand.py: itertools.combinations(range(64), r) with
	// mask bits set in increasing position order, for r=1..radius.
	indices := make([]int, radius)
	for k := 1; k <= radius; k++ {
		for i := 0; i < k; i++ {
			indices[i] = i
		}
		for {
			var mask uint64
			for i := 0; i < k; i++ {
				mask |= uint64(1) << uint(indices[i])
			}
			out = append(out, bucket^mask)

			pos := k - 1
			for pos >= 0 && indices[pos] == LSHBits-(k-pos) {
				pos--
			}
			if pos < 0 {
				break
			}
			indices[pos]++
			for j := pos + 1; j < k; j++ {
				indices[j] = indices[j-1] + 1
			}
		}
	}
	return out
}
