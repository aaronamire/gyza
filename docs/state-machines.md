# Gyza protocol state machines

> **Purpose.** Pre-spec artifact for §C1. Box-and-arrow state machines
> for the major protocol components. Each transition labeled with
> the trigger (event or guard) and the invariants it preserves
> (cross-referenced to `docs/invariants.md`). The TLA+ spec will
> formalize these as `Next` relations over state predicates.
>
> **Conventions.**
> - `S → S'` denotes a transition from state S to S' under some
>   trigger.
> - `[guard]` denotes a precondition. The transition fires only if
>   the guard holds.
> - `INV-X-N` references an entry in `docs/invariants.md`.
> - Terminal states (no outgoing transitions) end in `_FINAL` or
>   are marked with `(terminal)`.

---

## 1. WorkItem lifecycle

```
                 post_work_item                 (claim, signed by agent A)
   ┌─────────┐ ───────────────► ┌──────────────┐ ────────────────────────► ┌──────────────┐
   │ NOT_YET │                  │  UNCLAIMED   │ [INV-BB-1, INV-RUN-1]    │   CLAIMED    │
   └─────────┘                  └──────┬───────┘ [verify chain pre-claim] │     by A     │
                                       │                                  └──────┬───────┘
                                       │                                         │
                                       │ TTL expired                  ┌──────────┼──────────┐
                                       │ (created_at + ttl ≤ now)     │          │          │
                                       ▼                              │          │          │
                                ┌──────────────┐                    completed   released   abandoned
                                │   EXPIRED    │                    [INV-RUN-4] [INV-RUN-7] (timeout
                                │  (terminal)  │                      │          │           on claim)
                                └──────────────┘                      ▼          ▼          │
                                                             ┌────────────┐  ┌────────────┐ │
                                                             │ COMPLETED  │  │ RELEASED   │ │
                                                             │  by A      │  │  by A      │ │
                                                             │ (envelope  │  │ (no env)   │ │
                                                             │  in log)   │  │            │ │
                                                             └─────┬──────┘  └─────┬──────┘ │
                                                                   │               │        │
                                                                   │               ▼        ▼
                                                                   │           ┌─────────────┐
                                                                   │           │  UNCLAIMED  │
                                                                   │           │ (re-attempt
                                                                   │           │  by another
                                                                   │           │   agent)    │
                                                                   │           └─────────────┘
                                                                   │
                                                       gossip-merge or settled
                                                                   ▼
                                                            ┌──────────────┐
                                                            │   SETTLED    │
                                                            │  (terminal)  │
                                                            └──────────────┘
```

**Invariants preserved on each transition:**
- `UNCLAIMED → CLAIMED`: INV-RUN-1 (chain verify), INV-RUN-2 (reward threshold), INV-RUN-3 (similarity threshold), INV-BB-2 (uniqueness)
- `CLAIMED → COMPLETED`: INV-RUN-4 (envelope persisted), INV-BB-3 (uniqueness), INV-ICP-1..6 (envelope correctness)
- `COMPLETED → SETTLED`: INV-SETTLE-1..5 (settlement state machine)

---

## 2. Settlement entry lifecycle

```
        earner posts envelope                 earner submits settlement
   ┌────────────┐ ─────────────────────► ┌──────────────────┐
   │ COMPLETED  │                        │   PROPOSED       │
   │ (workitem) │                        │ (in-memory only) │
   └────────────┘                        └────────┬─────────┘
                                                  │
                                          earner signs entry
                                          ledger.entry.earner_signed → payer
                                                  ▼
                                         ┌──────────────────┐
                                         │  EARNER_SIGNED   │
                                         │ (in payer's bus) │
                                         └────────┬─────────┘
                                                  │
                              ┌───────────────────┼───────────────────┐
                              │                   │                   │
                  payer verifies earner sig  envelope_hash poll  amount tolerance
                  [INV-SETTLE-2]             [INV-SETTLE-3]      [INV-SETTLE-4]
                              │                   │                   │
                       fail  ▼  pass        fail ▼ pass          fail ▼ pass
                    ┌────────────┐        ┌────────────┐         ┌────────────┐
                    │ DISPUTED   │        │ DISPUTED   │         │ DISPUTED   │
                    │ "forged    │        │ "envelope  │         │ "amount    │
                    │  sig"      │        │  unknown"  │         │  outside   │
                    │ [INV-      │        │ [INV-      │         │  tol"      │
                    │  SETTLE-7] │        │  SETTLE-7] │         │ [INV-      │
                    └────────────┘        └────────────┘         │  SETTLE-7] │
                                                                 └────────────┘
                                                  │
                                                  │ all checks pass
                                                  ▼
                                       payer cosigns; payer applies locally
                                       ledger.entry.payer_cosigned → earner
                                       record_success(earner) on reputation
                                                  ▼
                                         ┌──────────────────┐
                                         │ PAYER_COSIGNED   │
                                         │ (on payer)       │
                                         └────────┬─────────┘
                                                  │
                            earner receives cosig; verifies payer sig
                            applies entry; record_success(payer)
                                                  ▼
                                         ┌──────────────────┐
                                         │     APPLIED      │
                                         │   (terminal)     │
                                         │ [INV-SETTLE-5]   │
                                         └──────────────────┘
```

