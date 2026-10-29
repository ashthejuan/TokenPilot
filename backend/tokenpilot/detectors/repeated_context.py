"""Detector C: the same context block re-sent across requests in one session.

Only hashes and sizes are ever read, never prompt or response text. A hash
seen in at least `context_repeat_min_occurrences` distinct events of one
session fires one finding (P16). Severity is capped at `medium` and the
impact stays NULL: cached-prefix billing makes a price unknowable, and
repeated context is not assumed to be waste.
"""

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.detectors.facts import ContextBlockFact, DetectionContext, EventFact

RULE_ID = "repeated_context"
RULE_VERSION = 1


class RepeatedContextDetector:
    """Flags context blocks repeated across requests in a single session."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "The same context block was sent with several requests. This is not "
        "necessarily avoidable: check whether the block is a shared system "
        "prompt or retrieved context, and whether caching or a shorter "
        "prefix would cover the repeated part."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """One finding per repeated (session, hash) pair, by anchor."""
        by_key: dict[tuple[str, str], dict[str, EventFact]] = {}
        sizes: dict[tuple[str, str], ContextBlockFact] = {}
        for event in ctx.events:
            if event.session_id is None:
                continue
            for block in event.context_blocks:
                key = (event.session_id, block.hash)
                by_key.setdefault(key, {}).setdefault(event.id, event)
                sizes.setdefault(key, block)
        findings = [
            finding
            for key in sorted(by_key)
            if (finding := _finding(key, by_key[key], sizes[key], ctx)) is not None
        ]
        findings.sort(key=lambda f: f.anchor)
        return findings


def _finding(
    key: tuple[str, str],
    events_by_id: dict[str, EventFact],
    block: ContextBlockFact,
    ctx: DetectionContext,
) -> Finding | None:
    """The finding for one hash, or `None` when it repeats too rarely."""
    session_id, block_hash = key
    thresholds = ctx.thresholds
    ordered = sorted(events_by_id.values(), key=lambda e: (e.started_at, e.id))
    count = len(ordered)
    if count < thresholds.context_repeat_min_occurrences:
        return None
    if block.chars < thresholds.context_min_chars:
        return None
    repeated_chars = block.chars * (count - 1)
    approx_repeated_tokens = block.approx_tokens * (count - 1)
    session = ctx.sessions.get(session_id)
    project_id = session.project_id if session else ordered[0].project_id
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"{session_id}:{block_hash}",
        severity=(
            "medium"
            if approx_repeated_tokens >= thresholds.context_medium_repeated_tokens
            else "low"
        ),
        confidence=0.50,
        title=f"Repeated context ({count} requests)",
        summary=(
            f"Context block {block_hash} was sent with {count} requests "
            f"({repeated_chars} repeated chars, about {approx_repeated_tokens} "
            "repeated tokens, hash only); this is not necessarily avoidable."
        ),
        scope=Scope(project_id=project_id, session_id=session_id),
        evidence=[
            EvidenceRef(
                kind="usage_event",
                id=event.id,
                measurement={
                    "block_hash": block_hash,
                    "block_chars": block.chars,
                    "approx_tokens": block.approx_tokens,
                },
            )
            for event in ordered
        ],
        measurements={
            "occurrence_count": count,
            "block_chars": block.chars,
            "block_approx_tokens": block.approx_tokens,
            "repeated_chars": repeated_chars,
            "approx_repeated_tokens": approx_repeated_tokens,
            "observation": "hash_only",
            "basis": "approximate",
        },
        estimated_impact=None,
        impact_currency=None,
    )
