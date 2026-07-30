"""Route 14 Part C — verifiable fraction of Gyza's OWN action vocabulary.

Code-only, zero credits. Every citation checked against the tree on 2026-07-30.
A property of Gyza's CURRENT vocabulary, not a general result.
"""
VOCAB = [
 # (action/claim type, bucket, witness file:line, note)
 ("ICP envelope authorship (signature)", "NATIVE", "gyza/icp.py:82 verify_envelope",
  "Ed25519 over canonical JSON; mechanical."),
 ("Envelope chain / DAG linkage", "NATIVE", "gyza/icp.py:105 verify_chain, :217 verify_dag",
  "parent-hash linkage + acyclicity."),
 ("Envelope hash binds payload", "NATIVE", "gyza/icp.py:63 compute_envelope_hash",
  "BLAKE3 content address."),
 ("Capability manifest identity", "NATIVE", "gyza/identity.py:101 manifest_hash_hex",
  "hash comparison."),
 ("Sandbox enforcement within manifest", "NATIVE", "gyza/sandbox/config.py:286 enforcement_satisfies_manifest",
  "the brick-3 gate; subset predicate over 4 dimensions."),
 ("Delegated authority attenuation", "NATIVE", "gyza/economy/delegation.py:213 verify_delegation, :157 capability_subset",
  "monotone non-increasing down the chain, with a proof."),
 ("Ledger entry bilateral signature", "NATIVE", "gyza/economy/ledger.py:348 verify_entry",
  "both parties' signatures over canonical bytes."),
 ("Spendable balance / headroom", "NATIVE", "gyza/economy/wallet.py:274 net_balance, gyza/economy/subcontract.py:184 available",
  "pure fold over append-only entries; the gate reads the same fold."),
 ("Tier-3 attestation quorum cosig", "NATIVE", "gyza/network/netd_client.py:1144 verify_attestation",
  "k-of-n cosignature check."),
 ("Artifact content address", "NATIVE", "gyza/network/artifact_store.py:47 store",
  "BLAKE3 CAS; hash comparison."),

 ("HLC timestamp ordering", "CHEAP_PARTIAL", "gyza/schema.py:123 HLC.now",
  "the monotone ratchet is mechanically checkable; whether the stamp reflects real time is not."),
 ("Reputation score (EWMA)", "CHEAP_PARTIAL", "gyza/economy/reputation.py:188 record_success, :192 record_failure",
  "range bound and per-event direction are checkable; whether the score tracks real trustworthiness is not."),
 ("Work-item claim exclusivity", "CHEAP_PARTIAL", "gyza/blackboard.py:252 post_work_item, gyza/network/network_blackboard.py:154 try_claim",
  "single-claim conservation is checkable; claimant competence is not."),

 ("Agent execution OUTPUT content", "NONE", "gyza/runner.py:374 _execute",
  "is the produced artifact CORRECT? semantic - the competence bound."),
 ("Episodic memory retrieval relevance", "NONE", "gyza/memory.py:402 retrieve_similar",
  "are these the right episodes? semantic."),
 ("LSH/demand routing match quality", "NONE", "gyza/demand.py:35 LSHIndex, :92 DemandOracle",
  "is this agent a good match? semantic."),
 ("External network send content", "NONE", "gyza/network/netd_client.py:461 send_message",
  "leaves modeled state entirely; beyond containment (R13 boundary)."),
]

def summary():
    from collections import Counter
    c = Counter(b for _, b, _, _ in VOCAB)
    n = len(VOCAB)
    return {"n_action_types": n,
            "counts": dict(c),
            "fractions": {k: round(v / n, 4) for k, v in c.items()}}

if __name__ == "__main__":
    import json
    s = summary()
    print(json.dumps(s, indent=1))
    for a, b, w, note in VOCAB:
        print(f"  [{b:13}] {a:38} {w}")
    json.dump({"vocab": [{"action": a, "bucket": b, "witness": w, "note": n}
                         for a, b, w, n in VOCAB], "summary": s},
              open("partc_result.json", "w"), indent=1)
