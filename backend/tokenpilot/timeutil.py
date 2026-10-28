"""UTC timestamp formatting shared by the ledger and the API."""

from datetime import UTC, datetime


def to_utc_z(value: datetime) -> str:
    """ISO 8601 UTC with `Z`, at second precision or milliseconds when present."""
    utc = value.astimezone(UTC)
    timespec = "milliseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def utc_now_z() -> str:
    return to_utc_z(datetime.now(UTC))