**Note on conservation (INV-SETTLE-6):** Conservation is a
network-wide invariant. It's a property of the protocol's safety,
not a per-transition check. Both `APPLIED` ledger sides are
byte-identical because both peers run the same `apply_cosigned_entry`
on the same canonical entry bytes. The TLA+ spec should prove
conservation as a `THEOREM` over the reachable state space.

---

## 3. Attestation cert lifecycle

```
         applicant decides to attest
   ┌───────────────────────────┐
   │ NOT_YET (no body, no cosigs)
   └─────────┬─────────────────┘
             │ applicant authors proposed_attestation_body
             │ (Session 14 — single body shared across validators)
             ▼
   ┌───────────────────────────┐
   │     PROPOSED              │
   │  (body, 0 cosigs)         │
   └─────────┬─────────────────┘
             │
             │ for each candidate validator:
             │   - libp2p stream /gyza/capability-challenge/1.0.0
             │   - validator IssueChallenge → applicant
             │   - applicant runs eval, signs ChallengeResponse
             │   - validator verifyResponse [INV-ATT-7,8,11,12]
             │   - validator cosigs body  [INV-ATT-1,2]
             ▼
   ┌───────────────────────────┐
   │      COSIGNING            │
   │ (body, n < MinCoSig)      │
   └─────────┬─────────────────┘
             │
             │ ≥ MinCoSignatures distinct validators cosig'd
             │ orchestrator early-exits on quorum
             ▼
   ┌───────────────────────────┐
   │     QUORUM_MET            │
   │ (body, n ≥ MinCoSig)      │
   └─────────┬─────────────────┘
             │
             │ AttestationCert assembled
             │ [INV-ATT-5 self-verify]
             ▼
   ┌───────────────────────────┐
   │     ASSEMBLED             │
   │ (in-memory)               │
   └─────────┬─────────────────┘
             │
             │ cap.publish_attestation(cert)
             │ [INV-ATT-15 ≥24h remaining lifetime]
             │ [INV-ATT-17 DHT key shape]
             ▼
   ┌───────────────────────────┐
   │     PUBLISHED             │
   │ (in DHT)                  │
   └─────────┬─────────────────┘
             │
             │ (consumer-side path)
             │ cap.fetch_attestation → bytes
             │ proto unmarshal
             │ [INV-DHT-1 validator runs at fetch]
             │ [INV-ATT-16 gyzaValidator expiry check]
             ▼
   ┌───────────────────────────┐
   │     FETCHED               │
   └─────────┬─────────────────┘
             │
             │ capability.VerifyAttestation [INV-ATT-5]
             │ OR RecursiveVerifier.Verify [INV-ATT-23..28]
             │ OR DHTAttestationVerifier.Verify [INV-ATT-18..22]
             │
        fail ▼ pass
     ┌────────────────────┐    ┌────────────────────┐
     │     REJECTED       │    │     VERIFIED       │
     │  (terminal at      │    │  (consumer accepts)│
     │   consumer)        │    │                    │
     └────────────────────┘    └─────────┬──────────┘
                                         │
                                         │ time passes; cert ages out
                                         ▼
                              ┌────────────────────┐
                              │      EXPIRED       │
                              │   (terminal)       │
                              │ [INV-ATT-16 grace] │
                              └────────────────────┘
```

**Plausibility-rejection sub-states (in COSIGNING).** A validator
that rejects an applicant-proposed body emits a `VerifyResponseResult{Success=false, Error=<reason>}`. Reasons (INV-ATT-8):
- `applicant_pubkey_mismatch`
- `wrong_tier`
- `issued_at_clock_skew_too_far`
- `lifetime_exceeds_max`
- `already_expired`
- `task_ids_mismatch`

