"""Availability slot generation and validation."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Tuple
from zoneinfo import ZoneInfo
import calendar


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def fmt_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def month_bounds(year: int, month: int) -> Tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def allowed_month_range(now_tz: datetime) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return (current (year,month), next (year,month))."""
    cur = (now_tz.year, now_tz.month)
    if now_tz.month == 12:
        nxt = (now_tz.year + 1, 1)
    else:
        nxt = (now_tz.year, now_tz.month + 1)
    return cur, nxt


def generate_day_slots(
    day_start: str, day_end: str, block_minutes: int, buffer_minutes: int = 0
) -> List[Tuple[str, str]]:
    """Return list of (start_hhmm, end_hhmm) within a working day."""
    start_t = parse_hhmm(day_start)
    end_t = parse_hhmm(day_end)
    cursor = datetime(2000, 1, 1, start_t.hour, start_t.minute)
    end_dt = datetime(2000, 1, 1, end_t.hour, end_t.minute)
    step = timedelta(minutes=block_minutes + buffer_minutes)
    block = timedelta(minutes=block_minutes)
    slots: List[Tuple[str, str]] = []
    while cursor + block <= end_dt:
        s = fmt_hhmm(cursor.time())
        e = fmt_hhmm((cursor + block).time())
        slots.append((s, e))
        cursor = cursor + step
    return slots


def iso_weekday(d: date) -> int:
    return d.isoweekday()  # 1..7


def to_utc(tz_name: str, d: date, hhmm: str) -> datetime:
    tz = ZoneInfo(tz_name)
    t = parse_hhmm(hhmm)
    local = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=tz)
    return local.astimezone(ZoneInfo("UTC"))


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def is_month_allowed(year: int, month: int, tz_name: str) -> bool:
    now = now_in_tz(tz_name)
    cur, nxt = allowed_month_range(now)
    return (year, month) == cur or (year, month) == nxt


def date_in_allowed_window(d: date, tz_name: str) -> bool:
    now = now_in_tz(tz_name)
    today = now.date()
    if d < today:
        return False
    # last day of next month
    cur, nxt = allowed_month_range(now)
    last_day = calendar.monthrange(nxt[0], nxt[1])[1]
    last = date(nxt[0], nxt[1], last_day)
    return d <= last
