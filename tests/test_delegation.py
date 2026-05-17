"""
Compositional-boundedness tests.

The keystone is `test_capability_laundering_is_blocked`: a
subcontractor that honestly stayed inside its OWN manifest must
still be rejected when that manifest is wider than what its parent
was allowed to delegate. If that single property fails, the entire
"bounds compose upward" claim — and the safety of the whole
agentic-civilization vision — is false.
"""
from __future__ import annotations

from gyza.economy.delegation import (
    MAX_DELEGATION_DEPTH,
    CapabilitySpec,
    DelegationHop,
    capability_subset,
    spec_from_enforcement,
    spec_from_manifest,
    verify_delegation,
)


def S(ro=(), rw=(), network=False, mem=None) -> CapabilitySpec:
    return CapabilitySpec(
        ro=frozenset(ro), rw=frozenset(rw), network=network, mem_cap=mem
    )


# ----------------------------------------------------------------------
# capability_subset — per dimension
# ----------------------------------------------------------------------

def test_subset_identical_and_tighter_pass():
    assert capability_subset(S(["/tmp"]), S(["/tmp"])) == (True, "")
    assert capability_subset(S([], [], False, 256),
                             S(["/tmp"], ["/tmp"], True, 512)) == (True, "")


def test_subset_wider_read_write_network_fail():
    ok, why = capability_subset(S(["/tmp", "/etc"]), S(["/tmp"]))
    assert not ok and "read paths exceed" in why
    ok, why = capability_subset(S([], ["/x"]), S([], []))
    assert not ok and "write paths exceed" in why
    ok, why = capability_subset(S(network=True), S(network=False))
    assert not ok and "network" in why


def test_memory_asymmetry():
    # outer has a cap → inner must declare one, ≤ it
    assert capability_subset(S(mem=256), S(mem=512))[0] is True
    assert capability_subset(S(mem=512), S(mem=512))[0] is True       # equal ok
    ok, why = capability_subset(S(mem=1024), S(mem=512))
    assert not ok and "exceeds the granted cap" in why
    ok, why = capability_subset(S(mem=None), S(mem=512))
    assert not ok and "declares no cap" in why                        # omission ≠ bypass
    # outer has NO cap → inner unconstrained on memory
    assert capability_subset(S(mem=99999), S(mem=None))[0] is True


# ----------------------------------------------------------------------
# spec projection
# ----------------------------------------------------------------------

def test_spec_from_manifest_and_enforcement():
    m = {
        "capabilities": {
            "filesystem": {"read": ["/a"], "write": ["/b"]},
            "network": {"allowed_hosts": ["api.x"]},
            "spawn": {"resource_budget": {"memory_limit_mb": 512}},
        }
    }
    s = spec_from_manifest(m)
    assert s == S(["/a"], ["/b"], True, 512)

    e = {"ro_paths": ["/a"], "rw_paths": [], "requires_network": False,
         "max_memory_mb": 256}
    assert spec_from_enforcement(e) == S(["/a"], [], False, 256)

    # malformed manifest → empty (nothing authorized) — safest failure
    assert spec_from_manifest({}) == S()
    # missing enforcement record → most-permissive (caller's subset
    # check will reject it against any real grant)
    perm = spec_from_enforcement(None)  # type: ignore[arg-type]
    assert perm.network is True


# ----------------------------------------------------------------------
# verify_delegation — structure
# ----------------------------------------------------------------------

def test_empty_chain_fails():
    ok, why = verify_delegation([])
    assert not ok and "empty" in why


def test_single_root_in_bounds_passes():
    root = DelegationHop("A", manifest=S(["/tmp"], mem=512),
                         enforcement=S(["/tmp"], mem=256))
    assert verify_delegation([root]) == (True, "")


def test_root_with_delegated_grant_is_rejected():
    root = DelegationHop("A", manifest=S(["/tmp"]),
                         enforcement=S(["/tmp"]), delegated=S(["/tmp"]))
    ok, why = verify_delegation([root])
    assert not ok and "root hop must not carry a delegated grant" in why


def test_root_enforcement_exceeding_manifest_fails():
    root = DelegationHop("A", manifest=S(["/tmp"]),
                         enforcement=S(["/tmp", "/etc"]))
    ok, why = verify_delegation([root])
    assert not ok and "hop 0: enforcement exceeds manifest" in why


def test_valid_two_hop_delegation_passes():
    root = DelegationHop("A", manifest=S(["/tmp", "/data"], mem=512),
                         enforcement=S(["/tmp"], mem=256))
    child = DelegationHop(
        "B",
        manifest=S(["/tmp"], mem=256),
        enforcement=S(["/tmp"], mem=128),
        delegated=S(["/tmp"], mem=256),     # ⊆ A.manifest, ⊇ B.manifest
    )
    assert verify_delegation([root, child]) == (True, "")


# ----------------------------------------------------------------------
# THE keystone — capability laundering
# ----------------------------------------------------------------------

