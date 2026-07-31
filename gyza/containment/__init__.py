"""
Containment layer — BUILD_PLAN §3.2 (C-1 … C-4).

The design is not free-form: every element traces to a measured constraint.

  C-1 harm registry     quantity is a PURE FUNCTION OF STATE, never of guard
                        state (discipline #5); the frame is declared and its
                        mutability is declared (C3); the bound is LOADED, never
                        invented, and an unset bound FAILS CLOSED (D1).
  C-2 invariant registry every invariant carries a class tag; untagged is
                        rejected at load. The tag is read by the scheduler to
                        decide concurrency (C6/C7), so it is machinery, not
                        documentation.
  C-3 reversibility     a STATIC TABLE over the action vocabulary, never a
                        prediction (C10). Unknown action type => IRREVERSIBLE.
  C-4 guard engine      evaluates per state transition, per action, invoking
                        THE SAME function the harm measure uses (C3).
  S1  append-only log   the ledger pattern with the domain removed: append-only,
                        partitioned, derived-not-stored, hash-chained.
  C-5 staging area      the reversible interior; nothing is visible outside it
                        until promotion.
  C-6 promotion gate    batched and SERIALIZED -- simultaneously the
                        irreversibility gate and the serialization point that
                        cumulative bounding requires (C7). The same place by
                        necessity, not convenience.
  C-7 rollback          returns the interior to the last promotion. Abandoned
                        events REMAIN in the log, so content survives (C9).
  C-8 guard config      signed by an authority the constrained system does not
                        hold a key for. If the agent can rewrite the invariant,
                        the induction has no base case.

The frame-alignment guarantee is structural here, not a convention: an
invariant never receives raw state to measure. It receives the harm value the
registry computed, so there is no second frame for it to drift against. R9's
G4' pinned its frame and lost 175000 where G4 bounded at 50; this layer makes
that class of mistake unrepresentable.
"""
from gyza.containment.harm import (
    HarmClass, HarmModelRegistry, UnsetBoundError,
)
from gyza.containment.invariants import (
    Invariant, InvariantClass, InvariantRegistry, UntaggedInvariantError,
)
from gyza.containment.reversibility import Reversibility, ReversibilityTable
from gyza.containment.engine import Decision, GuardEngine, Phase
from gyza.containment.guardconfig import (
    GuardConfigError, GuardConfigStore, VerifiedGuardConfig, sign_config,
    verify_config,
)
from gyza.containment.log import AppendOnlyLog, Event
from gyza.containment.staging import (
    Escalation, NotInteriorError, PromotionGate, PromotionResult, StagingArea,
)

__all__ = [
    "HarmClass", "HarmModelRegistry", "UnsetBoundError",
    "Invariant", "InvariantClass", "InvariantRegistry",
    "UntaggedInvariantError",
    "Reversibility", "ReversibilityTable",
    "Decision", "GuardEngine", "Phase",
    "AppendOnlyLog", "Event",
    "StagingArea", "PromotionGate", "PromotionResult", "Escalation",
    "NotInteriorError",
    "GuardConfigStore", "VerifiedGuardConfig", "GuardConfigError",
    "sign_config", "verify_config",
]
