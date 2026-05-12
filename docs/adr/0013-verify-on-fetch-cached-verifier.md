# ADR-0013: TTL-cached single-flight verify-on-fetch verifier

**Status:** Accepted (Session 15).

## Context

ADR-0009 / 0010 / 0011 / 0012 made it possible to EARN and PUBLISH
a Tier-3 cert. The consumer side still trusted the self-reported
`AgentAdvertisement.attestation_tier` field — anyone could advertise
tier=3 without an actual cert. `find_agents(min_tier=3)` filters
were accepting the lie.

Verify-on-fetch: at routing time, fetch the cert and verify it.
Naively, this is one DHT lookup per candidate ad — slow, expensive,
serializable.

## Decision

Add `netd/internal/dht/verifier.go::DHTAttestationVerifier`.
Wired into `GyzaDHT.FindAgents` when `min_tier >= IssuedTier`.

**Cache semantics:**

| Outcome | Cached? | TTL |
|---|---|---|
| Valid cert | yes, positive | `min(posTTL=5m, cert.expires_at - slack - now)` |
| Cert missing (NotFound) | yes, negative | `negTTL=30s` |
| Cert verify fails (sig/expired) | yes, negative | `negTTL=30s` |
| Cert in slack-window (near-expiry) | yes, negative | `negTTL=30s` |
| Fetch errored (transient) | NO | — |
| Fetch timed out | NO | — |
| Empty pubkey | NO | — (immediate reject) |

**Concurrency controls:**

- **Single-flight per pubkey.** Concurrent `Verify` calls for the
  same compositor pubkey share one DHT fetch. `map[string]*inflightCall`
  with a `done` channel.
- **Bounded global concurrency.** `sem chan struct{}` of capacity
  `MaxInflight = 16` caps total in-flight DHT fetches.
- **Per-fetch deadline.** `FetchTimeout = 250 ms` default. Beyond
  this, the fetch is abandoned (and NOT cached).

**Near-expiry slack window.** `expirySlack = 1 hour`. A cert with
remaining lifetime < 1h is rejected (negative-cached). Provides
routing-horizon stability — a routing decision made now should
still be valid for the request's lifetime.

**Verifier keys by compositor_pubkey, NOT agent_pubkey.** Multiple
agents share one compositor and one cert. Keying by agent would
force redundant fetches.

## Consequences

**Intended:**
- The `attestation_tier` field is now ENFORCED at the routing
  layer for `min_tier >= 3` queries. A Sybil advertising tier=3
  without a cert is dropped.
- Cache amortizes the per-fetch cost; hot routing paths see
  microsecond-scale verification on cache hits.
- Slack window stabilizes routing decisions through their natural
  lifetime.

**Accepted costs:**
- `find_agents` callers that depend on `attestation_tier` for
  non-`min_tier=3` paths still inherit the self-report weakness.
  Documented in CLAUDE.md §3.
- `kaddht.ModeAuto` on loopback meshes never promotes to Server
  mode — AutoNAT can't confirm reachability. Multi-daemon
  integration tests MUST pass `--dht-mode server`. Symptom: cert
  publishes silently disappear on Client-mode daemons. Documented
  in CLAUDE.md §3 + ADR-0015 wiring discussion.
- The transient-failures-NOT-cached asymmetry is load-bearing.
  Don't cache fetch errors / timeouts as negatives — would
  sticky-hide honest tier-3 ads.

## Alternatives considered

- **Synchronous fetch per query, no cache.** Rejected: routing-path
  latency proportional to candidate count.
- **Bypass via separate verify-on-routing method.** Rejected:
  fragments the API; callers would forget to call it.
- **Daemon-side verification only.** Rejected: consumer-side
  re-verify is appropriate for high-stakes paths. Daemon-side is
  the common case.

## References

- `netd/internal/dht/verifier.go` — DHTAttestationVerifier
- `netd/internal/dht/dht.go::FindAgents` — wiring
- `netd/cmd/gyza-netd/main.go::--dht-mode` flag
- `tests/test_verify_on_fetch.py` — Python integration test
- ADR-0014 (recursive Tier-3; layered on top of verify-on-fetch)
- CLAUDE.md §5-pre-3 (Session 15 narrative)
