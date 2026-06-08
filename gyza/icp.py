"""
Intent Chain Protocol — hash-chained Ed25519-signed envelopes.

Every agent action emits one ICPEnvelope. Each envelope's signature
covers the BLAKE3 hash of all its payload fields (signature excluded),
and that payload includes `parent_envelope_hash` — the hash of the
prior envelope in the chain. So:

  - Mutating any field of any envelope invalidates that envelope's
    signature.
  - Inserting a fake envelope between two real ones makes the next
    real envelope's `parent_envelope_hash` no longer match.

Result: the entire chain is structurally immutable post-hoc. The only
way to "rewrite history" is to forge an Ed25519 signature, which we
treat as cryptographically infeasible.

Canonical encoding: JSON with sorted keys and no whitespace, UTF-8.
The signature field is omitted (not blanked) before hashing — caller
inserts it after signing. Hashing is BLAKE3 throughout.
"""
from __future__ import annotations

import heapq
import json
import time
from dataclasses import asdict, dataclass, field

import blake3
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


@dataclass
class ICPEnvelope:
    intent_id: str
    action_id: str
    agent_pubkey: str
    capability_manifest_hash: str
    input_hashes: list[str]
    output_hash: str
    parent_envelope_hash: str | None
    timestamp_ns: int
    inference_backend: str
    model_identifier: str
    duration_ms: int
    tokens_in: int
    tokens_out: int
    schema_version: int = 1
    signature: str = ""


def _payload_bytes(env: ICPEnvelope) -> bytes:
    """Canonical JSON of every field except `signature`, UTF-8 encoded."""
    d = asdict(env)
    d.pop("signature", None)
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_envelope_hash(env: ICPEnvelope) -> str:
    return blake3.blake3(_payload_bytes(env)).hexdigest()


def sign_envelope(env: ICPEnvelope, private_key_bytes: bytes) -> ICPEnvelope:
    if len(private_key_bytes) != 32:
        raise ValueError(
            f"Ed25519 seed must be 32 bytes, got {len(private_key_bytes)}"
        )
    sk = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    payload_hash = blake3.blake3(_payload_bytes(env)).digest()
    sig = sk.sign(payload_hash).hex()
    # Return a fresh envelope so the caller's original stays unsigned —
    # avoids mutation surprises when the same envelope object is reused.
    fields = asdict(env)
    fields["signature"] = sig
    return ICPEnvelope(**fields)


def verify_envelope(env: ICPEnvelope, pubkey_bytes: bytes) -> bool:
    if not env.signature:
        return False
    try:
        sig = bytes.fromhex(env.signature)
    except ValueError:
        return False
    try:
        pk = Ed25519PublicKey.from_public_bytes(pubkey_bytes)
        payload_hash = blake3.blake3(_payload_bytes(env)).digest()
        pk.verify(sig, payload_hash)
        return True
    except (InvalidSignature, ValueError):
        return False


def _pubkey_bytes_of(env: ICPEnvelope) -> bytes | None:
    try:
        return bytes.fromhex(env.agent_pubkey)
    except ValueError:
        return None


def verify_chain(envelopes: list[ICPEnvelope]) -> tuple[bool, int]:
    """
    Walk the chain. At each hop check (in order):
      1. agent_pubkey decodes to 32 bytes and signature verifies.
      2. parent_envelope_hash matches BLAKE3 of envelopes[i-1] (or is
         None for the first hop).
      3. input_hashes is non-empty.
    Returns (True, -1) on full success, (False, first_bad_index) otherwise.
    """
    for i, env in enumerate(envelopes):
        pk = _pubkey_bytes_of(env)
        if pk is None or len(pk) != 32:
            return False, i
        if not verify_envelope(env, pk):
            return False, i

        if i == 0:
            if env.parent_envelope_hash is not None:
                return False, i
        else:
            expected = compute_envelope_hash(envelopes[i - 1])
            if env.parent_envelope_hash != expected:
                return False, i

        if not env.input_hashes:
            return False, i

    return True, -1


