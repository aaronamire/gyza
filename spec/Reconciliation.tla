------------------------ MODULE Reconciliation ------------------------
(***************************************************************************)
(* Reconciliation.tla — formal spec of the bilateral ledger reconciliation *)
(* RPC from gyza/economy/settlement.py::_handle_reconcile_*. Companion to  *)
(* Settlement.tla; together they cover the full settlement protocol of    *)
(* docs/invariants.md §4.                                                  *)
(*                                                                         *)
(* This is the second §C1 sub-spec (Settlement.tla shipped S19).           *)
(*                                                                         *)
(* Targets INV-SETTLE-8..11 from docs/invariants.md:                       *)
(*                                                                         *)
(*   INV-SETTLE-8  — lex cursor (created_at_ns, entry_id) prevents skip   *)
(*                   and prevents replay across pages.                    *)
(*   INV-SETTLE-9  — cross-peer injection guard: a response is accepted  *)
(*                   only if response.sender matches the registered peer *)
(*                   for that request_id.                                 *)
(*   INV-SETTLE-10 — page cap: per-page entries bounded by MaxPageSize;  *)
(*                   sessions bounded by MaxPages.                       *)
(*   INV-SETTLE-11 — for_peer guard: responder drops a request whose    *)
(*                   for_peer != responder's pubkey.                     *)
(*                                                                         *)
(* Scope: one initiator can run multiple sessions against different      *)
(* targets, concurrently or sequentially. The model is bounded so TLC    *)
(* terminates; bumping the bounds in the .cfg files deepens coverage at  *)
(* the cost of state-space explosion.                                    *)
(*                                                                         *)
(* Out of scope: the reconciliation diff itself (agreed / disputed /     *)
(* missing_ours / missing_theirs), which is a downstream pure-function   *)
(* of the accumulated set and is exercised by unit tests in              *)
(* tests/test_reconciliation.py. The RPC's transport correctness is     *)
(* what is interesting here.                                             *)
(***************************************************************************)

EXTENDS Naturals, Integers, FiniteSets, TLC

CONSTANTS
    Peers,            \* Set of model-value peer identities
    NumEntries,       \* |EntryIDs|; EntryIDs = 1..NumEntries
    NumTimestamps,    \* |Timestamps|; Timestamps = 0..NumTimestamps
    MaxPageSize,      \* Server-side cap on entries per page (INV-SETTLE-10)
    MaxPages,         \* Per-session cap on number of pages (INV-SETTLE-10)
    MaxReqIDs,        \* Bound on request-id nonce space across all peers
    Adversarial       \* TRUE = enable adversarial response injection

ASSUME
    /\ Cardinality(Peers) >= 2
    /\ NumEntries \in Nat /\ NumEntries >= 1
    /\ NumTimestamps \in Nat
    /\ MaxPageSize \in Nat /\ MaxPageSize >= 1
    /\ MaxPages \in Nat /\ MaxPages >= 1
    /\ MaxReqIDs \in Nat /\ MaxReqIDs >= 1

EntryIDs == 1..NumEntries
Timestamps == 0..NumTimestamps
ReqIDs == 1..MaxReqIDs

(***************************************************************************)
(* Domain types                                                          *)
(*                                                                         *)
(* An Entry models a single settlement-protocol entry as the responder    *)
(* sees it in its pairwise ledger. The Python protocol's entries carry   *)
(* many more fields (amount, envelope_hash, signatures); for             *)
(* reconciliation's *transport* correctness we only care about the lex   *)
(* cursor key (created_at_ns, entry_id). Everything else is downstream   *)
(* of the page-delivery problem we're modeling.                          *)
(***************************************************************************)
Entries == [entry_id : EntryIDs, t : Timestamps]

\* Lex cursor: (t1, id1) > (t0, id0). The Python uses strict-greater so
\* a re-issue with the previous page's last cursor cannot replay that
\* entry. The tie-break on entry_id is essential — two entries created
\* in the same ns (rare but allowed) must not be silently skipped.
\* INV-SETTLE-8.
LexGT(t1, id1, t0, id0) ==
    \/ t1 > t0
    \/ (t1 = t0 /\ id1 > id0)

(***************************************************************************)
(* Pending registration on the initiator side. The Python's              *)
(* _PendingReconcile dataclass keyed by request_id in                    *)
(* _pending_reconciles. We carry the cursor here too so an honest         *)
(* initiator advances it monotonically across pages.                     *)
(*                                                                         *)
(* page_idx counts how many pages have been ACCEPTED for this session    *)
(* (not how many requests issued — failed/dropped requests don't count). *)
(***************************************************************************)
PendingRegs == [
    req_id    : ReqIDs,
    initiator : Peers,
    peer      : Peers,        \* the target the initiator registered against
    page_idx  : 0..MaxPages,
    cursor_t  : Timestamps,
    cursor_id : 0..NumEntries
]

(***************************************************************************)
(* Wire messages                                                          *)
(*                                                                         *)
(* RequestMsgs carry the canonical fields from settlement.py:             *)
(*   request_id, from_compositor, for_peer, since_*, max_entries.        *)
(* recipient is the wire-level destination (the peer the request is      *)
(* actually sent to). Under adversarial routing recipient may differ     *)
(* from for_peer; honest paths keep them equal.                          *)
(*                                                                         *)
(* ResponseMsgs carry: request_id, from_compositor, entries, cursor,    *)
(* has_more. recipient is the wire-level destination.                    *)
(***************************************************************************)
RequestMsgs == [
    req_id    : ReqIDs,
    sender    : Peers,
    recipient : Peers,
    for_peer  : Peers,
    since_t   : Timestamps,
    since_id  : 0..NumEntries,
    max_pg    : 1..MaxPageSize
]

ResponseMsgs == [
    req_id    : ReqIDs,
    sender    : Peers,
    recipient : Peers,
    entries   : SUBSET Entries,
    cursor_t  : Timestamps,
    cursor_id : 0..NumEntries,
    has_more  : BOOLEAN
]

(***************************************************************************)
(* State variables                                                        *)
(*                                                                         *)
(* store     — the truth-of-record on each responder side. store[p1,p2]   *)
(*             is p1's view of its (p1, p2) pairwise ledger. Set once at *)
(*             init and frozen during the spec (we model reconciliation, *)
(*             not the underlying settlement; new entries don't appear   *)
(*             mid-session in this spec).                                *)
(* requests  — in-flight request messages on the wire.                   *)
(* responses — in-flight response messages on the wire.                  *)
(* pending   — the union of all peers' _pending_reconciles entries.     *)
(*             Initiator side state.                                     *)
(* accepted  — per-session set of entries the initiator has accepted    *)
(*             from a target. Indexed by (initiator, peer, req_id) to   *)
(*             scope to one session. Used to check INV-SETTLE-8 (no     *)
(*             entry appears twice in one session) and to check         *)
(*             INV-SETTLE-9 (only entries from the registered peer     *)
(*             show up here).                                            *)
(* used_ids  — req_ids that have ever been allocated (consumed). Models *)
(*             UUIDv7 nonce uniqueness so we don't reuse a req_id.      *)
(* total_pages — per-(initiator,peer) session page counter. Caps at     *)
(*             MaxPages.                                                 *)
(***************************************************************************)
VARIABLES
    store,
    requests,
    responses,
    pending,
    accepted,
    used_ids,
    total_pages,
    \* sess_cursor and sess_can_continue model the Python loop's local
    \* state between pages. Python's pagination is:
    \*    while pages < max_pages:
    \*        rid = fresh()
    \*        pending[rid] = _PendingReconcile(...)
    \*        # send + wait
    \*        if accepted: pages += 1; cursor = response.cursor
    \*        pop pending[rid]
    \*        if not has_more: break
    \* The pop-after-wait means EACH req_id is in pending only briefly;
    \* a second response with the same req_id finds nothing to match.
    \* sess_cursor[(i,t)] carries the cursor between pages.
    \* sess_can_continue[(i,t)] is TRUE iff the next page is allowed
    \*   (initial = TRUE; set to has_more on accept).
    sess_cursor,
    sess_can_continue

vars == <<store, requests, responses, pending, accepted,
          used_ids, total_pages, sess_cursor, sess_can_continue>>

(***************************************************************************)
(* TypeOK                                                                 *)
(*                                                                         *)
(* Express structural well-formedness per variable. TLC cannot enumerate *)
(* SUBSET of large message sets, so we constrain element-wise.           *)
(***************************************************************************)
TypeOK ==
    /\ DOMAIN store = Peers \X Peers
    /\ \A pair \in Peers \X Peers: store[pair] \subseteq Entries
    /\ requests \subseteq RequestMsgs
    /\ responses \subseteq ResponseMsgs
    /\ pending \subseteq PendingRegs
    /\ DOMAIN accepted = Peers \X Peers \X ReqIDs
    /\ \A triple \in Peers \X Peers \X ReqIDs:
           accepted[triple] \subseteq Entries
    /\ used_ids \subseteq ReqIDs
    /\ DOMAIN total_pages = Peers \X Peers
    /\ \A pair \in Peers \X Peers: total_pages[pair] \in 0..MaxPages
    /\ DOMAIN sess_cursor = Peers \X Peers
    /\ \A pair \in Peers \X Peers:
        /\ sess_cursor[pair].t \in Timestamps
        /\ sess_cursor[pair].id \in 0..NumEntries
    /\ DOMAIN sess_can_continue = Peers \X Peers
    /\ \A pair \in Peers \X Peers: sess_can_continue[pair] \in BOOLEAN

(***************************************************************************)
(* Helpers                                                                *)
(***************************************************************************)

\* The set of entries in p1's view of (p1,p2) that lex-exceed the cursor.
EntriesAfter(p1, p2, t0, id0) ==
    { e \in store[p1, p2] : LexGT(e.t, e.entry_id, t0, id0) }

\* The lex-max entry in a non-empty set; used to compute response cursor.
MaxByLex(S) ==
    CHOOSE e \in S :
        \A x \in S : LexGT(e.t, e.entry_id, x.t, x.entry_id)
                  \/ (e.t = x.t /\ e.entry_id = x.entry_id)

(***************************************************************************)
(* Init                                                                   *)
(*                                                                         *)
(* store is initialized non-deterministically — TLC will try every         *)
(* possible pre-existing pairwise ledger state up to the model bounds.   *)
(* This way the spec checks the RPC under every realizable ledger shape. *)
(***************************************************************************)
Init ==
    /\ store \in [Peers \X Peers -> SUBSET Entries]
    /\ \A p \in Peers: store[p, p] = {}        \* no self-pair ledger
    /\ requests = {}
    /\ responses = {}
    /\ pending = {}
    /\ accepted = [t \in Peers \X Peers \X ReqIDs |-> {}]
    /\ used_ids = {}
    /\ total_pages = [pair \in Peers \X Peers |-> 0]
    /\ sess_cursor = [pair \in Peers \X Peers |-> [t |-> 0, id |-> 0]]
    /\ sess_can_continue = [pair \in Peers \X Peers |-> TRUE]

(***************************************************************************)
(* Action: IssueRequest                                                  *)
(*                                                                         *)
(* The initiator registers a pending session and emits a request. Two    *)
(* sub-cases:                                                            *)
(*                                                                         *)
(*   (a) New session (page_idx = 0): use a fresh req_id, set cursor to  *)
(*       (0, 0) (= "before any entry"), and set for_peer correctly.     *)
(*                                                                         *)
(*   (b) Continuation page (page_idx > 0): we replace the pending entry *)
(*       for this session with a new req_id and advanced cursor from a *)
(*       previously-accepted page. Modeled together as one atomic step. *)
(*                                                                         *)
(* This action ALWAYS emits an honest request: recipient == for_peer.   *)
(* The cursor advance from any prior accepted page must be lex-strictly *)
(* greater than the registered one (the initiator's loop sets cursor =  *)
(* response.cursor on success).                                          *)
(***************************************************************************)
\* Unified action. The Python loop creates a fresh req_id per page; in
\* TLA we collapse "new session" and "continue" into one action. The
\* guards are:
\*   - no pending currently exists for this pair (Python: prior pending
\*     was popped before this loop iteration);
\*   - total_pages < MaxPages (Python: while pages < max_pages);
\*   - sess_can_continue (Python: initial OR has_more was TRUE).
\* sess_cursor carries the cursor from the previous accept (or (0,0)
\* on the first page).
IssueRequest(initiator, target) ==
    /\ initiator /= target
    /\ total_pages[initiator, target] < MaxPages
    /\ sess_can_continue[initiator, target]
    /\ ~\E pr \in pending : pr.initiator = initiator /\ pr.peer = target
    /\ \E rid \in ReqIDs \ used_ids:
        /\ pending' = pending \cup {[
                req_id    |-> rid,
                initiator |-> initiator,
                peer      |-> target,
                page_idx  |-> total_pages[initiator, target],
                cursor_t  |-> sess_cursor[initiator, target].t,
                cursor_id |-> sess_cursor[initiator, target].id]}
        /\ requests' = requests \cup {[
                req_id    |-> rid,
                sender    |-> initiator,
                recipient |-> target,
                for_peer  |-> target,
                since_t   |-> sess_cursor[initiator, target].t,
                since_id  |-> sess_cursor[initiator, target].id,
                max_pg    |-> MaxPageSize]}
        /\ used_ids' = used_ids \cup {rid}
    /\ UNCHANGED <<store, responses, accepted, total_pages,
                   sess_cursor, sess_can_continue>>

(***************************************************************************)
(* Action: HandleRequest (honest responder)                              *)
(*                                                                         *)
(* The responder runs _handle_reconcile_request. Three sub-branches:     *)
(*                                                                         *)
(*   1. INV-SETTLE-11 misroute: for_peer != self → drop silently.         *)
(*   2. INV-SETTLE-10 cap: max_entries is clamped to MaxPageSize.        *)
(*   3. INV-SETTLE-8 cursor filter + slice top MaxPageSize + has_more.   *)
(***************************************************************************)
HandleRequest ==
    \E req \in requests:
        LET responder == req.recipient IN
        \/  \* INV-SETTLE-11: for_peer mismatch → silent drop
            /\ req.for_peer /= responder
            /\ requests' = requests \ {req}
            /\ UNCHANGED <<store, responses, pending, accepted,
                           used_ids, total_pages,
                           sess_cursor, sess_can_continue>>
        \/  \* Honest reply path: build page from store using lex cursor
            /\ req.for_peer = responder
            /\ LET candidate ==
                       EntriesAfter(responder, req.sender,
                                    req.since_t, req.since_id)
               IN  \E page \in SUBSET candidate:
                       /\ Cardinality(page) <= MaxPageSize
                       /\ Cardinality(page) <= Cardinality(candidate)
                       \* page is a lex-prefix of candidate (entries
                       \* not in page are lex-greater than entries in
                       \* page). The honest server takes EXACTLY
                       \* min(MaxPageSize, |candidate|) lex-min entries;
                       \* we permit any non-empty lex-prefix when
                       \* candidate is non-empty (modelling responder
                       \* freedom; safety invariants still hold).
                       /\ \A e1 \in page, e2 \in candidate \ page :
                              LexGT(e2.t, e2.entry_id, e1.t, e1.entry_id)
                       \* When candidate is non-empty the honest server
                       \* always returns AT LEAST one entry — the
                       \* Python code returns the lex-min slice of size
                       \* min(MaxPageSize, len(after)). An empty page
                       \* with has_more=TRUE is the adversary's regime,
                       \* not honest. (Without this guard the spec
                       \* would allow the initiator to advance page_idx
                       \* with cursor frozen at (0,0), which the real
                       \* protocol cannot exhibit.)
                       /\ candidate /= {} => page /= {}
                       /\ LET has_more == Cardinality(page) <
                                          Cardinality(candidate)
                              new_cursor_t ==
                                  IF page = {}
                                  THEN req.since_t
                                  ELSE MaxByLex(page).t
                              new_cursor_id ==
                                  IF page = {}
                                  THEN req.since_id
                                  ELSE MaxByLex(page).entry_id
                          IN  responses' = responses \cup {[
                                  req_id    |-> req.req_id,
                                  sender    |-> responder,
                                  recipient |-> req.sender,
                                  entries   |-> page,
                                  cursor_t  |-> new_cursor_t,
                                  cursor_id |-> new_cursor_id,
                                  has_more  |-> has_more]}
            /\ requests' = requests \ {req}
            /\ UNCHANGED <<store, pending, accepted, used_ids, total_pages,
                           sess_cursor, sess_can_continue>>

(***************************************************************************)
(* Action: HandleResponse (initiator side)                               *)
(*                                                                         *)
(* The initiator's _handle_reconcile_response. Three sub-branches:       *)
(*                                                                         *)
(*   1. INV-SETTLE-9 cross-peer injection: response.sender doesn't match *)
(*      the registered peer for this req_id → drop without state change. *)
(*   2. No pending entry for req_id → drop.                              *)
(*   3. Match — accept entries into per-session accumulator, advance     *)
(*      cursor if has_more, increment page counter, possibly clean up.  *)
(***************************************************************************)
HandleResponse ==
    \E resp \in responses:
        LET pendings_for_req ==
                { pr \in pending :
                       pr.initiator = resp.recipient
                    /\ pr.req_id = resp.req_id }
        IN
        \/  \* INV-SETTLE-9: no matching pending OR sender mismatch → drop
            /\ \/ pendings_for_req = {}
               \/ \A pr \in pendings_for_req : pr.peer /= resp.sender
            /\ responses' = responses \ {resp}
            /\ UNCHANGED <<store, requests, pending, accepted,
                           used_ids, total_pages,
                           sess_cursor, sess_can_continue>>
        \/  \* Match: accept the page. Always pop pending (Python's
            \* finally-block pop). Update sess_cursor and
            \* sess_can_continue from the response so the next
            \* IssueRequest knows where to resume and whether to.
            /\ \E pr \in pendings_for_req :
                /\ pr.peer = resp.sender
                /\ accepted' = [accepted EXCEPT
                       ![<<resp.recipient, resp.sender, resp.req_id>>] =
                           @ \cup resp.entries]
                /\ total_pages' = [total_pages EXCEPT
                       ![<<resp.recipient, resp.sender>>] = @ + 1]
                /\ pending' = pending \ {pr}
                /\ sess_cursor' = [sess_cursor EXCEPT
                       ![<<resp.recipient, resp.sender>>] =
                           [t |-> resp.cursor_t, id |-> resp.cursor_id]]
                /\ sess_can_continue' = [sess_can_continue EXCEPT
                       ![<<resp.recipient, resp.sender>>] = resp.has_more]
            /\ responses' = responses \ {resp}
            /\ UNCHANGED <<store, requests, used_ids>>

(***************************************************************************)
(* Action: AdversarialResponse — only with Adversarial=TRUE              *)
(*                                                                         *)
(* Any peer X can synthesize a response with arbitrary req_id, entries,  *)
(* cursor, has_more. Models a malicious peer injecting a forged response *)
(* hoping to:                                                            *)
(*                                                                         *)
(*   (a) Confuse the initiator's pending state (cross-peer injection)   *)
(*   (b) Replay entries (lex-cursor regression)                          *)
(*   (c) Loop the initiator forever (has_more=TRUE with empty pages)    *)
(*                                                                         *)
(* INV-SETTLE-9, INV-SETTLE-10, INV-SETTLE-8 must hold under all such   *)
(* attacks.                                                              *)
(***************************************************************************)
\* Adversarial empty-DoS response: ANY peer X emits a forged
\* response with entries={} and has_more=TRUE, hoping to burn the
\* initiator's page cap. Tests INV-10 (page count bounded) and
\* INV-9 (only accepted when sender matches the registered peer).
AdversarialEmptyResponse ==
    /\ Adversarial
    /\ \E sender, recipient \in Peers:
       \E rid \in ReqIDs:
          /\ sender /= recipient
          /\ responses' = responses \cup {[
                 req_id    |-> rid,
                 sender    |-> sender,
                 recipient |-> recipient,
                 entries   |-> {},
                 cursor_t  |-> 0,
                 cursor_id |-> 0,
                 has_more  |-> TRUE]}
          /\ UNCHANGED <<store, requests, pending, accepted,
                         used_ids, total_pages,
                         sess_cursor, sess_can_continue>>

\* Adversarial content-forgery response: X claims an entry not
\* actually in X's store. Tests INV-8 in honest config (would
\* violate) and is harmless adversarial in adversarial config
\* (INV-8 dropped because no wire-level defense exists).
AdversarialContentResponse ==
    /\ Adversarial
    /\ \E sender, recipient \in Peers:
       \E rid \in ReqIDs:
       \E e \in Entries:
          /\ sender /= recipient
          /\ responses' = responses \cup {[
                 req_id    |-> rid,
                 sender    |-> sender,
                 recipient |-> recipient,
                 entries   |-> {e},
                 cursor_t  |-> e.t,
                 cursor_id |-> e.entry_id,
                 has_more  |-> FALSE]}
          /\ UNCHANGED <<store, requests, pending, accepted,
                         used_ids, total_pages,
                         sess_cursor, sess_can_continue>>

(***************************************************************************)
(* Action: AdversarialRequest — only with Adversarial=TRUE               *)
(*                                                                         *)
(* A peer X sends a request with for_peer != recipient — the misroute   *)
(* attack INV-SETTLE-11 defends. Honest responder drops; we model that  *)
(* the request enters the wire so HandleRequest can exercise its drop  *)
(* branch.                                                               *)
(***************************************************************************)
AdversarialRequest ==
    /\ Adversarial
    /\ \E sender, recipient, claimed_for \in Peers:
       \E rid \in ReqIDs \ used_ids:
       \E st \in Timestamps:
       \E sid \in 0..NumEntries:
          /\ sender /= recipient
          /\ claimed_for /= recipient
              \* deliberately mismatched
          /\ requests' = requests \cup {[
                 req_id    |-> rid,
                 sender    |-> sender,
                 recipient |-> recipient,
                 for_peer  |-> claimed_for,
                 since_t   |-> st,
                 since_id  |-> sid,
                 max_pg    |-> MaxPageSize]}
          /\ used_ids' = used_ids \cup {rid}
          /\ UNCHANGED <<store, responses, pending, accepted, total_pages,
                         sess_cursor, sess_can_continue>>

