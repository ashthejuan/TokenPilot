from datetime import UTC, datetime, timedelta, timezone

from tokenpilot.timeutil import parse_utc_z, to_utc_z, utc_now_z


def test_to_utc_z_is_fixed_millisecond_utc() -> None:
    assert to_utc_z(datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)) == "2026-10-27T10:00:00.000Z"
    assert (
        to_utc_z(datetime(2026, 10, 27, 10, 0, 0, 123999, tzinfo=UTC)) == "2026-10-27T10:00:00.123Z"
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    assert to_utc_z(datetime(2026, 10, 27, 10, 0, 0, tzinfo=ist)) == "2026-10-27T04:30:00.000Z"


def test_utc_now_z_shape() -> None:
    value = utc_now_z()

    assert len(value) == len("2026-10-27T10:00:00.000Z")
    assert value.endswith("Z")
    assert value[19] == "."


def test_parse_utc_z_round_trips_stored_timestamps() -> None:
    parsed = parse_utc_z("2026-10-27T10:00:00.123Z")

    assert parsed == datetime(2026, 10, 27, 10, 0, 0, 123000, tzinfo=UTC)
    assert to_utc_z(parsed) == "2026-10-27T10:00:00.123Z"
