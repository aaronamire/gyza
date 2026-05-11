// Package dht wires Gyza-flavored Kademlia DHT discovery on top of
// go-libp2p-kad-dht. The DHT carries one record type:
//
//	key:   /gyza/agents/{lsh_bucket_hex}
//	value: protobuf-serialized AgentBucket (a list of AgentAdvertisement)
//
// AgentBuckets are LWW-merged at the DHT layer (latest last_updated_ns
// wins). The publishing path reads the current bucket, merges the
// caller's advertisements per agent_pubkey (LWW on advertisement
// last_seen), and writes it back. Two concurrent publishers to the
// same bucket race — each may read the same prior state and overwrite
// the other's additions; the loser's advertisement is recovered on its
// next re-publish (which the daemon does every ttl/2 seconds).
//
// This is a Phase-3 simplification. Phase 4 should switch to provider
// records (PeerIDs as set members under a bucket key, with stream-pull
// fetch of advertisements from each provider) so concurrent publishers
// can't lose each other's data.
package dht

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"math"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"gyza/netd/internal/capability"
	pb "gyza/netd/internal/grpc/proto"

	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/routing"

	kaddht "github.com/libp2p/go-libp2p-kad-dht"

	record "github.com/libp2p/go-libp2p-record"
	"google.golang.org/protobuf/proto"
)

// LSHBits is the bit-width of the Gyza LSH bucket id. Hamming-radius
// enumeration in this package and the corresponding Python code
// (gyza/demand.py) both assume 64.
const LSHBits = 64

// EmbeddingDim is the specialization-embedding dimensionality. Bound
// to gyza/schema.py's EMBEDDING_DIM = 384.
const EmbeddingDim = 384

// Default Kademlia parameters. BucketSize must match the routing-table
// k-bucket size used by the public DHT we federate with (libp2p
// default is 20). Changing this is a hard fork.
const (
	BucketSize    = 20
	Alpha         = 3
	MaxBucketSize = 1 << 20 // 1 MiB upper bound on a single AgentBucket record
)

// relayDHTKey is the single canonical key under which the global relay
// list is published. All relay-capable Gyza nodes append to this list;
// non-relay nodes read it to seed their AutoRelay candidate pool.
const relayDHTKey = "/gyza/relays"

// RelayDHTKey is the public alias of relayDHTKey for callers outside
// this package who want to put/get the relay record directly via the
// raw DHTService.
func RelayDHTKey() string { return relayDHTKey }

// attestationKeyPrefix is the per-applicant prefix for AttestationCert
// records. Each Tier-3 applicant publishes exactly one cert under
// /gyza/attestations/{applicant_pubkey_hex}.
const attestationKeyPrefix = "/gyza/attestations/"

// AttestationDHTKey returns the canonical DHT key for the cert of the
// given applicant compositor pubkey (hex).
func AttestationDHTKey(applicantPubkeyHex string) string {
	return attestationKeyPrefix + applicantPubkeyHex
}

// AgentDHTKey returns the canonical DHT key for the given LSH bucket.
//
//	"/gyza/agents/{bucket_hex}"  // bucket_hex is 16-char zero-padded hex
//
// The 16-char hex is used identically on the Python side (they both
// agree on the LSH bucket → key mapping).
func AgentDHTKey(bucket uint64) string {
	const hexDigits = "0123456789abcdef"
	out := make([]byte, 0, len("/gyza/agents/")+16)
	out = append(out, "/gyza/agents/"...)
	for shift := 60; shift >= 0; shift -= 4 {
		out = append(out, hexDigits[(bucket>>uint(shift))&0xF])
	}
	return string(out)
}

// gyzaValidator implements libp2p's record.Validator interface so the
// Kademlia DHT will accept and re-store records under the /gyza/...
// namespace.
//
// Validate: confirm the value is a well-formed AgentBucket protobuf
// within the size cap. We do NOT verify per-advertisement signatures
// at this layer — the validator runs in many places (every storing
// peer + every fetching peer) without access to the trust registry.
// Application-level signature verification happens in FindAgents
// before returning to the gRPC caller.
//
// Select: pick the value with the highest last_updated_ns (LWW). Ties
// break on byte-comparison so the choice is deterministic across nodes.
type gyzaValidator struct{}

