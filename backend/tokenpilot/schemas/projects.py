"""Project request and response shapes."""

import re
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tokenpilot.schemas.common import SLUG_PATTERN

Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Slug = Annotated[str, Field(pattern=SLUG_PATTERN)]
Name = Annotated[str, Field(min_length=1, max_length=200)]


def slugify(name: str) -> str:
    """Lowercase, collapse runs of non-`[a-z0-9]` into `-`, trim `-` from the ends."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64].strip("-")


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    slug: Slug | None = None
    repository_path: str | None = None
    default_currency: Currency = "USD"

    @model_validator(mode="after")
    def derive_slug(self) -> Self:
        if self.slug is None:
            derived = slugify(self.name)
            if not derived:
                raise ValueError("name has no letters or digits to build a slug from")
            self.slug = derived
        return self


class ProjectUpdate(BaseModel):
    """Only the fields present in the body change; `repository_path: null` clears it."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    slug: Slug | None = None
    repository_path: str | None = None
    default_currency: Currency | None = None

    @field_validator("name", "slug", "default_currency")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        return value


class Project(BaseModel):
    id: str
    name: str
    slug: str | None
    repository_path: str | None
    default_currency: str
    created_at: str
    updated_at: str
