"""Your own destinations: "is it my internet, or is ARCA / my bank / my ERP down?"

Checked every 30 s (they are third-party services: we don't hammer them). Because checks are
sparse, the rule is consecutive results, not window statistics:
  down -> the last 3 checks failed AND your internet is healthy at the same time
  up   -> the last 2 checks succeeded
HTTP(S) counts as reachable on any status below 500 (403/404 still prove the server answers);
timeouts, DNS failures, TLS errors and 5xx count as failures. TLS certificates are verified.
"""

from __future__ import annotations

import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse

from . import __version__

KINDS = ("http", "tcp")
CHECK_EVERY = 30.0
TIMEOUT = 10.0
FAILS_TO_DOWN = 3
OKS_TO_UP = 2


class ServiceError(ValueError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    kind: str      # http | tcp
    target: str    # https://... or host:port


@dataclass
class Check:
    ts: float
    ok: bool
    ms: float | None
    detail: str    # "HTTP 200", "timeout", "DNS failure", ...


_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def validate(items: list[dict]) -> list[dict]:
    out, names = [], set()
    for raw in items:
        name = str(raw.get("name", "")).strip()
        kind = str(raw.get("kind", "http")).strip()
        target = str(raw.get("target", "")).strip()
        if not name or len(name) > 40:
            raise ServiceError("service name is required (max 40 characters)")
        if name in names:
            raise ServiceError(f"duplicate service name {name!r}")
        names.add(name)
        if kind not in KINDS:
            raise ServiceError("type must be http or tcp")
        if kind == "http":
            u = urlparse(target)
            if u.scheme not in ("http", "https") or not u.hostname:
                raise ServiceError(f"{name}: URL must look like https://www.example.com/")
        else:
            host, _, port = target.rpartition(":")
            if not host or not port.isdigit() or not 0 < int(port) < 65536 or not _HOST.match(host.strip("[]")):
                raise ServiceError(f"{name}: TCP target must look like host:port (e.g. erp.example.com:443)")
        out.append({"name": name, "kind": kind, "target": target})
    if len(out) > 20:
        raise ServiceError("at most 20 services")
    return out


def check_http(url: str, timeout: float = TIMEOUT) -> Check:
    start = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": f"isitmyisp/{__version__} (+connection monitor)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            resp.read(1024)
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError as exc:
        return Check(time.time(), False, None, _reason(exc.reason))
    except (TimeoutError, socket.timeout):
        return Check(time.time(), False, None, "timeout")
    except (OSError, ValueError) as exc:
        return Check(time.time(), False, None, _reason(exc))
    ms = round((time.perf_counter() - start) * 1000, 1)
    return Check(time.time(), status < 500, ms, f"HTTP {status}")


def check_tcp(target: str, timeout: float = TIMEOUT) -> Check:
    host, _, port = target.rpartition(":")
    start = time.perf_counter()
    try:
        with socket.create_connection((host.strip("[]"), int(port)), timeout=timeout):
            pass
    except (TimeoutError, socket.timeout):
        return Check(time.time(), False, None, "timeout")
    except OSError as exc:
        return Check(time.time(), False, None, _reason(exc))
    return Check(time.time(), True, round((time.perf_counter() - start) * 1000, 1), "TCP connect OK")


def _reason(err: object) -> str:
    text = str(err)
    if isinstance(err, socket.gaierror) or "Name or service not known" in text or "nodename" in text:
        return "DNS failure"
    if isinstance(err, ssl.SSLError) or "CERTIFICATE" in text.upper():
        return "TLS error"
    if isinstance(err, (TimeoutError, socket.timeout)) or "timed out" in text:
        return "timeout"
    if isinstance(err, ConnectionRefusedError) or "refused" in text:
        return "connection refused"
    return type(err).__name__ if not isinstance(err, str) else text[:60]


class ServiceProber:
    """Background checks; keeps the last results per service."""

    def __init__(self, services: list[Service], every: float = CHECK_EVERY, checker=None):
        self.services = list(services)
        self.every = every
        self.checker = checker or (lambda s: check_http(s.target) if s.kind == "http" else check_tcp(s.target))
        self.results: dict[str, deque[Check]] = {s.name: deque(maxlen=200) for s in self.services}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _round(self) -> None:
        def run(s: Service) -> None:
            c = self.checker(s)
            with self._lock:
                self.results[s.name].append(c)
        threads = [threading.Thread(target=run, args=(s,), daemon=True) for s in self.services]
        for t in threads:
            t.start()
        for t in threads:
            t.join(TIMEOUT + 2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self._round()
            self._stop.wait(max(1.0, self.every - (time.time() - started)))

    def __enter__(self) -> "ServiceProber":
        if self.services:
            threading.Thread(target=self._loop, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()

    def recent(self, name: str) -> list[Check]:
        with self._lock:
            return list(self.results.get(name, ()))


def state(checks: list[Check]) -> str | None:
    """'down' after FAILS_TO_DOWN consecutive failures, 'up' after OKS_TO_UP successes, else None (unchanged)."""
    if len(checks) >= FAILS_TO_DOWN and not any(c.ok for c in checks[-FAILS_TO_DOWN:]):
        return "down"
    if len(checks) >= OKS_TO_UP and all(c.ok for c in checks[-OKS_TO_UP:]):
        return "up"
    return None