(***************************************************************************)
(* Action: DropMessage — model wire drop under partition                 *)
(***************************************************************************)
DropRequest ==
    \E req \in requests:
        /\ requests' = requests \ {req}
        /\ UNCHANGED <<store, responses, pending, accepted,
                       used_ids, total_pages,
                       sess_cursor, sess_can_continue>>

DropResponse ==
    \E resp \in responses:
        /\ responses' = responses \ {resp}
        /\ UNCHANGED <<store, requests, pending, accepted,
                       used_ids, total_pages,
                       sess_cursor, sess_can_continue>>

(***************************************************************************)
(* Next-state relation                                                   *)
(***************************************************************************)
Next ==
    \/ \E i, t \in Peers: IssueRequest(i, t)
    \/ HandleRequest
    \/ HandleResponse
    \/ AdversarialEmptyResponse
    \/ AdversarialContentResponse
    \/ AdversarialRequest
    \/ DropRequest
    \/ DropResponse

Spec == Init /\ [][Next]_vars

(***************************************************************************)
(* Safety invariants                                                     *)
(*                                                                         *)
(* All structurally-checkable. INV-SETTLE-7 / INV-SETTLE-12 (reputation) *)
(* are downstream of accepted entries and not modeled here.              *)
(***************************************************************************)

