package dht

import (
	"math/bits"
	"testing"
)

// TestLSHAssetLoads — the //go:embed asset has the right shape and the
// loader produces unit-norm planes. Catches accidental file truncation
// or a bad regeneration that ships a non-normalized matrix.
func TestLSHAssetLoads(t *testing.T) {
	idx := MustDefaultLSHIndex()

	// Each plane row should be unit norm to within float32 tolerance.
	for i := 0; i < LSHBits; i++ {
		var sumSq float64
		for j := 0; j < EmbeddingDim; j++ {
			sumSq += float64(idx.Planes[i][j]) * float64(idx.Planes[i][j])
		}
		if d := sumSq - 1.0; d < -1e-5 || d > 1e-5 {
			t.Errorf("plane %d not unit norm: ‖row‖² = %v (Δ from 1.0 = %v)", i, sumSq, d)
		}
	}
}

// TestLSHMatchesPython — the cross-language byte-identity contract.
//
// Reference values were produced by gyza.demand.LSHIndex(seed=42) at
// the time scripts/generate_lsh_planes.py last ran. If you regenerate
// the embedded asset (because numpy's RNG output changed, the seed
// changed, or the dim changed) you MUST also update these values by
// running the script and pasting its output.
//
// A failure here means: any agent advertisement published from a
// Python node would land in a different bucket than a Go node would
// look in, breaking the entire global discovery layer.
func TestLSHMatchesPython(t *testing.T) {
	idx := MustDefaultLSHIndex()

	cases := []struct {
		name   string
		make   func() []float32
		bucket uint64
	}{
		{"zeros", func() []float32 { return make([]float32, EmbeddingDim) }, 0x0000000000000000},
		{"small_pos", func() []float32 {
			v := make([]float32, EmbeddingDim)
			for i := range v {
				v[i] = 0.1
			}
			return v
		}, 0xa355a65a95bffb7d},
		{"small_neg", func() []float32 {
			v := make([]float32, EmbeddingDim)
			for i := range v {
				v[i] = -0.1
			}
			return v
		}, 0x5caa59a56a400482},
		{"ramp", func() []float32 {
			v := make([]float32, EmbeddingDim)
			for i := range v {
				v[i] = float32(float64(i-EmbeddingDim/2) / float64(EmbeddingDim))
			}
			return v
		}, 0xf53efe8c94749131},
		{"alternating", func() []float32 {
			v := make([]float32, EmbeddingDim)
			for i := range v {
				if i%2 == 0 {
					v[i] = 1
				} else {
					v[i] = -1
				}
			}
			return v
		}, 0x948b88a86a24515f},
		{"first_half", func() []float32 {
			v := make([]float32, EmbeddingDim)
			for i := 0; i < EmbeddingDim/2; i++ {
				v[i] = 1
			}
			return v
		}, 0x03c1a6423b8d7e8f},
	}

	for _, c := range cases {
		got := idx.Hash(c.make())
		if got != c.bucket {
			t.Errorf("%s: got %#016x, want %#016x", c.name, got, c.bucket)
		}
	}
}

// TestLSHHashSignFlipDuality — for any embedding x, Hash(-x) is the
// bitwise complement of Hash(x), because every projection sign flips.
// This is a structural property of the algorithm; if it fails, the
// loop-and-shift logic in Hash is broken.
func TestLSHHashSignFlipDuality(t *testing.T) {
	idx := MustDefaultLSHIndex()
	v := make([]float32, EmbeddingDim)
	for i := range v {
		v[i] = float32((i*7)%23 - 11)
	}
	neg := make([]float32, EmbeddingDim)
	for i := range v {
		neg[i] = -v[i]
	}
	a := idx.Hash(v)
	b := idx.Hash(neg)
	// Equal-zero projections are unlikely with these values; if any
	// projection happened to be exactly zero, both Hash(v) and Hash(-v)
	// put a 0 bit there, breaking the duality. The test embedding
	// avoids the Hash-on-zero ambiguity by using non-trivial values.
	if a^b != ^uint64(0) {
		t.Errorf("Hash(-x) ⊕ Hash(x) = %#x, want all-ones", a^b)
	}
}

func TestLSHHashShapeGuard(t *testing.T) {
	idx := MustDefaultLSHIndex()
	if got := idx.Hash([]float32{1, 2, 3}); got != 0 {
		t.Fatalf("expected 0 on wrong-length input, got %x", got)
	}
}

// TestHammingNeighborsRadius1 — every single-bit flip is a neighbor at
// Hamming distance exactly 1, exactly 64 of them.
func TestHammingNeighborsRadius1(t *testing.T) {
	const bucket uint64 = 0xDEADBEEFCAFEBABE
	out := HammingNeighbors(bucket, 1)
	if len(out) != 1+LSHBits {
		t.Fatalf("expected %d neighbors at radius 1, got %d", 1+LSHBits, len(out))
	}
	if out[0] != bucket {
		t.Fatalf("first entry must be the bucket itself; got %x", out[0])
	}
	for _, n := range out[1:] {
		if d := bits.OnesCount64(n ^ bucket); d != 1 {
			t.Errorf("expected hamming distance 1, got %d for %x", d, n)
		}
	}
}

// TestHammingNeighborsRadius2 — C(64,0)+C(64,1)+C(64,2) = 1+64+2016 = 2081.
func TestHammingNeighborsRadius2(t *testing.T) {
	const bucket uint64 = 0
	out := HammingNeighbors(bucket, 2)
	want := 1 + LSHBits + LSHBits*(LSHBits-1)/2
	if len(out) != want {
		t.Fatalf("expected %d neighbors at radius 2, got %d", want, len(out))
	}
	for _, n := range out {
		if d := bits.OnesCount64(n ^ bucket); d > 2 {
			t.Errorf("neighbor %x has Hamming distance %d > 2", n, d)
		}
	}
}

func TestHammingNeighborsUniqueness(t *testing.T) {
	const bucket uint64 = 0xAA55AA55AA55AA55
	out := HammingNeighbors(bucket, 2)
	seen := make(map[uint64]struct{}, len(out))
	for _, n := range out {
		if _, dup := seen[n]; dup {
			t.Fatalf("duplicate neighbor %x", n)
		}
		seen[n] = struct{}{}
	}
}

func TestAgentDHTKey(t *testing.T) {
	cases := []struct {
		bucket uint64
		want   string
	}{
		{0, "/gyza/agents/0000000000000000"},
		{1, "/gyza/agents/0000000000000001"},
		{0xDEADBEEFCAFEBABE, "/gyza/agents/deadbeefcafebabe"},
		{^uint64(0), "/gyza/agents/ffffffffffffffff"},
	}
	for _, c := range cases {
		if got := AgentDHTKey(c.bucket); got != c.want {
			t.Errorf("AgentDHTKey(%x) = %q, want %q", c.bucket, got, c.want)
		}
	}
}
