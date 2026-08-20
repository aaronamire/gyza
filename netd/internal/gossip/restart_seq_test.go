package gossip_test

// A NODE THAT RESTARTS MUST NOT BE SILENCED TO ITS EXISTING PEERS.
//
// FIXED 2026-08-20 by seeding Manager.seqBase from the wall clock. This test
// demonstrated the defect first and now guards the fix.
//
// sender_seq is assigned by Manager.nextSeq from `publishSeq`, a map created
// fresh in NewManager and persisted NOWHERE. Receivers drop any delta whose
// seq is <= the highest already seen from that sender for that project
// (gossip.go:465).
//
// So a daemon that restarts — a deploy, a crash, an autoscale event — resumes
// at seq=1 while its peers still remember its old high-water mark, and every
// message it publishes is dropped until the counter climbs back past it. A
// long-lived node that restarts is effectively muted.
//
// This is invisible on the existing 2-node loopback tests because both
// managers are constructed once per test and never restarted.

import (
	"context"
	"testing"
	"time"

	"gyza/netd/internal/gossip"
	pb "gyza/netd/internal/grpc/proto"
)

func TestRestartedSenderIsSilencedByStaleDedupState(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()

	const project = "restart-seq-test"

	idA := makeIdentity(t)
	hA, closeA := hostFor(t, idA)

	idB := makeIdentity(t)
	hB, closeB := hostFor(t, idB)
	defer closeB()

	mgrB, err := gossip.NewManager(ctx, hB, idB, t.Logf)
	if err != nil {
		t.Fatalf("mgrB: %v", err)
	}
	defer mgrB.Close()

	mgrA, err := gossip.NewManager(ctx, hA, idA, t.Logf)
	if err != nil {
		t.Fatalf("mgrA: %v", err)
	}

	connect(t, ctx, hA, hB)
	if _, err := mgrA.JoinProject(ctx, project); err != nil {
		t.Fatalf("A.JoinProject: %v", err)
	}
	if _, err := mgrB.JoinProject(ctx, project); err != nil {
		t.Fatalf("B.JoinProject: %v", err)
	}
	chB, cancelB := mgrB.Subscribe([]string{project})
	defer cancelB()
	time.Sleep(1500 * time.Millisecond)

	mk := func(id string) *pb.BlackboardDelta {
		return &pb.BlackboardDelta{
			ProjectId: project,
			NewIntents: []*pb.IntentRecord{{
				IntentId:     id,
				GoalSpecJson: `{}`,
				CreatedAtNs:  time.Now().UnixNano(),
			}},
		}
	}

	// A publishes three deltas pre-restart; B accepts them and its dedup
	// high-water mark for A rises to 3.
	var highWater int64
	for i := 1; i <= 3; i++ {
		seq, err := mgrA.PublishDelta(ctx, mk("pre"))
		if err != nil {
			t.Fatalf("publish %d: %v", i, err)
		}
		got := drainOne(t, chB, 4*time.Second)
		if got.SenderSeq != seq {
			t.Fatalf("B got seq %d, want %d", got.SenderSeq, seq)
		}
		highWater = seq
	}
	t.Logf("pre-restart: B accepted 3 deltas from A, high-water seq=%d", highWater)

	// RESTART A PROPERLY: tear down the Manager AND the libp2p host, then
	// rebuild both from the SAME identity. Reusing the host is not a restart --
	// a pubsub router registers stream handlers on its host, so a second
	// GossipSub on a live host does not behave like a fresh daemon and the
	// test would measure the harness rather than the system.
	mgrA.Close()
	closeA()
	hA2, closeA2 := hostFor(t, idA)
	defer closeA2()
	mgrA2, err := gossip.NewManager(ctx, hA2, idA, t.Logf)
	if err != nil {
		t.Fatalf("mgrA2: %v", err)
	}
	defer mgrA2.Close()
	connect(t, ctx, hA2, hB)
	if _, err := mgrA2.JoinProject(ctx, project); err != nil {
		t.Fatalf("A2.JoinProject: %v", err)
	}
	time.Sleep(15 * time.Second) // mesh re-GRAFT: CLAUDE.md records 10-15s on 2-node loopback; 2.5s is inside the known-flaky window and confounds this test

	seq, err := mgrA2.PublishDelta(ctx, mk("post-restart"))
	if err != nil {
		t.Fatalf("post-restart publish: %v", err)
	}
	t.Logf("post-restart: A published seq=%d", seq)

	// THE FIX: seqBase is seeded from the wall clock, so a restarted sender
	// resumes ABOVE its previous high-water mark and its peers keep accepting.
	// Before this, seq reset to 1, B still remembered 3, and every message was
	// silently dropped -- a long-lived node was muted by restarting.
	select {
	case d := <-chB:
		if d.SenderSeq <= highWater {
			t.Errorf("restarted sender used seq=%d, <= the pre-restart high-water "+
				"mark %d; peers would drop it", d.SenderSeq, highWater)
		}
		t.Logf("B accepted the post-restart delta (seq=%d > pre-restart %d)",
			d.SenderSeq, highWater)
	case <-time.After(8 * time.Second):
		t.Fatalf("REGRESSION: B dropped the restarted sender's delta. sender_seq " +
			"is no longer monotonic across restarts, so a node that restarts is " +
			"silently muted to every peer that remembers its old seq.")
	}
}

