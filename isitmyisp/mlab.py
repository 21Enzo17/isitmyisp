"""M-Lab NDT7: a speed test engine with servers in many more cities than any other open one.

Measurement Lab (measurementlab.net) runs NDT servers inside transit providers and IXPs around the
world, and its locate API hands out the nearest ones. NDT7 is a WebSocket over TLS: on the download
URL the server sends for about 10 s, on the upload URL it receives. Both are spoken here with the
standard library only.

Why it exists next to Cloudflare: on some lines Cloudflare's own server, or its peering with the ISP,
is the ceiling (a 1000 Mbps fibre that measured 930 against M-Lab measured 490 against Cloudflare).

M-Lab PUBLISHES EVERY TEST AS OPEN DATA, including your public IP address. That is the price of a
free, open measurement platform, and why it has its own consent in Settings, off by default.

CPU: a small probe (a 2-core Pentium without AES-NI) runs near 95 % at 930 Mbps in Python TLS, so
reads and writes go in large blocks, and uploads send pre-built frames (no per-frame work).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable

from .speedtest import (
    DOWN_SECONDS,
    DOWN_SHARE,
    UA,
    UP_SECONDS,
    SpeedError,
    _Meter,
    _run_streams,
)

LOCATE_URL = "https://locate.measurementlab.net/v2/nearest/ndt/ndt7"
PROTOCOL = "net.measurementlab.ndt.v7"
DOWN_KEY, UP_KEY = "wss:///ndt/v7/download", "wss:///ndt/v7/upload"
STREAMS = 2            # NDT7 is one stream per test; two tokens for the same machine fill a gigabit line
READ = 1 << 18         # 256 kB per recv: fewer calls, less CPU
FRAME = 1 << 20        # 1 MiB upload messages (the largest NDT7 clients use)
NAME = "M-Lab"


def locate(opener=urllib.request.urlopen) -> list[dict]:
    """The nearest NDT7 machines, nearest first: [{machine, city, country, down, up}]. Each URL
    carries a short-lived access token for that machine."""
    req = urllib.request.Request(LOCATE_URL, headers={"User-Agent": UA})
    try:
        with opener(req, timeout=10) as resp:
            data = json.loads(resp.read() or b"{}")
    except (OSError, ValueError) as exc:
        raise SpeedError(f"{NAME}: locate: {exc}") from exc
    out = []
    for r in data.get("results") or []:
        urls, loc = r.get("urls") or {}, r.get("location") or {}
        if urls.get(DOWN_KEY) and urls.get(UP_KEY):
            out.append({"machine": r.get("machine") or "", "city": loc.get("city") or "",
                        "country": loc.get("country") or "", "down": urls[DOWN_KEY], "up": urls[UP_KEY]})
    if not out:
        raise SpeedError(f"{NAME}: locate: no server available")
    return out


def _tcp_ms(url: str, timeout: float = 3.0) -> float | None:
    """How long a TCP handshake to that machine takes (name already resolved): its round trip."""
    u = urllib.parse.urlparse(url)
    try:
        addr = socket.getaddrinfo(u.hostname, u.port or 443, type=socket.SOCK_STREAM)[0][4]
        t0 = time.monotonic()
        socket.create_connection(addr[:2], timeout=timeout).close()
    except (OSError, IndexError, UnicodeError):
        return None
    return (time.monotonic() - t0) * 1000


def pick(opener=urllib.request.urlopen, streams: int = STREAMS,
         rtt: Callable[[str], float | None] = _tcp_ms) -> list[dict]:
    """`streams` tokens for the same machine (one locate call per token), so every stream measures
    the same path. The locate API's "nearest" is by geolocation and can be another country; of the
    machines it offers, the one with the shortest round trip wins. If a later call doesn't offer
    that machine, its nearest one is used."""
    first = locate(opener)
    timed = [(t, i) for i, m in enumerate(first) if (t := rtt(m["down"])) is not None]
    chosen = [first[min(timed)[1] if timed else 0]]
    for _ in range(streams - 1):
        more = locate(opener)
        chosen.append(next((m for m in more if m["machine"] == chosen[0]["machine"]), more[0]))
    return chosen


def connect(url: str, timeout: float = 10.0) -> tuple[socket.socket, float, bytes]:
    """Open the WebSocket: (socket, TCP connect time in ms, bytes already read past the headers)."""
    u = urllib.parse.urlparse(url)
    host, port = u.hostname or "", u.port or 443
    addr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4]   # resolve first: DNS isn't round trip
    t0 = time.monotonic()
    raw = socket.create_connection(addr[:2], timeout=timeout)
    rtt = (time.monotonic() - t0) * 1000
    try:
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {u.path}?{u.query} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                      f"Sec-WebSocket-Protocol: {PROTOCOL}\r\nUser-Agent: {UA}\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            block = sock.recv(4096)
            if not block or len(head) > 65536:
                raise OSError("connection closed during the handshake")
            head += block
        status, _, rest = head.partition(b"\r\n\r\n")
        line = status.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in f"{line} ":
            raise OSError(f"refused: {line.strip()[:80]}")
        sock.settimeout(timeout)
        return sock, rtt, rest
    except Exception:
        raw.close()
        raise


def upload_frame(size: int = FRAME) -> bytes:
    """One masked binary WebSocket message, built once and sent over and over. Masked data is the
    payload XOR the key, so random bytes are already a valid masked payload: nothing to compute."""
    if size < 126:
        length = bytes([0x80 | size])
    elif size < 65536:
        length = bytes([0x80 | 126]) + size.to_bytes(2, "big")
    else:
        length = bytes([0x80 | 127]) + size.to_bytes(8, "big")
    return bytes([0x82]) + length + os.urandom(4) + os.urandom(size)


def _drain(sock) -> None:
    """Read and drop what the server sends during the upload (its measurements), so it never stalls."""
    try:
        while sock.recv(65536):
            pass
    except OSError:
        pass


def run(max_bytes: int, *, opener=urllib.request.urlopen, connect: Callable = connect,
        clock: Callable[[], float] = time.monotonic, down_seconds: float = DOWN_SECONDS,
        up_seconds: float = UP_SECONDS, mark: Callable[[str], dict] | None = None,
        streams: int = STREAMS, rtt: Callable[[str], float | None] = _tcp_ms) -> dict:
    """Download and upload against the nearest M-Lab machine. The result has the shape of an iperf3
    server's (see speedtest.run_server), plus the machine's city and its round-trip time."""
    out = {"name": NAME, "engine": "mlab", "where": None, "forced": False, "asn": None, "as_name": None,
           "down_mbps": None, "up_mbps": None, "bytes": 0, "error": None, "rtt_ms": None, "city": None}
    rtts: list[float] = []
    try:
        machines = pick(opener, streams, rtt)
        host = urllib.parse.urlparse(machines[0]["down"]).hostname or ""
        out["city"] = machines[0]["city"] or None
        out["name"] = f"{NAME} {machines[0]['city']}".strip() if machines[0]["city"] else NAME
        info = (mark or (lambda h: {}))(host) or {}
        out.update({k: info.get(k) for k in ("asn", "as_name", "where")})

        down = _Meter(int(max_bytes * DOWN_SHARE), clock)

        def downloader(url):
            def work():
                sock, rtt, rest = connect(url)
                rtts.append(rtt)
                try:
                    down.add(len(rest))
                    while not down.stop.is_set():
                        block = sock.recv(READ)
                        if not block:
                            break
                        down.add(len(block))
                finally:
                    sock.close()
            return work
        _run_streams([downloader(m["down"]) for m in machines], down, down_seconds, NAME)
        out["down_mbps"], out["bytes"] = down.mbps(), down.total

        up = _Meter(int(max_bytes * (1 - DOWN_SHARE)), clock)
        frame = upload_frame()
        payload = FRAME

        def uploader(url):
            def work():
                sock, rtt, _ = connect(url)
                rtts.append(rtt)
                threading.Thread(target=_drain, args=(sock,), daemon=True).start()
                try:
                    while not up.stop.is_set():
                        sock.sendall(frame)
                        up.add(payload)
                finally:
                    sock.close()
            return work
        _run_streams([uploader(m["up"]) for m in machines], up, up_seconds, NAME)
        out["up_mbps"] = up.mbps()
        out["bytes"] += up.total
    except SpeedError as exc:
        out["error"] = str(exc)
    if rtts:
        out["rtt_ms"] = round(min(rtts), 1)
    return out
