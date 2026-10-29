"""Integration tests for git worktree isolation."""

import subprocess
from pathlib import Path

import pytest

from tokenpilot.benchmarks.agent_tools import AgentTools
from tokenpilot.benchmarks.worktree import (
    create_worktree,
    export_patch,
    remove_worktree,
    resolve_sha,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "fixture-repo"
    repo_path.mkdir()
    (repo_path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=repo_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
         "commit", "-m", "init"],
        cwd=repo_path, check=True, capture_output=True,
    )
    return repo_path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path


def _worktree_paths(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo,
        check=True, capture_output=True, text=True,
    )
    return [line for line in out.stdout.splitlines() if line.startswith("worktree ")]


def test_worktrees_start_from_same_sha_and_are_independent(
    repo: Path, data_dir: Path
) -> None:
    head = resolve_sha(repo, "HEAD")
    wt1 = create_worktree(repo, "HEAD", "run-1", data_dir=data_dir)
    wt2 = create_worktree(repo, "HEAD", "run-2", data_dir=data_dir)
    try:
        assert wt1.sha == head
        assert wt2.sha == head
        assert wt1.path == data_dir / "worktrees" / "run-1"
        assert wt2.path == data_dir / "worktrees" / "run-2"

        AgentTools(wt1.path).write_file("calc.py", "def add(a, b):\n    return 999\n")
        assert "999" in AgentTools(wt1.path).read_file("calc.py")
        assert "999" not in AgentTools(wt2.path).read_file("calc.py")
        assert "999" not in (repo / "calc.py").read_text()
    finally:
        remove_worktree(wt1)
        remove_worktree(wt2)


def test_patch_exported_and_worktree_removed(repo: Path, data_dir: Path) -> None:
    wt = create_worktree(repo, "HEAD", "run-patch", data_dir=data_dir)
    AgentTools(wt.path).write_file("calc.py", "def add(a, b):\n    return a - b\n")
    patch = export_patch(wt, data_dir=data_dir)
    try:
        assert patch == data_dir / "patches" / "run-patch.patch"
        text = patch.read_text()
        assert text.strip(), "patch must be non-empty"
        assert "calc.py" in text
    finally:
        remove_worktree(wt)
    assert not wt.path.exists()
    assert [w for w in _worktree_paths(repo) if "run-patch" in w] == []


def test_patch_includes_untracked_files(repo: Path, data_dir: Path) -> None:
    wt = create_worktree(repo, "HEAD", "run-untracked", data_dir=data_dir)
    try:
        result = AgentTools(wt.path).write_file(
            "brand_new.py", "NEW_MARKER = 'untracked-content-here'\n"
        )
        assert not result.startswith("Error: ")
        patch = export_patch(wt, data_dir=data_dir)
        text = patch.read_text()
        assert "brand_new.py" in text
        assert "untracked-content-here" in text
    finally:
        remove_worktree(wt)
