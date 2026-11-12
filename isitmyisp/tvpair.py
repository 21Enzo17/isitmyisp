"""Pairing a wall screen with a short code, like a streaming app on a TV.

Typing a long secret link with a TV remote is miserable. Instead the TV opens <address>/tv and shows
a short code; an admin types that code in Settings, and the TV receives its own long-lived device
cookie. Nothing secret is ever typed on the TV, every screen can be unpaired on its own, and the
code is useless after it's used or after ten minutes.

Only hashes are stored: the pending pairing's browser secret and each device's token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from .store import Store

PENDING = "_tv_pending"       # {code: {"secret": sha256, "ts": created, "device": token-or-None}}
DEVICES = "tv_devices"        # [{"id", "name", "hash", "created", "seen"}]
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L: readable across a room
CODE_LEN = 6
TTL = 10 * 60                 # a code is valid this long
MAX_PENDING = 20              # anyone can open /tv: don't let them fill the database
MAX_DEVICES = 20
SEEN_EVERY = 300              # update "last seen" at most this often


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def pretty(code: str) -> str:
    return f"{code[:3]}-{code[3:]}"


def normalize(code: str) -> str:
    return "".join(c for c in code.upper() if c in ALPHABET)


def _pending(store: Store, now: float) -> dict:
    return {c: p for c, p in (store.get_setting(PENDING) or {}).items() if now - p.get("ts", 0) < TTL}


def start(store: Store, now: float | None = None) -> tuple[str, str] | None:
    """A new code for a screen: (code, browser secret), or None when too many are pending."""
    now = now or time.time()
    pend = _pending(store, now)
    if len(pend) >= MAX_PENDING:
        return None
    code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
    secret = secrets.token_urlsafe(24)
    pend[code] = {"secret": _h(secret), "ts": now, "device": None}
    store.set_settings({PENDING: pend}, bump=False)
    return code, secret


def status(store: Store, secret: str, now: float | None = None) -> tuple[str | None, str | None]:
    """For the screen that holds `secret`: (its code while waiting, its device token once approved)."""
    now = now or time.time()
    hs = _h(secret)
    pend = _pending(store, now)
    for code, p in pend.items():
        if hmac.compare_digest(p["secret"], hs):
            if p.get("device"):
                token = p["device"]
                del pend[code]                       # handed over once, then the code is gone
                store.set_settings({PENDING: pend}, bump=False)
                return None, token
            return code, None
    return None, None


def approve(store: Store, code: str, name: str, now: float | None = None) -> bool:
    """An admin typed the code shown on a screen: give that screen a device of its own."""
    now = now or time.time()
    code = normalize(code)
    pend = _pending(store, now)
    if code not in pend or pend[code].get("device"):
        return False
    devices = store.get_setting(DEVICES) or []
    if len(devices) >= MAX_DEVICES:
        return False
    token = secrets.token_urlsafe(32)
    devices.append({"id": secrets.token_hex(6), "name": (name or "").strip()[:40] or pretty(code),
                    "hash": _h(token), "created": now, "seen": None})
    pend[code]["device"] = token
    store.set_settings({DEVICES: devices, PENDING: pend}, bump=False)
    return True


def device(store: Store, token: str | None, now: float | None = None) -> dict | None:
    """The paired screen this cookie belongs to (and note that it was seen)."""
    if not token:
        return None
    now = now or time.time()
    ht = _h(token)
    devices = store.get_setting(DEVICES) or []
    for d in devices:
        if hmac.compare_digest(d["hash"], ht):
            if not d.get("seen") or now - d["seen"] > SEEN_EVERY:
                d["seen"] = now
                store.set_settings({DEVICES: devices}, bump=False)
            return d
    return None


def unpair(store: Store, device_id: str) -> None:
    store.set_settings({DEVICES: [d for d in store.get_setting(DEVICES) or [] if d["id"] != device_id]}, bump=False)


def listing(store: Store) -> list[dict]:
    return [{k: d.get(k) for k in ("id", "name", "created", "seen")} for d in store.get_setting(DEVICES) or []]
