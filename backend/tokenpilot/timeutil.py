"""UTC timestamp formatting shared by the ledger, the API, and migrations."""

from datetime import UTC, datetime


def to_utc_z(value: datetime) -> str:
    """Fixed-width ISO 8601 UTC, `YYYY-MM-DDTHH:MM:SS.fffZ`.

    Always milliseconds (truncated) so stored strings sort chronologically and
    compare correctly against filter bounds and cursors.
    """
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_now_z() -> str:
    return to_utc_z(datetime.now(UTC))
