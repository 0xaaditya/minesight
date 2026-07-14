from datetime import date, datetime, timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC times stored, IST displayed (CLAUDE.md convention) — UTC midnight is 5:30am IST,
    right in the middle of a mining shift, so any 'today' rollup must use IST day
    boundaries or it'll split a live shift across two report-days."""
    start_ist_as_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - IST_OFFSET
    return start_ist_as_utc, start_ist_as_utc + timedelta(days=1)


def ist_range_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """[start of start_day, end of end_day) in IST — multi-day generalization of
    ist_day_bounds for week/period rollups. end_day is inclusive."""
    start, _ = ist_day_bounds(start_day)
    _, end = ist_day_bounds(end_day)
    return start, end


def _parse_hhmm(value: str) -> int:
    """'HH:MM' -> minutes since IST midnight."""
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def in_quiet_hours(event_time_utc: datetime, start: str, end: str) -> bool:
    """Whether a UTC timestamp falls in the IST wall-clock quiet-hours window
    [start, end). start > end (the default 20:00-06:00) crosses midnight — that's the
    normal path for a mining theft window, not an edge case, so it's tested first."""
    ist = event_time_utc + IST_OFFSET
    minute_of_day = ist.hour * 60 + ist.minute
    start_min, end_min = _parse_hhmm(start), _parse_hhmm(end)
    if start_min > end_min:
        return minute_of_day >= start_min or minute_of_day < end_min
    return start_min <= minute_of_day < end_min
