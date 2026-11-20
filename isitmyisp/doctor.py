"""`isitmyisp doctor`: a one-off health check of the network, run without installing the monitor.

Each check is green, yellow or red (``ok`` / ``warn`` / ``bad``, or ``skip`` when it can't be measured
from here), says its scope and comes with one sentence and what to do. Scope matters: some checks
are about the whole network (CGNAT, DNS, MTU, the router), others only about the machine running the
probe (its cable, its card, its Wi-Fi), and a red there says nothing about the rest of the house.

The checks are pure functions of :class:`Facts`; :func:`gather` measures them for real (about 15 s).
The grade (A–F) only summarises the list and is never shown without it.
"""

from __future__ import annotations

import re
import shutil
import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .discovery import Network
from .lan import LanStats

DNS_NAMES = ("www.google.com", "www.wikipedia.org", "www.cloudflare.com")
DNS_SLOW_MS = 150.0      # median answer time of your DNS servers
DNS_BAD_MS = 400.0
DNS_TRAP = "192.0.2.53"  # TEST-NET-1, routed nowhere: an answer from it means someone grabs port 53
MTU_TARGET = "1.1.1.1"
MTU_SMALL = 56
REBOOT_RECENT_S = 86400.0
SLOW_LINK_MBPS = 100     # a card at 100 Mb/s or less, with no plan to compare against
STATUSES = ("ok", "warn", "bad", "skip")
SCOPES = ("network", "probe")


@dataclass
class Mtu:
    iface: int | None = None      # MTU of the probe's card
    path: int | None = None       # largest packet that got through, or the MTU the network reported
    signalled: bool = False       # the network said "too big" (PMTUD works)
    blackhole: bool = False       # bigger packets vanish without a word
    no_icmp: bool = False         # not even a small ping got an answer: can't tell


@dataclass
class Facts:
    net: Network
    dns_ms: dict[str, list[float | None]] = field(default_factory=dict)
    dns_trapped: bool | None = None
    mtu: Mtu | None = None
    speed_mbps: int | None = None
    duplex: str | None = None
    errors_before: int | None = None
    errors_after: int | None = None
    plan_mbps: float = 0.0
    router_uptime_s: float | None = None
    lan: LanStats | None = None
    seconds: float = 0.0


@dataclass
class Check:
    id: str
    scope: str            # network | probe
    status: str           # ok | warn | bad | skip
    key: str              # text key in texts.DOCTOR: "<id>_<case>"
    params: dict = field(default_factory=dict)


def _fmt_ago(s: float) -> str:
    if s < 3600:
        return f"{max(1, round(s / 60))} min"
    if s < 2 * 86400:
        return f"{s / 3600:.0f} h"
    return f"{s / 86400:.0f} d"


# ------------------------------------------------------------------ the checks

def check_cgnat(f: Facts) -> Check:
    if not f.net.path:
        return Check("cgnat", "network", "skip", "cgnat_skip")
    if f.net.cgnat:
        hops = [h for h in f.net.nat_hops if h not in f.net.home_routers]
        return Check("cgnat", "network", "warn", "cgnat_yes", {"hops": ", ".join(hops)})
    return Check("cgnat", "network", "ok", "cgnat_no")


def check_double_nat(f: Facts) -> Check:
    if not f.net.path:
        return Check("double_nat", "network", "skip", "double_nat_skip")
    if f.net.double_nat:
        return Check("double_nat", "network", "warn", "double_nat_yes", {"hops": ", ".join(f.net.home_routers)})
    return Check("double_nat", "network", "ok", "double_nat_no")


def check_ipv6(f: Facts) -> Check:
    if not f.net.ipv6_global:
        return Check("ipv6", "network", "ok", "ipv6_none")
    if f.net.ipv6_works:
        return Check("ipv6", "network", "ok", "ipv6_ok")
    return Check("ipv6", "network", "bad", "ipv6_broken")


def check_dns(f: Facts) -> Check:
    if not f.dns_ms:
        return Check("dns", "network", "bad", "dns_none")
    answered = {s: [x for x in v if x is not None] for s, v in f.dns_ms.items()}
    dead = [s for s, v in answered.items() if not v]
    alive = {s: statistics.median(v) for s, v in answered.items() if v}
    if not alive:
        return Check("dns", "network", "bad", "dns_dead", {"servers": ", ".join(dead)})
    best = min(alive.values())
    shown = ", ".join(f"{s} {ms:.0f} ms" for s, ms in alive.items())
    if dead:
        return Check("dns", "network", "warn", "dns_some_dead", {"servers": ", ".join(dead), "ms": shown})
    if best >= DNS_BAD_MS:
        return Check("dns", "network", "bad", "dns_slow", {"ms": shown})
    if best >= DNS_SLOW_MS:
        return Check("dns", "network", "warn", "dns_slow", {"ms": shown})
    return Check("dns", "network", "ok", "dns_ok", {"ms": shown})


