package gossip

// DEDUP STATE MUST BE BOUNDED, AND BOUNDING IT MUST NOT UNMUTE A REPLAY.
//
// Two maps grew without a ceiling before 2026-08-20:
//
//   - topicState.lastSeen — one entry per DISTINCT SENDER ever seen on a
//     topic, freed only when the topic was left. A long-lived topic in a large
//     mesh grows with the population, not with the working set.
//   - Manager.publishSeq — was map[project_id]int64, and LeaveProject deleted
//     m.topics without deleting it. It is now a single atomic counter, so
//     there is no per-project state left to leak.
//
// The interesting part is that the OBVIOUS fix for the second one was wrong:
// deleting the per-project counter on leave restarts it at seqBase+1, below
// the seqBase+N peers already remember, which is precisely the muting
// TestRestartedSenderIsSilencedByStaleDedupState exists to prevent. These
// tests pin the bound AND the property the bound must not break.

import (
	"fmt"
	"testing"
	"time"

	pb "gyza/netd/internal/grpc/proto"
)

func withRetention(t *testing.T, retention, sweep time.Duration) {
	t.Helper()
	oldR, oldS := dedupRetention, dedupSweepEvery
	dedupRetention, dedupSweepEvery = retention, sweep
	t.Cleanup(func() { dedupRetention, dedupSweepEvery = oldR, oldS })
}

func delta(sender string, seq int64) *pb.BlackboardDelta {
	return &pb.BlackboardDelta{SenderCompositorPubkey: sender, SenderSeq: seq}
}

// A sender that has gone quiet past the retention window is evicted, so
// lastSeen tracks the ACTIVE population rather than the cumulative one.
func TestIdleSendersAreEvictedFromDedupState(t *testing.T) {
	withRetention(t, 30*time.Minute, 0) // sweep on every call

	m := &Manager{}
	st := &topicState{lastSeen: make(map[string]seqEntry)}

	stale := time.Now().Add(-2 * time.Hour)
	for i := 0; i < 1000; i++ {
		st.lastSeen[fmt.Sprintf("idle-%d", i)] = seqEntry{seq: 7, at: stale}
	}

	if !m.checkAndUpdateSeq(st, delta("live", 1)) {
		t.Fatal("first delta from a new sender must be accepted")
	}
	if got := len(st.lastSeen); got != 1 {
		t.Fatalf("lastSeen = %d entries after sweep, want 1 (only the live sender)", got)
	}
}

// Eviction must be driven by IDLENESS, not by map pressure: a sender that is
// still publishing keeps its high-water mark, and its replays keep losing.
func TestActiveSenderKeepsItsHighWaterMarkAcrossSweeps(t *testing.T) {
	withRetention(t, 30*time.Minute, 0)

	m := &Manager{}
	st := &topicState{lastSeen: make(map[string]seqEntry)}

	if !m.checkAndUpdateSeq(st, delta("active", 100)) {
		t.Fatal("seq 100 must be accepted")
	}
	// Thousands of one-shot senders churn through, each triggering a sweep.
	for i := 0; i < 2000; i++ {
		m.checkAndUpdateSeq(st, delta(fmt.Sprintf("churn-%d", i), 1))
	}
	if m.checkAndUpdateSeq(st, delta("active", 100)) {
		t.Fatal("REPLAY ACCEPTED: an active sender's high-water mark was swept")
	}
	if m.checkAndUpdateSeq(st, delta("active", 99)) {
		t.Fatal("REPLAY ACCEPTED: a lower seq from an active sender was swept")
	}
	if !m.checkAndUpdateSeq(st, delta("active", 101)) {
		t.Fatal("a genuinely newer delta must still be accepted")
	}
}

// The eviction window is a real cost, not a hidden one: once a sender is
// evicted, its old delta IS accepted again. This test asserts the cost so it
// is documented by a failing test if anyone changes the tradeoff silently.
func TestEvictionReopensTheReplayWindowForThatSender(t *testing.T) {
	withRetention(t, time.Nanosecond, 0)

	m := &Manager{}
	st := &topicState{lastSeen: make(map[string]seqEntry)}

	if !m.checkAndUpdateSeq(st, delta("gone", 500)) {
		t.Fatal("seq 500 must be accepted")
	}
	time.Sleep(2 * time.Millisecond) // exceed the 1ns retention
	if !m.checkAndUpdateSeq(st, delta("gone", 1)) {
		t.Fatal("expected the replay to be accepted after eviction; if this " +
			"now fails the retention semantics changed and the comment in " +
			"gossip.go about the replay window needs rewriting")
	}
}

// One counter serves every project. Interleaved publishes skip values on any
// single topic, which the `seq <= last` dedup does not read, but the sequence
// each receiver observes is still strictly increasing.
func TestGlobalCounterIsStrictlyIncreasingPerTopic(t *testing.T) {
	m := &Manager{seqBase: 0}
	st := &topicState{lastSeen: make(map[string]seqEntry)}

	var lastA int64
	for i := 0; i < 50; i++ {
		a := m.nextSeq() // project A
		_ = m.nextSeq()  // project B, interleaved
		if a <= lastA {
			t.Fatalf("seq on project A not increasing: %d after %d", a, lastA)
		}
		lastA = a
		if !m.checkAndUpdateSeq(st, delta("self", a)) {
			t.Fatalf("receiver rejected own increasing seq %d", a)
		}
	}
}
