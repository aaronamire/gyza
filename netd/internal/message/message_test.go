package message_test

// MessageManager exercise: frame encoding round-trip, two-host
// send/receive, broadcast fan-out, oversized-frame rejection.
//
// We use real libp2p hosts on loopback. No mocks — the entire point
// of this layer is the libp2p stream protocol.

import (
	"bytes"
	"context"
	"crypto/rand"
	"strings"
	"testing"
	"time"

	"gyza/netd/internal/message"

	libp2p "github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"
)

// hostFor spins up a loopback libp2p host with a fresh Ed25519 key.
func hostFor(t *testing.T) (host.Host, func()) {
	t.Helper()
	priv, _, err := crypto.GenerateEd25519Key(rand.Reader)
	if err != nil {
		t.Fatalf("genkey: %v", err)
	}
	h, err := libp2p.New(
		libp2p.Identity(priv),
		libp2p.ListenAddrStrings("/ip4/127.0.0.1/udp/0/quic-v1"),
		libp2p.Transport(libp2pquic.NewTransport),
	)
	if err != nil {
		t.Fatalf("libp2p.New: %v", err)
	}
	return h, func() { _ = h.Close() }
}

func connect(t *testing.T, ctx context.Context, a, b host.Host) {
	t.Helper()
	if err := a.Connect(ctx, peer.AddrInfo{ID: b.ID(), Addrs: b.Addrs()}); err != nil {
		t.Fatalf("connect: %v", err)
	}
}

