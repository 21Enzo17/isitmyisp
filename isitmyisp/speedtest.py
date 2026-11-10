"""Speed test against the contracted plan: OFF by default, and on purpose.

What it does: for a few seconds it downloads and uploads as fast as it can against Cloudflare's
public speed test (speed.cloudflare.com), with several parallel streams, and pings 1.1.1.1 at the
same time to see how much the latency grows when the link is full (bufferbloat).

Why it can hurt, which is why it ships disabled and asks you to accept the risks:
  - while it runs it FILLS your link: calls and video calls can cut out for a few seconds;
  - it uses data (about 1 GB per test on a 1000 Mbps plan): it has a monthly budget and every
    test stops at its share of it;
  - on a backup link with a data cap (4G) it could use the cap up: it doesn't run there;
  - Cloudflare sees your public IP and that you ran a test;
  - if this machine is on Wi-Fi, the result is your Wi-Fi, not your ISP (it says so).

Scheduled tests also skip when an incident is open or the router (SNMP) shows the link busy:
a test on a busy link measures the leftovers, and makes the busy users' problem worse.
"""

from __future__ import annotations

import calendar
import re
import statistics
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from . import __version__
from .probes.icmp import C_ENV

DOWN_URL = "https://speed.cloudflare.com/__down?bytes={n}"
UP_URL = "https://speed.cloudflare.com/__up"
SERVER = "speed.cloudflare.com"
STREAMS = 4
DOWN_SECONDS, UP_SECONDS = 8.0, 6.0
WARMUP = 1.0          # TCP slow start: the first second doesn't count
CHUNK = 25_000_000    # bytes per download request
UP_CHUNK = 2_000_000  # bytes per upload request
UA = f"isitmyisp/{__version__} (+speed test)"
SCHEDULES = ("weekly", "daily", "manual")
PER_TEST_MAX = 2_000_000_000  # enough for 1 Gbps down for 8 s plus the upload; never more per test

DEFAULTS = {"enabled": False, "accepted": False, "schedule": "weekly", "weekday": 6, "hour": 3,
            "budget_gb": 5.0, "run_on_backup": False, "max_busy_pct": 30}


class SpeedError(RuntimeError):
    pass


@dataclass
class Result:
    ts: float
    down_mbps: float | None = None
    up_mbps: float | None = None
    idle_ms: float | None = None      # latency before the test
    loaded_ms: float | None = None    # latency while downloading (bufferbloat = loaded - idle)
    bytes_used: int = 0
    seconds: float = 0.0
    wan_down_mbps: float | None = None  # everything the router's WAN carried during the download (SNMP)
    wireless: bool = False
    trigger: str = "manual"           # manual | scheduled
    error: str | None = None
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ measuring

class _Meter:
    """Thread-safe byte counter with a time series, to compute throughput after the warm-up."""

    def __init__(self, cap: int, clock: Callable[[], float]):
        self.cap, self.clock = cap, clock
        self.lock = threading.Lock()
        self.total = 0
        self.t0 = clock()
        self.marks: list[tuple[float, int]] = [(0.0, 0)]
        self.stop = threading.Event()

    def add(self, n: int) -> None:
        with self.lock:
            self.total += n
            self.marks.append((self.clock() - self.t0, self.total))
            if self.total >= self.cap:
                self.stop.set()

    def mbps(self) -> float | None:
        with self.lock:
            marks = list(self.marks)
        if len(marks) < 2:
            return None
        end_t, end_b = marks[-1]
        start = next(((t, b) for t, b in marks if t >= WARMUP), None)
        if start is None or end_t - start[0] < 0.5:   # too short to skip the warm-up: use it all
            start = marks[0]
        span = end_t - start[0]
        return round((end_b - start[1]) * 8 / span / 1e6, 1) if span > 0 else None


def _download(meter: _Meter, seconds: float, opener) -> None:
    def worker():
        while not meter.stop.is_set():
            req = urllib.request.Request(DOWN_URL.format(n=CHUNK), headers={"User-Agent": UA})
            with opener(req, timeout=15) as resp:
                while not meter.stop.is_set():
                    block = resp.read(262_144)
                    if not block:
                        break
                    meter.add(len(block))
    _run_streams(worker, meter, seconds)


def _upload(meter: _Meter, seconds: float, opener) -> None:
    body = b"\0" * UP_CHUNK

    def worker():
        while not meter.stop.is_set():
            req = urllib.request.Request(UP_URL, data=body, method="POST",
                                         headers={"User-Agent": UA, "Content-Type": "application/octet-stream"})
            with opener(req, timeout=15) as resp:
                resp.read()
            meter.add(len(body))
    _run_streams(worker, meter, seconds)