Each is a transition `COSIGNING → COSIGNING` (this validator didn't
cosig; orchestrator continues to next candidate).

---

## 4. Agent runner lifecycle

```
   ┌────────────┐
   │  CREATED   │
   └──────┬─────┘
          │ runner.start()
          ▼
   ┌────────────┐         poll_interval elapsed,
   │  POLLING   │ ◄───────────────────────┐
   └──────┬─────┘                         │
          │                               │
          │ candidate work item found     │
          │ [INV-RUN-2, INV-RUN-3]        │
          ▼                               │
   ┌────────────┐                         │
   │ EVALUATING │                         │
   │ candidate  │                         │
   └──────┬─────┘                         │
          │                               │
   ┌──────┼──────┐                        │
   │      │      │                        │
   no-claim  claim                        │
   (skip)    [INV-RUN-1]                  │
          │                               │
          ▼                               │
   ┌────────────┐                         │
   │ CLAIMING   │                         │
   └──────┬─────┘                         │
          │                               │
   ┌──────┼──────┐                        │
   │      │      │                        │
   lost   won                             │
   race   claim                           │
   │      │                               │
   │      ▼                               │
   │  ┌────────────┐                      │
   │  │ EXECUTING  │                      │
   │  └──────┬─────┘                      │
   │         │                            │
   │ ┌───────┼───────┐                    │
   │ │       │       │                    │
   │ error fail success                   │
   │ │       │       │                    │
   │ │       ▼       ▼                    │
   │ │  ┌─────────┐  ┌────────────┐      │
   │ │  │ RELEASE │  │  SIGNING   │      │
   │ │  │ (no env)│  │ [INV-RUN-4]│      │
   │ │  └────┬────┘  └─────┬──────┘      │
   │ │       │             │              │
   │ │       │             ▼              │
   │ │       │       ┌──────────────┐    │
   │ │       │       │ COMPLETING   │    │
   │ │       │       │ (envelope    │    │
   │ │       │       │  persisted)  │    │
   │ │       │       │ [INV-BB-5]   │    │
   │ │       │       └──────┬───────┘    │
   │ │       │              │            │
   │ └───────┼──────────────┘            │
   │         │                           │
   └─────────┴───────────────────────────┘
          stop()
          ▼
   ┌────────────┐
   │  STOPPED   │
   │ (terminal) │
   └────────────┘
```

Reputation updates fire at `COMPLETING` (success +1) and `RELEASE`
(failure −0.5). Dispute events arrive from the settlement service
and apply asynchronously to the agent's compositor.

---

## 5. DHT record lifecycle

Two record-type lifecycles overlap in the DHT layer. Both share the
record-validator and LWW-select machinery.

### 5a. AgentBucket record

```
   ┌─────────┐ PublishAgent(ad)  ┌──────────────┐
   │ NOT_YET │ ───────────────►  │  PUBLISHED   │
   └─────────┘                   │ (local cache │
                                 │  + DHT put)  │
                                 │ [INV-DHT-6]  │
                                 └──────┬───────┘
                                        │
                                        │ Republish loop tick
                                        │ (every interval ≤ TTL/2)
                                        │ [INV-DHT-8]
                                        │
                                        │ refresh ad.LastSeen = now
                                        ▼
                                 ┌──────────────┐
                                 │ REPUBLISHED  │ ─────► back to same state
                                 │  (LWW merge  │
                                 │  by ag_pk)   │
                                 │ [INV-DHT-4]  │
                                 └──────┬───────┘
                                        │
                                        │ No republish for > TTL
                                        ▼
                                 ┌──────────────┐
                                 │   AGED OUT   │
                                 │  (terminal,  │
                                 │ libp2p GCs)  │
                                 └──────────────┘

   ┌─────────────┐ UnpublishAgent  ┌──────────────┐
   │ PUBLISHED   │ ──────────────► │ UNPUBLISHED  │
   │  (any state)│                 │ (local rm +  │
   └─────────────┘                 │  empty bucket│
                                   │  re-publish) │
                                   │ [INV-DHT-9]  │
                                   └──────────────┘
```

### 5b. AttestationCert record

