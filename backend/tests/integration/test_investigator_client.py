"""MetaClient structured-completion request shape (Task 3.2)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from tests.fakes.fake_upstream import FakeUpstream
from tokenpilot.config import Settings
from tokenpilot.investigator.client import MetaClient
from tokenpilot.investigator.schema import investigation_json_schema


@pytest.fixture
def client_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        local_token=SecretStr("test-local-token"),
        db_path=tmp_path / "tokenpilot.sqlite3",
        data_dir=tmp_path,
        upstream_base_url="https://fake.meta.test/v1",
        upstream_api_key=SecretStr("fake-model-key"),
    )


def test_client_sends_response_format_and_no_forbidden_params(
    client_settings: Settings, fake: FakeUpstream
) -> None:
    payload = {
        "title": "t",
        "summary": "s",
        "observed_facts": [{"statement": "f", "evidence_ids": ["e1"]}],
        "root_cause_hypothesis": "h",
        "impact_assessment": "i",
        "recommendation": {
            "action": "a",
            "variable_to_change": "retry_policy",
            "expected_direction": "lower_cost",
            "validation_procedure": "v",
            "proposed_benchmark": None,
        },
        "confidence": "low",
        "limitations": [],
        "verdict": "insufficient_evidence",
    }
    fake.enqueue_investigation(
        payload,
        usage={
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "prompt_tokens_details": {"cached_tokens": 2},
        },
    )

    client = MetaClient(
        client_settings,
        http_client=httpx.Client(transport=fake.transport()),
    )
    parsed, usage = client.complete_structured(
        system="sys",
        user="user",
        schema=investigation_json_schema(),
        model="muse-spark-1.3-contributor",
    )

    assert parsed["verdict"] == "insufficient_evidence"
    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7
    assert usage["cached_tokens"] == 2

    assert len(fake.requests) == 1
    body = json.loads(fake.requests[0].content.decode("utf-8"))
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "investigation"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body.get("reasoning_effort") == "low"
    assert "stop" not in body
    assert "n" not in body
    assert "logit_bias" not in body
