"""TCP-connect and DNS probes: what users actually feel.

ICMP alone can lie in both directions: some ISPs deprioritize ICMP (looks bad, is fine)
and "ping works but websites don't" is a real failure mode. So for each anchor we also
time a TCP handshake to port 443, and we time real DNS queries to each resolver.
No dependencies: plain sockets and a hand-built DNS query.
"""

from __future__ import annotations

import random
import socket
import struct
import threading
import time

from .icmp import WindowStats, _EventBuffer

DNS_NAMES = ["www.google.com", "www.cloudflare.com", "www.wikipedia.org"]


def tcp_connect_ms(host: str, port: int = 443, timeout: float = 2.0) -> float | None:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return round((time.perf_counter() - start) * 1000, 2)
    except OSError:
        return None


def _dns_query(name: str, qid: int) -> bytes:
    header = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)  # recursion desired, 1 question
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return header + qname + struct.pack("!HH", 1, 1)  # type A, class IN


def dns_query_ms(server: str, name: str, timeout: float = 2.0) -> float | None:
    """Time an A query. Returns None on timeout, SERVFAIL or REFUSED (NXDOMAIN counts as answered)."""
    qid = random.randint(0, 0xFFFF)
    packet = _dns_query(name, qid)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        start = time.perf_counter()
        try:
            sock.sendto(packet, (server, 53))
            deadline = start + timeout
            while True:
                sock.settimeout(max(0.01, deadline - time.perf_counter()))
                data, _ = sock.recvfrom(4096)
                if len(data) >= 4 and struct.unpack("!H", data[:2])[0] == qid:
                    rcode = data[3] & 0x0F
                    if rcode in (2, 5):  # SERVFAIL, REFUSED
                        return None
                    return round((time.perf_counter() - start) * 1000, 2)
        except OSError:
            return None


class SocketProber:
    """Runs TCP and DNS checks on a schedule in a background thread.

    Targets are named "tcp://host:port" and "dns://server" so they can share storage and
    statistics with ICMP targets.
    """

    def __init__(self, tcp: list[str], dns: list[str], interval: float = 5.0, timeout: float = 2.0):
        self.tcp = list(dict.fromkeys(tcp))
        self.dns = list(dict.fromkeys(dns))
        self.interval, self.timeout = interval, timeout
        self.buf = _EventBuffer(keep=2000)
        self._stop = threading.Event()
        self._seq = 0
        self._threads: list[threading.Thread] = []

    @staticmethod
    def tcp_name(host: str, port: int = 443) -> str:
        return f"tcp://{host}:{port}"

    @staticmethod
    def dns_name(server: str) -> str:
        return f"dns://{server}"

    @property
    def targets(self) -> list[str]:
        return [self.tcp_name(h) for h in self.tcp] + [self.dns_name(s) for s in self.dns]

    def _round(self) -> None:
        self._seq += 1
        seq, now = self._seq, time.time()
        jobs = [(self.tcp_name(h), lambda h=h: tcp_connect_ms(h, 443, self.timeout)) for h in self.tcp]
        name = DNS_NAMES[seq % len(DNS_NAMES)]
        jobs += [(self.dns_name(s), lambda s=s: dns_query_ms(s, name, self.timeout)) for s in self.dns]
        results: dict[str, float | None] = {}

        def run(key, fn):
            results[key] = fn()

        threads = [threading.Thread(target=run, args=j, daemon=True) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(self.timeout + 1)
        for key, _ in jobs:
            self.buf.record(key, now, seq, results.get(key))

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self._round()
            self._stop.wait(max(0.0, self.interval - (time.time() - started)))

    def __enter__(self) -> "SocketProber":
        if self.tcp or self.dns:
            t = threading.Thread(target=self._loop, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()

    def window(self, seconds: float) -> dict[str, WindowStats]:
        now = time.time()
        return {t: self.buf.window(t, seconds, now) for t in self.targets}

