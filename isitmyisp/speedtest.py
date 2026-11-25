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

Inside and outside the ISP: besides Cloudflare you can add up to MAX_SERVERS iperf3 servers (your
own VPS, another branch, or one inside the ISP's network). Each one is marked inside or outside the
ISP by its ASN, and comparing both says where the bottleneck is: 300 Mbps up to the ISP and 40 to
the rest of the internet is its exit (peering, transit), not your access. The test's data cap is
shared between all the servers, and the other guards (budget, incidents, backup link) still hold.

M-Lab NDT7 (see mlab.py) is a second engine, off unless you consent separately: M-Lab publishes
every test, with your public IP, as open data. On some lines Cloudflare is the ceiling, not the ISP.

Against the plan: any server can only measure less than your access, never more (its own limits and
its path add up). So the plan is compared with the best figure of the test, from whichever engine
or server gave it (best()), and a slow far server is never read as your ISP falling short.
"""

from __future__ import annotations

import calendar
import json
import re
import shutil
import socket
import statistics
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from . import __version__
from .netutil import ip_kind
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

CLOUDFLARE_ASN = "AS13335"
IPERF_PORT = 5201
MAX_SERVERS = 3
WHERE = ("auto", "inside", "outside")   # auto: by the server's ASN against your ISP's
SLOW_RATIO = 0.6   # outside below 60 % of inside: the exit is the bottleneck (inside below 60 % of the plan: the access)

DEFAULTS = {"enabled": False, "accepted": False, "schedule": "weekly", "weekday": 6, "hour": 3,
            "budget_gb": 5.0, "run_on_backup": False, "max_busy_pct": 30, "servers": [],
            "mlab": False, "mlab_accepted": False}


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
    where: str = "outside"            # Cloudflare's side of the ISP (inside only if your ISP is Cloudflare)
    servers: list[dict] = field(default_factory=list)  # the iperf3 servers: see run_server()


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
    _run_streams([worker] * STREAMS, meter, seconds)


def _upload(meter: _Meter, seconds: float, opener) -> None:
    body = b"\0" * UP_CHUNK

    def worker():
        while not meter.stop.is_set():
            req = urllib.request.Request(UP_URL, data=body, method="POST",
                                         headers={"User-Agent": UA, "Content-Type": "application/octet-stream"})
            with opener(req, timeout=15) as resp:
                resp.read()
            meter.add(len(body))
    _run_streams([worker] * STREAMS, meter, seconds)


def _run_streams(workers: list[Callable[[], None]], meter: _Meter, seconds: float, name: str = SERVER) -> None:
    """Run one thread per worker until the time or the byte cap; an error only counts if nothing moved."""
    errors: list[Exception] = []

    def guarded(worker):
        try:
            worker()
        except Exception as exc:  # noqa: BLE001 - network errors end the stream, reported below
            errors.append(exc)
    threads = [threading.Thread(target=guarded, args=(w,), daemon=True) for w in workers]
    for th in threads:
        th.start()
    meter.stop.wait(seconds)
    meter.stop.set()
    for th in threads:
        th.join(timeout=16)
    if errors and meter.total == 0:
        raise SpeedError(f"{name}: {errors[0]}")


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
        up_seconds: float = UP_SECONDS, servers: list[dict] | None = None,
        mark: Callable[[str], dict] | None = None, isp_asn: str | None = None,
        iperf: Callable[..., tuple[float | None, int]] | None = None, mlab: bool = False,
        mlab_run: Callable[..., dict] | None = None) -> Result:
    """One test. Cloudflare first, then M-Lab (if on), then each iperf3 server; the byte cap is split
    evenly between them. Download gets 70 % of each share, upload 30 %; each stops at its time or its cap."""
    servers = servers or []
    share = max_bytes // (1 + len(servers) + (1 if mlab else 0))
    res = _run_cloudflare(share, wireless=wireless, trigger=trigger, counters=counters, opener=opener,
                          ping=ping, clock=clock, down_seconds=down_seconds, up_seconds=up_seconds)
    if isp_asn == CLOUDFLARE_ASN:
        res.where = "inside"
    started = clock()
    if mlab:
        if mlab_run is None:
            from .mlab import run as mlab_run
        one = mlab_run(share, mark=mark, down_seconds=down_seconds, up_seconds=up_seconds)
        res.servers.append(one)
        res.bytes_used += one["bytes"]
    for srv in servers:
        one = run_server(srv, share, mark=mark, iperf=iperf, down_seconds=down_seconds, up_seconds=up_seconds)
        res.servers.append(one)
        res.bytes_used += one["bytes"]
    res.seconds = round(res.seconds + clock() - started, 1)
    return res


def _run_cloudflare(max_bytes: int, *, wireless, trigger, counters, opener, ping, clock,
                    down_seconds, up_seconds) -> Result:
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


# ------------------------------------------------------------------ iperf3 servers, inside or outside the ISP

def iperf_available() -> bool:
    return shutil.which("iperf3") is not None


def _iperf3(host: str, port: int, max_bytes: int, *, reverse: bool, seconds: float,
            runner=subprocess.run) -> tuple[float | None, int]:
    """One direction against an iperf3 server: (Mbps, bytes moved). The rate cap (-b, per stream)
    is what keeps it within its bytes: iperf3 can stop at a time or at a size, not at whichever
    comes first. The first second (TCP slow start) is omitted from the result, like Cloudflare's."""
    secs = max(1, int(seconds))
    rate = max(8_000, int(max_bytes * 8 / (secs + 1) / STREAMS))
    cmd = ["iperf3", "-c", host, "-p", str(port), "-J", "-t", str(secs), "-O", "1", "-P", str(STREAMS),
           "-b", str(rate), "--connect-timeout", "5000"] + (["-R"] if reverse else [])
    try:
        out = runner(cmd, capture_output=True, text=True, timeout=secs + 25, env=C_ENV).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpeedError(f"{host}: {exc}") from exc
    try:
        data = json.loads(out or "{}")
    except ValueError as exc:
        raise SpeedError(f"{host}: unreadable iperf3 output") from exc
    if data.get("error"):
        raise SpeedError(f"{host}: {data['error']}")
    end = data.get("end") or {}
    recv, sent = end.get("sum_received") or {}, end.get("sum_sent") or {}
    bps = recv.get("bits_per_second")
    moved = max(int(recv.get("bytes") or 0), int(sent.get("bytes") or 0))
    moved = int(moved * (secs + 1) / secs)       # plus the omitted second, which also used data
    return (round(bps / 1e6, 1) if bps else None), moved


def label(srv: dict) -> str:
    host = f"[{srv['host']}]" if ":" in srv["host"] else srv["host"]
    return host if srv.get("port", IPERF_PORT) == IPERF_PORT else f"{host}:{srv['port']}"


def run_server(srv: dict, max_bytes: int, *, mark: Callable[[str], dict] | None = None,
               iperf: Callable[..., tuple[float | None, int]] | None = None,
               down_seconds: float = DOWN_SECONDS, up_seconds: float = UP_SECONDS) -> dict:
    """Download (-R) and upload against one iperf3 server, and which side of the ISP it is on."""
    out = {"name": label(srv), "where": None, "forced": srv.get("where", "auto") != "auto", "asn": None,
           "as_name": None, "down_mbps": None, "up_mbps": None, "bytes": 0, "error": None}
    info = (mark or (lambda host: {}))(srv["host"]) or {}
    out.update({k: info.get(k) for k in ("asn", "as_name", "where")})
    if out["forced"]:
        out["where"] = srv["where"]
    if iperf is None:
        if not iperf_available():
            out["error"] = "iperf3 is not installed"
            return out
        iperf = _iperf3
    port = int(srv.get("port", IPERF_PORT))
    try:
        out["down_mbps"], down = iperf(srv["host"], port, int(max_bytes * 0.7), reverse=True, seconds=down_seconds)
        out["bytes"] += down
        out["up_mbps"], up = iperf(srv["host"], port, int(max_bytes * 0.3), reverse=False, seconds=up_seconds)
        out["bytes"] += up
    except SpeedError as exc:
        out["error"] = str(exc)
    return out


def mark(host: str, *, isp_asn: str | None, data_dir=None, online: bool = False,
         resolve=socket.getaddrinfo, lookup=None) -> dict:
    """Which side of the ISP a server is on: 'inside' (same ASN as your ISP, or in its CGNAT space),
    'outside' (another ASN), 'private' (a LAN or VPN address: can't tell) or None (no ASN data)."""
    try:
        ip = resolve(host, None, type=socket.SOCK_STREAM)[0][4][0]
    except (OSError, IndexError, UnicodeError):
        return {"where": None, "asn": None, "as_name": None}
    kind = ip_kind(ip)
    if kind == "cgnat":
        return {"where": "inside", "asn": isp_asn, "as_name": None}
    if kind != "public":
        return {"where": "private", "asn": None, "as_name": None}
    if lookup is None:
        from .asn import lookup
    asn_, name = lookup([ip], data_dir=data_dir, online=online).get(ip) or (None, None)
    where = None if not (asn_ and isp_asn) else ("inside" if asn_ == isp_asn else "outside")
    return {"where": where, "asn": asn_, "as_name": name}


def best(res: dict) -> dict:
    """The best download and upload of one test, from any engine or server, and who gave them:
    {"down", "down_name", "up", "up_name"} (None when nothing measured). A server can only measure
    less than your access, never more, so this is the figure to hold against the plan."""
    rows = []
    if not res.get("error"):
        rows.append((res.get("down_mbps"), res.get("up_mbps"), SERVER))
    rows += [(s.get("down_mbps"), s.get("up_mbps"), s.get("name") or "?")
             for s in res.get("servers") or [] if not s.get("error")]
    out: dict = {"down": None, "down_name": None, "up": None, "up_name": None}
    for key, i in (("down", 0), ("up", 1)):
        got = [(r[i], r[2]) for r in rows if r[i]]
        if got:
            out[key], out[f"{key}_name"] = max(got, key=lambda x: x[0])
    return out


def locate(res: dict, plan_down: float = 0.0) -> dict | None:
    """Where the bottleneck is, comparing the best download inside the ISP with the best outside.
    None when one of the two sides wasn't measured. Codes:
      exit:   outside < 60 % of inside: the ISP's exit (peering, transit) is the limit, not your access;
      access: both alike, but under 60 % of the plan even inside the ISP: the access itself;
      even:   inside and outside alike, and near the plan (or no plan to compare with)."""
    sides: dict[str, list[tuple[float, str]]] = {"inside": [], "outside": []}
    if not res.get("error") and res.get("down_mbps"):
        sides[res.get("where") or "outside"].append((res["down_mbps"], SERVER))
    for s in res.get("servers") or []:
        if not s.get("error") and s.get("down_mbps") and s.get("where") in sides:
            sides[s["where"]].append((s["down_mbps"], s["name"]))
    if not (sides["inside"] and sides["outside"]):
        return None
    (inside, in_name), (outside, out_name) = max(sides["inside"]), max(sides["outside"])
    if outside < SLOW_RATIO * inside:
        code = "exit"
    elif plan_down and inside < SLOW_RATIO * plan_down:
        code = "access"
    else:
        code = "even"
    return {"code": code, "inside": inside, "outside": outside, "inside_name": in_name, "outside_name": out_name}


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
    # M-Lab publishes each test with your IP: its own consent, and turning it off forgets the consent
    out["mlab"] = bool(raw.get("mlab"))
    if out["mlab"] and not raw.get("mlab_accepted"):
        raise ValueError("to use M-Lab, confirm that it publishes each test with your public IP")
    out["mlab_accepted"] = out["mlab"]
    if "servers" in raw:
        out["servers"] = parse_servers(raw["servers"])
    return out


_HOST = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$")


def parse_servers(text: str | list) -> list[dict]:
    """One iperf3 server per line: `host[:port] [inside|outside]` (IPv6 in brackets). Without
    inside/outside, the side is told by the server's ASN."""
    lines = text if isinstance(text, list) else str(text or "").splitlines()
    out = []
    for line in lines:
        if isinstance(line, dict):
            line = f"{label(line)} {line.get('where', 'auto')}"
        parts = line.split("#", 1)[0].split()
        if not parts:
            continue
        if len(parts) > 2 or (len(parts) == 2 and parts[1].lower() not in WHERE):
            raise ValueError(f"iperf3 server: {line.strip()!r} (host[:port] and, optionally, inside or outside)")
        where = parts[1].lower() if len(parts) == 2 else "auto"
        m = re.fullmatch(r"\[([0-9A-Fa-f:.]+)\](?::(\d+))?|([^:\s]+)(?::(\d+))?", parts[0])
        if not m:
            raise ValueError(f"iperf3 server: {parts[0]!r}")
        host, port = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if not m.group(1) and not _HOST.match(host):
            raise ValueError(f"iperf3 server: {host!r} is not a host name or address")
        port = int(port or IPERF_PORT)
        if not 1 <= port <= 65535:
            raise ValueError(f"iperf3 server: port {port}")
        out.append({"host": host, "port": port, "where": where})
    if len(out) > MAX_SERVERS:
        raise ValueError(f"at most {MAX_SERVERS} iperf3 servers")
    return out


WEEKDAYS = {"en": list(calendar.day_name),
            "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]}


class Runner:
    """Lives in the monitor loop: decides when a test runs and runs it in its own thread, so the
    measurements keep going (and show the latency under load) while the link is full."""

    REQUEST_TTL = 600  # a "test now" press older than this (monitor was down) is ignored

    def __init__(self, store, run_fn=run, data_dir=None, asn_online: bool = False):
        self.store, self.run_fn = store, run_fn
        self.data_dir, self.asn_online = data_dir, asn_online
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
             link_busy_pct: float | None, counters=None, isp_asn: str | None = None) -> str | None:
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
        extra = {}
        if cfg.get("servers") or cfg.get("mlab"):
            extra = {"servers": cfg.get("servers") or [], "isp_asn": isp_asn,
                     "mark": lambda host: mark(host, isp_asn=isp_asn, data_dir=self.data_dir, online=self.asn_online)}
        if cfg.get("mlab") and cfg.get("mlab_accepted"):
            extra["mlab"] = True

        def job():
            try:
                res = self.run_fn(cap, wireless=wireless, trigger=trigger, counters=counters, **extra)
            except Exception as exc:  # noqa: BLE001 - recorded, never kills the monitor
                res = Result(ts=time.time(), wireless=wireless, trigger=trigger, error=str(exc))
            self.store.add_speedtest(res)
            self.ended = time.time()

        self.started, self.ended = now, None
        self.thread = threading.Thread(target=job, daemon=True, name="speedtest")
        self.thread.start()
        return "started"
