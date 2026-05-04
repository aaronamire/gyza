"""
Gyza data layer types.

WorkItem and Artifact are pure data containers — persistence belongs to
blackboard.py, signing/verification belongs to a future ICP module.

HLC implements the Kulkarni 2014 hybrid logical clock (Algorithm 1 from
"Logical Physical Clocks", Kulkarni et al. 2014). Physical component is
millisecond wall time; counter breaks ties when wall time hasn't advanced
since the last event.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np


EMBEDDING_DIM = 384


@dataclass
class WorkItem:
    id: str
    lineage_root: str
    parent_id: str | None
    description: str
    desc_embedding: np.ndarray
    reward: float
    reward_updated_ns: int
    required_tier: int
    input_hashes: list[str]
    output_spec: dict[str, Any]
    streaming_ok: bool
    claimed_by: str | None
    claimed_at_ns: int | None
    claim_hlc_l: int
    claim_hlc_c: int
    claim_hlc_node: str
    completed_at_ns: int | None
    output_hash: str | None
    icp_envelope_hash: str | None
    success: bool | None
    created_at_ns: int
    ttl_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.desc_embedding, np.ndarray):
            raise TypeError("desc_embedding must be np.ndarray")
        if self.desc_embedding.dtype != np.float32:
            raise TypeError(
                f"desc_embedding dtype must be float32, got {self.desc_embedding.dtype}"
            )
        if self.desc_embedding.shape != (EMBEDDING_DIM,):
            raise ValueError(
                f"desc_embedding shape must be ({EMBEDDING_DIM},), got {self.desc_embedding.shape}"
            )
        if not 0.0 <= self.reward <= 1.0:
            raise ValueError(f"reward must be in [0,1], got {self.reward}")
        if self.required_tier not in (0, 1, 2, 3):
            raise ValueError(f"required_tier must be 0..3, got {self.required_tier}")


@dataclass
class Artifact:
    hash: str
    data: bytes
    signature: str
    signer_pubkey: str
    parent_hashes: list[str]
    timestamp_ns: int


def _pt_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass
class HLC:
    """
    Kulkarni 2014 hybrid logical clock.

    `l` is millisecond wall time captured at the last event; `c` is the
    counter that disambiguates events sharing the same `l`. Both move
    monotonically forward — never reset on backwards wall-clock jumps.
    """
    node_id: str
    l: int = 0
    c: int = 0

    def now(self) -> tuple[int, int, str]:
        pt = _pt_ms()
        l_old = self.l
        self.l = max(l_old, pt)
        if self.l == l_old:
            self.c += 1
        else:
            self.c = 0
        return (self.l, self.c, self.node_id)

    def recv(self, l: int, c: int, node: str) -> None:
        pt = _pt_ms()
        l_old = self.l
        c_old = self.c
        self.l = max(l_old, l, pt)
        if self.l == l_old and self.l == l:
            self.c = max(c_old, c) + 1
        elif self.l == l_old:
            self.c = c_old + 1
        elif self.l == l:
            self.c = c + 1
        else:
            self.c = 0
