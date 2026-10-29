"""Unit tests for AgentTools: path-safe list/read/write with no shell."""

import os
from pathlib import Path

import pytest

from tokenpilot.benchmarks.agent_tools import AgentTools


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg" / "a.py").write_text("print('a')\n")
    (project / "README.md").write_text("# proj\n")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("[core]\n")
    return project


def test_list_files_sorted_relative_posix_excluding_git(root: Path) -> None:
    tools = AgentTools(root)
    assert tools.list_files() == ["README.md", "pkg/a.py"]


def test_read_file_returns_content(root: Path) -> None:
    tools = AgentTools(root)
    assert tools.read_file("pkg/a.py") == "print('a')\n"


def test_read_file_rejects_escape_paths(root: Path) -> None:
    tools = AgentTools(root)
    assert tools.read_file("../outside.py").startswith("Error: ")
    assert tools.read_file("/etc/hosts").startswith("Error: ")
    assert tools.read_file(".git/config").startswith("Error: ")


def test_read_file_missing_returns_error(root: Path) -> None:
    tools = AgentTools(root)
    assert tools.read_file("nope.py").startswith("Error: ")


def test_read_file_rejects_over_100kb(root: Path) -> None:
    big = root / "big.txt"
    big.write_text("x" * (100 * 1024 + 1))
    tools = AgentTools(root)
    result = tools.read_file("big.txt")
    assert result.startswith("Error: ")


def test_write_file_success_creates_parents(root: Path) -> None:
    tools = AgentTools(root)
    result = tools.write_file("new/dir/b.py", "print('b')\n")
    assert not result.startswith("Error: ")
    assert (root / "new" / "dir" / "b.py").read_text() == "print('b')\n"


def test_write_file_rejects_escape_paths(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = AgentTools(root)
    outside = tmp_path / "outside.py"
    etc_hosts = Path("/etc/hosts").read_text()
    link = root / "evil-link"
    link.symlink_to(outside)
    git_config = (root / ".git" / "config").read_text()

    assert tools.write_file("../outside.py", "pwned").startswith("Error: ")
    assert tools.write_file("/etc/hosts", "pwned").startswith("Error: ")
    assert tools.write_file("evil-link", "pwned").startswith("Error: ")
    assert tools.write_file(".git/config", "pwned").startswith("Error: ")

    assert not outside.exists()
    assert Path("/etc/hosts").read_text() == etc_hosts
    assert (root / ".git" / "config").read_text() == git_config
    monkeypatch.undo()  # fixture only documents no-cwd-dependence


def test_write_file_rejects_nested_git_dir(root: Path) -> None:
    tools = AgentTools(root)
    assert tools.write_file("a/.git/x", "pwned").startswith("Error: ")
    assert tools.write_file(".git", "pwned").startswith("Error: ")
    assert not (root / "a").exists()


def test_symlink_inside_root_is_allowed(root: Path) -> None:
    (root / "real.txt").write_text("real\n")
    (root / "link.txt").symlink_to(root / "real.txt")
    tools = AgentTools(root)
    assert tools.read_file("link.txt") == "real\n"


def test_git_rejection_is_case_insensitive(root: Path) -> None:
    # On case-insensitive APFS, ".Git/config" resolves onto ".git/config".
    tools = AgentTools(root)
    before = sorted(os.listdir(root))
    git_config = (root / ".git" / "config").read_text()
    for variant in (".Git/config", ".GIT/config", ".gIt/config", "a/.GIT/x"):
        assert tools.write_file(variant, "pwned").startswith("Error: "), variant
        assert tools.read_file(variant).startswith("Error: "), variant
    assert (root / ".git" / "config").read_text() == git_config
    assert sorted(os.listdir(root)) == before


def test_has_no_shell_tool(root: Path) -> None:
    tools = AgentTools(root)
    assert not hasattr(tools, "run_shell")
    assert not hasattr(tools, "shell")
    assert not hasattr(tools, "exec")