def test_capability_laundering_is_blocked():
    # A may only touch /tmp. A delegates exactly /tmp (within its
    # bounds — A is honest). But B's OWN manifest is /tmp+/etc, and B
    # honestly ran inside its own manifest (enforcement ⊆ B.manifest).
    # Naive per-node checks (B stayed in B's manifest) would PASS.
    # Compositionality must catch it: B.manifest ⊄ what A delegated.
    root = DelegationHop("A", manifest=S(["/tmp"]),
                         enforcement=S(["/tmp"]))
    laundering = DelegationHop(
        "B",
        manifest=S(["/tmp", "/etc"]),          # B's own (wide) manifest
        enforcement=S(["/tmp", "/etc"]),       # B honestly used it all
        delegated=S(["/tmp"]),                 # but A only granted /tmp
    )
    ok, why = verify_delegation([root, laundering])
    assert not ok
    assert "capability-laundering blocked" in why
    assert "manifest exceeds what the parent delegated" in why


def test_parent_cannot_delegate_more_than_it_holds():
    root = DelegationHop("A", manifest=S(["/tmp"]),
                         enforcement=S(["/tmp"]))
    child = DelegationHop(
        "B",
        manifest=S(["/tmp", "/etc"]),
        enforcement=S(["/tmp", "/etc"]),
        delegated=S(["/tmp", "/etc"]),         # A granted /etc it never had
    )
    ok, why = verify_delegation([root, child])
    assert not ok and "parent delegated more than it held" in why


def test_non_root_missing_delegated_grant_fails():
    root = DelegationHop("A", manifest=S(["/tmp"]), enforcement=S(["/tmp"]))
    child = DelegationHop("B", manifest=S(["/tmp"]), enforcement=S(["/tmp"]))
    ok, why = verify_delegation([root, child])
    assert not ok and "missing its delegated grant" in why


# ----------------------------------------------------------------------
# cycle + depth (runaway / mutual-farm guards)
# ----------------------------------------------------------------------

def test_delegation_cycle_blocked():
    a = DelegationHop("A", manifest=S(["/tmp"]), enforcement=S(["/tmp"]))
    b = DelegationHop("B", manifest=S(["/tmp"]), enforcement=S(["/tmp"]),
                      delegated=S(["/tmp"]))
    a2 = DelegationHop("A", manifest=S(["/tmp"]), enforcement=S(["/tmp"]),
                       delegated=S(["/tmp"]))    # A again — cycle
    ok, why = verify_delegation([a, b, a2])
    assert not ok and "cycle" in why


def test_depth_bound_blocked():
    chain = [DelegationHop("A0", manifest=S(["/tmp"]),
                           enforcement=S(["/tmp"]))]
    for i in range(1, MAX_DELEGATION_DEPTH + 2):
        chain.append(DelegationHop(
            f"A{i}", manifest=S(["/tmp"]), enforcement=S(["/tmp"]),
            delegated=S(["/tmp"])))
    ok, why = verify_delegation(chain)
    assert not ok and "exceeds max" in why


# ----------------------------------------------------------------------
# transitive memory composition — a capped ancestor binds all heirs
# ----------------------------------------------------------------------

def test_capped_ancestor_forces_descendants_capped_lower():
    root = DelegationHop("A", manifest=S(["/t"], mem=512),
                         enforcement=S(["/t"], mem=512))
    mid = DelegationHop("B", manifest=S(["/t"], mem=512),
                        enforcement=S(["/t"], mem=400),
                        delegated=S(["/t"], mem=512))
    # leaf tries 1024 — exceeds every ancestor; must fail at the
    # manifest ⊆ delegated edge.
    leaf_bad = DelegationHop("C", manifest=S(["/t"], mem=1024),
                             enforcement=S(["/t"], mem=1024),
                             delegated=S(["/t"], mem=512))
    ok, why = verify_delegation([root, mid, leaf_bad])
    assert not ok and "exceeds the granted cap" in why

    # a mid that drops the cap under a capped root must fail
    mid_uncapped = DelegationHop("B", manifest=S(["/t"], mem=None),
                                 enforcement=S(["/t"], mem=None),
                                 delegated=S(["/t"], mem=512))
    ok, why = verify_delegation([root, mid_uncapped])
    assert not ok and "declares no cap" in why

    # fully valid 3-level chain with strictly-tightening caps
    leaf_ok = DelegationHop("C", manifest=S(["/t"], mem=200),
                            enforcement=S(["/t"], mem=128),
                            delegated=S(["/t"], mem=400))
    assert verify_delegation([root, mid, leaf_ok]) == (True, "")


# ----------------------------------------------------------------------
# DelegationGrant — the signed wire record
# ----------------------------------------------------------------------
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

from gyza.economy.delegation import (  # noqa: E402
    DelegationGrant,
    grant_binds_to,
    grant_hash,
    sign_grant,
    verify_grant,
)


def _key(seed_byte: int):
    seed = bytes([seed_byte]) * 32
    pk = (Ed25519PrivateKey.from_private_bytes(seed)
          .public_key().public_bytes_raw().hex())
    return seed, pk


