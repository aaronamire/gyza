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
