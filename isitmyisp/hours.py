"""Business hours: when the business is open, so reports and alerts can count what happens then.

For a shop, 20 minutes down at 3 a.m. and at 11 a.m. are not the same thing. Hours are set per
weekday (Monday = 0), with up to two shifts a day (the split shift with a siesta that's normal in
much of Argentina). A shift that runs past midnight is entered as two: until 24:00, and from 00:00
the next day. Everything is local time (the TZ the monitor runs with). Standard library only.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from .store import Store

KEY = "business_hours"
DAYS = 7
MAX_SHIFTS = 2
# what the form shows the first time: a typical shop (Mon–Fri with siesta, Saturday morning)
SUGGESTED = {str(d): [["08:00", "13:00"], ["17:00", "21:00"]] for d in range(5)} | {"5": [["09:00", "13:00"]], "6": []}
DEFAULTS = {"enabled": False, "quiet_alerts": False, "days": {str(d): [] for d in range(DAYS)}}

_HHMM = re.compile(r"^([01]?\d|2[0-4]):([0-5]\d)$")


class HoursError(ValueError):
    pass


def _minutes(hhmm: str) -> int:
    m = _HHMM.match(hhmm.strip())
    if not m:
        raise HoursError(f"{hhmm!r} is not a time like 08:30")
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi:
        raise HoursError("24:00 is the latest time")
    return h * 60 + mi


def validate(raw: dict) -> dict:
    """{"enabled", "quiet_alerts", "days": {"0".."6": [[from, to], ...]}} -> clean copy, or HoursError."""
    out = {"enabled": bool(raw.get("enabled")), "quiet_alerts": bool(raw.get("quiet_alerts")), "days": {}}
    for d in range(DAYS):
        shifts = []
        for pair in (raw.get("days") or {}).get(str(d)) or []:
            a, b = (str(x or "").strip() for x in pair)
            if not a and not b:
                continue
            if not a or not b:
                raise HoursError("every shift needs an opening and a closing time")
            ma, mb = _minutes(a), _minutes(b)
            if mb <= ma:
                raise HoursError(f"{a}–{b}: closing must be after opening (past midnight: until 24:00, "
                                 "then from 00:00 the next day)")
            shifts.append((ma, mb))
        if len(shifts) > MAX_SHIFTS:
            raise HoursError(f"at most {MAX_SHIFTS} shifts a day")
        shifts.sort()
        for (_, end), (start, _) in zip(shifts, shifts[1:]):
            if start < end:
                raise HoursError("shifts of the same day overlap")
        out["days"][str(d)] = [[f"{a // 60:02d}:{a % 60:02d}", f"{b // 60:02d}:{b % 60:02d}"] for a, b in shifts]
    if out["enabled"] and not any(out["days"].values()):
        raise HoursError("set at least one day with opening hours, or turn business hours off")
    return out


def load(store: Store) -> dict:
    cfg = store.get_setting(KEY) or {}
    return {**DEFAULTS, **cfg, "days": {**DEFAULTS["days"], **(cfg.get("days") or {})}}


def save(store: Store, raw: dict) -> dict:
    cfg = validate(raw)
    store.set_settings({KEY: cfg}, bump=False)   # nothing to restart: read when needed
    return cfg


def active(cfg: dict) -> bool:
    return bool(cfg.get("enabled")) and any(cfg["days"].values())


# ------------------------------------------------------------------ time arithmetic

def intervals(cfg: dict, start: float, end: float) -> list[tuple[float, float]]:
    """Open intervals (epoch seconds, local time) overlapping [start, end], clipped to it."""
    if not active(cfg) or end <= start:
        return []
    out: list[tuple[float, float]] = []
    day = datetime.fromtimestamp(start).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    last = datetime.fromtimestamp(end)
    while day <= last:
        for a, b in cfg["days"].get(str(day.weekday()), []):
            s = (day + timedelta(minutes=_minutes(a))).timestamp()
            e = (day + timedelta(minutes=_minutes(b))).timestamp()
            s, e = max(s, start), min(e, end)
            if e > s:
                out.append((s, e))
        day += timedelta(days=1)
    out.sort()
    merged: list[tuple[float, float]] = []
    for s, e in out:                       # 21:00–24:00 + 00:00–02:00 the next day is one stretch
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def open_seconds(cfg: dict, start: float, end: float) -> float:
    return sum(e - s for s, e in intervals(cfg, start, end))


def is_open(cfg: dict, ts: float | None = None) -> bool:
    ts = time.time() if ts is None else ts
    return bool(intervals(cfg, ts - 1, ts + 1))


def current_open_start(cfg: dict, ts: float) -> float | None:
    """When the stretch the business is in right now opened (None when closed)."""
    found = [s for s, e in intervals(cfg, ts - 8 * 86400, ts + 1) if s <= ts < e]
    return found[-1] if found else None


def previous_close(cfg: dict, ts: float) -> float | None:
    """When the business last closed before `ts` (None when it never did in the last 8 days)."""
    ends = [e for _, e in intervals(cfg, ts - 8 * 86400, ts) if e < ts]
    return ends[-1] if ends else None


def in_hours(cfg: dict, opened: float, closed: float) -> float:
    """Seconds of [opened, closed] that fell inside business hours."""
    return open_seconds(cfg, opened, closed)