def _grant(parent_pk, *, auth=None, weh="env-h", mh="man-h",
           wid="W1", ts=1) -> DelegationGrant:
    return DelegationGrant(
        parent_envelope_hash=weh,
        parent_agent_pubkey=parent_pk,
        parent_manifest_hash=mh,
        child_work_item_id=wid,
        delegated_authority=(auth or S(["/tmp"], mem=256).to_canonical()),
        created_at_ns=ts,
    )


def test_grant_sign_verify_roundtrip():
    seed, pk = _key(1)
    g = sign_grant(_grant(pk), seed)
    assert g.signature
    assert verify_grant(g) == (True, "")


def test_grant_tamper_any_signed_field_fails():
    seed, pk = _key(2)
    g = sign_grant(_grant(pk), seed)
    from dataclasses import replace
    for mut in (
        {"child_work_item_id": "W2"},
        {"parent_envelope_hash": "other"},
        {"parent_manifest_hash": "other"},
        {"created_at_ns": 999},
        {"delegated_authority": S(["/tmp", "/etc"]).to_canonical()},
    ):
        bad = replace(g, **mut)               # signature carried over
        ok, why = verify_grant(bad)
        assert not ok, f"tamper {mut} not detected"
        assert "does not verify" in why


def test_grant_signed_by_wrong_key_fails():
    seed_a, _ = _key(3)
    _, pk_b = _key(4)
    g = sign_grant(_grant(pk_b), seed_a)      # claims B, signed by A
    ok, why = verify_grant(g)
    assert not ok and "does not verify" in why


def test_grant_unsigned_and_malformed_fail():
    _, pk = _key(5)
    assert verify_grant(_grant(pk))[0] is False           # unsigned
    bad = DelegationGrant("e", "nothex", "m", "W", {}, 1, 1, "zz")
    assert verify_grant(bad)[0] is False                  # non-hex


def test_grant_binding_defends_replay_and_decoupling():
    seed, pk = _key(6)
    g = sign_grant(_grant(pk, weh="EH", mh="MH", wid="W1"), seed)
    ok, why = grant_binds_to(
        g, parent_envelope_hash="EH", parent_agent_pubkey=pk,
        parent_capability_manifest_hash="MH", child_work_item_id="W1")
    assert ok, why
    # each mismatch is its own defense
    assert not grant_binds_to(
        g, parent_envelope_hash="OTHER", parent_agent_pubkey=pk,
        parent_capability_manifest_hash="MH", child_work_item_id="W1")[0]
    assert not grant_binds_to(
        g, parent_envelope_hash="EH", parent_agent_pubkey="OTHER",
        parent_capability_manifest_hash="MH", child_work_item_id="W1")[0]
    ok, why = grant_binds_to(
        g, parent_envelope_hash="EH", parent_agent_pubkey=pk,
        parent_capability_manifest_hash="OTHER", child_work_item_id="W1")
    assert not ok and "decoupling" in why
    ok, why = grant_binds_to(
        g, parent_envelope_hash="EH", parent_agent_pubkey=pk,
        parent_capability_manifest_hash="MH", child_work_item_id="W2")
    assert not ok and "replay" in why


def test_capability_spec_canonical_roundtrip_and_sort_determinism():
    s = CapabilitySpec(ro=frozenset(["/b", "/a"]),
                        rw=frozenset(["/z", "/y"]),
                        network=True, mem_cap=256)
    c = s.to_canonical()
    assert c["ro"] == ["/a", "/b"] and c["rw"] == ["/y", "/z"]  # sorted
    assert CapabilitySpec.from_canonical(c) == s

    # frozenset order must NOT affect the signed bytes: two logically
    # equal specs built from different insertion orders sign identically.
    seed, pk = _key(7)
    g1 = sign_grant(_grant(pk, auth=CapabilitySpec(
        ro=frozenset(["/a", "/b", "/c"])).to_canonical()), seed)
    g2 = sign_grant(_grant(pk, auth=CapabilitySpec(
        ro=frozenset(["/c", "/a", "/b"])).to_canonical()), seed)
    assert grant_hash(g1) == grant_hash(g2)
    assert g1.signature == g2.signature      # Ed25519 deterministic


def test_grant_slots_into_proven_delegation_floor():
    # The wire artifact's delegated_authority feeds DelegationHop.
    seed, pk = _key(8)
    delegated = S(["/tmp"], mem=256)
    g = sign_grant(_grant(pk, auth=delegated.to_canonical()), seed)
    assert verify_grant(g)[0]

    parent = DelegationHop(pk, manifest=S(["/tmp", "/x"], mem=512),
                           enforcement=S(["/tmp"], mem=256))
    granted = CapabilitySpec.from_canonical(g.delegated_authority)

    good_child = DelegationHop(
        "child", manifest=S(["/tmp"], mem=200),
        enforcement=S(["/tmp"], mem=128), delegated=granted)
    assert verify_delegation([parent, good_child]) == (True, "")

    laundering = DelegationHop(
        "child", manifest=S(["/tmp", "/etc"]),
        enforcement=S(["/tmp", "/etc"]), delegated=granted)
    ok, why = verify_delegation([parent, laundering])
    assert not ok and "capability-laundering blocked" in why