```
   ┌─────────────┐ cap.publish_attestation        ┌─────────────────────┐
   │ ASSEMBLED   │ ───────────────────────────►   │ PUBLISH_ATTEMPTED   │
   │ (in-memory  │ [INV-ATT-15: ≥24h remaining]   │                     │
   │  cert)      │                                └────────┬────────────┘
   └─────────────┘                                         │
                                       check remaining lifetime
                                       │
                          fail (<24h)  ▼  pass
                    ┌──────────────────┐    ┌────────────────────┐
                    │ PUBLISH_REJECTED │    │  STORED_LOCALLY    │
                    │ (cert not put)   │    │  AND_BROADCAST     │
                    │ [INV-ATT-15]     │    │ (kad.PutValue)     │
                    │  (terminal)      │    └────────┬───────────┘
                    └──────────────────┘             │
                                                     │ (DHT validator runs at PutValue)
                                                     │ [INV-DHT-1, INV-ATT-16]
                                                     ▼
                                            ┌────────────────────┐
                                            │  PUBLISHED         │
                                            │ (replicated to k   │
                                            │  closest peers)    │
                                            └────────┬───────────┘
                                                     │
                          ┌──────────────────────────┼──────────────────────────┐
                          │                          │                          │
                  cap.fetch_attestation    cert.expires_at_ns          [INV-DHT-10]
                  (consumer side)          ≤ now − grace               cert is NOT
                          │                (gyzaValidator at           auto-republished
                          │                 fetch refuses)             — manual only
                          ▼                          ▼                          │
                  ┌───────────────┐         ┌────────────────┐                 │
                  │  FETCHED      │         │   REJECTED     │                 │
                  │ (consumer has │         │   AS EXPIRED   │                 │
                  │  cert bytes)  │         │ [INV-ATT-16]   │                 │
                  └───────┬───────┘         │  (terminal)    │                 │
                          │                 └────────────────┘                 │
                          │                                                    │
                  (verify path — see §3 attestation cert lifecycle)            │
                          │                                                    │
                          │                                                    ▼
                          │                                          ┌────────────────┐
                          │                                          │   AGED OUT     │
                          │                                          │ (DHT TTL >>    │
                          │                                          │  cert's own;   │
                          │                                          │  may exceed    │
                          │                                          │  cert validity│
                          │                                          │  — open item) │
                          │                                          │  (terminal)   │
                          │                                          └────────────────┘
```

---

## 6. Capability challenge protocol (libp2p stream)

```
   Validator                          libp2p stream                       Applicant
   ───────────                        ─────────────                       ─────────
   handleIncoming()
   ─ accept stream
   ─ deadline=120s [INV-CAPSTREAM-3]
   ─ applicantPubkey = stream.Conn().RemotePeer()
     [INV-CAPSTREAM-1]
   ─ capMgr.IssueChallenge(...)
   ─ writeFrame(Challenge)            ────►                              readFrame()
                                                                          ─ VerifyChallenge
                                                                            [INV-CAPSTREAM-5]
                                                                          ─ run eval suite
                                                                            [INV-EVAL-2]
                                                                          ─ sign body with
                                                                            COMPOSITOR key
                                                                            [INV-ATT-11]
                                                                          ─ attach proposed
                                                                            attestation body
                                                                            [INV-ATT-7]
                                                                          writeFrame(Response)
   readFrame(Response)                ◄────
   ─ capMgr.VerifyResponse(...)
     ┌─────────────────────────────────┐
     │ verify ApplicantSignature       │ [INV-ATT-11]
     │ verifyTaskResult per task       │ [INV-ATT-12]
     │ verifyProposedAttestationBody   │ [INV-ATT-8]
     │   - applicant_pubkey match
     │   - tier=IssuedTier
     │   - clock skew ≤1h
     │   - lifetime ≤ MaxAttestationTTL
     │   - not already expired
     │   - challenge_task_ids match
     │ sign(canonicalMarshal(body))    │ [INV-ATT-1,2]
     └─────────────────────────────────┘
                                                                          readFrame()
   writeFrame(VerifyResponseResult)   ────►                              ─ outcome.Success
     - Success=true + cosig                                                 ? assemble cert
     - Success=false + Error                                              [INV-ATT-13]
   close stream
```

