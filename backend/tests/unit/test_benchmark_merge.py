"""RunConfig merge and allow_outside_paths (phase 10)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tokenpilot.schemas.benchmarks import AlternativeSpec, RunConfig, merge_variant_config

_BASELINE = RunConfig(
    model_id="fake-large",
    max_steps=12,
)


def test_run_config_defaults_allow_outside_paths_false() -> None:
    assert _BASELINE.allow_outside_paths is False


def test_merge_variant_config_overlays_allow_outside_paths_and_context_files() -> None:
    spec = AlternativeSpec(
        name="targeted-alt",
        changes={
            "allow_outside_paths": True,
            "model_id": "alt-model",
            "context_strategy": "targeted",
        },
        context_files=["docs/"],
    )
    merged = merge_variant_config(_BASELINE, spec)
    assert merged["allow_outside_paths"] is True
    assert merged["model_id"] == "alt-model"
    assert merged["context_strategy"] == "targeted"
    assert merged["context_files"] == ["docs/"]


def test_merge_variant_config_rejects_invalid_allow_outside_paths_type() -> None:
    spec = AlternativeSpec(
        name="bad",
        changes={"allow_outside_paths": "not-a-bool"},
    )
    with pytest.raises(ValidationError):
        merge_variant_config(_BASELINE, spec)
