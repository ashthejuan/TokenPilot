import json
from dataclasses import asdict

from tokenpilot.ledger.fingerprint import context_blocks, request_fingerprint

MESSAGES = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Fix the failing test."},
]
TOOLS = [{"type": "function", "function": {"name": "run_tests"}}, {"name": "edit_file"}]


def test_fingerprint_ignores_temperature_and_stream() -> None:
    # Only model, role/content and tool names enter the hash, so sampling and
    # transport options (and message ids) cannot change it.
    with_noise = [{**m, "id": f"msg-{i}", "temperature": 0.9} for i, m in enumerate(MESSAGES)]

    assert request_fingerprint("m", MESSAGES, TOOLS) == request_fingerprint("m", with_noise, TOOLS)


def test_fingerprint_changes_with_model_content_or_tools() -> None:
    base = request_fingerprint("m", MESSAGES, TOOLS)

    assert request_fingerprint("other", MESSAGES, TOOLS) != base
    extended = [*MESSAGES, {"role": "user", "content": "again"}]
    assert request_fingerprint("m", extended, TOOLS) != base
    assert request_fingerprint("m", MESSAGES, TOOLS[:1]) != base


def test_fingerprint_tool_order_and_none_tools() -> None:
    assert request_fingerprint("m", MESSAGES, TOOLS) == request_fingerprint(
        "m", MESSAGES, list(reversed(TOOLS))
    )
    assert request_fingerprint("m", MESSAGES, None) == request_fingerprint("m", MESSAGES, [])


def test_fingerprint_canonicalizes_parts_content() -> None:
    a = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    b = [{"role": "user", "content": [{"text": "hi", "type": "text"}]}]

    assert request_fingerprint("m", a, None) == request_fingerprint("m", b, None)
    assert len(request_fingerprint("m", a, None)) == 64


def test_context_blocks_hash_only() -> None:
    long_text = "secret-looking-source-code " * 100  # 2700 chars
    big = ("x" * 2400)
    messages = [
        {"role": "system", "content": "short"},
        {"role": "user", "content": big},
        {"role": "user", "content": [{"type": "text", "text": long_text}]},
    ]

    blocks = context_blocks(messages)

    assert len(blocks) == 1
    assert (blocks[0].chars, blocks[0].approx_tokens, blocks[0].position) == (2400, 600, 1)
    assert len(blocks[0].hash) == 64
    assert big not in json.dumps([asdict(b) for b in blocks])


def test_context_blocks_threshold_and_rounding() -> None:
    messages = [
        {"role": "user", "content": "a" * 1999},
        {"role": "user", "content": "b" * 2001},
    ]

    blocks = context_blocks(messages)

    assert [(b.position, b.approx_tokens) for b in blocks] == [(1, 501)]
