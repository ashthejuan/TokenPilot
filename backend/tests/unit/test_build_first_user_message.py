"""Unit tests for build_first_user_message targeted expand + scope lines."""

from pathlib import Path

from tokenpilot.benchmarks.agent import build_first_user_message
from tokenpilot.benchmarks.agent_tools import AgentTools
from tokenpilot.schemas.benchmarks import RunConfig


def _config(**overrides: object) -> RunConfig:
    base: dict[str, object] = {
        "model_id": "fake-large",
        "context_strategy": "targeted",
        "max_steps": 8,
        "retry_policy": {"max_retries": 0},
    }
    base.update(overrides)
    return RunConfig.model_validate(base)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("PKG_A = 1\n")
    (root / "pkg" / "sub" / "b.py").write_text("PKG_B = 2\n")
    (root / "root.py").write_text("ROOT = 3\n")
    (root / "other.py").write_text("OTHER = 4\n")
    (root / "big.bin").write_bytes(b"x" * (100 * 1024 + 1))
    (root / "nul.txt").write_bytes(b"ok\x00nope")
    return root


def test_targeted_empty_context_files_listing_only_no_scope(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tools = AgentTools(root)
    msg = build_first_user_message("Fix it.", _config(context_files=[]), tools)
    assert "Repository listing:" in msg
    assert "root.py" in msg
    assert "other.py" in msg
    assert "=== " not in msg
    assert "Perform operations only on:" not in msg
    assert "You may also read and write files outside:" not in msg


def test_targeted_dir_expands_recursively_skips_unusable(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "pkg" / "big.bin").write_bytes(b"y" * (100 * 1024 + 1))
    (root / "pkg" / "nul.txt").write_bytes(b"a\x00b")
    tools = AgentTools(root)
    msg = build_first_user_message(
        "Fix it.",
        _config(context_files=["pkg"], allow_outside_paths=False),
        tools,
    )
    assert "=== pkg/a.py ===\nPKG_A = 1\n" in msg
    assert "=== pkg/sub/b.py ===\nPKG_B = 2\n" in msg
    assert "=== pkg ===" not in msg
    assert "PKG_B" in msg
    assert "ROOT =" not in msg
    assert "OTHER =" not in msg
    assert "=== pkg/big.bin ===" not in msg
    assert "=== pkg/nul.txt ===" not in msg


def test_targeted_allow_outside_false_scoped_listing_and_scope_line(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    tools = AgentTools(root)
    msg = build_first_user_message(
        "Fix it.",
        _config(context_files=["pkg", "root.py"], allow_outside_paths=False),
        tools,
    )
    listing = msg.split("Repository listing:\n", 1)[1].split("\n\n", 1)[0]
    assert "pkg/a.py" in listing
    assert "pkg/sub/b.py" in listing
    assert "root.py" in listing
    assert "other.py" not in listing
    assert msg.rstrip().endswith("Perform operations only on: pkg, root.py.")
    assert "You may also read and write files outside:" not in msg


def test_targeted_allow_outside_true_full_listing_and_scope_line(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    tools = AgentTools(root)
    msg = build_first_user_message(
        "Fix it.",
        _config(context_files=["pkg"], allow_outside_paths=True),
        tools,
    )
    listing = msg.split("Repository listing:\n", 1)[1].split("\n\n", 1)[0]
    assert "other.py" in listing
    assert "root.py" in listing
    assert "pkg/a.py" in listing
    assert "=== pkg/a.py ===" in msg
    assert "ROOT =" not in msg  # not inlined; only listed
    assert msg.rstrip().endswith("You may also read and write files outside: pkg.")
    assert "Perform operations only on:" not in msg