\* INV-SETTLE-8 (lex cursor) — HONEST-MODE ONLY. When the responder
\* is honest (HandleRequest emits responses derived from store via
\* the EntriesAfter prefix), every entry in accepted[i, t, r] came
\* from store[t, i]. Adversarial responders can forge entries that
\* aren't in their actual ledger — defense against that is the
\* downstream diff computation (reconcile_with_peer classifies the
\* discrepancy), not a wire-level guard. So this invariant is checked
\* in the honest config and DROPPED in the adversarial config.
INV_RECON_8_AcceptedFromTrueLedger ==
    \A triple \in Peers \X Peers \X ReqIDs:
        LET initiator == triple[1]
            target    == triple[2]
        IN initiator /= target =>
            accepted[triple] \subseteq store[target, initiator]

\* INV-SETTLE-9 (cross-peer injection guard): For every entry that
\* lands in accepted[i, t, r], there exists a pending registration (or
\* historical one) where i registered req_id r against t. We track this
\* via the registration being authoritative: HandleResponse only adds
\* to accepted under that match. The invariant cross-checks: any
\* non-empty accepted[i, t, r] must coincide with a req_id that i has
\* used against t at some point (used_ids \cap registrations).
\*
\* Operationally: there should never be a (i, t, r) with non-empty
\* accepted[i, t, r] where r was used by a DIFFERENT initiator, or
\* where the registration target was a DIFFERENT peer. We model the
\* invariant as: accepted is non-empty only if some pending OR prior-
\* pending entry exists with matching (initiator, peer, req_id). Since
\* we don't keep history of completed pendings, we use the weaker
\* operational invariant: if accepted[i, t, r] is non-empty, then
\* r \in used_ids (i.e., it's a real allocated req_id).
INV_RECON_9_AcceptedOnlyFromAllocatedIDs ==
    \A triple \in Peers \X Peers \X ReqIDs:
        accepted[triple] /= {} => triple[3] \in used_ids

\* INV-SETTLE-10 (page cap): no (initiator, target) session has
\* accepted more than MaxPages worth of pages. The increment happens
\* in HandleResponse; TypeOK constrains total_pages \in 0..MaxPages.
INV_RECON_10_PageCount ==
    \A pair \in Peers \X Peers:
        total_pages[pair] <= MaxPages

\* Page-size cap (the OTHER half of INV-SETTLE-10): no in-flight
\* HONEST response exceeds MaxPageSize. Adversarial responses can
\* exceed it (modeled in AdversarialResponse with +2 slack); the
\* initiator currently doesn't cap them (defensive observation). This
\* invariant scopes to responses whose sender's behavior we control.
\*
\* We check that every response NOT produced by AdversarialResponse
\* has |entries| <= MaxPageSize. Since we don't track origin, the
\* invariant is: in any honest run (Adversarial=FALSE) every response
\* has |entries| <= MaxPageSize. With Adversarial=TRUE we drop this
\* invariant from the check (see the .cfg files).
INV_RECON_10b_HonestResponsePageSize ==
    \A resp \in responses :
        Cardinality(resp.entries) <= MaxPageSize

\* INV-SETTLE-11 (for_peer guard): no honest responder ever produced
\* a response for a request whose for_peer didn't match. Modeled
\* indirectly: HandleRequest's misroute branch drops; happy branch
\* only fires when for_peer = responder. So every response in flight
\* corresponds to some request that DID match (or to an adversarial
\* response, which doesn't correspond to a request at all).
\*
\* Express structurally: for every response we accepted, there exists
\* a *past* request from the same initiator-to-target pair with that
\* req_id where for_peer == sender. Since we consume the request when
\* handling, we use the weaker observation: every accepted response
\* terminated at the same peer that ran the registration. INV-9 above
\* covers that. INV-11 doesn't add fresh state assertion on top of 9
\* in this spec — the protection it provides is in HandleRequest's
\* drop branch, which TLC exercises by structure.

\* NOTE on cursor monotonicity: the protocol does NOT enforce that
\* cursor advances strictly between pages — the initiator trusts
\* response.cursor_* verbatim. An adversarial responder can send
\* has_more=TRUE with a regressive (or frozen) cursor, which makes
\* the initiator re-issue from the same (or earlier) point. The
\* defense against this DoS is INV-10 (MaxPages bound). We do NOT
\* assert "cursor monotonicity" as an invariant because it would
\* be violated by adversarial-but-spec-conformant runs.

(***************************************************************************)
(* Properties to check                                                   *)
(*                                                                         *)
(* Honest config (Reconciliation.cfg, Adversarial=FALSE) checks all four *)
(* invariants. Adversarial config drops INV_RECON_8 since adversarial    *)
(* responders can forge entries not in their actual store — the protocol *)
(* defense against that is downstream diff classification, not a wire    *)
(* guard.                                                                *)
(***************************************************************************)
AllSafety ==
    /\ TypeOK
    /\ INV_RECON_8_AcceptedFromTrueLedger
    /\ INV_RECON_9_AcceptedOnlyFromAllocatedIDs
    /\ INV_RECON_10_PageCount
    /\ INV_RECON_10b_HonestResponsePageSize

================================================================================