def _run_streams(worker, meter: _Meter, seconds: float) -> None:
    errors: list[Exception] = []

    def guarded():
        try:
            worker()
        except Exception as exc:  # noqa: BLE001 - network errors end the stream, reported below
            errors.append(exc)
    threads = [threading.Thread(target=guarded, daemon=True) for _ in range(STREAMS)]
    for th in threads:
        th.start()
    meter.stop.wait(seconds)
    meter.stop.set()
    for th in threads:
        th.join(timeout=16)
    if errors and meter.total == 0:
        raise SpeedError(f"{SERVER}: {errors[0]}")


_RTT = re.compile(r"time[=<]([\d.]+) ms")


def _ping(target: str, count: int, interval: float) -> list[float]:
    try:
        out = subprocess.run(["ping", "-n", "-c", str(count), "-i", str(interval), "-W", "2", target],
                             capture_output=True, text=True, timeout=count * interval + 5, env=C_ENV).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [float(x) for x in _RTT.findall(out)]


def run(max_bytes: int, *, wireless: bool = False, trigger: str = "manual",
        counters: Callable[[], tuple[int, int] | None] | None = None,
        opener=urllib.request.urlopen, ping: Callable[[str, int, float], list[float]] = _ping,
        clock: Callable[[], float] = time.monotonic, down_seconds: float = DOWN_SECONDS,
        up_seconds: float = UP_SECONDS) -> Result:
    """One test. Download gets 70 % of the byte cap, upload 30 %; each stops at its time or its cap."""
    res = Result(ts=time.time(), wireless=wireless, trigger=trigger)
    started = clock()
    idle = ping("1.1.1.1", 5, 0.2)
    res.idle_ms = round(statistics.median(idle), 1) if idle else None
    try:
        loaded: list[float] = []
        pinger = threading.Thread(target=lambda: loaded.extend(ping("1.1.1.1", int(down_seconds / 0.5), 0.5)),
                                  daemon=True)
        before = counters() if counters else None
        t_down = clock()
        down = _Meter(int(max_bytes * 0.7), clock)
        pinger.start()
        _download(down, down_seconds, opener)
        after = counters() if counters else None
        down_span = clock() - t_down
        pinger.join(timeout=down_seconds + 6)
        res.down_mbps = down.mbps()
        res.loaded_ms = round(statistics.median(loaded), 1) if loaded else None
        if before and after and down_span > 0 and after[0] >= before[0]:
            res.wan_down_mbps = round((after[0] - before[0]) * 8 / down_span / 1e6, 1)
        up = _Meter(int(max_bytes * 0.3), clock)
        _upload(up, up_seconds, opener)
        res.up_mbps = up.mbps()
        res.bytes_used = down.total + up.total
        if down.total >= down.cap:
            res.notes.append("budget")       # stopped by the data cap, not the clock
    except SpeedError as exc:
        res.error = str(exc)
    res.seconds = round(clock() - started, 1)
    return res


# ------------------------------------------------------------------ scheduling and safety

def month_start(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def runs_per_month(cfg: dict) -> int:
    return {"weekly": 5, "daily": 31, "manual": 0}[cfg["schedule"]]


def per_test_bytes(cfg: dict) -> int:
    """Each test's share of the monthly budget (two manual tests are always budgeted for)."""
    return int(min(PER_TEST_MAX, cfg["budget_gb"] * 1e9 / (runs_per_month(cfg) + 2)))


def last_slot(cfg: dict, now: float) -> float | None:
    """The most recent scheduled moment at or before `now` (local time)."""
    if cfg["schedule"] == "manual":
        return None
    t = time.localtime(now)
    today = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, cfg["hour"], 0, 0, 0, 0, -1))
    if cfg["schedule"] == "daily":
        return today if today <= now else today - 86400
    days_back = (t.tm_wday - cfg["weekday"]) % 7
    slot = today - days_back * 86400
    return slot if slot <= now else slot - 7 * 86400


def due(cfg: dict, last_run: float | None, now: float, grace: float = 6 * 3600) -> bool:
    """A scheduled test is due once per slot, within `grace` of it (a machine that was off at
    03:00 doesn't fire a test at 15:00 in the middle of the working day)."""
    slot = last_slot(cfg, now)
    return slot is not None and now - slot <= grace and (last_run is None or last_run < slot)


