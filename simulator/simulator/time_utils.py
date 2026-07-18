# time_utils.py — mirrors backend/app/time_utils.py's convention (all times stored/sent
# as UTC, wall-clock expressed in IST) without importing the backend package itself
# (which would drag in sqlalchemy/psycopg the simulator has no use for).
from datetime import datetime, timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_wallclock_to_utc(date_str: str, time_str: str) -> datetime:
    year, month, day = (int(x) for x in date_str.split("-"))
    hour, minute = (int(x) for x in time_str.split(":"))
    ist_naive = datetime(year, month, day, hour, minute)
    return (ist_naive - IST_OFFSET).replace(tzinfo=timezone.utc)