// TestSendAndSubscribe — end-to-end round-trip. A sends one message;
// B's subscriber receives it with the right type, payload, and
// sender PeerID.
func TestSendAndSubscribe(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	hA, closeA := hostFor(t)
	defer closeA()
	hB, closeB := hostFor(t)
	defer closeB()
	mgrA := message.NewManager(hA, t.Logf)
	defer mgrA.Close()
	mgrB := message.NewManager(hB, t.Logf)
	defer mgrB.Close()

	connect(t, ctx, hA, hB)

	chB, cancelB := mgrB.Subscribe([]string{"ledger.test"})
	defer cancelB()

	payload := []byte("the rain in spain falls mainly on the plain")
	if err := mgrA.Send(ctx, hB.ID(), "ledger.test", payload); err != nil {
		t.Fatalf("Send: %v", err)
	}

	select {
	case msg := <-chB:
		if msg.MessageType != "ledger.test" {
			t.Errorf("type = %q, want ledger.test", msg.MessageType)
		}
		if !bytes.Equal(msg.Payload, payload) {
			t.Errorf("payload mismatch: %q vs %q", msg.Payload, payload)
		}
		if msg.SenderPeerId != hA.ID().String() {
			t.Errorf("sender = %q, want %q", msg.SenderPeerId, hA.ID())
		}
		if msg.SenderPubkey == "" {
			t.Errorf("SenderPubkey not extracted from PeerID")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("subscriber did not receive message within 3s")
	}
}

// TestSubscribeFilter — a subscriber whose filter excludes the
// incoming type doesn't receive it. A subscriber with empty filter
// receives everything.
func TestSubscribeFilter(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	hA, closeA := hostFor(t)
	defer closeA()
	hB, closeB := hostFor(t)
	defer closeB()
	mgrA := message.NewManager(hA, t.Logf)
	defer mgrA.Close()
	mgrB := message.NewManager(hB, t.Logf)
	defer mgrB.Close()
	connect(t, ctx, hA, hB)

	filtered, cancelFiltered := mgrB.Subscribe([]string{"only.this"})
	defer cancelFiltered()
	allCh, cancelAll := mgrB.Subscribe(nil)
	defer cancelAll()

	if err := mgrA.Send(ctx, hB.ID(), "different.type", []byte("hello")); err != nil {
		t.Fatalf("Send: %v", err)
	}

	// Filtered: must receive nothing within 200ms.
	select {
	case got := <-filtered:
		t.Fatalf("filter leaked: got %+v", got)
	case <-time.After(200 * time.Millisecond):
	}

	// All: must have received it.
	select {
	case got := <-allCh:
		if got.MessageType != "different.type" {
			t.Errorf("got %q, want different.type", got.MessageType)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("unfiltered subscriber missed message")
	}
}

// TestSendRejectsSelf — sending to our own PeerID is a programming
// error and must fail loudly.
func TestSendRejectsSelf(t *testing.T) {
	ctx := context.Background()
	h, closeH := hostFor(t)
	defer closeH()
	mgr := message.NewManager(h, t.Logf)
	defer mgr.Close()
	if err := mgr.Send(ctx, h.ID(), "x", []byte("y")); err == nil {
		t.Fatal("Send to self should fail")
	}
}

// TestBroadcastFanout — A connects to B and C, broadcasts, both
// receive. Excluding B excludes B.
func TestBroadcastFanout(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	hA, closeA := hostFor(t)
	defer closeA()
	hB, closeB := hostFor(t)
	defer closeB()
	hC, closeC := hostFor(t)
	defer closeC()

	mgrA := message.NewManager(hA, t.Logf)
	defer mgrA.Close()
	mgrB := message.NewManager(hB, t.Logf)
	defer mgrB.Close()
	mgrC := message.NewManager(hC, t.Logf)
	defer mgrC.Close()
	connect(t, ctx, hA, hB)
	connect(t, ctx, hA, hC)

	chB, cancelB := mgrB.Subscribe(nil)
	defer cancelB()
	chC, cancelC := mgrC.Subscribe(nil)
	defer cancelC()

	delivered := mgrA.Broadcast(ctx, "broadcast.test", []byte("hi"), nil)
	if delivered != 2 {
		t.Errorf("delivered = %d, want 2", delivered)
	}

	gotB := false
	gotC := false
	deadline := time.After(3 * time.Second)
	for !(gotB && gotC) {
		select {
		case <-chB:
			gotB = true
		case <-chC:
			gotC = true
		case <-deadline:
			t.Fatalf("timed out (gotB=%v gotC=%v)", gotB, gotC)
		}
	}

	// Now exclude C — only B receives.
	delivered = mgrA.Broadcast(ctx, "broadcast.test", []byte("again"),
		[]peer.ID{hC.ID()})
	if delivered != 1 {
		t.Errorf("excluded broadcast: delivered = %d, want 1", delivered)
	}
}

// TestOversizedPayloadRejected — Send refuses payloads larger than
// MaxPayloadLen and the receiver enforces the same cap.
func TestOversizedPayloadRejected(t *testing.T) {
	ctx := context.Background()
	hA, closeA := hostFor(t)
	defer closeA()
	hB, closeB := hostFor(t)
	defer closeB()
	mgrA := message.NewManager(hA, t.Logf)
	defer mgrA.Close()
	_ = message.NewManager(hB, t.Logf)
	connect(t, ctx, hA, hB)

	huge := make([]byte, message.MaxPayloadLen+1)
	err := mgrA.Send(ctx, hB.ID(), "oversized", huge)
	if err == nil {
		t.Fatal("Send accepted oversized payload")
	}
	if !strings.Contains(err.Error(), "too large") {
		t.Errorf("unexpected error: %v", err)
	}
}

// TestCloseStopsSubscribers — Close on the manager closes all
// subscriber channels so SubscribeMessages handlers exit cleanly.
func TestCloseStopsSubscribers(t *testing.T) {
	h, closeH := hostFor(t)
	defer closeH()
	mgr := message.NewManager(h, t.Logf)
	ch, _ := mgr.Subscribe(nil)
	mgr.Close()
	select {
	case _, ok := <-ch:
		if ok {
			t.Fatal("got value on closed channel")
		}
	case <-time.After(time.Second):
		t.Fatal("channel not closed within 1s")
	}
}
