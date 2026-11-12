"""Figure out what to measure and where each segment of the path begins.

Segments are defined by address type and ASN, not by hop position:
  home   -> every private hop at the start of the path (your router, plus a second router
            if you have double NAT, e.g. your own router behind the ISP's)
  isp    -> CGNAT hops (100.64.0.0/10) and public hops in the same AS as the first public hop
  beyond -> everything after the ISP's AS
Without ASN data we stay conservative: the ISP segment is CGNAT hops plus the first public hop.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import asn
from .netutil import ip_kind
from .probes.icmp import C_ENV
from .probes.mtr import Hop, MtrError, run_mtr

ANCHORS_V4 = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
ANCHOR_V6 = "2606:4700:4700::1111"


@dataclass
class PathHop:
    hop: Hop
    segment: str  # home | isp | beyond
    asn: str | None = None
    as_name: str | None = None


@dataclass
class Network:
    gateway: str | None = None
    interface: str | None = None
    wireless: bool = False
    dns_servers: list[str] = field(default_factory=list)
    dns_detected: list[str] = field(default_factory=list)  # what discovery found, before Settings → DNS servers
    public_ipv4: str | None = None  # only filled if the user opts in (--public-ip)
    home_routers: list[str] = field(default_factory=list)
    isp_hop: str | None = None  # first responding hop of the ISP segment
    isp_asn: str | None = None
    isp_name: str | None = None
    cgnat: bool = False
    double_nat: bool = False
    nat_hops: list[str] = field(default_factory=list)
    ipv6_global: bool = False
    ipv6_works: bool = False
    asn_source: str = "none"  # offline | online | none
    path: list[PathHop] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _run(cmd: list[str], timeout: float = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False, env=C_ENV).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def default_route() -> tuple[str | None, str | None]:
    raw = _run(["ip", "-j", "route", "show", "default"])
    try:
        routes = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        routes = []
    routes.sort(key=lambda r: r.get("metric", 0))
    for r in routes:
        if r.get("gateway"):
            return r["gateway"], r.get("dev")
    return None, None


def is_wireless(dev: str | None) -> bool:
    return bool(dev) and os.path.exists(f"/sys/class/net/{dev}/wireless")


def _nameservers(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return [l.split()[1] for l in fh if l.startswith("nameserver") and len(l.split()) > 1]
    except OSError:
        return []


# Local forwarders that stand in front of the real resolver, for this machine only: measuring them says
# nothing about your network's DNS. systemd-resolved's stub, and Tailscale's MagicDNS (it rewrites
# /etc/resolv.conf). Any other loopback address is a resolver running here (AdGuard Home, Pi-hole,
# dnsmasq, unbound), which is measured like any other, if it answers.
STUB_RESOLVERS = ("127.0.0.53", "127.0.0.54", "100.100.100.100")


def _is_stub(server: str) -> bool:
    return server in STUB_RESOLVERS


def _answers_dns(server: str) -> bool:
    from .probes.sockets import dns_query_ms
    return any(dns_query_ms(server, name, timeout=2.0) is not None for name in ("www.google.com", "www.cloudflare.com"))


def dns_servers(dev: str | None, gateway: str | None = None) -> list[str]:
    """Upstream DNS servers this machine really uses.

    With systemd-resolved, /etc/resolv.conf only shows the 127.0.0.53 stub, and with Tailscale's
    MagicDNS only 100.100.100.100. The real servers come from `resolvectl`, or
    /run/systemd/resolve/resolv.conf (mount it read-only in Docker). As a last resort the router,
    which is the resolver on most home networks, but only if it answers DNS: plenty of business
    routers and firewalls don't, and measuring one would blame "your DNS" forever. A resolver on this
    machine (127.0.0.1) is kept only if it answers, for the same reason. Settings → DNS servers
    overrides all of it.
    """
    servers = [s for s in _nameservers("/etc/resolv.conf") if ":" not in s]
    if not servers or all(_is_stub(s) for s in servers):
        out = _run(["resolvectl", "dns", dev] if dev else ["resolvectl", "dns"])
        found = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", out.split(":", 1)[-1])
        servers = ([s for s in found if not _is_stub(s)]
                   or [s for s in _nameservers("/run/systemd/resolve/resolv.conf") if ":" not in s and not _is_stub(s)])
    servers = [s for s in dict.fromkeys(servers) if s and not _is_stub(s)]
    servers = [s for s in servers if not s.startswith("127.") or _answers_dns(s)]
    if not servers and gateway and _answers_dns(gateway):
        servers = [gateway]
    return servers


def public_ipv4(timeout: float = 5) -> str | None:
    """Opt-in only: asks a third-party service (ipify) for our public IP."""
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "isitmyisp"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ip = resp.read().decode().strip()
            return ip if ip_kind(ip) == "public" else None
    except OSError:
        return None


def ipv6_status() -> tuple[bool, bool]:
    raw = _run(["ip", "-j", "-6", "addr", "show", "scope", "global"])
    try:
        addrs = [ai.get("local", "") for iface in json.loads(raw or "[]") for ai in iface.get("addr_info", [])]
    except json.JSONDecodeError:
        addrs = []
    # Linux labels ULAs (fd00::/8, e.g. Tailscale's fd7a:115c:a1e0::/48) as "scope global":
    # only real public IPv6 counts.
    has_global = any(ip_kind(a) == "public" for a in addrs)
    works = has_global and " 0% packet loss" in _run(["ping", "-6", "-n", "-c", "2", "-W", "2", ANCHOR_V6])
    return has_global, works


# A second private router at home adds well under this much latency over the first one;
# a private hop farther away is the ISP using private addressing in its access network.
HOME_HOP_MAX_EXTRA_MS = 2.0


def segment_path(hops: list[Hop], asn_info: dict[str, tuple[str, str]]) -> list[PathHop]:
    """Assign each hop to home / isp / beyond. Pure function: easy to test."""
    out: list[PathHop] = []
    stage = "home"
    isp_asn: str | None = None
    first_public_seen = False
    last_home_rtt: float | None = None
    for h in hops:
        if not h.responds:
            out.append(PathHop(h, segment=stage))  # silent hop: resolved below
            continue
        kind = h.kind
        info = asn_info.get(h.host)
        near = last_home_rtt is None or h.best - last_home_rtt <= HOME_HOP_MAX_EXTRA_MS
        if stage == "home" and kind == "private" and near:
            seg = "home"
            last_home_rtt = h.best
        elif stage == "home" and kind == "private":
            seg = stage = "isp"
        elif kind == "cgnat" and stage in ("home", "isp"):
            seg = stage = "isp"
        elif kind == "public" and not first_public_seen:
            first_public_seen = True
            isp_asn = info[0] if info else None
            seg = stage = "isp"
        elif stage == "isp" and kind == "public" and isp_asn and info and info[0] == isp_asn:
            seg = "isp"
        elif stage == "isp" and kind == "private":
            seg = "isp"  # private addressing inside the ISP's core (common in LATAM)
        else:
            seg = stage = "beyond"
        out.append(PathHop(h, seg, *(info or (None, None))))
    # A silent hop belongs to the segment of the next hop that answers (a silent first ISP
    # device right after the gateway is common). At the end of the path, keep the last stage.
    for i, ph in enumerate(out):
        if not ph.hop.responds:
            ph.segment = next((p.segment for p in out[i + 1:] if p.hop.responds), ph.segment)
    return out


def discover(trace_target: str = ANCHORS_V4[0], cycles: int = 5, data_dir: Path | None = None,
             asn_online: bool = False, want_public_ip: bool = False) -> Network:
    net = Network()
    net.gateway, net.interface = default_route()
    net.wireless = is_wireless(net.interface)
    net.dns_servers = dns_servers(net.interface, net.gateway)
    net.ipv6_global, net.ipv6_works = ipv6_status()
    if want_public_ip:
        net.public_ipv4 = public_ipv4()

    try:
        hops = run_mtr(trace_target, cycles=cycles)
    except MtrError as exc:
        net.notes.append(f"mtr: {exc}")
        return net

    info = asn.lookup([h.host for h in hops], data_dir=data_dir, online=asn_online)
    if data_dir is not None and asn.db_path(data_dir).exists():
        net.asn_source = "offline"
    elif asn_online:
        net.asn_source = "online"
    net.path = segment_path(hops, info)

    net.home_routers = [p.hop.host for p in net.path if p.segment == "home" and p.hop.responds]
    if net.gateway and net.gateway not in net.home_routers:
        net.home_routers.insert(0, net.gateway)
    extra = [r for r in net.home_routers if r != net.gateway]
    if extra:
        net.double_nat = True
        net.nat_hops += extra
    for p in net.path:
        if p.segment == "isp" and p.hop.kind == "cgnat":
            net.cgnat = True
            net.nat_hops.append(p.hop.host)
    isp = [p for p in net.path if p.segment == "isp" and p.hop.responds]
    if isp:
        net.isp_hop = isp[0].hop.host
        named = next((p for p in isp if p.asn), None)
        if named:
            net.isp_asn, net.isp_name = named.asn, named.as_name
    return net


def network_to_dict(net: Network) -> dict:
    """JSON-friendly snapshot of the network context, stored with the measurements."""
    return {
        "gateway": net.gateway, "interface": net.interface, "wireless": net.wireless,
        "dns_servers": net.dns_servers, "home_routers": net.home_routers, "isp_hop": net.isp_hop,
        "isp_asn": net.isp_asn, "isp_name": net.isp_name, "cgnat": net.cgnat, "double_nat": net.double_nat,
        "ipv6_global": net.ipv6_global, "ipv6_works": net.ipv6_works,
        "path": [{"index": p.hop.index, "host": p.hop.host, "segment": p.segment, "asn": p.asn,
                  "as_name": p.as_name} for p in net.path],
    }
