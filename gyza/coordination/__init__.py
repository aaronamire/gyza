"""Coordination layer — BUILD_PLAN §3.4 (K-1 … K-8), partial."""
from gyza.coordination.task import TaskResult, TaskSpec, Termination
from gyza.coordination.orchestrator import (
    Combination, Combiner, EscalationItem, EscalationQueue, ExecutorPool,
    NotSelectedError, RunMetrics, Scheduler, alarms, allocate, decompose,
    retry_policy,
)

__all__ = [
    "TaskSpec", "TaskResult", "Termination",
    "Scheduler", "Combiner", "Combination", "ExecutorPool",
    "EscalationQueue", "EscalationItem", "RunMetrics", "alarms",
    "NotSelectedError", "decompose", "allocate", "retry_policy",
]
