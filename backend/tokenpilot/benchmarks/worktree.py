"""Detached git worktrees per benchmark run, plus patch export and cleanup."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tokenpilot.config import DEFAULT_DATA_DIR

# Top-level entries never staged into the patch: acceptance runs create
# interpreter and pytest caches in the worktree, and the fixture ships no
# .gitignore to exclude them.
_SKIP_TOP_SEGMENTS = frozenset({".git", ".pytest_cache", "__pycache__"})


@dataclass(frozen=True)
class Worktree:
    path: Path
    sha: str


def _data_dir(data_dir: Path | None) -> Path:
    return data_dir if data_dir is not None else DEFAULT_DATA_DIR


def _git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    )
    return completed.stdout.strip()


def _git_bytes(args: list[str], cwd: Path) -> bytes:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True,
    )
    return completed.stdout


def resolve_sha(repo: Path, ref: str) -> str:
    """Resolve `ref` to a full commit SHA in `repo`."""
    return _git(["rev-parse", ref], cwd=repo)


def create_worktree(
    repo_path: Path, ref: str, run_id: str, data_dir: Path | None = None
) -> Worktree:
    """Add a detached worktree at `<data_dir>/worktrees/<run_id>` checked out at `ref`."""
    base = _data_dir(data_dir)
    target = base / "worktrees" / run_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        subprocess.run(
            ["git", "worktree", "prune"], cwd=repo_path,
            check=False, capture_output=True,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "--detach", str(target), ref], cwd=repo_path)
    sha = _git(["rev-parse", "HEAD"], cwd=target)
    return Worktree(path=target, sha=sha)


def export_patch(wt: Worktree, data_dir: Path | None = None) -> Path:
    """Write `git diff HEAD` from the worktree to `<data_dir>/patches/<run_id>.patch`.

    Untracked non-ignored files are first staged as intent-to-add (`git add -N`)
    so new files the agent created appear in the patch.
    """
    base = _data_dir(data_dir)
    patches = base / "patches"
    patches.mkdir(parents=True, exist_ok=True)
    patch_path = patches / f"{wt.path.name}.patch"
    others = _git(
        ["ls-files", "--others", "--exclude-standard", "-z"], cwd=wt.path
    ).split("\0")
    untracked = [
        entry
        for entry in others
        if entry and entry.split("/")[0].casefold() not in _SKIP_TOP_SEGMENTS
    ]
    if untracked:
        _git(["add", "-N", "--", *untracked], cwd=wt.path)
    diff = _git_bytes(["diff", "HEAD"], cwd=wt.path)
    if diff:
        diff = diff.rstrip(b"\n") + b"\n"
    patch_path.write_bytes(diff)
    return patch_path


def remove_worktree(wt: Worktree) -> None:
    """Force-remove the worktree and prune the worktree list. Idempotent."""
    if wt.path.exists():
        common_dir = subprocess.run(
            ["git", "-C", str(wt.path), "rev-parse", "--git-common-dir"],
            check=False, capture_output=True, text=True,
        ).stdout.strip()
        if common_dir:
            subprocess.run(
                ["git", "--git-dir", common_dir,
                 "worktree", "remove", "--force", str(wt.path)],
                check=False, capture_output=True,
            )
        shutil.rmtree(wt.path, ignore_errors=True)
        if common_dir:
            subprocess.run(
                ["git", "--git-dir", common_dir, "worktree", "prune"],
                check=False, capture_output=True,
            )
