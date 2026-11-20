"""Static public IP (#102): if you pay for a fixed address, say so and you're told when it isn't the one.

Off unless you set the address in Settings: only then does the monitor ask a third-party service
(ipify) for your public IP, once every 10 minutes. Most homes get a new address every now and then
and that's normal, so without a static IP nothing is checked and nothing is said.

Two lookups in a row with another address open an incident (one odd answer is not enough); it
closes as soon as the expected address is back. A lookup that fails (no internet, ipify down) says
nothing: being offline is another incident's business.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .store import Store

SCOPE = CODE = "public_ip"
EVERY = 600.0
CONFIRM = 2

Lookup = Callable[[], "str | None"]


def _lookup() -> str | None:
    from .discovery import public_ipv4
    return public_ipv4()


class Checker:
    def __init__(self, store: Store, lookup: Lookup = _lookup, every: float = EVERY,
                 background: bool = True) -> None:
        self.store, self.lookup, self.every, self.background = store, lookup, every, background
        self._last = 0.0
        self._misses = 0
        self._result: tuple[float, str | None] | None = None
        self._busy = False
        self._lock = threading.Lock()

    def _open(self) -> list:
        return [i for i in self.store.active_incidents() if i.scope == SCOPE]

    def _ask(self, now: float) -> None:
        def job() -> None:
            ip = self.lookup()
            with self._lock:
                self._result, self._busy = (now, ip), False
        self._busy = True
        if self.background:
            threading.Thread(target=job, daemon=True, name="public-ip").start()
        else:
            job()

    def tick(self, expected: str, now: float | None = None) -> str | None:
        """Call once per window. Returns "opened" or "closed" when the incident changed."""
        now = now or time.time()
        if not expected:                       # turned off: nothing to watch, nothing left open
            self._misses = 0
            for inc in self._open():
                self.store.close_incident(inc.id, ts=now)
            return None
        with self._lock:
            got, self._result = self._result, None
            due = not self._busy and now - self._last >= self.every
        if due:
            self._last = now
            self._ask(now)
            if not self.background:
                with self._lock:
                    got, self._result = self._result, None
        if got is None or got[1] is None:
            return None
        ts, ip = got
        open_ = self._open()
        if ip == expected:
            self._misses = 0
            for inc in open_:
                self.store.close_incident(inc.id, ts=ts)
            return "closed" if open_ else None
        self._misses += 1
        if open_:
            inc = open_[0]
            if (inc.details or {}).get("seen") != ip:   # it changed again: keep the latest one
                self.store.set_incident_details(inc.id, {**(inc.details or {}), "seen": ip})
            return None
        if self._misses < CONFIRM:
            return None
        iid = self.store.open_incident(CODE, [f"{expected} → {ip}"], ts=ts, scope=SCOPE)
        self.store.set_incident_details(iid, {"expected": expected, "seen": ip})
        return "opened"
