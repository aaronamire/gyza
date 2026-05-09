// Package identity loads the Gyza compositor key from disk and exposes
// it as a libp2p crypto.PrivKey + peer.ID.
//
// The on-disk format is a 32-byte master seed (compatible with the
// Python LocalCompositor at gyza/identity.py). The compositor's actual
// Ed25519 keypair is derived from that seed via a BLAKE3 keyed hash,
// using the same domain-separation tag as the Python side. Result: the
// libp2p PeerID computed here matches the compositor public key
// reported by Python's LocalCompositor.pubkey_hex — one identity, two
// runtimes.
//
// Why derive instead of using the master seed directly: see
// gyza/identity.py — the master seed is the apex secret for *all* keys
// (compositor + per-agent), and the compositor key is one specific
// derivation. If the Go side used the master seed bytes directly as
// Ed25519, the resulting pubkey would have no relationship to anything
// Python signs with.
package identity

import (
	"crypto/ed25519"
	"errors"
	"fmt"
	"os"

	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/zeebo/blake3"
)

// Domain-separation tag — must match _CTX_COMPOSITOR_SEED in
// gyza/identity.py byte-for-byte. Changing this string in either
// runtime breaks cross-language identity entirely.
var ctxCompositorSeed = []byte("gyza.compositor.ed25519.v1")

// Identity bundles every form of the compositor key the daemon needs.
type Identity struct {
	PrivKey    crypto.PrivKey // libp2p crypto.PrivKey wrapping Ed25519
	PubKey     crypto.PubKey
	PeerID     peer.ID
	RawSeed    []byte // 32-byte derived Ed25519 seed (== Ed25519.PrivateKey.Seed())
	RawPubKey  []byte // 32-byte Ed25519 public key
	PubKeyHex  string // hex-encoded RawPubKey, matches compositor.pubkey_hex in Python
	MasterSeed []byte // 32-byte master seed read from disk (kept for agent-key derivation later)
}

// LoadIdentity reads the 32-byte master seed at keyPath and derives the
// compositor's Ed25519 keypair, exactly as Python's LocalCompositor does.
//
// The file mode is required to be 0600 — anything looser is a refusal,
// not a warning. The compositor key is the apex secret in this system.
func LoadIdentity(keyPath string) (*Identity, error) {
	master, err := os.ReadFile(keyPath)
	if err != nil {
		return nil, fmt.Errorf("read compositor key %q: %w", keyPath, err)
	}
	if len(master) != 32 {
		return nil, fmt.Errorf(
			"compositor key %q is corrupt: expected 32 bytes, got %d",
			keyPath, len(master),
		)
	}
	if info, err := os.Stat(keyPath); err == nil {
		mode := info.Mode().Perm()
		if mode&0o077 != 0 {
			return nil, fmt.Errorf(
				"compositor key %q has permissive mode %#o; require 0600",
				keyPath, mode,
			)
		}
	}

	// Mirror Python: comp_seed = BLAKE3(ctx ∥ "|" ∥ "", key=master).
	// Note the lone trailing "|"; the info field is empty for the
	// compositor derivation, but the separator is still present.
	hasher, err := blake3.NewKeyed(master)
	if err != nil {
		return nil, fmt.Errorf("blake3 keyed: %w", err)
	}
	hasher.Write(ctxCompositorSeed)
	hasher.Write([]byte{'|'})
	derived := hasher.Sum(nil) // 32 bytes
	if len(derived) != 32 {
		return nil, errors.New("blake3 derivation produced wrong length")
	}

	edPriv := ed25519.NewKeyFromSeed(derived)
	priv, err := crypto.UnmarshalEd25519PrivateKey(edPriv)
	if err != nil {
		return nil, fmt.Errorf("unmarshal ed25519 priv: %w", err)
	}
	pub := priv.GetPublic()
	pid, err := peer.IDFromPublicKey(pub)
	if err != nil {
		return nil, fmt.Errorf("peer id: %w", err)
	}
	rawPub := edPriv.Public().(ed25519.PublicKey)
	return &Identity{
		PrivKey:    priv,
		PubKey:     pub,
		PeerID:     pid,
		RawSeed:    derived,
		RawPubKey:  []byte(rawPub),
		PubKeyHex:  fmt.Sprintf("%x", []byte(rawPub)),
		MasterSeed: master,
	}, nil
}

// SignBytes signs arbitrary bytes with the compositor key. Convenience
// wrapper around the underlying ed25519.PrivateKey.
func (i *Identity) SignBytes(data []byte) []byte {
	edPriv := ed25519.NewKeyFromSeed(i.RawSeed)
	return ed25519.Sign(edPriv, data)
}
