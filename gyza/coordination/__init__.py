"""Coordination layer — BUILD_PLAN §3.4 (K-1 … K-8), partial."""
from gyza.coordination.task import TaskResult, TaskSpec, Termination
from gyza.coordination.orchestrator import (
    Combination, Combiner, EscalationItem, EscalationQueue, ExecutorPool,
    DEFAULT_DECOMPOSITION_BASIS, DEFAULT_DECOMPOSITION_STRATEGY,
    DEFAULT_RETRY_BASIS, DEFAULT_RETRY_POLICY, RetryPolicy,
    DecompositionStrategy,
    NotSelectedError, RunMetrics, Scheduler, alarms, allocate, decompose,
    retry_policy,
)

__all__ = [
    "TaskSpec", "TaskResult", "Termination",
    "Scheduler", "Combiner", "Combination", "ExecutorPool",
    "EscalationQueue", "EscalationItem", "RunMetrics", "alarms",
    "NotSelectedError", "decompose", "allocate", "retry_policy",
    "DecompositionStrategy", "DEFAULT_DECOMPOSITION_STRATEGY",
    "DEFAULT_DECOMPOSITION_BASIS",
    "RetryPolicy", "DEFAULT_RETRY_POLICY", "DEFAULT_RETRY_BASIS",
]