func (gyzaValidator) Validate(key string, value []byte) error {
	if len(value) > MaxBucketSize {
		return fmt.Errorf("gyza dht record exceeds %d bytes (got %d)", MaxBucketSize, len(value))
	}
	// Different keys under /gyza/ carry different record types. Dispatch
	// by prefix so the validator stays accurate across record types
	// while keeping a single namespace registration.
	switch {
	case len(key) >= len(relayDHTKey) && key[:len(relayDHTKey)] == relayDHTKey:
		var r pb.RelayList
		if err := proto.Unmarshal(value, &r); err != nil {
			return fmt.Errorf("gyza dht record is not RelayList: %w", err)
		}
		return nil
	case len(key) >= len(attestationKeyPrefix) &&
		key[:len(attestationKeyPrefix)] == attestationKeyPrefix:
		var c pb.AttestationCert
		if err := proto.Unmarshal(value, &c); err != nil {
			return fmt.Errorf("gyza dht record is not AttestationCert: %w", err)
		}
		// Cryptographic verification of the cert is intentionally NOT
		// done here. The validator runs in every storing peer in the
		// DHT — it's network-wide, not application-bound — and would
		// need access to a list of legitimate Tier-3 validator keys
		// to do strict checks. We accept any well-formed cert here
		// and let application-level VerifyAttestation gate trust.
		return nil
	default:
		var b pb.AgentBucket
		if err := proto.Unmarshal(value, &b); err != nil {
			return fmt.Errorf("gyza dht record is not AgentBucket: %w", err)
		}
		// Empty buckets are allowed: UnpublishAgent writes an empty
		// bucket back when the removed agent was the sole occupant, and
		// peers should accept that as "this neighborhood is empty for now"
		// rather than ignore the update and keep serving stale entries.
		return nil
	}
}

func (gyzaValidator) Select(key string, values [][]byte) (int, error) {
	if len(values) == 0 {
		return -1, errors.New("gyza dht: select called on empty slice")
	}
	isRelay := len(key) >= len(relayDHTKey) && key[:len(relayDHTKey)] == relayDHTKey
	isAttestation := len(key) >= len(attestationKeyPrefix) &&
		key[:len(attestationKeyPrefix)] == attestationKeyPrefix

	bestIdx := -1
	var bestUpdated int64 = -1
	var bestBytes []byte
	for i, v := range values {
		var lastUpdated int64
		switch {
		case isRelay:
			var r pb.RelayList
			if err := proto.Unmarshal(v, &r); err != nil {
				continue
			}
			lastUpdated = r.LastUpdatedNs
		case isAttestation:
			// For attestations, "newer" is whichever cert was issued
			// most recently. An applicant who re-attests after expiry
			// publishes a fresh cert that wins on issued_at_ns.
			var c pb.AttestationCert
			if err := proto.Unmarshal(v, &c); err != nil || c.Body == nil {
				continue
			}
			lastUpdated = c.Body.IssuedAtNs
		default:
			var b pb.AgentBucket
			if err := proto.Unmarshal(v, &b); err != nil {
				continue
			}
			lastUpdated = b.LastUpdatedNs
		}
		if lastUpdated > bestUpdated ||
			(lastUpdated == bestUpdated && bytes.Compare(v, bestBytes) > 0) {
			bestIdx = i
			bestUpdated = lastUpdated
			bestBytes = v
		}
	}
	if bestIdx < 0 {
		return -1, errors.New("gyza dht: all candidate values were malformed")
	}
	return bestIdx, nil
}