def check_dns_trap(f: Facts) -> Check:
    if f.dns_trapped is None:
        return Check("dns_trap", "network", "skip", "dns_trap_skip")
    if f.dns_trapped:
        return Check("dns_trap", "network", "warn", "dns_trap_yes", {"ip": DNS_TRAP})
    return Check("dns_trap", "network", "ok", "dns_trap_no")


def check_mtu(f: Facts) -> Check:
    m = f.mtu
    if m is None or m.no_icmp or m.path is None:
        return Check("mtu", "network", "skip", "mtu_skip")
    if m.blackhole:
        return Check("mtu", "network", "bad", "mtu_blackhole", {"mtu": m.path})
    if m.iface and m.path < m.iface:
        return Check("mtu", "network", "ok", "mtu_lower", {"mtu": m.path, "iface": m.iface})
    return Check("mtu", "network", "ok", "mtu_ok", {"mtu": m.path})


def check_router_uptime(f: Facts) -> Check:
    if f.router_uptime_s is None:
        return Check("router_uptime", "network", "skip", "router_uptime_skip")
    ago = _fmt_ago(f.router_uptime_s)
    if f.router_uptime_s < REBOOT_RECENT_S:
        return Check("router_uptime", "network", "warn", "router_uptime_recent", {"ago": ago})
    return Check("router_uptime", "network", "ok", "router_uptime_ok", {"ago": ago})


def check_loop(f: Facts) -> Check:
    if f.lan is None or (f.lan.replies == 0 and f.lan.mcast_pps is None and not f.lan.macs):
        return Check("loop", "network", "skip", "loop_skip")
    signals = f.lan.signals()
    if signals:
        return Check("loop", "network", "bad", "loop_yes", {"signals": "; ".join(signals)})
    return Check("loop", "network", "ok", "loop_no", {"s": round(f.seconds)})


def check_link_speed(f: Facts) -> Check:
    if f.net.wireless or not f.speed_mbps or f.speed_mbps <= 0:
        return Check("link_speed", "probe", "skip", "link_speed_skip")
    p = {"speed": f.speed_mbps, "plan": round(f.plan_mbps), "iface": f.net.interface or "?"}
    if f.duplex == "half":
        return Check("link_speed", "probe", "bad", "link_speed_half", p)
    if f.plan_mbps > 0 and f.speed_mbps < f.plan_mbps:
        return Check("link_speed", "probe", "bad", "link_speed_below_plan", p)
    if f.plan_mbps <= 0 and f.speed_mbps <= SLOW_LINK_MBPS:
        return Check("link_speed", "probe", "warn", "link_speed_slow", p)
    return Check("link_speed", "probe", "ok", "link_speed_ok", p)


def check_nic_errors(f: Facts) -> Check:
    if f.errors_before is None or f.errors_after is None:
        return Check("nic_errors", "probe", "skip", "nic_errors_skip")
    grew = f.errors_after - f.errors_before
    if grew > 0:
        return Check("nic_errors", "probe", "bad", "nic_errors_growing",
                     {"n": grew, "s": round(f.seconds), "iface": f.net.interface or "?"})
    return Check("nic_errors", "probe", "ok", "nic_errors_ok", {"total": f.errors_after})


def check_wifi(f: Facts) -> Check:
    if f.net.wireless:
        return Check("wifi", "probe", "warn", "wifi_yes", {"iface": f.net.interface or "?"})
    return Check("wifi", "probe", "ok", "wifi_no")


CHECKS: tuple[Callable[[Facts], Check], ...] = (
    check_cgnat, check_double_nat, check_ipv6, check_dns, check_dns_trap, check_mtu,
    check_router_uptime, check_loop, check_link_speed, check_nic_errors, check_wifi,
)


def run_checks(f: Facts) -> list[Check]:
    return [c(f) for c in CHECKS]


def grade(checks: list[Check]) -> str:
    """A–F from the reds (2 points) and yellows (1) of the whole-network checks; only ever shown next
    to the list. A check about the probe machine alone (its card, its Wi-Fi) says nothing about the
    rest of the network, so it is listed but doesn't lower the grade."""
    pts = sum({"bad": 2, "warn": 1}.get(c.status, 0) for c in checks if c.scope == "network")
    return "A" if pts == 0 else "B" if pts == 1 else "C" if pts <= 3 else "D" if pts <= 5 else "F"


