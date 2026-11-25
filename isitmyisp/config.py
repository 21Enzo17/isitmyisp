"""Optional configuration file (TOML, parsed with the standard library).

Looked up in this order: --config, $ISITMYISP_CONFIG, <data dir>/config.toml,
~/.config/isitmyisp/config.toml. Everything works without one.

    [[tunnel]]
    name = "branch-office"
    underlay = "203.0.113.10"   # the far end's PUBLIC address (outside the tunnel)
    overlay = "10.10.0.1"       # an address on the far side reached THROUGH the tunnel
    type = "ipsec-l2tp"         # ipsec-l2tp | ipsec | wireguard | openvpn | other

    [speedtest]                 # your own speed test engine, run next to the built-in ones (#115)
    command = ["speedtest", "-f", "json", "--accept-license", "--accept-gdpr"]
    name = "Ookla"              # optional: how results are labelled
    format = "auto"             # auto | ookla | speedtest-cli | librespeed | iperf3 | json
    timeout = 120               # seconds

The command can also come from $ISITMYISP_SPEEDTEST_COMMAND (split like a shell would, but never run
by one). It is set here and only here, never from the web UI: a command an admin page could change
would be remote code execution for anyone who gets that page, or a forged form post.
"""

from __future__ import annotations

import ipaddress
import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    tomllib = None

TUNNEL_TYPES = {"ipsec-l2tp", "ipsec", "wireguard", "openvpn", "other"}
COMMAND_FORMATS = ("auto", "ookla", "speedtest-cli", "librespeed", "iperf3", "json")
COMMAND_ENV = "ISITMYISP_SPEEDTEST_COMMAND"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Tunnel:
    name: str
    underlay: str
    overlay: str
    type: str = "other"


@dataclass(frozen=True)
class SpeedCommand:
    """An external speed test the user installs and runs: argv, never a shell line."""
    argv: tuple[str, ...]
    name: str = ""
    format: str = "auto"
    timeout: int = 120

    def text(self) -> str:
        return shlex.join(self.argv)


@dataclass
class Config:
    tunnels: list[Tunnel] = field(default_factory=list)
    path: Path | None = None
    speed_command: SpeedCommand | None = None


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
    return Config(tunnels=tunnels, path=path, speed_command=speed_command(data.get("speedtest") or {}))


def speed_command(raw: dict) -> SpeedCommand | None:
    """The [speedtest] section: None when it has no command."""
    if not isinstance(raw, dict):
        raise ConfigError("[speedtest] must be a table")
    cmd = raw.get("command")
    if cmd in (None, "", []):
        return None
    if isinstance(cmd, str):
        try:
            argv = shlex.split(cmd)
        except ValueError as exc:
            raise ConfigError(f"[speedtest] command: {exc}") from exc
    elif isinstance(cmd, list) and all(isinstance(a, str) for a in cmd):
        argv = list(cmd)
    else:
        raise ConfigError("[speedtest] command must be a list of strings, or one string")
    if not argv or not argv[0]:
        raise ConfigError("[speedtest] command is empty")
    fmt = str(raw.get("format", "auto")).lower()
    if fmt not in COMMAND_FORMATS:
        raise ConfigError(f"[speedtest] format must be one of {list(COMMAND_FORMATS)}")
    try:
        timeout = int(raw.get("timeout", 120))
    except (TypeError, ValueError) as exc:
        raise ConfigError("[speedtest] timeout must be a number of seconds") from exc
    if not 5 <= timeout <= 600:
        raise ConfigError("[speedtest] timeout must be between 5 and 600 seconds")
    return SpeedCommand(tuple(argv), str(raw.get("name") or "")[:40], fmt, timeout)


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
    cfg = Config()
    for p in candidates(explicit, data_dir):
        if p.is_file():
            if tomllib is None:
                raise ConfigError("config files need Python 3.11+")
            with open(p, "rb") as fh:
                cfg = parse(tomllib.load(fh), p)
            break
        if explicit and p == Path(explicit):
            raise ConfigError(f"config file not found: {p}")
    env = os.environ.get(COMMAND_ENV, "").strip()
    if env:   # the environment wins over the file, as in most containers
        base = cfg.speed_command
        cfg.speed_command = speed_command({"command": env, "name": base.name if base else "",
                                           "format": base.format if base else "auto",
                                           "timeout": base.timeout if base else 120})
    return cfg
