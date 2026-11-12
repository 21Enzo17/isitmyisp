"""Devices on your own network: "did the card terminal drop, or the internet?"

The card terminal, the fiscal printer, the camera recorder, the phone system, an access point: they
fail too, and when they do the owner blames the internet. Each device is checked every 30 seconds by
ping, or by connecting to one TCP port when it doesn't answer ping (printers on 9100, cameras on 554,
phone systems on 5060…). Like your services, the rule is consecutive results:
  down -> the last 3 checks failed AND your own network is fine at the same time (the router answers)
  up   -> the last 2 checks succeeded
Only here are private addresses allowed: these targets are meant to be on your LAN.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

from .services import Check, check_tcp, _HOST

KINDS = ("pos", "printer", "camera", "pbx", "ap", "other")
MAX_DEVICES = 30
PING_TIMEOUT = 2
LOCAL_SUFFIX = re.compile(r"\.(local|lan|home|internal|home\.arpa)$", re.I)


class DeviceError(ValueError):
    pass


@dataclass(frozen=True)
class Device:
    name: str
    kind: str              # pos | printer | camera | pbx | ap | other
    target: str            # an address or a local name on your network
    port: int | None = None  # TCP port to connect to; None means ping

    @property
    def how(self) -> str:
        return f"TCP {self.port}" if self.port else "ping"

    @property
    def endpoint(self) -> str:
        return f"{self.target}:{self.port}" if self.port else self.target


def _local(target: str) -> bool:
    """A private, link-local or loopback address, or a plain host name (resolved on your network)."""
    try:
        ip = ipaddress.ip_address(target.strip("[]"))
    except ValueError:
        # a name only your network resolves: no domain, or a local suffix
        return bool(_HOST.match(target)) and ("." not in target or bool(LOCAL_SUFFIX.search(target)))
    return ip.is_private or ip.is_link_local or ip.is_loopback


def validate(items: list[dict]) -> list[dict]:
    out, names = [], set()
    for raw in items:
        name = str(raw.get("name", "")).strip()
        kind = str(raw.get("kind", "other")).strip()
        target = str(raw.get("target", "")).strip()
        port_raw = str(raw.get("port") or "").strip()
        if not name or len(name) > 40:
            raise DeviceError("device name is required (max 40 characters)")
        if name in names:
            raise DeviceError(f"duplicate device name {name!r}")
        names.add(name)
        if kind not in KINDS:
            raise DeviceError(f"kind must be one of {', '.join(KINDS)}")
        if not target or not _local(target):
            raise DeviceError(f"{name}: use the device's address on your network (e.g. 192.168.1.50) "
                              "or its local name; internet addresses go in Your services")
        port = None
        if port_raw:
            if not port_raw.isdigit() or not 0 < int(port_raw) < 65536:
                raise DeviceError(f"{name}: the port must be a number between 1 and 65535")
            port = int(port_raw)
        out.append({"name": name, "kind": kind, "target": target, "port": port})
    if len(out) > MAX_DEVICES:
        raise DeviceError(f"at most {MAX_DEVICES} devices")
    return out


def check_ping(host: str, timeout: int = PING_TIMEOUT) -> Check:
    """One echo request, with the system's ping (fping when that's all there is)."""
    env = {**os.environ, "LC_ALL": "C"}
    if shutil.which("ping"):
        cmd = ["ping", "-n", "-c", "1", "-W", str(timeout), host]
    elif shutil.which("fping"):
        cmd = ["fping", "-c", "1", "-t", str(timeout * 1000), host]
    else:
        return Check(time.time(), False, None, "no ping tool")
    start = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return Check(time.time(), False, None, "timeout")
    out = r.stdout + r.stderr
    m = re.search(r"time[=<]\s*([\d.]+)\s*ms", out) or re.search(r"\[0\], [^,]+, ([\d.]+) ms", out)
    if r.returncode == 0:
        ms = float(m.group(1)) if m else round((time.perf_counter() - start) * 1000, 1)
        return Check(time.time(), True, ms, "ping OK")
    if "unknown host" in out.lower() or "not known" in out.lower() or "address not found" in out.lower():
        return Check(time.time(), False, None, "name not found")
    return Check(time.time(), False, None, "no reply to ping")


def check(dev: Device) -> Check:
    return check_tcp(dev.endpoint, timeout=4.0) if dev.port else check_ping(dev.target)
