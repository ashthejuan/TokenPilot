"""Path-safe file tools for the benchmark agent. There is intentionally no shell tool."""

from pathlib import Path

MAX_READ_BYTES = 100 * 1024


def _contains_git(parts: tuple[str, ...]) -> bool:
    """True if any path segment is `.git` (case-insensitive: macOS APFS)."""
    return any(part.casefold() == ".git" for part in parts)


class AgentTools:
    """List, read, and write files under `root`. Errors are returned, never raised."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _resolve(self, path: str) -> tuple[Path | None, str | None]:
        """Resolve `path` against the root; return (resolved, None) or (None, error)."""
        root = self._root.resolve()
        candidate = (self._root / path).resolve()
        if candidate != root and not candidate.is_relative_to(root):
            return None, f"Error: path escapes workspace root: {path!r}"
        if candidate == root:
            return None, f"Error: path is the workspace root: {path!r}"
        if _contains_git(candidate.relative_to(root).parts):
            return None, f"Error: path inside .git is forbidden: {path!r}"
        return candidate, None

    def list_files(self) -> list[str]:
        """Sorted relative-posix paths of files under root, excluding `.git/`."""
        root = self._root.resolve()
        found: list[str] = []
        if not root.is_dir():
            return found
        for entry in root.rglob("*"):
            if not entry.is_file():
                continue
            resolved = entry.resolve()
            if resolved != root and not resolved.is_relative_to(root):
                continue
            rel = resolved.relative_to(root)
            if _contains_git(rel.parts):
                continue
            found.append(rel.as_posix())
        return sorted(found)

    def read_file(self, path: str) -> str:
        """Return file content, or an `Error: ...` string on any violation."""
        resolved, error = self._resolve(path)
        if resolved is None:
            return error or "Error: invalid path"
        if not resolved.is_file():
            return f"Error: file not found: {path!r}"
        try:
            if resolved.stat().st_size > MAX_READ_BYTES:
                return f"Error: file exceeds 100KB read cap: {path!r}"
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error: cannot read {path!r}: {exc.strerror or exc}"

    def write_file(self, path: str, content: str) -> str:
        """Write `content`, creating parent dirs; return confirmation or `Error: ...`."""
        resolved, error = self._resolve(path)
        if resolved is None:
            return error or "Error: invalid path"
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"Error: cannot write {path!r}: {exc.strerror or exc}"
        return f"Wrote {resolved.relative_to(self._root.resolve()).as_posix()}"
