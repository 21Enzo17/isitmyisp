"""Authentication, built on audited libraries instead of hand-rolled crypto.

  local -> Flask-Login sessions, Argon2id password hashes (argon2-cffi), rate-limited login
  proxy -> trust a header (Remote-User) set by Authelia / Authentik / oauth2-proxy / Tailscale,
           ONLY when the request comes from a trusted proxy address
  none  -> no login; allowed only when the UI listens on loopback, and settings are read-only

Every state-changing request also needs a CSRF token (Flask-WTF) and a same-origin `Origin`.
"""

from __future__ import annotations

import hmac
import ipaddress

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask_login import UserMixin

from ..store import Store

_ph = PasswordHasher()  # Argon2id with argon2-cffi's (RFC 9106) defaults
MIN_PASSWORD = 10


ROLES = ("admin", "viewer")


class User(UserMixin):
    def __init__(self, uid: str, username: str, source: str = "local", role: str = "admin"):
        self.id = uid
        self.username = username
        self.source = source  # local | proxy | none | demo
        self.role = role      # admin: everything; viewer: sees everything, changes nothing

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(store: Store, username: str, password: str) -> User | None:
    row = store.get_user(username=username)
    if row is None:
        _ph.hash(password)  # same cost whether or not the user exists (no username oracle via timing)
        return None
    uid, name, phash = row
    try:
        _ph.verify(phash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return None
    info = store.user_info(uid)
    if info is None or info["disabled"]:   # checked after the hash: same cost as a wrong password
        return None
    if _ph.check_needs_rehash(phash):
        store.set_password_hash(uid, _ph.hash(password))
    return User(str(uid), name, role=info["role"])


def password_problem(password: str, confirm: str) -> str | None:
    if password != confirm:
        return "mismatch"
    if len(password) < MIN_PASSWORD:
        return "short"
    return None


def load_local_user(store: Store, uid: str) -> User | None:
    try:
        info = store.user_info(int(uid))
    except (TypeError, ValueError):
        return None
    if info is None or info["disabled"]:   # a disabled account loses its open sessions at once
        return None
    return User(str(info["id"]), info["username"], role=info["role"])


USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-@")


def username_problem(name: str) -> str | None:
    if not 2 <= len(name) <= 64 or not set(name) <= USERNAME_CHARS:
        return "username"
    return None


def token_hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def client_is_trusted_proxy(remote_addr: str | None, trusted: list[str]) -> bool:
    if not remote_addr:
        return False
    try:
        ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False
    for net in trusted:
        try:
            if ip in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def proxy_user(remote_addr: str | None, headers, header: str, trusted: list[str]) -> User | None:
    if not client_is_trusted_proxy(remote_addr, trusted):
        return None
    name = (headers.get(header) or "").strip()
    if not name or len(name) > 128:
        return None
    return User(f"proxy:{name}", name, source="proxy")


def is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def bearer_matches(auth_header: str | None, expected: str) -> bool:
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    return hmac.compare_digest(auth_header[len("Bearer "):].strip(), expected)
