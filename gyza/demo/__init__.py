"""
gyza.demo — runnable demonstrations of Gyza's core properties.

This package hosts self-contained, narratable scenarios. The flagship
is ``gyza.demo.ddil_partition`` — a five-node DDIL (Denied, Degraded,
Intermittent, Limited) partition story that exercises the *real*
safety verifiers (``enforcement_satisfies_manifest`` and
``verify_delegation``) and the *real* ICP chain verifier
(``verify_chain``) end to end.

The supporting components — a content-addressed CRDT coordination
plane, an anti-entropy gossip mechanism, and a quorum-gated control
plane — live alongside it so the scenario reads top to bottom without
reaching into production wiring. Nothing here modifies the signed ICP
envelope schema or the brick-3 signing gate; both are consumed, never
changed.
"""
from __future__ import annotations

__all__: list[str] = []
