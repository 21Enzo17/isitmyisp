"""Parse report periods: '7d', '24h', '90m' (ago) or 'YYYY-MM-DD[ HH:MM]' (local time)."""

from __future__ import annotations

import time

UNITS = {"d": 86400, "h": 3600, "m": 60}


def parse_when(value: str, now: float | None = None) -> float:
    value = value.strip()
    if value and value[-1] in UNITS and value[:-1].isdigit():
        return (now or time.time()) - int(value[:-1]) * UNITS[value[-1]]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(value, fmt))
        except ValueError:
            continue
    raise ValueError(f"invalid date: {value!r} (use 7d, 24h, 90m or YYYY-MM-DD[ HH:MM])")
