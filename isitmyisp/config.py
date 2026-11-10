"""Optional configuration file (TOML, parsed with the standard library).

Looked up in this order: --config, $ISITMYISP_CONFIG, <data dir>/config.toml,
~/.config/isitmyisp/config.toml. Everything works without one.

    [[tunnel]]
    name = "branch-office"
    underlay = "203.0.113.10"   # the far end's PUBLIC address (outside the tunnel)
    overlay = "10.10.0.1"       # an address on the far side reached THROUGH the tunnel
    type = "ipsec-l2tp"         # ipsec-l2tp | ipsec | wireguard | openvpn | other
"""

from __future__ import annotations

import ipaddress
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    tomllib = None

TUNNEL_TYPES = {"ipsec-l2tp", "ipsec", "wireguard", "openvpn", "other"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Tunnel:
    name: str
    underlay: str
    overlay: str
    type: str = "other"


@dataclass
class Config:
    tunnels: list[Tunnel] = field(default_factory=list)
    path: Path | None = None


def _ip(value: object, what: str, name: str) -> str:
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError as exc:
        raise ConfigError(f"tunnel {name!r}: {what} must be an IP address, got {value!r}") from exc


def parse(data: dict, path: Path | None = None) -> Config:
    tunnels: list[Tunnel] = []
    names: set[str] = set()
    for i, raw in enumerate(data.get("tunnel", [])):
        name = str(raw.get("name") or f"tunnel-{i + 1}")
        if name in names:
            raise ConfigError(f"duplicate tunnel name {name!r}")
        names.add(name)
        if "underlay" not in raw or "overlay" not in raw:
            raise ConfigError(f"tunnel {name!r}: both 'underlay' and 'overlay' are required")
        ttype = str(raw.get("type", "other")).lower()
        if ttype not in TUNNEL_TYPES:
            raise ConfigError(f"tunnel {name!r}: type must be one of {sorted(TUNNEL_TYPES)}")
        tunnels.append(Tunnel(name, _ip(raw["underlay"], "underlay", name), _ip(raw["overlay"], "overlay", name), ttype))
    return Config(tunnels=tunnels, path=path)


def candidates(explicit: str | None, data_dir: Path) -> list[Path]:
    out = []
    if explicit:
        out.append(Path(explicit))
    if os.environ.get("ISITMYISP_CONFIG"):
        out.append(Path(os.environ["ISITMYISP_CONFIG"]))
    out.append(data_dir / "config.toml")
    out.append(Path(os.path.expanduser("~/.config/isitmyisp/config.toml")))
    return out


def load(explicit: str | None, data_dir: Path) -> Config:
    for p in candidates(explicit, data_dir):
        if p.is_file():
            if tomllib is None:
                raise ConfigError("config files need Python 3.11+")
            with open(p, "rb") as fh:
                return parse(tomllib.load(fh), p)
        if explicit and p == Path(explicit):
            raise ConfigError(f"config file not found: {p}")
    return Config()