// GyzaDHT bundles the libp2p Kademlia DHT instance with the LSH index
// used for bucket-aware publish/find. Local advertisements are also
// kept in memory so a node can answer FindAgents queries about itself
// without a DHT round-trip.
type GyzaDHT struct {
	host host.Host
	kad  *kaddht.IpfsDHT
	lsh  *LSHIndex

	// verifier filters AgentAdvertisements in FindAgents when the
	// caller asks for min_tier >= IssuedTier. nil means "no
	// verification" — used by older tests; production paths set
	// the default via NewGyzaDHT and tests can override with
	// SetAttestationVerifier. See verifier.go for the contract.
	verifierMu sync.RWMutex
	verifier   AttestationVerifier

	mu          sync.Mutex
	local       map[string]*pb.AgentAdvertisement // agent_pubkey -> ad (own ads)
	localBucket map[string]uint64                 // agent_pubkey -> last published bucket
	lastPutKey  string
	lastPutErr  error

	republishCount atomic.Uint64
}

// NewGyzaDHT constructs the Kademlia DHT, registers the gyza
// validator, and bootstraps the routing table. The caller is
// responsible for ConnectBootstrap-ing the host first if it expects
// to interact with a wider network.
func NewGyzaDHT(ctx context.Context, h host.Host, mode kaddht.ModeOpt) (*GyzaDHT, error) {
	if h == nil {
		return nil, errors.New("nil host")
	}
	idx, err := DefaultLSHIndex()
	if err != nil {
		return nil, fmt.Errorf("lsh: %w", err)
	}

	// Wrap our validator in the public-key validator that the DHT
	// also requires — the public-key namespace is reserved for libp2p
	// internal use, and skipping its registration breaks key lookups.
	validator := record.NamespacedValidator{
		"pk":   record.PublicKeyValidator{},
		"gyza": gyzaValidator{},
	}

	kad, err := kaddht.New(ctx, h,
		kaddht.ProtocolPrefix("/gyza/1.0"),
		kaddht.Mode(mode),
		kaddht.BucketSize(BucketSize),
		kaddht.Validator(validator),
	)
	if err != nil {
		return nil, fmt.Errorf("kaddht.New: %w", err)
	}

	if err := kad.Bootstrap(ctx); err != nil {
		// Bootstrap failure is non-fatal — the DHT is still usable
		// for local-only ops (and may discover peers later via
		// further connect-by-multiaddr calls).
		_ = err
	}

	d := &GyzaDHT{
		host:        h,
		kad:         kad,
		lsh:         idx,
		local:       make(map[string]*pb.AgentAdvertisement),
		localBucket: make(map[string]uint64),
	}
	// Default verifier closes over d.FetchAttestation. We can't
	// reference d before the struct exists; do it after construction
	// so the closure captures the right pointer.
	d.verifier = NewDHTAttestationVerifier(d.FetchAttestation, VerifierConfig{})
	return d, nil
}

// SetAttestationVerifier overrides the cert-verification used by
// FindAgents when min_tier >= IssuedTier. Passing nil disables
// verification — useful for tests that exercise tier-integer filtering
// without publishing real certs. Production callers should leave the
// default constructed by NewGyzaDHT in place.
func (d *GyzaDHT) SetAttestationVerifier(v AttestationVerifier) {
	d.verifierMu.Lock()
	d.verifier = v
	d.verifierMu.Unlock()
}

// attestationVerifier returns the current verifier under read lock —
// the FindAgents hot path uses this to avoid contending with rare
// SetAttestationVerifier calls.
func (d *GyzaDHT) attestationVerifier() AttestationVerifier {
	d.verifierMu.RLock()
	defer d.verifierMu.RUnlock()
	return d.verifier
}

// Close releases the underlying DHT resources. Does not close the host
// — caller owns the host.
func (d *GyzaDHT) Close() error { return d.kad.Close() }

// RoutingTableSize returns the number of peers currently in the local
// Kademlia routing table. Surfaced via NodeService.GetStatus.
func (d *GyzaDHT) RoutingTableSize() int {
	if d == nil || d.kad == nil {
		return 0
	}
	return d.kad.RoutingTable().Size()
}

