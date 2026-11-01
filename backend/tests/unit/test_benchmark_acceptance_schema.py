"""AcceptanceConfig mode and RunOutcome observational (phase 9)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from tokenpilot.schemas.benchmarks import AcceptanceConfig, RunOutcome


def test_acceptance_config_default_mode_is_command() -> None:
    cfg = AcceptanceConfig(command=["pytest", "-q"])
    assert cfg.mode == "command"


def test_acceptance_config_command_mode_empty_command_raises() -> None:
    with pytest.raises(ValidationError):
        AcceptanceConfig(mode="command", command=[])


def test_acceptance_config_command_mode_non_empty_command_ok() -> None:
    cfg = AcceptanceConfig(mode="command", command=["npm", "test"])
    assert cfg.mode == "command"
    assert cfg.command == ["npm", "test"]


def test_acceptance_config_metrics_only_empty_command_ok() -> None:
    cfg = AcceptanceConfig(mode="metrics_only", command=[])
    assert cfg.mode == "metrics_only"
    assert cfg.command == []


def test_run_outcome_accepts_observational() -> None:
    adapter = TypeAdapter(RunOutcome)
    assert adapter.validate_python("observational") == "observational"