# ---------------------------------------------------------------------------
# DAG-native provenance (the multi-parent generalization of verify_chain)
# ---------------------------------------------------------------------------
#
# verify_chain validates a *linear* history. Real agent work is a DAG:
# fan-out (one task spawns many), fan-in (a synthesis step consumes
# several results), and concurrent branches (a partition fork, as in
# gyza.demo.ddil_partition). The ICPEnvelope schema is ALREADY capable
# of expressing this — `input_hashes` is a list — so DAG provenance
# needs no schema change and no re-signing: only a verifier that treats
# the existing fields as a graph. Two edge kinds, both pointing from an
# envelope to an EARLIER one it depends on:
#
#   * causal spine — `parent_envelope_hash` (an agent's own prior
#     action; single-parent, the verify_chain edge);
#   * data dependency — each `input_hashes` entry that resolves to a
#     held envelope's `output_hash` (a cross-agent dependency; this is
#     how fan-in is expressed).
#
# This is deliberately additive: _payload_bytes / sign_envelope /
# compute_envelope_hash are untouched, so existing signatures and the
# Rust byte-parity fixtures are unaffected.


@dataclass
class DagVerification:
    """Outcome of ``verify_dag``.

    ``topo_order`` is a deterministic (Kahn + content-address tie-break)
    root-first linearization, so two replicas holding the same envelope
    set produce a byte-identical order. ``roots`` have no held
    dependency; ``leaves`` are depended upon by nothing held.
    """
    valid: bool
    reason: str
    topo_order: list["ICPEnvelope"]
    roots: list[str]
    leaves: list[str]


def _provenance_parents(
    by_hash: "dict[str, ICPEnvelope]",
    by_output: "dict[str, str]",
) -> "dict[str, set[str]]":
    """The dependency-parent set per envelope hash, unioning the causal
    spine and the resolved data edges. Self-edges are dropped (an
    envelope whose input happens to equal its own output)."""
    parents: dict[str, set[str]] = {h: set() for h in by_hash}
    for h, env in by_hash.items():
        p = env.parent_envelope_hash
        if p is not None and p in by_hash:
            parents[h].add(p)
        for ih in env.input_hashes:
            producer = by_output.get(ih)
            if producer is not None and producer != h:
                parents[h].add(producer)
    return parents


