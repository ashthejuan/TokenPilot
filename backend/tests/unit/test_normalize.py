import hashlib
import json

import pytest
from pydantic import ValidationError

from tokenpilot.ledger.normalize import normalize
from tokenpilot.schemas.usage import UsageEventIn


def make_raw(**overrides: object) -> UsageEventIn:
    base: dict[str, object] = {
        "provider": "meta",
        "model_id": "muse-spark-1.3",
        "started_at": "2026-10-27T10:00:00Z",
        "usage_source": "provider",
        "status": "success",
    }
    return UsageEventIn.model_validate({**base, **overrides})


def test_normalize_keeps_missing_tokens_null() -> None:
    event = normalize(make_raw(input_tokens=10), "api")

    assert event.input_tokens == 10
    assert event.output_tokens is None
    assert event.cached_tokens is None
    assert event.reasoning_tokens is None
    assert event.latency_ms is None
    assert event.completed_at is None


def test_normalize_rejects_negative_tokens() -> None:
    with pytest.raises(ValidationError):
        make_raw(output_tokens=-1)


def test_normalize_converts_timestamps_to_utc() -> None:
    event = normalize(
        make_raw(
            started_at="2026-10-27T10:00:00+05:30",
            completed_at="2026-10-27T10:00:01.250+05:30",
        ),
        "api",
    )

    assert event.started_at == "2026-10-27T04:30:00Z"
    assert event.completed_at == "2026-10-27T04:30:01.250Z"


def test_normalize_strips_secret_metadata() -> None:
    event = normalize(
        make_raw(metadata={"authorization": "Bearer x", "api_key": "y", "note": "ok"}), "api"
    )

    assert event.metadata == {"note": "ok"}


def test_nested_secret_metadata_stripped() -> None:
    event = normalize(
        make_raw(metadata={"a": {"Api-Key": "k", "x": "sk-AAAAAAAAAAAAAAAAAAAA"}}), "api"
    )

    assert event.metadata == {"a": {"x": "[REDACTED]"}}


def test_secrets_inside_lists_are_sanitized() -> None:
    event = normalize(
        make_raw(metadata={"items": [{"password": "p", "n": 1}, "Bearer abc", 2]}), "api"
    )

    assert event.metadata == {"items": [{"n": 1}, "[REDACTED]", 2]}


def test_raw_event_json_is_sanitized_and_sorted() -> None:
    event = normalize(make_raw(metadata={"api_key": "y", "note": "ok"}), "api")

    payload = json.loads(event.raw_event_json)
    assert payload["metadata"] == {"note": "ok"}
    assert event.raw_event_json == json.dumps(payload, sort_keys=True)


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        make_raw(messages=[{"role": "user", "content": "hi"}])


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        make_raw(started_at="2026-10-27T10:00:00")


def test_explicit_idempotency_key_wins() -> None:
    event = normalize(make_raw(idempotency_key="k1", source_event_id="s1"), "api")

    assert event.idempotency_key == "k1"
    assert event.dedup == "key"


def test_idempotency_key_derived_from_source_event_id() -> None:
    event = normalize(make_raw(source_event_id="s1"), "api")

    assert event.idempotency_key == hashlib.sha256(b"api:meta:s1").hexdigest()
    assert event.dedup == "key"


def test_idempotency_key_random_when_nothing_to_dedup_on() -> None:
    first = normalize(make_raw(), "api")
    second = normalize(make_raw(), "api")

    assert first.dedup == "not_possible"
    assert first.idempotency_key != second.idempotency_key
