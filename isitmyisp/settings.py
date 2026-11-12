"""Runtime settings: stored in SQLite, edited from the web UI, applied live by the monitor.

A TOML file (see config.py) still works: when one is present, tunnels come from the file
and the UI shows them read-only ("configuration as code" for those who prefer it).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, ConfigError, Tunnel, load as load_toml, parse as parse_tunnels
from .devices import Device
from .services import Service
from .store import Store

from .speedtest import DEFAULTS as SPEED_DEFAULTS

AUTH_MODES = ("local", "proxy", "none")

DEFAULTS: dict = {
    "anchors": ["1.1.1.1", "8.8.8.8", "9.9.9.9"],
    "interval": 2.0,           # seconds between pings
    "window": 30,              # seconds per measurement window
    "lang": "en",
    "auth_mode": "local",
    "proxy_header": "Remote-User",
    "trusted_proxies": ["127.0.0.1/32", "::1/128"],
    "voip_target": "",         # optional: your SIP provider / cloud PBX, to judge call quality against it
    "speedtest": {},           # see speedtest.DEFAULTS: OFF until you turn it on and accept the risks
    "tunnels": [],             # list of {name, underlay, overlay, type}
    "services": [],            # list of {name, kind: http|tcp, target}
    "devices": [],             # list of {name, kind, target, port|None}: card terminals, printers… on your LAN
    "link": {"enabled": False, "host": "", "community": "", "port": 161, "interface": "",
             "down_mbps": 0, "up_mbps": 0},  # WAN usage read from the router by SNMP
}

SETUP_TOKEN_TTL = 24 * 3600


class SettingsError(ValueError):
    pass


@dataclass
class Settings:
    anchors: list[str] = field(default_factory=lambda: list(DEFAULTS["anchors"]))
    interval: float = DEFAULTS["interval"]
    window: int = DEFAULTS["window"]
    lang: str = DEFAULTS["lang"]
    auth_mode: str = DEFAULTS["auth_mode"]
    proxy_header: str = DEFAULTS["proxy_header"]
    trusted_proxies: list[str] = field(default_factory=lambda: list(DEFAULTS["trusted_proxies"]))
    tunnels: list[Tunnel] = field(default_factory=list)
    tunnels_from_file: Path | None = None  # set when a TOML file provides the tunnels
    services: list = field(default_factory=list)  # list[services.Service]
    devices: list = field(default_factory=list)   # list[devices.Device]
    link: dict = field(default_factory=lambda: dict(DEFAULTS["link"]))
    voip_target: str = ""
    speedtest: dict = field(default_factory=dict)
    version: int = 0


# ------------------------------------------------------------------ validation

def validate(values: dict) -> dict:
    """Validate user input (from a form or an import). Returns a clean dict or raises SettingsError."""
    out: dict = {}
    if "anchors" in values:
        anchors = [a.strip() for a in values["anchors"] if a and a.strip()]
        if not 1 <= len(anchors) <= 6:
            raise SettingsError("between 1 and 6 anchors")
        for a in anchors:
            try:
                ip = ipaddress.ip_address(a)
            except ValueError as exc:
                raise SettingsError(f"anchor {a!r} is not an IP address") from exc
            if not ip.is_global:
                raise SettingsError(f"anchor {a} must be a public address")
        out["anchors"] = list(dict.fromkeys(anchors))
    if "interval" in values:
        try:
            interval = float(values["interval"])
        except (TypeError, ValueError) as exc:
            raise SettingsError("interval must be a number") from exc
        if not 0.5 <= interval <= 10:
            raise SettingsError("interval must be between 0.5 and 10 seconds")
        out["interval"] = interval
    if "window" in values:
        try:
            window = int(values["window"])
        except (TypeError, ValueError) as exc:
            raise SettingsError("window must be a whole number") from exc
        if not 10 <= window <= 300:
            raise SettingsError("window must be between 10 and 300 seconds")
        out["window"] = window
    if "lang" in values:
        if values["lang"] not in ("en", "es"):
            raise SettingsError("language must be en or es")
        out["lang"] = values["lang"]
    if "auth_mode" in values:
        if values["auth_mode"] not in AUTH_MODES:
            raise SettingsError(f"auth mode must be one of {AUTH_MODES}")
        out["auth_mode"] = values["auth_mode"]
    if "proxy_header" in values:
        header = str(values["proxy_header"]).strip()
        if not header or not all(c.isalnum() or c == "-" for c in header):
            raise SettingsError("proxy header must be a header name like Remote-User")
        out["proxy_header"] = header
    if "trusted_proxies" in values:
        nets = []
        for n in values["trusted_proxies"]:
            n = n.strip()
            if not n:
                continue
            try:
                nets.append(str(ipaddress.ip_network(n, strict=False)))
            except ValueError as exc:
                raise SettingsError(f"trusted proxy {n!r} is not an IP or CIDR") from exc
        out["trusted_proxies"] = nets
    if "voip_target" in values:
        target = str(values["voip_target"] or "").strip()
        if target:
            try:
                ip = ipaddress.ip_address(target)
            except ValueError as exc:
                raise SettingsError(f"calls destination {target!r} must be an IP address") from exc
            if not ip.is_global:
                raise SettingsError(f"calls destination {target} must be a public address")
        out["voip_target"] = target
    if "speedtest" in values:
        from .speedtest import validate as validate_speed
        try:
            out["speedtest"] = validate_speed(values["speedtest"], values.get("_speed_current") or {})
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
    if "tunnels" in values:
        try:
            parsed = parse_tunnels({"tunnel": values["tunnels"]}).tunnels
        except ConfigError as exc:
            raise SettingsError(str(exc)) from exc
        out["tunnels"] = [t.__dict__ for t in parsed]
    if "link" in values:
        out["link"] = _validate_link(values["link"])
    if "devices" in values:
        from .devices import DeviceError, validate as validate_devices
        try:
            out["devices"] = validate_devices(values["devices"])
        except DeviceError as exc:
            raise SettingsError(str(exc)) from exc
    if "services" in values:
        from .services import ServiceError, validate as validate_services
        try:
            out["services"] = validate_services(values["services"])
        except ServiceError as exc:
            raise SettingsError(str(exc)) from exc
    return out


def _validate_link(raw: dict) -> dict:
    link = {**DEFAULTS["link"], **raw}
    link["enabled"] = bool(link.get("enabled"))
    link["host"] = str(link.get("host", "")).strip()
    link["community"] = str(link.get("community", "")).strip()
    link["interface"] = str(link.get("interface", "")).strip()
    try:
        link["port"] = int(link.get("port") or 161)
        link["down_mbps"] = float(link.get("down_mbps") or 0)
        link["up_mbps"] = float(link.get("up_mbps") or 0)
    except (TypeError, ValueError) as exc:
        raise SettingsError("port and speeds must be numbers") from exc
    if not 0 < link["port"] < 65536 or link["down_mbps"] < 0 or link["up_mbps"] < 0:
        raise SettingsError("invalid port or speed")
    if link["enabled"]:
        try:
            ipaddress.ip_address(link["host"])
        except ValueError as exc:
            raise SettingsError("router address must be an IP") from exc
        if not link["community"] or len(link["community"]) > 64:
            raise SettingsError("a read-only community is required")
        if link["down_mbps"] <= 0 or link["up_mbps"] <= 0:
            raise SettingsError("set the contracted download and upload speeds (needed to tell if the link is full)")
    return link


# ------------------------------------------------------------------ load / save

def load(store: Store, toml_path: str | None = None, data_dir: Path | None = None,
         default_lang: str | None = None) -> Settings:
    raw = {k: store.get_setting(k, v) for k, v in DEFAULTS.items()}
    if store.get_setting("lang") is None and default_lang in ("en", "es"):
        raw["lang"] = default_lang  # never chosen in the UI: follow `--lang` / $LANG
    s = Settings(
        anchors=list(raw["anchors"]), interval=float(raw["interval"]), window=int(raw["window"]),
        lang=raw["lang"], auth_mode=raw["auth_mode"], proxy_header=raw["proxy_header"],
        trusted_proxies=list(raw["trusted_proxies"]),
        tunnels=[Tunnel(**t) for t in raw["tunnels"]], version=store.settings_version(),
        services=[Service(**sv) for sv in raw["services"]],
        devices=[Device(**dv) for dv in raw.get("devices") or []],
        link={**DEFAULTS["link"], **(raw.get("link") or {})},
        voip_target=str(raw.get("voip_target") or ""),
        speedtest={**SPEED_DEFAULTS, **(raw.get("speedtest") or {})},
    )
    if data_dir is not None or toml_path:
        cfg: Config = load_toml(toml_path, data_dir or Path("."))
        if cfg.path is not None:
            s.tunnels, s.tunnels_from_file = cfg.tunnels, cfg.path
    return s


def save(store: Store, values: dict) -> None:
    store.set_settings(validate(values))


# ------------------------------------------------------------------ secrets

def secret_key(store: Store) -> bytes:
    """Flask session signing key, generated once and kept in the database."""
    key = store.get_setting("_secret_key")
    if not key:
        key = secrets.token_hex(32)
        store.set_settings({"_secret_key": key}, bump=False)
    return bytes.fromhex(key)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_setup_token(store: Store) -> str:
    """One-time token printed in the logs; needed to create the first admin."""
    token = secrets.token_urlsafe(24)
    store.set_settings({"_setup_token": {"hash": _hash(token), "expires": time.time() + SETUP_TOKEN_TTL}}, bump=False)
    return token


def check_setup_token(store: Store, token: str) -> bool:
    data = store.get_setting("_setup_token")
    if not data or not token or time.time() > data.get("expires", 0):
        return False
    return hmac.compare_digest(data["hash"], _hash(token))


def consume_setup_token(store: Store) -> None:
    store.set_settings({"_setup_token": None}, bump=False)


def metrics_token(store: Store, rotate: bool = False) -> str:
    """Bearer token for Prometheus (`authorization: credentials` in scrape_configs)."""
    token = store.get_setting("_metrics_token")
    if not token or rotate:
        token = secrets.token_urlsafe(32)
        store.set_settings({"_metrics_token": token}, bump=False)
    return token
