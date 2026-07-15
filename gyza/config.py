"""
Gyza configuration.

A single dataclass holds the tunables that callers (CLI, demos, runners)
need at startup. JSON file at ~/.gyza/config.json overrides defaults.
Environment variables override JSON for sensitive values.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path


def _resolve(p: str) -> str:
    return os.path.expanduser(p)


@dataclass
class GyzaConfig:
    blackboard_db_path: str = "~/.gyza/blackboard.db"
    memory_db_path: str = "~/.gyza/memory.db"
    compositor_key_path: str = "~/.gyza/compositor.key"
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    default_model: str = "claude-sonnet-4-5"
    poll_interval_s: float = 1.0
    spawn_threshold: float = 5.0
    drift_rate: float = 0.03
    lsh_planes: int = 64
    inflation_halflife_s: float = 30.0
    # Phase-2 networking.
    quic_port: int = 7749
    artifact_port: int = 7750
    raft_port: int = 8749
    manual_peers: list[str] = field(default_factory=list)
    max_artifact_store_gb: float = 10.0
    # Phase-3 networking — gyza-netd lifecycle and global participation.
    netd_socket_path: str = "~/.gyza/netd.sock"
    # Bare name → resolved on PATH, else auto-detected from a source
    # checkout (<repo>/netd/bin/gyza-netd) by NetdClient.start_daemon.
    # Set an absolute path here to override.
    netd_binary_path: str = "gyza-netd"
    netd_listen_port: int = 7749
    netd_bootstrap_peers: list[str] = field(default_factory=list)
    netd_ledger_db_path: str = "~/.gyza/ledger.db"
    enable_relay: bool = False
    attestation_tier: int = 1
    # Above this debt level, the runner refuses additional remote work for
    # the offending peer until reconciliation/settlement clears the gap.
    # Pure local guidance — peers compute their own thresholds.
    max_compute_debt_credits: float = 100.0
    # When True (and a content-addressed artifact store is attached), the
    # payer independently audits the delivered work — from evidence the
    # earner ships with settlement — before cosigning, and declines to
    # pay for work that doesn't audit clean. The mechanism that makes a
    # credit certify verified bounded labor rather than a mere claim.
    # Has no effect where no artifact store is present (legacy path).
    settlement_audit_before_cosign: bool = True

    def resolved_paths(self) -> dict[str, str]:
        return {
            "blackboard_db_path": _resolve(self.blackboard_db_path),
            "memory_db_path": _resolve(self.memory_db_path),
            "compositor_key_path": _resolve(self.compositor_key_path),
            "netd_socket_path": _resolve(self.netd_socket_path),
            "netd_binary_path": _resolve(self.netd_binary_path),
            "netd_ledger_db_path": _resolve(self.netd_ledger_db_path),
        }


def load_config(path: str = "~/.gyza/config.json") -> GyzaConfig:
    p = Path(_resolve(path))
    cfg = GyzaConfig()
    if not p.exists():
        return cfg
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    valid = {f.name for f in fields(cfg)}
    for k, v in data.items():
        if k in valid:
            setattr(cfg, k, v)
    # Env override for the API key — never commit a key to the JSON.
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        cfg.anthropic_api_key = env_key
    return cfg


__all__ = ["GyzaConfig", "load_config"]
