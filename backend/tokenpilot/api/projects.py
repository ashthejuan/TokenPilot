"""Project CRUD."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.projects import Project, ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _slug_conflict(exc: sqlite3.IntegrityError) -> HTTPException | None:
    if "projects.slug" in str(exc):
        return HTTPException(status_code=409, detail="a project with this slug already exists")
    return None


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