// PublishAgent advertises the agent on the DHT. Bucket is computed
// from ad.SpecializationEmbedding via the shared LSH. Existing bucket
// contents are read, the caller's ad is upserted (LWW on last_seen
// per agent_pubkey), and the merged bucket is re-published.
//
// last_seen is set to time.Now() if the caller left it zero, so a
// freshly-issued advertisement isn't immediately considered stale.
func (d *GyzaDHT) PublishAgent(ctx context.Context, ad *pb.AgentAdvertisement) (string, error) {
	if ad == nil {
		return "", errors.New("nil advertisement")
	}
	if len(ad.SpecializationEmbedding)%4 != 0 {
		return "", fmt.Errorf("specialization_embedding length %d is not 4-byte-aligned", len(ad.SpecializationEmbedding))
	}
	emb, err := decodeF32LE(ad.SpecializationEmbedding)
	if err != nil {
		return "", err
	}
	if len(emb) != EmbeddingDim {
		return "", fmt.Errorf("specialization_embedding has %d dims, want %d", len(emb), EmbeddingDim)
	}
	bucket := d.lsh.Hash(emb)
	ad.LshBucket = int64(bucket)
	if ad.LastSeen == 0 {
		ad.LastSeen = time.Now().UnixNano()
	}

	d.mu.Lock()
	d.local[ad.AgentPubkey] = ad
	d.localBucket[ad.AgentPubkey] = bucket
	d.mu.Unlock()

	key := AgentDHTKey(bucket)

	// Read-modify-write. Errors on the read are tolerated — a missing
	// bucket simply means we're the first publisher.
	existing, _ := d.kad.GetValue(ctx, key) // err: routing.ErrNotFound is normal
	merged := mergeBucket(existing, ad, bucket)

	value, err := proto.Marshal(merged)
	if err != nil {
		return "", fmt.Errorf("marshal bucket: %w", err)
	}
	// DHT put may fail if the routing table is empty (single-node
	// network) or if no peer accepts the record. We log via the
	// returned key — the caller sees `key` either way, and the
	// advertisement is at least in the local cache. Re-publish loops
	// (every TTL/2 seconds) recover after peers join.
	if err := d.kad.PutValue(ctx, key, value); err != nil {
		// Wrap the error but stash it on the GyzaDHT for observability.
		// We don't fail PublishAgent: a published-but-not-DHT-stored
		// advertisement is still visible to local FindAgents calls and
		// to peers that subsequently fetch it via direct lookup.
		d.recordPutFailure(key, err)
	}
	return key, nil
}

// LastPutFailure returns the most recent DHT put error encountered,
// or nil if the last put succeeded. Surfaced for the gRPC layer's
// error reporting and for diagnostics in the demo output.
func (d *GyzaDHT) LastPutFailure() (string, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.lastPutKey, d.lastPutErr
}

func (d *GyzaDHT) recordPutFailure(key string, err error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.lastPutKey = key
	d.lastPutErr = err
}

// UnpublishAgent removes the agent from local state and rewrites the
// affected DHT bucket without it. We track each local agent's last
// bucket so the rewrite is targeted (not "re-publish every survivor"
// — that left buckets where the unpublished agent was sole occupant
// pointing at stale DHT records).
//
// If the bucket becomes empty after filtering, we write back an empty
// AgentBucket so peers' lookups see the update rather than a TTL-aged
// stale entry. The validator accepts empty buckets for this reason.
//
// Signature verification on the unpublish request is enforced by the
// caller (gRPC service / proof-of-capability layer); this method
// trusts inputs.
func (d *GyzaDHT) UnpublishAgent(ctx context.Context, agentPubkey string) error {
	if agentPubkey == "" {
		return errors.New("empty agent pubkey")
	}

	d.mu.Lock()
	bucket, hadLocal := d.localBucket[agentPubkey]
	delete(d.local, agentPubkey)
	delete(d.localBucket, agentPubkey)
	d.mu.Unlock()

	if !hadLocal {
		// We have no record of having published this agent; nothing
		// to remove from the DHT. Caller may still want this for
		// best-effort propagation; we just no-op.
		return nil
	}

	key := AgentDHTKey(bucket)
	existing, _ := d.kad.GetValue(ctx, key)

	out := &pb.AgentBucket{LshBucket: bucket}
	if len(existing) > 0 {
		var prior pb.AgentBucket
		if err := proto.Unmarshal(existing, &prior); err == nil {
			for _, a := range prior.Advertisements {
				if a.AgentPubkey != agentPubkey {
					out.Advertisements = append(out.Advertisements, a)
				}
			}
		}
	}
	out.LastUpdatedNs = time.Now().UnixNano()

	value, err := proto.Marshal(out)
	if err != nil {
		return fmt.Errorf("marshal post-unpublish bucket: %w", err)
	}
	if err := d.kad.PutValue(ctx, key, value); err != nil {
		// Same lenience as PublishAgent: the local cache is already
		// scrubbed; a put failure means peers will see the
		// unpublication via TTL expiry rather than instantly.
		d.recordPutFailure(key, err)
	}
	return nil
}

