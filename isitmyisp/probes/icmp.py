"""Continuous ICMP probing.

Engine choice:
  * fping (preferred): one process for all targets, built for monitoring (SmokePing uses it),
    and in loop mode it prints one line per packet *including* an explicit "timed out" line,
    so loss is never guessed.
  * system ping (fallback): one process per target, used only when fping is missing.
    BusyBox ping lacks -D/-O, so it is not supported; the Docker image always ships fping.

All subprocesses run with LC_ALL=C so their output is never localized.
"""

from __future__ import annotations

import os
import re
import shutil
import statistics
import subprocess
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from ..netutil import is_ipv6

C_ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}

# fping -l -D:  [1794279664.24863] 1.1.1.1   : [0], 64 bytes, 29.3 ms (29.3 avg, 0% loss)
#               [1794279665.03275] 192.0.2.1 : [0], timed out (NaN avg, 100% loss)
_FPING = re.compile(
    r"^\[(?P<ts>\d+\.\d+)\]\s+(?P<host>\S+)\s+:\s+\[(?P<seq>\d+)\],\s+"
    r"(?:(?:\d+ bytes, (?P<rtt>[\d.]+) ms)|(?P<timeout>timed out))"
)
# ping -D -O:   [1794278609.305086] 64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=28.9 ms
#               [1794279521.685757] no answer yet for icmp_seq=1
_PING_REPLY = re.compile(r"^\[(?P<ts>\d+\.\d+)\].*icmp_seq=(?P<seq>\d+).*time=(?P<rtt>[\d.]+) ms")
_PING_LOST = re.compile(r"^\[(?P<ts>\d+\.\d+)\] no answer yet for icmp_seq=(?P<seq>\d+)")

Event = tuple[float, int, "float | None"]  # (timestamp, seq, rtt_ms or None if lost)


@dataclass
class WindowStats:
    target: str
    sent: int
    received: int
    rtt_min: float | None
    rtt_avg: float | None
    rtt_max: float | None
    jitter: float | None  # mean absolute difference between consecutive RTTs
    rtt_median: float | None = None

    @property
    def lost(self) -> int:
        return self.sent - self.received

    @property
    def loss(self) -> float:
        return 0.0 if self.sent == 0 else round(100.0 * self.lost / self.sent, 1)


def summarize(target: str, events: list[Event]) -> WindowStats:
    by_seq: dict[int, float | None] = {}
    for _, seq, rtt in events:
        if rtt is not None or seq not in by_seq:
            by_seq[seq] = rtt
    rtts = [r for r in by_seq.values() if r is not None]
    jitter = None
    if len(rtts) >= 2:
        jitter = round(statistics.fmean(abs(a - b) for a, b in zip(rtts, rtts[1:])), 2)
    return WindowStats(
        target=target,
        sent=len(by_seq),
        received=len(rtts),
        rtt_min=min(rtts) if rtts else None,
        rtt_avg=round(statistics.fmean(rtts), 2) if rtts else None,
        rtt_max=max(rtts) if rtts else None,
        jitter=jitter,
        rtt_median=round(statistics.median(rtts), 2) if rtts else None,
    )


class _EventBuffer:
    def __init__(self, keep: int = 7200):
        self._events: dict[str, deque[Event]] = defaultdict(lambda: deque(maxlen=keep))
        self._lock = threading.Lock()

    def record(self, target: str, ts: float, seq: int, rtt: float | None) -> None:
        with self._lock:
            buf = self._events[target]
            if rtt is not None:  # a late reply replaces an earlier "lost" for the same seq
                for i in range(len(buf) - 1, max(-1, len(buf) - 11), -1):
                    if buf[i][1] == seq:
                        buf[i] = (buf[i][0], seq, rtt)
                        return
            buf.append((ts, seq, rtt))

    def window(self, target: str, seconds: float, now: float) -> WindowStats:
        start = now - seconds
        with self._lock:
            events = [e for e in self._events.get(target, ()) if start <= e[0] <= now]
        return summarize(target, events)