**Failure modes** (all of which surface as a final
`VerifyResponseResult{Success=false}`):
- Bad Challenge signature → applicant rejects pre-eval [INV-CAPSTREAM-5]
- Bad ApplicantSignature → validator rejects at step 2
- Per-task ICP verify fail → validator rejects at step 3
- Plausibility check fails → validator rejects at step 4
- Stream deadline (120s) → silent close [INV-CAPSTREAM-3]

---

## 7. RequestAttestation gRPC bridge (Python ↔ Daemon)

```
   Python applicant                         Daemon bridge                   Validator daemon
   ────────────────                         ─────────────                   ────────────────
   cap.request_attestation(peer_id, eval_cb)
   ─ open bidi gRPC stream
                                            grpc Send/Recv loop
                                            ─ Recv first frame
                                            ─ MUST be AttestationStartRequest
                                              [INV-CAPBRIDGE-1]
                                            ─ peer.Decode(target_peer_id)
                                              [INV-CAPBRIDGE-2]
                                            ─ capStream.RequestAttestation(peer)
                                                                              libp2p stream
                                                                              opens to validator
                                            EvalRunner closure invoked
                                            EXACTLY ONCE [INV-CAPBRIDGE-4]
                                                                              Challenge frame
   AttestationStartRequest    ────►                                       ◄── (libp2p)
   { target_peer_id }
                                            (closure body)
                                            ─ stream.Send(Challenge to Python)
   Challenge                  ◄────
   ─ eval_callback(challenge):
     run mock-eval / real-eval
     build TaskResults
     sign ResponseBody with compositor
     attach proposed_attestation_body
   ChallengeResponse           ────►
                                            ─ stream.Recv(ChallengeResponse)
                                            ─ return to capStream
                                                                              ChallengeResponse
                                                                          ──► (libp2p)
                                                                              validator verifies
                                                                              VerifyResponseResult
                                                                          ◄── (libp2p)
                                            ─ cosig returned to bridge
                                            ─ stream.Send(Outcome to Python)
                                              [INV-CAPBRIDGE-3 — every
                                               error path emits exactly
                                               one Outcome]
   Outcome { success, cosig }  ◄────
   ─ return (True, cosig, "")
   stream closes
```

**Invariant:** Every error path AFTER the Challenge has been sent
to Python surfaces as exactly one final Outcome frame. Python's read
loop has uniform shape. Errors BEFORE Challenge (bad peer ID,
unreachable peer, libp2p open failure) surface as a leading Outcome
frame.

---

## 8. Verifier cache state (verify-on-fetch)

Per-`compositor_pubkey` cache state in `DHTAttestationVerifier`.

```
   ┌──────────────┐  Verify(pk) call
   │   MISS       │ ─────────────────► single-flight check
   │ (no entry)   │                    ┌────────────────────────┐
   └──────────────┘                    │ another goroutine      │
                                       │ already fetching pk?   │
                                       └──────────┬─────────────┘
                                          no      │      yes
                                       ┌──────────┴──────────┐
                                       │                     │
                                       ▼                     ▼
                              ┌─────────────────┐    ┌──────────────┐
                              │   FETCHING      │    │  WAITING     │
                              │ (sem slot held) │    │ (on done ch) │
                              └────────┬────────┘    └──────┬───────┘
                                       │                    │
                              ┌────────┼────────┐           │
                              │   fetch returns │           │
                              ▼                 ▼           ▼
                       ┌─────────────┐   ┌─────────────┐   (re-read cache)
                       │ no cert /   │   │ cert verifies│
                       │ cert nil    │   │ AND remaining│
                       │ AND not in  │   │ lifetime ≥   │
                       │ slack window│   │ expirySlack  │
                       └──────┬──────┘   └──────┬──────┘
                              │ neg cache       │ pos cache
                              │ TTL=negTTL=30s  │ TTL=min(posTTL=5m,
                              │                 │   exp_at−slack−now)
                              ▼                 ▼
                       ┌─────────────┐   ┌─────────────┐
                       │ CACHED_NEG  │   │ CACHED_POS  │
                       │ [INV-ATT-19]│   │ [INV-ATT-19]│
                       └──────┬──────┘   └──────┬──────┘
                              │ TTL elapses     │ TTL elapses
                              ▼                 ▼
                       ┌─────────────────────────┐
                       │   EVICTED → MISS        │
                       └─────────────────────────┘

   Transient failure path (NOT cached) [INV-ATT-19]:
   ─ DHT fetch error → return false; entry NOT created
   ─ Fetch timeout → return false; entry NOT created
   ─ Semaphore ctx cancel → return false; entry NOT created
```