// FindAgents searches the DHT for agents matching the query embedding.
// Iterates Hamming neighbors of the query bucket up to radius=2,
// collects all advertisements, filters by tier/reputation, scores by
// cosine similarity to the query, returns top-k.
//
// LocalOnly mode (host.Host == nil or DHT-disconnected) returns
// matches from the local ad cache only — useful for unit testing the
// match/score path without spinning up libp2p.
func (d *GyzaDHT) FindAgents(
	ctx context.Context,
	queryEmbedding []float32,
	k int,
	minTier int32,
	minReputation float64,
) ([]*pb.AgentAdvertisement, error) {
	if len(queryEmbedding) != EmbeddingDim {
		return nil, fmt.Errorf("query embedding has %d dims, want %d",
			len(queryEmbedding), EmbeddingDim)
	}
	if k <= 0 {
		k = BucketSize
	}

	bucket := d.lsh.Hash(queryEmbedding)
	neighbors := HammingNeighbors(bucket, 2)

	type scored struct {
		ad    *pb.AgentAdvertisement
		score float64
	}
	candidates := make([]scored, 0, len(neighbors)*4)
	seen := make(map[string]struct{}) // dedupe by agent_pubkey across buckets

	consume := func(advs []*pb.AgentAdvertisement) {
		for _, a := range advs {
			if a == nil {
				continue
			}
			if a.AttestationTier < minTier {
				continue
			}
			if a.ReputationScore < minReputation {
				continue
			}
			if _, dup := seen[a.AgentPubkey]; dup {
				continue
			}
			seen[a.AgentPubkey] = struct{}{}

			emb, err := decodeF32LE(a.SpecializationEmbedding)
			if err != nil || len(emb) != EmbeddingDim {
				continue
			}
			s := cosine(queryEmbedding, emb)
			candidates = append(candidates, scored{ad: a, score: s})
		}
	}

	// Local advertisements first — cheapest, no network.
	d.mu.Lock()
	localAds := make([]*pb.AgentAdvertisement, 0, len(d.local))
	for _, a := range d.local {
		localAds = append(localAds, a)
	}
	d.mu.Unlock()
	consume(localAds)

	// DHT lookups for neighbor buckets.
	for _, nb := range neighbors {
		key := AgentDHTKey(nb)
		val, err := d.kad.GetValue(ctx, key)
		if err != nil {
			// Most common: routing.ErrNotFound — bucket has no record.
			// Anything else is a transient routing failure; not fatal.
			if !errors.Is(err, routing.ErrNotFound) {
				_ = err
			}
			continue
		}
		var b pb.AgentBucket
		if err := proto.Unmarshal(val, &b); err != nil {
			continue
		}
		consume(b.Advertisements)
	}

	sort.Slice(candidates, func(i, j int) bool {
		return candidates[i].score > candidates[j].score
	})

	// Verify-on-fetch (#21f). When the caller demands min_tier >=
	// IssuedTier, the AttestationTier integer alone is a self-reported
	// claim — a Sybil node can advertise tier=3 without owning a cert.
	// Filter candidates against the AttestationVerifier so only ads
	// whose compositor has a fetchable, valid Tier-3 cert survive.
	// The verifier handles caching, bounded concurrency, and per-fetch
	// timeouts internally.
	//
	// We apply this AFTER scoring so the verifier sees candidates
	// pre-sorted: if the verifier ever gets slow enough that we want
	// to short-circuit after collecting k verified results, the
	// highest-scoring ads are tried first. Today the verifier is
	// cheap on cache hits so we just verify everything.
	if minTier >= int32(capability.IssuedTier) {
		if vfr := d.attestationVerifier(); vfr != nil {
			verified := make([]scored, 0, len(candidates))
			for _, c := range candidates {
				if vfr.Verify(ctx, c.ad.CompositorPubkey) {
					verified = append(verified, c)
				}
			}
			candidates = verified
		}
	}

	if len(candidates) > k {
		candidates = candidates[:k]
	}
	out := make([]*pb.AgentAdvertisement, len(candidates))
	for i, c := range candidates {
		out[i] = c.ad
	}
	return out, nil
}

