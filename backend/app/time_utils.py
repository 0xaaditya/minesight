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