class _ProcessProber:
    def __init__(self, targets: list[str], interval: float, timeout: float):
        self.targets = list(dict.fromkeys(targets))
        self.interval, self.timeout = interval, timeout
        self.buf = _EventBuffer()
        self._procs: list[subprocess.Popen] = []

    def stop(self) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()

    def window(self, seconds: float) -> dict[str, WindowStats]:
        # Ignore the last `timeout` seconds: those packets may still be in flight.
        now = time.time() - self.timeout
        return {t: self.buf.window(t, seconds, now) for t in self.targets}

    def _spawn(self, cmd: list[str], merge_stderr: bool) -> subprocess.Popen:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL,
                                text=True, bufsize=1, env=C_ENV)
        self._procs.append(proc)
        return proc


class FpingProber(_ProcessProber):
    """All targets in one `fping -l -D` process (one per address family)."""

    def __init__(self, targets: list[str], interval: float = 1.0, timeout: float = 1.0):
        super().__init__(targets, interval, min(timeout, interval * 0.9))

    @staticmethod
    def available() -> bool:
        return shutil.which("fping") is not None

    def start(self) -> None:
        for fam, group in (("-4", [t for t in self.targets if not is_ipv6(t)]),
                           ("-6", [t for t in self.targets if is_ipv6(t)])):
            if group:
                proc = self._spawn(["fping", fam, "-l", "-D", "-p", str(int(self.interval * 1000)),
                                    "-t", str(int(self.timeout * 1000)), *group], merge_stderr=True)
                threading.Thread(target=self._reader, args=(proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout
        for line in proc.stdout:
            self.feed(line)

    def feed(self, line: str) -> None:
        m = _FPING.match(line)
        if m:
            rtt = None if m["timeout"] else float(m["rtt"])
            self.buf.record(m["host"], float(m["ts"]), int(m["seq"]), rtt)


class PingProber(_ProcessProber):
    """Fallback: one iputils `ping -D -O` per target."""

    def __init__(self, targets: list[str], interval: float = 1.0, timeout: float = 2.0):
        super().__init__(targets, interval, timeout)

    @staticmethod
    def available() -> bool:
        return shutil.which("ping") is not None

    def start(self) -> None:
        for t in self.targets:
            cmd = ["ping", "-n", "-D", "-O", "-i", str(self.interval), "-W", str(self.timeout)]
            if is_ipv6(t):
                cmd.insert(1, "-6")
            proc = self._spawn([*cmd, t], merge_stderr=False)
            threading.Thread(target=self._reader, args=(t, proc), daemon=True).start()

    def _reader(self, target: str, proc: subprocess.Popen) -> None:
        assert proc.stdout
        for line in proc.stdout:
            self.feed(target, line)

    def feed(self, target: str, line: str) -> None:
        m = _PING_REPLY.match(line)
        if m:
            self.buf.record(target, float(m["ts"]), int(m["seq"]), float(m["rtt"]))
            return
        m = _PING_LOST.match(line)
        if m:
            self.buf.record(target, float(m["ts"]), int(m["seq"]), None)


class IcmpProber:
    """Context manager that picks fping, else ping."""

    def __init__(self, targets: list[str], interval: float = 1.0, engine: str | None = None):
        use_fping = engine == "fping" or (engine is None and FpingProber.available())
        if use_fping:
            self.engine: FpingProber | PingProber = FpingProber(targets, interval)
        elif PingProber.available():
            self.engine = PingProber(targets, interval)
        else:
            raise RuntimeError("neither fping nor ping is installed (apt install fping)")

    @property
    def name(self) -> str:
        return "fping" if isinstance(self.engine, FpingProber) else "ping"

    def __enter__(self) -> "IcmpProber":
        self.engine.start()
        return self

    def __exit__(self, *exc) -> None:
        self.engine.stop()

    def window(self, seconds: float) -> dict[str, WindowStats]:
        return self.engine.window(seconds)