// LocalAgents returns a snapshot of all advertisements this node has
// published locally. Useful for re-publish loops and the gRPC
// observability surface.
func (d *GyzaDHT) LocalAgents() []*pb.AgentAdvertisement {
	d.mu.Lock()
	defer d.mu.Unlock()
	out := make([]*pb.AgentAdvertisement, 0, len(d.local))
	for _, a := range d.local {
		out = append(out, a)
	}
	return out
}

// StartRepublishLoop spawns a goroutine that re-publishes every local
// advertisement on each `interval` tick. Without this, advertisements
// expire from the DHT after their TTL and the node disappears from
// FindAgents results until something triggers a fresh PublishAgent.
//
// interval should be ≤ TTL/2 in steady state. Default deployment uses
// TTL=3600s and interval=1800s. Pass interval ≤ 0 to disable (useful in
// unit tests that only want the local-cache path).
//
// The goroutine exits when ctx is cancelled. There's no Stop method —
// caller cancels the context they passed to NewGyzaDHT.
func (d *GyzaDHT) StartRepublishLoop(ctx context.Context, interval time.Duration) {
	if d == nil || interval <= 0 {
		return
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				d.republishAll(ctx)
			}
		}
	}()
}

// republishAll snapshots the local ad map and re-publishes each one.
// Bumps last_seen so freshness logic on the receiving side resets the
// clock — without this, a stale-but-still-cached ad would re-enter the
// DHT looking just as old as it was.
func (d *GyzaDHT) republishAll(ctx context.Context) {
	d.mu.Lock()
	ads := make([]*pb.AgentAdvertisement, 0, len(d.local))
	for _, a := range d.local {
		ads = append(ads, a)
	}
	d.mu.Unlock()

	now := time.Now().UnixNano()
	for _, ad := range ads {
		ad.LastSeen = now
		_, _ = d.PublishAgent(ctx, ad)
	}
	d.republishCount.Add(1)
}

// RepublishCount returns the number of completed republish ticks since
// StartRepublishLoop was called. Surfaced for tests and diagnostics.
func (d *GyzaDHT) RepublishCount() uint64 {
	if d == nil {
		return 0
	}
	return d.republishCount.Load()
}

// PublishRelay merges this node's relay entry into the global
// /gyza/relays record and re-publishes it. Same read-modify-write
// pattern as PublishAgent: read the current relay list (LWW-validated),
// upsert by peer_id, write back.
//
// staleAfter sets how long an entry is considered fresh for; entries
// past their freshness window are dropped on read in FindRelays.
// Pass 0 for no staleness pruning.
func (d *GyzaDHT) PublishRelay(
	ctx context.Context,
	entry *pb.RelayEntry,
	staleAfter time.Duration,
) error {
	if entry == nil || entry.PeerId == "" {
		return errors.New("relay entry must have peer_id")
	}
	if entry.LastSeen == 0 {
		entry.LastSeen = time.Now().UnixNano()
	}

	existing, _ := d.kad.GetValue(ctx, relayDHTKey)
	merged := mergeRelayList(existing, entry, staleAfter)

	value, err := proto.Marshal(merged)
	if err != nil {
		return fmt.Errorf("marshal relay list: %w", err)
	}
	if err := d.kad.PutValue(ctx, relayDHTKey, value); err != nil {
		d.recordPutFailure(relayDHTKey, err)
		// Same lenience as PublishAgent: a single-node net can't put,
		// but we want callers to see the merged list locally — the
		// next peer that comes online will pick it up via republish.
	}
	return nil
}