def _topo_order(parents: "dict[str, set[str]]") -> "list[str] | None":
    """Kahn topological sort with a content-address (hash) tie-break for
    determinism. Returns ``None`` iff the graph has a cycle."""
    indeg = {h: len(ps) for h, ps in parents.items()}
    children: dict[str, list[str]] = {h: [] for h in parents}
    for h, ps in parents.items():
        for p in ps:
            children[p].append(h)
    ready = [h for h, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        h = heapq.heappop(ready)
        order.append(h)
        for c in sorted(children[h]):
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(ready, c)
    if len(order) != len(parents):
        return None
    return order


def verify_dag(
    envelopes: "list[ICPEnvelope]",
    *,
    require_closed: bool = False,
) -> DagVerification:
    """
    Verify a provenance DAG — the multi-parent generalization of
    ``verify_chain``.

    Per envelope (the verify_chain invariants, lifted to a graph): the
    signature must verify under ``agent_pubkey`` and ``input_hashes``
    must be non-empty. The union of spine + data edges must be acyclic
    — a data-dependency cycle (two agents each consuming the other's
    output) is a mutual-farm corruption, the same class the delegation
    cycle guard defends, and is reachable with perfectly valid
    signatures, so the check is load-bearing rather than defensive.

    ``require_closed=True`` demands every non-``None``
    ``parent_envelope_hash`` resolve to a held envelope. This recovers
    verify_chain's tamper/loss detection in DAG form: altering a
    predecessor changes its content address, orphaning its child, which
    then surfaces as a missing spine parent. With ``require_closed=
    False`` a dangling spine parent is permitted (the node becomes a
    root) so partial replicas mid-gossip still verify what they hold.

    A linear chain is the special case of a single spine path with one
    root and one leaf.
    """
    by_hash: dict[str, ICPEnvelope] = {}
    for env in envelopes:
        by_hash[compute_envelope_hash(env)] = env

    for h, env in by_hash.items():
        pk = _pubkey_bytes_of(env)
        if pk is None or len(pk) != 32:
            return DagVerification(False, f"{h[:12]}: pubkey not 32-byte hex",
                                   [], [], [])
        if not verify_envelope(env, pk):
            return DagVerification(False, f"{h[:12]}: signature invalid",
                                   [], [], [])
        if not env.input_hashes:
            return DagVerification(False, f"{h[:12]}: input_hashes empty",
                                   [], [], [])
        if (require_closed and env.parent_envelope_hash is not None
                and env.parent_envelope_hash not in by_hash):
            return DagVerification(
                False,
                f"{h[:12]}: spine parent {env.parent_envelope_hash[:12]} "
                f"not held (DAG not closed — predecessor lost or altered)",
                [], [], [],
            )

    # output_hash -> producing envelope hash (first producer wins on the
    # rare duplicate-output case; deterministic via sorted iteration).
    by_output: dict[str, str] = {}
    for h in sorted(by_hash):
        by_output.setdefault(by_hash[h].output_hash, h)

    parents = _provenance_parents(by_hash, by_output)
    order = _topo_order(parents)
    if order is None:
        return DagVerification(False, "provenance cycle detected", [], [], [])

    consumed: set[str] = set()
    for ps in parents.values():
        consumed |= ps
    roots = sorted(h for h, ps in parents.items() if not ps)
    leaves = sorted(h for h in by_hash if h not in consumed)
    return DagVerification(True, "ok", [by_hash[h] for h in order],
                           roots, leaves)


def injection_breaks_chain(
    chain: list[ICPEnvelope],
    injected_index: int,
) -> bool:
    """
    Splice a fake envelope at `injected_index` and re-verify.

    Always returns True for an honest chain that originally verified:
    the injected envelope either (a) won't carry a valid signature for
    its claimed pubkey, or (b) breaks the parent-hash linkage of the
    next real envelope. Either condition makes verify_chain fail.
    """
    if injected_index < 0 or injected_index > len(chain):
        raise IndexError(
            f"injected_index {injected_index} out of range for chain "
            f"of length {len(chain)}"
        )

    template = chain[0] if chain else None
    fake = ICPEnvelope(
        intent_id=(template.intent_id if template else "fake-intent"),
        action_id="act-fake",
        agent_pubkey="00" * 32,
        capability_manifest_hash="00" * 32,
        input_hashes=["ff" * 32],
        output_hash="ff" * 32,
        parent_envelope_hash=(
            compute_envelope_hash(chain[injected_index - 1])
            if injected_index > 0
            else None
        ),
        timestamp_ns=time.time_ns(),
        inference_backend="mock",
        model_identifier="injected",
        duration_ms=0,
        tokens_in=0,
        tokens_out=0,
        signature="ab" * 32,  # not a real signature
    )

    spliced = list(chain)
    spliced.insert(injected_index, fake)
    valid, _ = verify_chain(spliced)
    return not valid


class ICPSigner:
    def __init__(
        self,
        private_key_seed: bytes,
        agent_pubkey_hex: str,
        capability_manifest_hash: str,
    ):
        if len(private_key_seed) != 32:
            raise ValueError(
                f"private_key_seed must be 32 bytes, got {len(private_key_seed)}"
            )
        # Cross-check that the supplied pubkey hex matches the seed —
        # a mismatch here would silently produce envelopes nobody can verify.
        sk = Ed25519PrivateKey.from_private_bytes(private_key_seed)
        derived = sk.public_key().public_bytes_raw().hex()
        if derived != agent_pubkey_hex:
            raise ValueError(
                "agent_pubkey_hex does not match private_key_seed; refusing "
                "to sign with mismatched identity"
            )
        self._seed = private_key_seed
        self._pubkey_hex = agent_pubkey_hex
        self._manifest_hash = capability_manifest_hash

    def sign_action(
        self,
        intent_id: str,
        action_id: str,
        input_hashes: list[str],
        output_hash: str,
        parent_envelope: ICPEnvelope | None,
        inference_backend: str,
        model_identifier: str,
        duration_ms: int,
        tokens_in: int,
        tokens_out: int,
    ) -> ICPEnvelope:
        env = ICPEnvelope(
            intent_id=intent_id,
            action_id=action_id,
            agent_pubkey=self._pubkey_hex,
            capability_manifest_hash=self._manifest_hash,
            input_hashes=list(input_hashes),
            output_hash=output_hash,
            parent_envelope_hash=(
                compute_envelope_hash(parent_envelope)
                if parent_envelope is not None
                else None
            ),
            timestamp_ns=time.time_ns(),
            inference_backend=inference_backend,
            model_identifier=model_identifier,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return sign_envelope(env, self._seed)


def explain_chain_failure(envelopes: list[ICPEnvelope]) -> str:
    """
    Human-readable trace of where verify_chain breaks and why.
    Used by demos/tests — not load-bearing for correctness.
    """
    lines: list[str] = []
    lines.append(f"chain length: {len(envelopes)}")
    for i, env in enumerate(envelopes):
        prefix = f"  [{i}] action={env.action_id} pk={env.agent_pubkey[:8]}…"
        pk = _pubkey_bytes_of(env)
        if pk is None or len(pk) != 32:
            lines.append(f"{prefix}  ✘ pubkey not 32-byte hex")
            return "\n".join(lines)
        if not verify_envelope(env, pk):
            lines.append(f"{prefix}  ✘ signature invalid for declared pubkey")
            return "\n".join(lines)
        if i == 0:
            if env.parent_envelope_hash is not None:
                lines.append(
                    f"{prefix}  ✘ first hop must have parent_envelope_hash=None"
                )
                return "\n".join(lines)
            lines.append(f"{prefix}  ✓ root hop (parent=None) — sig OK")
            continue
        expected = compute_envelope_hash(envelopes[i - 1])
        if env.parent_envelope_hash != expected:
            lines.append(
                f"{prefix}  ✘ parent_envelope_hash mismatch:\n"
                f"        declared {env.parent_envelope_hash}\n"
                f"        expected {expected}\n"
                f"        → predecessor at [{i-1}] was tampered with or replaced"
            )
            return "\n".join(lines)
        if not env.input_hashes:
            lines.append(f"{prefix}  ✘ input_hashes empty (chain cannot read nothing)")
            return "\n".join(lines)
        lines.append(f"{prefix}  ✓ sig OK, parent linkage OK")
    lines.append("chain verified end-to-end")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-machine verification (Phase 2)
# ---------------------------------------------------------------------------

def verify_chain_multi_compositor(
    envelopes: list[ICPEnvelope],
    trust_registry,
    artifact_store,
) -> tuple[bool, int, str]:
    """Walk a chain whose hops may originate from agents under different
    compositors. Returns (valid, first_invalid_index, reason).

    Per hop:
      1. Manifest bytes fetched from artifact_store by capability_manifest_hash.
      2. Manifest's compositor_pubkey is in trust_registry and not revoked.
      3. Manifest's compositor signature verifies.
      4. Manifest's agent_id matches envelope.agent_pubkey.
      5. Envelope signature verifies under that agent_pubkey.
      6. parent_envelope_hash matches BLAKE3 of envelopes[i-1] (or None for first).
      7. input_hashes is non-empty AND every input artifact exists.
      8. Output artifact exists in artifact_store.
    """
    for i, env in enumerate(envelopes):
        manifest_bytes = artifact_store.get(env.capability_manifest_hash)
        if manifest_bytes is None:
            return False, i, (
                f"capability manifest "
                f"{env.capability_manifest_hash[:16]} not in artifact store"
            )
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return False, i, f"manifest decode failed: {e}"

        ok, reason = trust_registry.verify_manifest_from_trusted_compositor(
            manifest,
        )
        if not ok:
            return False, i, reason

        if manifest.get("agent_id") != env.agent_pubkey:
            return False, i, (
                "manifest.agent_id does not match envelope.agent_pubkey"
            )

        try:
            agent_pk = bytes.fromhex(env.agent_pubkey)
        except ValueError:
            return False, i, "agent_pubkey is not valid hex"
        if len(agent_pk) != 32:
            return False, i, "agent_pubkey wrong length"
        if not verify_envelope(env, agent_pk):
            return False, i, "envelope signature invalid"

        if i == 0:
            if env.parent_envelope_hash is not None:
                return False, i, "first hop must have parent_envelope_hash=None"
        else:
            expected = compute_envelope_hash(envelopes[i - 1])
            if env.parent_envelope_hash != expected:
                return False, i, "parent_envelope_hash linkage broken"

        if not env.input_hashes:
            return False, i, "input_hashes empty"
        for ih in env.input_hashes:
            if not artifact_store.exists(ih):
                return False, i, (
                    f"input artifact {ih[:16]} not in artifact store"
                )

        if not artifact_store.exists(env.output_hash):
            return False, i, (
                f"output artifact {env.output_hash[:16]} not in artifact store"
            )

    return True, -1, "ok"


def generate_chain_report(
    envelopes: list[ICPEnvelope],
    trust_registry,
    artifact_store,
) -> str:
    """Human-readable report. Used by demos and the compositor card UI."""
    sep_thick = "═" * 60
    sep_thin = "─" * 60

    # Count distinct compositors so the header summarizes the cross-
    # machine span. We have to look up each manifest to learn the
    # compositor key; cache the results to avoid double-fetching.
    compositors_per_hop: list[str] = []
    manifests_per_hop: list[dict | None] = []
    for env in envelopes:
        mb = artifact_store.get(env.capability_manifest_hash)
        if mb is None:
            compositors_per_hop.append("?")
            manifests_per_hop.append(None)
            continue
        try:
            m = json.loads(mb.decode("utf-8"))
            compositors_per_hop.append(str(m.get("compositor_pubkey", "?")))
            manifests_per_hop.append(m)
        except Exception:
            compositors_per_hop.append("?")
            manifests_per_hop.append(None)
    distinct = len({c for c in compositors_per_hop if c != "?"})

    valid, first_bad, reason = verify_chain_multi_compositor(
        envelopes, trust_registry, artifact_store,
    )

    lines: list[str] = []
    lines.append(sep_thick)
    lines.append("ICP CHAIN VERIFICATION REPORT")
    lines.append(
        f"Chain length: {len(envelopes)} hops across {distinct} compositors"
    )
    lines.append(sep_thin)
    for i, env in enumerate(envelopes):
        comp_pk = compositors_per_hop[i]
        comp_short = (comp_pk[:16] + "...") if comp_pk and comp_pk != "?" else "?"
        trusted = trust_registry.is_trusted(comp_pk) if comp_pk != "?" else False
        trust_marker = "[TRUSTED ✓]" if trusted else "[UNTRUSTED ✗]"

        # Inputs / signature status — re-derive from the same checks as
        # verify_chain_multi_compositor so the report and the verdict
        # never disagree.
        input_count = len(env.input_hashes)
        inputs_ok = (
            input_count > 0 and
            all(artifact_store.exists(h) for h in env.input_hashes)
        )
        try:
            agent_pk = bytes.fromhex(env.agent_pubkey)
            sig_ok = (len(agent_pk) == 32) and verify_envelope(env, agent_pk)
        except ValueError:
            sig_ok = False

        lines.append(f"Hop {i + 1}: {env.action_id}")
        lines.append(f"  Agent:      {env.agent_pubkey[:16]}...")
        lines.append(f"  Compositor: {comp_short} {trust_marker}")
        lines.append(
            f"  Inputs:     {input_count} artifacts "
            f"{'verified ✓' if inputs_ok else 'MISSING ✗'}"
        )
        lines.append(f"  Output:     {env.output_hash[:16]}...")
        lines.append(f"  Signature:  {'VALID ✓' if sig_ok else 'INVALID ✗'}")
        lines.append(
            f"  Duration:   {env.duration_ms}ms via {env.inference_backend}"
        )
        lines.append(sep_thin)

    if valid:
        verdict = "CHAIN INTEGRITY: VALID ✓"
    else:
        verdict = f"CHAIN INTEGRITY: BROKEN at hop {first_bad + 1}: {reason}"
    lines.append(verdict)

    # Full chain root: BLAKE3 of every envelope hash concatenated.
    concat = b"".join(
        bytes.fromhex(compute_envelope_hash(e)) for e in envelopes
    )
    root = blake3.blake3(concat).hexdigest()
    lines.append(f"Full chain root: {root}")
    lines.append(sep_thick)
    return "\n".join(lines)


# Re-export so callers do `from gyza.icp import ICPEnvelope` cleanly.
__all__ = [
    "ICPEnvelope",
    "ICPSigner",
    "compute_envelope_hash",
    "sign_envelope",
    "verify_envelope",
    "verify_chain",
    "verify_dag",
    "DagVerification",
    "verify_chain_multi_compositor",
    "generate_chain_report",
    "injection_breaks_chain",
    "explain_chain_failure",
]

# Silence unused-import warnings for `field` if a downstream linter
# trims the cryptography re-exports.
_ = field
