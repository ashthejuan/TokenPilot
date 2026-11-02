"""Runner constructs AgentTools with scoped allowed_roots for targeted runs."""

from pathlib import Path

from tokenpilot.benchmarks.runner import agent_tools_for_run
from tokenpilot.schemas.benchmarks import RunConfig


def _config(**overrides: object) -> RunConfig:
    base: dict[str, object] = {
        "model_id": "fake-large",
        "context_strategy": "full_repo",
        "max_steps": 8,
        "retry_policy": {"max_retries": 0},
    }
    base.update(overrides)
    return RunConfig.model_validate(base)


def test_agent_tools_scoped_when_targeted_and_paths_locked(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    tools = agent_tools_for_run(
        root,
        _config(
            context_strategy="targeted",
            context_files=["pkg/a.py", "docs/"],
            allow_outside_paths=False,
        ),
    )
    assert tools._allowed_roots == ("pkg/a.py", "docs")


def test_agent_tools_unrestricted_for_full_repo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    tools = agent_tools_for_run(root, _config(context_strategy="full_repo"))
    assert tools._allowed_roots == ()


def test_agent_tools_unrestricted_when_allow_outside_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    tools = agent_tools_for_run(
        root,
        _config(
            context_strategy="targeted",
            context_files=["pkg/"],
            allow_outside_paths=True,
        ),
    )
    assert tools._allowed_roots == ()


def test_agent_tools_unrestricted_when_targeted_but_empty_context_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    tools = agent_tools_for_run(
        root,
        _config(
            context_strategy="targeted",
            context_files=[],
            allow_outside_paths=False,
        ),
    )
    assert tools._allowed_roots == ()
