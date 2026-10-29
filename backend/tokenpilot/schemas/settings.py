"""Settings-adjacent response shapes: privacy status and retention delete."""

from pydantic import BaseModel


class PrivacyOut(BaseModel):
    """Read-only reflections of `Settings`/env (Q14). No PUT: edit `.env` and restart."""

    store_content: bool
    allow_content_transmission: bool
    upstream_base_url: str
    investigator_model: str
    local_token_configured: bool
    contributor_training: bool


class DataDeleteResponse(BaseModel):
    """Counts from `DELETE /api/v1/data` (Q13)."""

    deleted_events: int
    deleted_excerpt_files: int
    deleted_worktrees: int
