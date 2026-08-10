"""Verification layer — BUILD_PLAN §3.3 (V-1 … V-5)."""
from gyza.verification.registry import (
    AuthorshipError, PartialSpec, PartialSpecRegistry, RegistryVersionError,
    Verifier, VerifierRegistry,
)
from gyza.verification.router import CutoverPolicy, Routing, TierRouter
from gyza.verification.specs import SpecStrength, evaluate_spec_strength
from gyza.verification.scheduler import ChainDecision, consult_tier_algebra

__all__ = [
    "Verifier", "VerifierRegistry", "PartialSpec", "PartialSpecRegistry",
    "AuthorshipError", "RegistryVersionError",
    "TierRouter", "Routing", "CutoverPolicy",
    "SpecStrength", "evaluate_spec_strength",
    "consult_tier_algebra", "ChainDecision",
]
