"""Project CRUD."""

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from tokenpilot.benchmarks.agent_tools import _contains_git
from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.projects import (
    Project,
    ProjectCreate,
    ProjectTree,
    ProjectUpdate,
    TreeEntry,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _slug_conflict(exc: sqlite3.IntegrityError) -> HTTPException | None:
    if "projects.slug" in str(exc):
        return HTTPException(status_code=409, detail="a project with this slug already exists")
    return None


def _resolve_tree_dir(root: Path, path: str) -> Path:
    """Resolve `path` under `root` for directory listing.

    Raises HTTPException: 400 on workspace escape, 404 when missing / not a dir / `.git`.
    """
    root_resolved = root.resolve()
    candidate = root_resolved if path in ("", ".") else (root / path).resolve()
    if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
        raise HTTPException(status_code=400, detail=f"path escapes workspace: {path!r}")
    if candidate != root_resolved and _contains_git(candidate.relative_to(root_resolved).parts):
        raise HTTPException(status_code=404, detail="path not found")
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail="path not found")
    return candidate


def _list_tree_entries(root: Path, directory: Path) -> list[TreeEntry]:
    """Immediate children under `directory`, skipping `.git` and escape symlinks."""
    root_resolved = root.resolve()
    entries: list[TreeEntry] = []
    try:
        children = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        raise HTTPException(status_code=404, detail="path not found") from None
    for entry in children:
        if _contains_git((entry.name,)):
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            continue
        if resolved != root_resolved and not resolved.is_relative_to(root_resolved):
            continue
        rel = resolved.relative_to(root_resolved)
        if _contains_git(rel.parts):
            continue
        if resolved.is_dir():
            kind = "dir"
        elif resolved.is_file():
            kind = "file"
        else:
            continue
        entries.append(TreeEntry(name=entry.name, path=rel.as_posix(), kind=kind))
    return entries


@router.post("", status_code=201)
def create_project(body: ProjectCreate, db: Annotated[Database, Depends(get_db)]) -> Project:
    assert body.slug is not None  # filled in by ProjectCreate
    try:
        with db.write() as conn:
            return LedgerRepository(conn).create_project(
                name=body.name,
                slug=body.slug,
                repository_path=body.repository_path,
                default_currency=body.default_currency,
            )
    except sqlite3.IntegrityError as exc:
        raise _slug_conflict(exc) or exc from exc


@router.get("")
def list_projects(db: Annotated[Database, Depends(get_db)]) -> list[Project]:
    with db.read() as conn:
        return LedgerRepository(conn).list_projects()


@router.get("/{project_id}/tree")
def get_project_tree(
    project_id: str,
    db: Annotated[Database, Depends(get_db)],
    path: Annotated[str, Query()] = "",
) -> ProjectTree:
    with db.read() as conn:
        project = LedgerRepository(conn).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if not project.repository_path:
        raise HTTPException(status_code=404, detail="project has no repository_path")
    root = Path(project.repository_path)
    directory = _resolve_tree_dir(root, path)
    return ProjectTree(path=path, entries=_list_tree_entries(root, directory))


@router.get("/{project_id}")
def get_project(project_id: str, db: Annotated[Database, Depends(get_db)]) -> Project:
    with db.read() as conn:
        project = LedgerRepository(conn).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.patch("/{project_id}")
def update_project(
    project_id: str, body: ProjectUpdate, db: Annotated[Database, Depends(get_db)]
) -> Project:
    try:
        with db.write() as conn:
            project = LedgerRepository(conn).update_project(
                project_id, body.model_dump(exclude_unset=True)
            )
    except sqlite3.IntegrityError as exc:
        raise _slug_conflict(exc) or exc from exc
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Annotated[Database, Depends(get_db)]) -> Response:
    with db.write() as conn:
        deleted = LedgerRepository(conn).delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="project not found")
    return Response(status_code=204)