// A LEAVE/REJOIN OF THE SAME PROJECT MUST NOT RESET THE SENDER'S SEQUENCE.
//
// This guards the fix that was ALMOST made for the publishSeq leak. That
// counter was map[project_id]int64 and LeaveProject never deleted it, so it
// grew per project ever published to. The obvious cleanup -- delete the entry
// on leave -- reintroduces this test's failure exactly: seqBase is fixed for
// the process, so the rejoin restarts at seqBase+1, below the seqBase+N that
// peers still hold, and every delta after the rejoin is dropped. Same muting
// as a restart, from a leave. The counter is now global and per-project state
// is gone rather than managed.
func TestSendSeqIsMonotoneAcrossProjectRejoin(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	const project = "rejoin-seq-test"

	id := makeIdentity(t)
	h, closeH := hostFor(t, id)
	defer closeH()

	mgr, err := gossip.NewManager(ctx, h, id, t.Logf)
	if err != nil {
		t.Fatalf("NewManager: %v", err)
	}
	defer mgr.Close()

	mk := func() *pb.BlackboardDelta {
		return &pb.BlackboardDelta{
			ProjectId: project,
			NewIntents: []*pb.IntentRecord{{
				IntentId:     "rejoin",
				GoalSpecJson: `{}`,
				CreatedAtNs:  time.Now().UnixNano(),
			}},
		}
	}

	if _, err := mgr.JoinProject(ctx, project); err != nil {
		t.Fatalf("JoinProject: %v", err)
	}
	var before int64
	for i := 0; i < 3; i++ {
		if before, err = mgr.PublishDelta(ctx, mk()); err != nil {
			t.Fatalf("publish before leave: %v", err)
		}
	}

	if err := mgr.LeaveProject(project); err != nil {
		t.Fatalf("LeaveProject: %v", err)
	}
	if _, err := mgr.JoinProject(ctx, project); err != nil {
		t.Fatalf("rejoin: %v", err)
	}

	after, err := mgr.PublishDelta(ctx, mk())
	if err != nil {
		t.Fatalf("publish after rejoin: %v", err)
	}
	if after <= before {
		t.Fatalf("SEQ REGRESSED ACROSS REJOIN: %d before leave, %d after rejoin. "+
			"Every peer holding %d will drop this delta and the node is muted "+
			"on this project.", before, after, before)
	}
	t.Logf("rejoin monotone: %d before leave, %d after", before, after)
}