def to_dict(checks: list[Check], ts: float | None = None) -> dict:
    return {"ts": ts or time.time(), "grade": grade(checks), "checks": [asdict(c) for c in checks]}


def from_dict(d: dict) -> list[Check]:
    return [Check(**c) for c in d.get("checks", [])]


# ------------------------------------------------------------------ measuring for real

_MTU_HINT = re.compile(r"mtu\s*=\s*(\d+)")


def ping_df(size: int, target: str = MTU_TARGET) -> tuple[bool, int | None]:
    """One ping with Don't Fragment set: (answered, MTU the network or the kernel reported)."""
    try:
        r = subprocess.run(["ping", "-n", "-M", "do", "-s", str(size), "-c", "2", "-W", "2", target],
                           capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    out = r.stdout + r.stderr
    hint = _MTU_HINT.search(out)
    return r.returncode == 0, int(hint.group(1)) if hint else None


def probe_mtu(iface_mtu: int | None, ping: Callable[[int], tuple[bool, int | None]] = ping_df) -> Mtu:
    """Full-size packets with DF set; if they vanish silently, find the largest that gets through."""
    m = Mtu(iface=iface_mtu)
    top = (iface_mtu or 1500) - 28
    ok, hint = ping(top)
    if ok:
        m.path = top + 28
        return m
    if hint:                                   # "Frag needed (mtu = 1492)": path MTU discovery works
        m.path, m.signalled = hint, True
        return m
    if not ping(MTU_SMALL)[0]:
        m.no_icmp = True
        return m
    lo, hi = MTU_SMALL, top                    # lo answers, hi doesn't
    while hi - lo > 8:
        mid = (lo + hi) // 2
        if ping(mid)[0]:
            lo = mid
        else:
            hi = mid
    m.path, m.blackhole = lo + 28, True
    return m


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def nic_errors(iface: str | None, sys_root: str = "/sys/class/net") -> int | None:
    if not iface:
        return None
    vals = [_read_int(Path(sys_root, iface, "statistics", n)) for n in ("rx_errors", "tx_errors")]
    return None if all(v is None for v in vals) else sum(v or 0 for v in vals)


def nic_link(iface: str | None, sys_root: str = "/sys/class/net") -> tuple[int | None, int | None, str | None]:
    """(speed Mb/s, MTU, duplex) of the card; speed is None on Wi-Fi or when the driver won't say."""
    if not iface:
        return None, None, None
    base = Path(sys_root, iface)
    speed = _read_int(base / "speed")
    try:
        duplex = (base / "duplex").read_text().strip() or None
    except OSError:
        duplex = None
    return (speed if speed and speed > 0 else None), _read_int(base / "mtu"), duplex


def router_uptime(link: dict) -> float | None:
    """sysUpTime over SNMP when the router is connected in Settings (seconds)."""
    if not link.get("enabled") or not link.get("host"):
        return None
    from .snmp import OID_SYS_UPTIME, SnmpClient, SnmpError
    try:
        v = SnmpClient(link["host"], link["community"], int(link.get("port") or 161)).get([OID_SYS_UPTIME])
    except SnmpError:
        return None
    ticks = v.get(OID_SYS_UPTIME)
    return ticks / 100 if isinstance(ticks, int) else None


def gather(net: Network, link: dict | None = None, seconds: float = 15.0,
           progress: Callable[[str], None] | None = None) -> Facts:
    """Measure everything for about ``seconds``: the LAN watch runs while DNS and MTU are tested."""
    from .lan import LanWatch
    from .probes.sockets import dns_query_ms
    link = link or {}
    say = progress or (lambda _s: None)
    speed, mtu, duplex = nic_link(net.interface)
    f = Facts(net=net, speed_mbps=speed, duplex=duplex, plan_mbps=float(link.get("down_mbps") or 0),
              errors_before=nic_errors(net.interface))
    start = time.monotonic()
    with LanWatch(net.gateway, net.interface, sample_s=1.0) as lw:
        say("dns")
        f.dns_ms = {s: [dns_query_ms(s, n, timeout=2.0) for n in DNS_NAMES] for s in net.dns_servers}
        f.dns_trapped = dns_query_ms(DNS_TRAP, DNS_NAMES[0], timeout=1.5) is not None
        say("mtu")
        f.mtu = probe_mtu(mtu) if shutil.which("ping") else None
        say("router")
        f.router_uptime_s = router_uptime(link)
        say("lan")
        while (left := seconds - (time.monotonic() - start)) > 0:
            time.sleep(min(1.0, left))
        f.lan = lw.window()
    f.seconds = time.monotonic() - start
    f.errors_after = nic_errors(net.interface)
    return f
