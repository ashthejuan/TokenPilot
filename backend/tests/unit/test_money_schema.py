import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from tokenpilot.schemas.common import Money


class Priced(BaseModel):
    cost: Money | None = None


def test_money_dumps_to_json_number_not_string() -> None:
    dumped = json.loads(Priced(cost=Decimal("0.0000001235")).model_dump_json())

    assert isinstance(dumped["cost"], float)
    assert dumped["cost"] == pytest.approx(1.235e-7)
    assert json.loads(Priced().model_dump_json()) == {"cost": None}


def test_money_stays_decimal_in_python_and_accepts_common_inputs() -> None:
    for value in (Decimal("1.5"), 1, 1.5, "1.5"):
        assert isinstance(Priced(cost=value).cost, Decimal)
    assert Priced(cost=Decimal("0.0000001235")).model_dump()["cost"] == Decimal("0.0000001235")


def _schema(app: FastAPI, name: str, field: str) -> dict[str, Any]:
    schema: dict[str, Any] = app.openapi()["components"]["schemas"][name]["properties"][field]
    return schema


def test_openapi_declares_session_money_as_nullable_number(app: FastAPI) -> None:
    for name, field in (
        ("SessionSummary", "total_estimated_cost"),
        ("ModelBreakdown", "estimated_cost"),
    ):
        types = {option.get("type") for option in _schema(app, name, field)["anyOf"]}
        assert types == {"number", "null"}, (name, field)
