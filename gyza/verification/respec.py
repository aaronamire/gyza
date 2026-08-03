"""
Respecified claims — two types moved out of the NO_VERIFIER bucket.

THIS IS A DESIGN CHANGE, NOT A CHECKING CHANGE. The lever is *what the agent is
asked to claim*, not *how hard the claim is checked*. AR-2 closed the checking
lever: a type-level envelope recovers 18.6% of genuine failures at the only
affordable granularity. So neither verifier here tries to judge relevance or
appropriateness. Each recomputes a property the restated claim makes explicit.

WHY THESE TWO (route DR): moving `memory_retrieval_relevance` and
`external_send_content` out of NONE cuts the general architecture's per-step log
decay from -0.2156 to -0.1078 -- it halves the rate at which the shipped system
goes silently wrong with depth. Respecification helps the contain-by-default
architecture MORE than the restricted one, because it removes an ERROR SOURCE
rather than a refusal.

THE TAUTOLOGY TRAP, guarded explicitly. A respecified claim helps only if the
agent's output is genuinely constrained by it. If the claim were generated from
the same computation the verifier reruns, the check would verify itself --
R14's oracle-embedding species. Both verifiers below are therefore required to
FAIL on a real divergence in shipped code, not on a synthetic mutant:

  * retrieval  -- the LanceDB path over-fetches ``max(4k, 16)`` candidates and
                  applies the success/threshold filter AFTER, so qualifying
                  episodes ranked past the cutoff are silently dropped
                  (`gyza/memory.py:308-326` vs the exhaustive scan at
                  `gyza/memory.py:432-437`); and it scores cosine against
                  UN-NORMALIZED stored vectors while the SQLite path normalizes.
  * send       -- a sender that hashes what it INTENDED to send rather than the
                  bytes that actually left.

Both are plausible implementation errors, both are caught, and both are pinned
by tests.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Sequence

import blake3

from gyza.canon import values_equal


class IncompleteClaim(ValueError):
    """A claim that does not name its own parameters cannot be checked against
    them. Rejected at construction, never defaulted."""


# --------------------------------------------------------------------------- #
#  A — retrieval                                                               #
# --------------------------------------------------------------------------- #
METRIC_COSINE_UNIT = "cosine_unit"          # dot product of L2-normalized vectors
FILTER_SUCCESS_ONLY = "success_only"
FILTER_NONE = "none"

_METRICS = {METRIC_COSINE_UNIT}
_FILTERS = {FILTER_SUCCESS_ONLY, FILTER_NONE}


def corpus_snapshot_digest(items: Sequence[tuple[str, "object", bool]]) -> str:
    """Content-address the candidate set.

    THE IMMUTABLE FRAME (artifact #13's species in this domain). A retrieval
    claim whose reference set can move is not checkable: the verifier cannot
    reproduce a neighbour set over a corpus that has since changed. The claim
    therefore names a digest of the exact candidate set it ranked, and the
    verifier refuses if the corpus it is handed does not match.

    Wire is length-prefixed and sorted by id, so it is injective.
    """
    import numpy as np

    h = blake3.blake3()
    for eid, vec, ok in sorted(items, key=lambda t: t[0]):
        b = np.asarray(vec, dtype=np.float32).tobytes()
        idb = eid.encode("utf-8")
        h.update(b"I"); h.update(struct.pack(">I", len(idb))); h.update(idb)
        h.update(b"V"); h.update(struct.pack(">I", len(b))); h.update(b)
        h.update(b"S"); h.update(b"\x01" if ok else b"\x00")
    return h.hexdigest()


@dataclass(frozen=True)
class RetrievalClaim:
    """"The returned set is exactly the first `k` items, in descending `metric`
    order, of the candidates in snapshot `corpus_snapshot` that satisfy
    `filter_predicate` and score >= `threshold`."

    Every parameter is part of the CLAIM. The pre-respecification code carried
    all four implicitly in the implementation (`gyza/memory.py:402-446`), which
    is precisely why nothing could check it.
    """
    corpus_snapshot: str
    metric: str
    k: int
    threshold: float
    filter_predicate: str
    returned_ids: tuple[str, ...]

    def __post_init__(self):
        missing = [n for n in ("corpus_snapshot", "metric", "filter_predicate")
                   if not getattr(self, n)]
        if missing:
            raise IncompleteClaim(f"claim does not name: {missing}")
        if self.metric not in _METRICS:
            raise IncompleteClaim(f"unknown metric {self.metric!r}")
        if self.filter_predicate not in _FILTERS:
            raise IncompleteClaim(f"unknown filter {self.filter_predicate!r}")
        if not isinstance(self.k, int) or self.k <= 0:
            raise IncompleteClaim(f"k must be a positive int, got {self.k!r}")
        # cosine ranges over [-1, 1]. The first version of this check demanded
        # [0, 1] and rejected every legitimate "no floor" claim -- a real
        # validator bug, caught by the tests, not a loosened threshold.
        if not (-1.0 <= float(self.threshold) <= 1.0):
            raise IncompleteClaim(f"threshold out of range: {self.threshold!r}")
        if len(self.returned_ids) > self.k:
            raise IncompleteClaim(
                f"claim returns {len(self.returned_ids)} ids but k={self.k}")


def verify_retrieval_claim(claim: RetrievalClaim,
                           candidates: Sequence[tuple[str, "object", bool]],
                           query_vec) -> bool:
    """RECOMPUTE the neighbour set and compare. PROOF-carried: it recomputes the
    property rather than sampling it.

    Returns False (never raises) on: corpus digest mismatch, wrong membership,
    or wrong order.
    """
    import numpy as np

    if not values_equal(corpus_snapshot_digest(candidates), claim.corpus_snapshot):
        return False                      # the corpus moved: unverifiable, refuse

    def _unit(v):
        a = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(a))
        return a / n if n > 0 else a

    q = _unit(query_vec)
    scored = []
    for eid, vec, ok in candidates:
        if claim.filter_predicate == FILTER_SUCCESS_ONLY and not ok:
            continue
        s = float(np.dot(q, _unit(vec)))
        if s >= claim.threshold - 1e-9:
            scored.append((eid, s))
    # deterministic tie-break by id, so a tie cannot make a correct
    # implementation look divergent
    scored.sort(key=lambda t: (-t[1], t[0]))
    expected = tuple(eid for eid, _ in scored[:claim.k])
    return values_equal(expected, tuple(claim.returned_ids))


# --------------------------------------------------------------------------- #
#  B — external send                                                           #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SendClaim:
    """"The bytes that left were artifact `artifact_hash`, under policy
    `policy_id`, to `destination`, at `timestamp_ns`."

    `artifact_hash` MUST be computed from the bytes actually emitted. A hash the
    sender computed from what it INTENDED to send is self-reporting at a finer
    grain -- the same circularity S5 B3 records for binary hashes -- and
    `verify_send_claim` is given the emitted bytes precisely so the claim cannot
    stand in for them.
    """
    artifact_hash: str
    policy_id: str
    destination: str
    timestamp_ns: int
    n_bytes: int

    def __post_init__(self):
        missing = [n for n in ("artifact_hash", "policy_id", "destination")
                   if not getattr(self, n)]
        if missing:
            raise IncompleteClaim(f"claim does not name: {missing}")
        if len(self.artifact_hash) != 64:
            raise IncompleteClaim("artifact_hash must be a 64-hex blake3 digest")
        if self.n_bytes < 0:
            raise IncompleteClaim("n_bytes must be non-negative")


def wire_digest(emitted: bytes) -> str:
    """The digest of what actually left. Reuses the existing content-addressing
    discipline (`artifact_content_address`, PROOF-carried) rather than inventing
    a second mechanism."""
    return blake3.blake3(emitted).hexdigest()


def verify_send_claim(claim: SendClaim, emitted: bytes,
                      policy: Callable[[SendClaim, bytes], bool] | None = None
                      ) -> bool:
    """Hash-compare against the EMITTED bytes, then check policy satisfaction.

    `policy` is a mechanical predicate over (claim, bytes). It is supplied by
    the caller and is NOT authored here: a policy this module wrote for the
    sends this module checks would be the tautology the header warns about.
    """
    if not values_equal(wire_digest(emitted), claim.artifact_hash):
        return False
    if not values_equal(len(emitted), claim.n_bytes):
        return False
    if policy is not None and not policy(claim, emitted):
        return False
    return True


__all__ = ["FILTER_NONE", "FILTER_SUCCESS_ONLY", "IncompleteClaim",
           "METRIC_COSINE_UNIT", "RetrievalClaim", "SendClaim",
           "corpus_snapshot_digest", "verify_retrieval_claim",
           "verify_send_claim", "wire_digest"]
