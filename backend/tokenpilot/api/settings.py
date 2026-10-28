"""Runtime settings: the versioned pricing catalogue."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from tokenpilot.db.database import Database, get_db
from tokenpilot.pricing.catalog import (
    PricingVersion,
    PricingVersionConflictError,
    create_version,
    current_versions,
)
from tokenpilot.pricing.cost import reprice_all
from tokenpilot.schemas.pricing import PricingVersionCreate, PricingVersionOut, RepriceResponse
from tokenpilot.timeutil import to_utc_z, utc_now_z

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _to_out(version: PricingVersion) -> PricingVersionOut:
    return PricingVersionOut(
        id=version.id,
        provider=version.provider,
        model_id=version.model_id,
        currency=version.currency,
        input_price_per_million=version.input_price_per_million,
        output_price_per_million=version.output_price_per_million,
        cached_input_price=version.cached_input_price,
        pricing_source=version.pricing_source,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        created_at=version.created_at,
    )


@router.get("/pricing")
def list_pricing(db: Annotated[Database, Depends(get_db)]) -> list[PricingVersionOut]:
    with db.read() as conn:
        return [_to_out(version) for version in current_versions(conn)]


@router.put("/pricing")
def upsert_pricing(
    body: PricingVersionCreate, db: Annotated[Database, Depends(get_db)]
) -> RepriceResponse:
    valid_from = to_utc_z(body.valid_from) if body.valid_from is not None else utc_now_z()
    with db.write() as conn:
        try:
            version, created = create_version(
                conn,
                provider=body.provider,
                model_id=body.model_id,
                currency=body.currency,
                input_price_per_million=body.input_price_per_million,
                output_price_per_million=body.output_price_per_million,
                cached_input_price=body.cached_input_price,
                pricing_source=body.pricing_source,
                valid_from=valid_from,
            )
        except PricingVersionConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # An identical PUT changes nothing, so there is nothing to reprice.
        repriced = (
            reprice_all(conn, provider=body.provider, model_id=body.model_id)
            if created
            else 0
        )
    return RepriceResponse(version=_to_out(version), repriced=repriced)