// FindRelays returns up to `num` known relays from the global
// /gyza/relays record. Entries past their freshness window
// (now - last_seen > staleAfter) are filtered out — staleAfter=0
// disables filtering.
//
// Returned in original order (no scoring); caller can shuffle if random
// selection is desired.
func (d *GyzaDHT) FindRelays(
	ctx context.Context,
	num int,
	staleAfter time.Duration,
) ([]*pb.RelayEntry, error) {
	if num <= 0 {
		num = BucketSize
	}
	val, err := d.kad.GetValue(ctx, relayDHTKey)
	if err != nil && !errors.Is(err, routing.ErrNotFound) {
		return nil, err
	}
	if len(val) == 0 {
		return nil, nil
	}
	var list pb.RelayList
	if err := proto.Unmarshal(val, &list); err != nil {
		return nil, fmt.Errorf("unmarshal relay list: %w", err)
	}
	cutoff := int64(0)
	if staleAfter > 0 {
		cutoff = time.Now().Add(-staleAfter).UnixNano()
	}
	out := make([]*pb.RelayEntry, 0, len(list.Entries))
	for _, e := range list.Entries {
		if cutoff > 0 && e.LastSeen < cutoff {
			continue
		}
		out = append(out, e)
		if len(out) >= num {
			break
		}
	}
	return out, nil
}

// mergeRelayList merges an incoming relay entry into a previously-stored
// RelayList. LWW per peer_id (newer last_seen wins), and entries older
// than staleAfter are pruned.
func mergeRelayList(existing []byte, entry *pb.RelayEntry, staleAfter time.Duration) *pb.RelayList {
	out := &pb.RelayList{}
	if len(existing) > 0 {
		var prior pb.RelayList
		if err := proto.Unmarshal(existing, &prior); err == nil {
			out.Entries = append(out.Entries, prior.Entries...)
		}
	}
	cutoff := int64(0)
	if staleAfter > 0 {
		cutoff = time.Now().Add(-staleAfter).UnixNano()
	}

	replaced := false
	keep := out.Entries[:0]
	for _, e := range out.Entries {
		if cutoff > 0 && e.LastSeen < cutoff {
			continue
		}
		if e.PeerId == entry.PeerId {
			if entry.LastSeen >= e.LastSeen {
				keep = append(keep, entry)
			} else {
				keep = append(keep, e)
			}
			replaced = true
		} else {
			keep = append(keep, e)
		}
	}
	out.Entries = keep
	if !replaced {
		out.Entries = append(out.Entries, entry)
	}
	out.LastUpdatedNs = time.Now().UnixNano()
	return out
}

// PublishAttestation stores the given AttestationCert at
// /gyza/attestations/{applicant_pubkey}. The cert overrides any prior
// cert for the same applicant via the validator's LWW-on-issued_at_ns.
//
// The DHT-side check is well-formedness-only — application code must
// run capability.VerifyAttestation before trusting the cert content.
// We deliberately don't check sig validity here so the same Put path
// works in tests that exercise malformed-cert handling.
func (d *GyzaDHT) PublishAttestation(
	ctx context.Context,
	cert *pb.AttestationCert,
) (string, error) {
	if cert == nil || cert.Body == nil {
		return "", errors.New("nil cert / cert.body")
	}
	if cert.Body.ApplicantPubkey == "" {
		return "", errors.New("applicant_pubkey required")
	}
	value, err := proto.Marshal(cert)
	if err != nil {
		return "", fmt.Errorf("marshal cert: %w", err)
	}
	if len(value) > MaxBucketSize {
		return "", fmt.Errorf("attestation cert exceeds %d bytes (got %d)",
			MaxBucketSize, len(value))
	}
	key := AttestationDHTKey(cert.Body.ApplicantPubkey)
	if err := d.kad.PutValue(ctx, key, value); err != nil {
		d.recordPutFailure(key, err)
	}
	return key, nil
}