def blocked(cfg: dict, *, manual: bool, used_bytes: int, on_backup: bool, incident: bool,
            link_busy_pct: float | None) -> str | None:
    """Why a test must not run now (a key for the UI), or None."""
    if not (cfg["enabled"] and cfg["accepted"]):
        return "disabled"
    if used_bytes + per_test_bytes(cfg) > cfg["budget_gb"] * 1e9:
        return "budget"
    if on_backup and not cfg["run_on_backup"]:
        return "backup"
    if not manual and incident:
        return "incident"
    if not manual and link_busy_pct is not None and link_busy_pct > cfg["max_busy_pct"]:
        return "busy"
    return None


def validate(raw: dict, current: dict) -> dict:
    out = {**DEFAULTS, **current}
    out["enabled"] = bool(raw.get("enabled"))
    if out["enabled"] and not raw.get("accepted"):
        raise ValueError("to turn the speed test on, confirm that you understand what it does")
    out["accepted"] = bool(raw.get("accepted")) and out["enabled"]
    if raw.get("schedule", out["schedule"]) not in SCHEDULES:
        raise ValueError("schedule must be weekly, daily or manual")
    out["schedule"] = raw.get("schedule", out["schedule"])
    try:
        out["weekday"] = int(raw.get("weekday", out["weekday"]))
        out["hour"] = int(raw.get("hour", out["hour"]))
        out["budget_gb"] = float(raw.get("budget_gb", out["budget_gb"]))
        out["max_busy_pct"] = int(raw.get("max_busy_pct", out["max_busy_pct"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("weekday, hour, budget and busy limit must be numbers") from exc
    if not (0 <= out["weekday"] <= 6 and 0 <= out["hour"] <= 23):
        raise ValueError("weekday 0-6 and hour 0-23")
    if not 0.5 <= out["budget_gb"] <= 500:
        raise ValueError("the monthly budget must be between 0.5 and 500 GB")
    if not 5 <= out["max_busy_pct"] <= 100:
        raise ValueError("the busy limit must be between 5 and 100 %")
    out["run_on_backup"] = bool(raw.get("run_on_backup"))
    return out


WEEKDAYS = {"en": list(calendar.day_name),
            "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]}


class Runner:
    """Lives in the monitor loop: decides when a test runs and runs it in its own thread, so the
    measurements keep going (and show the latency under load) while the link is full."""

    REQUEST_TTL = 600  # a "test now" press older than this (monitor was down) is ignored

    def __init__(self, store, run_fn=run):
        self.store, self.run_fn = store, run_fn
        self.thread: threading.Thread | None = None
        self.started: float | None = None
        self.ended: float | None = None
        self.last_request = store.get_setting("_speed_request") or 0.0
        self.last_reason: str | None = None

    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def suppress(self, now: float, window: float) -> bool:
        """True if a test filled the link at any point of the window ending now."""
        if self.started is None:
            return False
        return self.running() or (self.ended is not None and self.ended > now - window)

    def tick(self, cfg: dict, now: float, *, wireless: bool, on_backup: bool, incident: bool,
             link_busy_pct: float | None, counters=None) -> str | None:
        """Start a test if one is due or was requested. Returns what happened: 'started', a blocking
        reason, or None (nothing to do)."""
        if self.running():
            return None
        req = self.store.get_setting("_speed_request") or 0.0
        manual = req > self.last_request and now - req < self.REQUEST_TTL
        if req > self.last_request:
            self.last_request = req
        if not manual:
            recent = [r for r in self.store.speedtests_between(now - 8 * 86400, now) if r.get("trigger") == "scheduled"]
            if not due(cfg, recent[-1]["ts"] if recent else None, now):
                return None
        reason = blocked(cfg, manual=manual, used_bytes=self.store.speed_bytes_since(month_start(now)),
                         on_backup=on_backup, incident=incident, link_busy_pct=link_busy_pct)
        if reason:
            if manual:
                self.store.set_settings({"_speed_blocked": {"ts": now, "reason": reason}}, bump=False)
            self.last_reason = reason
            return reason
        cap = per_test_bytes(cfg)
        trigger = "manual" if manual else "scheduled"

        def job():
            try:
                res = self.run_fn(cap, wireless=wireless, trigger=trigger, counters=counters)
            except Exception as exc:  # noqa: BLE001 - recorded, never kills the monitor
                res = Result(ts=time.time(), wireless=wireless, trigger=trigger, error=str(exc))
            self.store.add_speedtest(res)
            self.ended = time.time()

        self.started, self.ended = now, None
        self.thread = threading.Thread(target=job, daemon=True, name="speedtest")
        self.thread.start()
        return "started"
