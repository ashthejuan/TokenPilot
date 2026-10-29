"""The CLI fake answers investigation-schema chat requests with bundle-derived content."""

import json

from tests.fakes.fake_upstream import canned_investigation_for_request
from tokenpilot.investigator.evidence import EvidenceBundle
from tokenpilot.investigator.schema import InvestigationOutput
from tokenpilot.investigator.validate import validate_output


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        investigation_id="inv-e2e",
        insight={"rule_id": "retry_amplification", "rule_version": 1},
        events=[{"id": "evt-9f2c41aa7d", "model_id": "fake-small"}],
        aggregates={"event_count": 3, "known_cost_sum": 0.11},
        outcomes=[],
        pricing=[],
        excerpts=[],
        coverage={},
        allowed_ids=["ins-1", "evt-9f2c41aa7d"],
        allowed_numbers=[3, 0.11, 1],
    )


def _request_body(bundle: EvidenceBundle) -> bytes:
    return json.dumps(
        {
            "model": "muse-spark-1.3-contributor",
            "messages": [
                {"role": "system", "content": "investigate"},
                {"role": "user", "content": json.dumps(bundle.to_dict(), default=str)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "investigation", "schema": {}},
            },
        }
    ).encode()


def test_canned_investigation_validates_against_bundle() -> None:
    bundle = _bundle()

    content = canned_investigation_for_request(_request_body(bundle))

    assert content is not None
    out = InvestigationOutput.model_validate(content)
    assert out.verdict == "supported"
    assert validate_output(out, bundle) == []


def test_non_investigation_body_returns_none() -> None:
    body = json.dumps({"model": "x", "messages": []}).encode()

    assert canned_investigation_for_request(body) is None
    assert canned_investigation_for_request(b"not json") is None
