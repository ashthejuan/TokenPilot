"""Pure helpers for retry inference and context-size accounting. They never store text."""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

# Messages shorter than this are not worth reporting as a context block.
CONTEXT_BLOCK_MIN_CHARS = 2000


@dataclass(frozen=True)
class ContextBlock:
    """A large message, described by its hash and size only (never its text)."""

    hash: str
    chars: int
    approx_tokens: int
    position: int


def _tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return str(function["name"])
    name = tool.get("name")
    return name if isinstance(name, str) else ""


def request_fingerprint(
    model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> str:
    """sha256 over model, role/content of each message, and the sorted tool names.

    Sampling and transport options (temperature, stream) and any ids are left out,
    so two attempts at the same request hash alike. Non-string `content` (parts
    arrays) is hashed through the same sorted-key JSON encoding.
    """
    canonical = {
        "model": model,
        "messages": [{"role": m.get("role"), "content": m.get("content")} for m in messages],
        "tools": sorted(_tool_name(t) for t in tools or []),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def context_blocks(messages: list[dict[str, Any]]) -> list[ContextBlock]:
    """Hash and size every message whose string content is at least 2000 chars.

    `approx_tokens` is `ceil(chars / 4)`; callers record it with
    `context_blocks_basis = "approximate"`.
    """
    blocks: list[ContextBlock] = []
    for position, message in enumerate(messages):
        content = message.get("content")
        if isinstance(content, str) and len(content) >= CONTEXT_BLOCK_MIN_CHARS:
            blocks.append(
                ContextBlock(
                    hash=hashlib.sha256(content.encode()).hexdigest(),
                    chars=len(content),
                    approx_tokens=math.ceil(len(content) / 4),
                    position=position,
                )
            )
    return blocks
