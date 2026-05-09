package gossip

// Exposing a thin wrapper around the unexported app-signature check so
// gossip_test (which lives in package gossip_test for hygiene) can
// drive forgery-detection paths without setting up a full pubsub
// network. Production callers don't need this; the verifier runs
// inside the receive loop automatically.

import (
	"crypto/ed25519"
	"encoding/hex"

	pb "gyza/netd/internal/grpc/proto"

	"github.com/zeebo/blake3"
	"google.golang.org/protobuf/proto"
)

// VerifyForTest unmarshals a wire-format delta and runs the full
// app-layer signature check. Returns true iff the signature is valid
// against the claimed sender pubkey. False on unmarshal errors,
// missing signatures, or signature mismatch.
//
// This is the same code path the receive loop runs; we just expose
// it standalone so tampered-delta tests don't need a live host.
func VerifyForTest(wire []byte) bool {
	d := &pb.BlackboardDelta{}
	if err := proto.Unmarshal(wire, d); err != nil {
		return false
	}
	if len(d.AppSignature) != ed25519.SignatureSize {
		return false
	}
	pubBytes, err := hex.DecodeString(d.SenderCompositorPubkey)
	if err != nil || len(pubBytes) != ed25519.PublicKeySize {
		return false
	}
	sig := d.AppSignature
	d.AppSignature = nil
	preSig, err := proto.MarshalOptions{Deterministic: true}.Marshal(d)
	if err != nil {
		return false
	}
	digest := blake3.Sum256(preSig)
	return ed25519.Verify(ed25519.PublicKey(pubBytes), digest[:], sig)
}
