"""Signs of a loop or a broadcast storm on the local network.

Three cheap signals that need no extra permissions, read while the monitor runs:

- duplicate replies (``DUP!``) to a ping to the gateway: a frame that went round a loop arrives twice;
- the network card's multicast counter (most drivers count broadcast in it too) jumping far above
  its usual rate;
- the gateway's MAC changing back and forth in the ARP table: the router's frames arriving through
  two different paths.

``fping -l`` drops duplicate replies silently, so the gateway gets its own iputils ping here (1/s).
The router side (broadcast per interface, over SNMP) lives in :mod:`isitmyisp.snmp`.
"""

from __future__ import annotations

import re
import shutil
import statistics
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

STORM_PPS = 500.0        # multicast + broadcast packets/s on the card: a storm whatever the usual rate
STORM_FACTOR = 10.0      # or this many times the usual rate...
STORM_MIN_PPS = 100.0    # ...when it is at least this much
DUP_MIN = 2              # duplicate replies in one window before calling it a loop
FLAP_MIN = 2             # MAC changes in one window (A→B→A); a single change can be a router swap
SAMPLE_S = 2.0

_DUP = re.compile(r"icmp_seq=\d+.*\(DUP!\)")
_REPLY = re.compile(r"bytes from .*icmp_seq=\d+")
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@dataclass
class LanStats:
    dups: int = 0                    # duplicate replies from the gateway in the window
    replies: int = 0                 # all replies, duplicates included
    macs: list[str] = field(default_factory=list)   # gateway MACs, in the order they showed up
    flaps: int = 0                   # times the gateway MAC changed in the window
    mcast_pps: float | None = None   # peak multicast/broadcast rate on the card (per sample)
    mcast_base: float | None = None  # its usual rate, from earlier windows

    @property
    def storm(self) -> bool:
        p = self.mcast_pps
        if p is None:
            return False
        if p >= STORM_PPS:
            return True
        return self.mcast_base is not None and p >= STORM_MIN_PPS and p >= STORM_FACTOR * max(self.mcast_base, 1.0)

    def signals(self) -> list[str]:
        """Evidence lines for each sign found (empty: no sign of a loop)."""
        out = []
        if self.dups >= DUP_MIN:
            out.append(f"gateway ping: {self.dups} duplicate replies (DUP) out of {self.replies}")
        if self.storm:
            usual = f" (usual {self.mcast_base:.0f})" if self.mcast_base is not None else ""
            out.append(f"broadcast on your network card: {self.mcast_pps:.0f} packets/s{usual}")
        if self.flaps >= FLAP_MIN:
            out.append(f"gateway MAC changed {self.flaps} times: {' / '.join(self.macs[:3])}")
        return out


def arp_mac(ip: str, text: str) -> str | None:
    """The MAC for ``ip`` in a /proc/net/arp dump (None when absent or incomplete)."""
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 4 and cols[0] == ip and _MAC.match(cols[3].lower()) and cols[3] != "00:00:00:00:00:00":
            return cols[3].lower()
    return None


class LanWatch:
    """Samples the card and the ARP table every few seconds, and pings the gateway, in the background."""

    def __init__(self, gateway: str | None, interface: str | None, sample_s: float = SAMPLE_S,
                 ping: bool = True, sys_root: str = "/sys/class/net", arp_path: str = "/proc/net/arp"):
        self.gateway, self.interface, self.sample_s = gateway, interface, sample_s
        self._ping = ping and bool(gateway) and shutil.which("ping") is not None
        self._counter = Path(sys_root, interface or "-", "statistics", "multicast")
        self._arp = Path(arp_path)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._last: tuple[float, int] | None = None
        self._rates: list[float] = []
        self._history: deque[float] = deque(maxlen=60)   # median rate of earlier calm windows
        self._mac: str | None = None
        self._macs: list[str] = []
        self._flaps = 0
        self._dups = self._replies = 0

    def __enter__(self) -> LanWatch:
        if self._ping:
            try:
                self._proc = subprocess.Popen(["ping", "-n", "-i", "1", self.gateway], stdout=subprocess.PIPE,
                                              stderr=subprocess.DEVNULL, text=True, bufsize=1)
                threading.Thread(target=self._reader, args=(self._proc,), daemon=True).start()
            except OSError:
                self._proc = None
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def _reader(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            self.feed_ping(line)

    def feed_ping(self, line: str) -> None:
        if not _REPLY.search(line):
            return
        with self._lock:
            self._replies += 1
            if _DUP.search(line):
                self._dups += 1

    def _loop(self) -> None:
        while not self._stop.wait(self.sample_s):
            self.sample()

    def sample(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        count = mac = None
        try:
            count = int(self._counter.read_text().strip())
        except (OSError, ValueError):
            pass
        if self.gateway:
            try:
                mac = arp_mac(self.gateway, self._arp.read_text())
            except OSError:
                pass
        with self._lock:
            if count is not None:
                prev, self._last = self._last, (now, count)
                if prev and now > prev[0] and count >= prev[1]:   # a lower count: driver reset
                    self._rates.append((count - prev[1]) / (now - prev[0]))
            if mac:
                if mac not in self._macs:
                    self._macs.append(mac)
                if self._mac and mac != self._mac:
                    self._flaps += 1
                self._mac = mac

    def window(self) -> LanStats:
        """What was seen since the last call; starts a new window."""
        with self._lock:
            base = statistics.median(self._history) if self._history else None
            st = LanStats(self._dups, self._replies, list(self._macs), self._flaps,
                          round(max(self._rates), 1) if self._rates else None,
                          None if base is None else round(base, 1))
            if self._rates and not st.storm:
                self._history.append(statistics.median(self._rates))
            self._rates, self._dups, self._replies, self._flaps = [], 0, 0, 0
            self._macs = [self._mac] if self._mac else []
        return st
