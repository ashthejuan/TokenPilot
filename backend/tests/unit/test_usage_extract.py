"""Usage extraction from provider response bodies (Task 1.4)."""

from tokenpilot.gateway.usage_extract import UsageFields, extract_usage


def test_full_usage_with_details() -> None:
    body = {
        "id": "chatcmpl-1",
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    }

    assert extract_usage(body) == UsageFields(
        input_tokens=5,
        output_tokens=7,
        cached_tokens=2,
        reasoning_tokens=3,
        source_event_id="chatcmpl-1",
    )


def test_missing_usage_is_all_none_but_id() -> None:
    assert extract_usage({"id": "chatcmpl-2"}) == UsageFields(
        input_tokens=None,
        output_tokens=None,
        cached_tokens=None,
        reasoning_tokens=None,
        source_event_id="chatcmpl-2",
    )


def test_missing_everything_is_all_none() -> None:
    assert extract_usage({}) == UsageFields(
        input_tokens=None,
        output_tokens=None,
        cached_tokens=None,
        reasoning_tokens=None,
        source_event_id=None,
    )


def test_wrong_types_become_none() -> None:
    body = {
        "id": 123,
        "usage": {
            "prompt_tokens": "5",
            "completion_tokens": 7.5,
            "prompt_tokens_details": {"cached_tokens": True},
            "completion_tokens_details": {"reasoning_tokens": [3]},
        },
    }

    assert extract_usage(body) == UsageFields(
        input_tokens=None,
        output_tokens=None,
        cached_tokens=None,
        reasoning_tokens=None,
        source_event_id=None,
    )


def test_non_dict_usage_and_details_become_none() -> None:
    body = {"id": "x", "usage": "nope"}
    assert extract_usage(body).input_tokens is None

    body = {
        "usage": {"prompt_tokens": 1, "prompt_tokens_details": [1], "completion_tokens_details": 9}
    }
    fields = extract_usage(body)
    assert fields.input_tokens == 1
    assert fields.cached_tokens is None
    assert fields.reasoning_tokens is None


def test_negative_counts_become_none() -> None:
    # Negative token counts are nonsense; NULL-not-zero keeps them out of math.
    fields = extract_usage(
        {
            "usage": {
                "prompt_tokens": -5,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": -1},
                "completion_tokens_details": {"reasoning_tokens": -2},
            }
        }
    )
    assert fields.input_tokens is None
    assert fields.output_tokens == 7
    assert fields.cached_tokens is None
    assert fields.reasoning_tokens is None


def test_partial_usage_keeps_present_fields() -> None:
    fields = extract_usage({"usage": {"completion_tokens": 4}})
    assert fields.input_tokens is None
    assert fields.output_tokens == 4
    assert fields.source_event_id is None


def test_responses_usage_fields() -> None:
    body = {
        "id": "resp_1",
        "usage": {
            "input_tokens": 11,
            "output_tokens": 9,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }
    assert extract_usage(body) == UsageFields(
        input_tokens=11,
        output_tokens=9,
        cached_tokens=3,
        reasoning_tokens=2,
        source_event_id="resp_1",
    )


def test_responses_fields_preferred_when_both_shapes_present() -> None:
    body = {
        "id": "mixed",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 2,
            "prompt_tokens": 100,
            "completion_tokens": 200,
        },
    }
    fields = extract_usage(body)
    assert (fields.input_tokens, fields.output_tokens) == (1, 2)
