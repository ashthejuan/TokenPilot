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

    assert event.started_at == "2026-10-27T04:30:00.000Z"
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


def test_timestamps_always_fixed_millisecond_precision() -> None:
    event = normalize(
        make_raw(started_at="2026-10-27T10:00:00Z", completed_at="2026-10-27T10:00:00.123456Z"),
        "api",
    )

    assert event.started_at == "2026-10-27T10:00:00.000Z"
    assert event.completed_at == "2026-10-27T10:00:00.123Z"


def test_content_keys_dropped_at_any_depth() -> None:
    event = normalize(
        make_raw(
            metadata={
                "messages": [{"role": "user", "content": "my secret prompt"}],
                "debug": {"Prompt": "p", "inner": [{"choices": [1], "ok": 1}]},
                "Response": "r",
                "completion": "c",
                "content": "x",
                "message_count": 3,
                "contents_hash": "abc",
            }
        ),
        "api",
    )

    assert event.metadata == {
        "debug": {"inner": [{"ok": 1}]},
        "message_count": 3,
        "contents_hash": "abc",
    }
    assert "my secret prompt" not in event.raw_event_json


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "access_token",
        "refresh_token",
        "x-auth-token",
        "authorization",
        "Authorization",
        "api_key",
        "api-key",
        "apikey",
        "secret",
        "client_secret",
        "password",
        "passwd",
        "cookie",
        "set-cookie",
        "bearer",
    ],
)
def test_secret_keys_dropped(key: str) -> None:
    assert normalize(make_raw(metadata={key: "v", "keep": 1}), "api").metadata == {"keep": 1}


@pytest.mark.parametrize(
    "key",
    ["max_tokens", "total_tokens", "token_count", "token_counts", "tokenizer", "input_tokens"],
)
def test_token_count_keys_survive(key: str) -> None:
    assert normalize(make_raw(metadata={key: 5}), "api").metadata == {key: 5}


def test_free_text_fields_redacted_everywhere() -> None:
    secret = "Authorization: Bearer abcdefghijklmnop"
    event = normalize(
        make_raw(
            error_category=secret,
            request_fingerprint=secret,
            external_session_id=secret,
            task_id=secret,
            retry_of=secret,
            source_event_id=secret,
            model_id="sk-AAAAAAAAAAAAAAAAAAAA",
            provider=secret,
        ),
        "api",
    )

    redacted = "Authorization: [REDACTED]"
    assert event.error_category == redacted
    assert event.request_fingerprint == redacted
    assert event.external_session_id == redacted
    assert event.task_id == redacted
    assert event.retry_of == redacted
    assert event.source_event_id == redacted
    assert event.model_id == "[REDACTED]"
    assert event.provider == redacted
    assert "abcdefghijklmnop" not in event.raw_event_json
    assert "sk-AAAA" not in event.raw_event_json


def test_secret_shaped_idempotency_key_is_hashed_but_stays_stable() -> None:
    key_a = "Bearer aaaaaaaaaaaaaaaa"
    first = normalize(make_raw(idempotency_key=key_a), "api")
    again = normalize(make_raw(idempotency_key=key_a), "api")
    other = normalize(make_raw(idempotency_key="Bearer bbbbbbbbbbbbbbbb"), "api")

    assert first.idempotency_key == again.idempotency_key
    assert first.idempotency_key != other.idempotency_key
    assert "aaaaaaaaaaaaaaaa" not in first.idempotency_key
    assert "aaaaaaaaaaaaaaaa" not in first.raw_event_json
    assert first.dedup == "key"


def test_secret_shaped_source_event_id_dedups_on_original_value() -> None:
    first = normalize(make_raw(source_event_id="Bearer aaaaaaaaaaaaaaaa"), "api")
    other = normalize(make_raw(source_event_id="Bearer bbbbbbbbbbbbbbbb"), "api")

    assert first.source_event_id == "[REDACTED]"
    assert first.idempotency_key != other.idempotency_key


def test_over_length_strings_rejected() -> None:
    with pytest.raises(ValidationError):
        make_raw(model_id="m" * 257)
    with pytest.raises(ValidationError):
        make_raw(error_category="e" * 2049)
    assert make_raw(error_category="e" * 2048).error_category is not None