// FetchAttestation returns the AttestationCert published under the
// given applicant pubkey, or nil + nil error if no cert exists.
//
// Returning nil-cert-no-error for "not found" is intentional —
// querying the cert is a routine Tier-3 ad-validation step and a
// missing cert is a normal outcome (not all advertisers have
// attested). Distinguish "no cert" from "DHT failure" by the error.
func (d *GyzaDHT) FetchAttestation(
	ctx context.Context,
	applicantPubkeyHex string,
) (*pb.AttestationCert, error) {
	if applicantPubkeyHex == "" {
		return nil, errors.New("applicant_pubkey required")
	}
	key := AttestationDHTKey(applicantPubkeyHex)
	value, err := d.kad.GetValue(ctx, key)
	if err != nil {
		if errors.Is(err, routing.ErrNotFound) {
			return nil, nil
		}
		return nil, err
	}
	if len(value) == 0 {
		return nil, nil
	}
	cert := &pb.AttestationCert{}
	if err := proto.Unmarshal(value, cert); err != nil {
		return nil, fmt.Errorf("unmarshal cert: %w", err)
	}
	return cert, nil
}

// =============================================================================
// helpers
// =============================================================================

// mergeBucket parses a prior bucket value (may be nil/empty), upserts
// `ad` by agent_pubkey using LWW on last_seen, and stamps the bucket's
// last_updated_ns with `now`.
func mergeBucket(existingValue []byte, ad *pb.AgentAdvertisement, bucket uint64) *pb.AgentBucket {
	out := &pb.AgentBucket{
		LshBucket: bucket,
	}
	if len(existingValue) > 0 {
		var prior pb.AgentBucket
		if err := proto.Unmarshal(existingValue, &prior); err == nil {
			out.Advertisements = append(out.Advertisements, prior.Advertisements...)
		}
	}

	replaced := false
	for i, e := range out.Advertisements {
		if e.AgentPubkey == ad.AgentPubkey {
			// LWW per agent: keep the newer entry.
			if ad.LastSeen >= e.LastSeen {
				out.Advertisements[i] = ad
			}
			replaced = true
			break
		}
	}
	if !replaced {
		out.Advertisements = append(out.Advertisements, ad)
	}

	out.LastUpdatedNs = time.Now().UnixNano()
	return out
}

// decodeF32LE reads a sequence of 4-byte little-endian float32 values
// out of a wire-format embedding, matching the Python side's encoding
// (np.ndarray.astype('<f4').tobytes()).
func decodeF32LE(b []byte) ([]float32, error) {
	if len(b)%4 != 0 {
		return nil, fmt.Errorf("byte length %d not multiple of 4", len(b))
	}
	n := len(b) / 4
	out := make([]float32, n)
	for i := 0; i < n; i++ {
		bits := uint32(b[i*4]) |
			uint32(b[i*4+1])<<8 |
			uint32(b[i*4+2])<<16 |
			uint32(b[i*4+3])<<24
		out[i] = math.Float32frombits(bits)
	}
	return out, nil
}

// DecodeF32LEAvailable is the exported alias of decodeF32LE so the
// gRPC layer (different package) can validate embeddings on the wire
// without re-implementing the same parser.
func DecodeF32LEAvailable(b []byte) ([]float32, error) { return decodeF32LE(b) }

// EncodeF32LE is the inverse of decodeF32LE — exposed for callers that
// build advertisements in Go.
func EncodeF32LE(v []float32) []byte {
	out := make([]byte, len(v)*4)
	for i, f := range v {
		bits := math.Float32bits(f)
		out[i*4] = byte(bits)
		out[i*4+1] = byte(bits >> 8)
		out[i*4+2] = byte(bits >> 16)
		out[i*4+3] = byte(bits >> 24)
	}
	return out
}

func cosine(a, b []float32) float64 {
	if len(a) != len(b) {
		return 0
	}
	var dot, na, nb float64
	for i := range a {
		af, bf := float64(a[i]), float64(b[i])
		dot += af * bf
		na += af * af
		nb += bf * bf
	}
	if na == 0 || nb == 0 {
		return 0
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}