---

## 9. RecursiveVerifier in-call state

Per top-level `RecursiveVerifier.Verify` call. Carries `seen` set
(cycle detection) and `depth` counter (depth bound) through recursion.

```
   ┌────────────────┐ Verify(cert)
   │  ENTRY         │ ──────────────────────────────┐
   │ depth=0        │                               │
   │ seen={}        │                               │
   └────────────────┘                               │
                                                    ▼
                                          verifyInner(cert, seen, depth)
                                          ┌─────────────────────────────┐
                                          │ standard checks:            │
                                          │ ─ tier, freshness, marshal  │
                                          │ ─ per-cosig:                │
                                          │     verify Ed25519          │
                                          │     isTier3(pk, seen, depth)│
                                          └──────────┬──────────────────┘
                                                     │
                                                     ▼
                                          isTier3(pk, seen, depth)
                                          ┌─────────────────────────────┐
                                          │ pk in TrustedBootstrap?     │
                                          │ ─ yes → return true (base)  │
                                          │ pk in seen?                 │
                                          │ ─ yes → return false (cycle)│
                                          │ depth ≥ MaxDepth?           │
                                          │ ─ yes → return false (bound)│
                                          │ pk in cache (positive)?     │
                                          │ ─ yes → return true         │
                                          │ FetchCert(pk):              │
                                          │ ─ err → return false        │
                                          │ ─ cert.ApplicantPubkey      │
                                          │   != pk → return false      │
                                          │   (substitution defense)    │
                                          │ recurse:                    │
                                          │   newSeen = seen ∪ {pk}     │
                                          │   verifyInner(cert,         │
                                          │     newSeen, depth+1)       │
                                          │ ─ pass → cache pos + true   │
                                          │ ─ fail → return false       │
                                          │   (NOT cached)              │
                                          └─────────────────────────────┘
```

Cycle: A signs B's cert, B signs A's cert. Without `seen` tracking,
the recursion would either loop forever (with extra defenses needed)
or accept the mutual-attestation farm. With `seen`, the second
appearance of any pubkey in the recursion path rejects, so a
cycle's mutual cosigs collapse to ≤1 valid Tier-3 cosig per cert,
which is below quorum, so both reject.

---

## 10. HLC ratchet state

```
   ┌──────────────────────┐
   │  (l, c)              │
   │  l = wall ms          │
   │  c = logical counter  │
   └──────────────┬───────┘
                  │
                  │ now() call (mutex-held)
                  │
                  │ wall_now = time.time_ms()
                  │ if wall_now > l:
                  │   new = (wall_now, 0)
                  │ else:
                  │   new = (l, c + 1)
                  ▼
   ┌──────────────────────┐
   │ new (l', c')         │
   │ where (l', c') >     │
   │ (l, c) lex order     │
   │ [INV-X-5]            │
   └──────────────────────┘

   ┌──────────────────────┐
   │ (l_local, c_local)   │
   └──────────────┬───────┘
                  │
                  │ recv(l_remote, c_remote) (mutex-held)
                  │
                  │ wall_now = time.time_ms()
                  │ l' = max(l_local, l_remote, wall_now)
                  │ if l' == l_local and l' == l_remote:
                  │   c' = max(c_local, c_remote) + 1
                  │ elif l' == l_local:
                  │   c' = c_local + 1
                  │ elif l' == l_remote:
                  │   c' = c_remote + 1
                  │ else:
                  │   c' = 0
                  ▼
   ┌──────────────────────┐
   │ (l', c')             │
   │ ≥ (l_local, c_local) │
   │ AND ≥ (l_remote, c_remote)│
   └──────────────────────┘
```

---

## How to use these state machines

For §C1 (TLA+ spec writing):

1. Each state machine maps to a TLA+ module's `Next` relation.
   States become elements of a TypeOK predicate; transitions become
   case-arms of `Next`.
2. The guards (`[INV-X-N]` annotations) become preconditions on
   transitions. The TLA+ `Action` body asserts the precondition and
   evolves state accordingly.
3. Terminal states are reachable; non-terminal states must have at
   least one outgoing transition (fairness).
4. Cross-machine interactions (e.g., COMPLETED → SETTLED) become
   `INSTANCE`-bridged or via shared variables.

For the TLA+ spec, recommend ONE module per state machine, with a
top-level `Gyza.tla` that composes them via `INSTANCE`.
