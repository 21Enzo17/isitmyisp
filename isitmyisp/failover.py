"""Failover detection: is the office still going out through its main ISP?

Why a separate check: with a dual-WAN router (MikroTik, Fortinet, pfSense...) the probe's own
gateway never changes when the router fails over, so nothing on this machine notices. Until the
next scheduled re-discovery the monitor would keep measuring the old ISP's first hop through the
new link, and could even blame the wrong network.

How: once per window, one ping with a limited TTL asks "who is the first hop of my ISP now?"
(the router at that distance answers with ICMP Time Exceeded). One packet, no extra tools.
A different answer twice in a row triggers an immediate re-discovery, and the new path is then
compared with the main ISP:

  failover  the traffic leaves through another provider
  failback  back on the main provider
  (same provider, different router: an internal reroute, nothing to report)

A provider is identified by its ASN when the offline ASN dataset is available, and by the /16
of its first public hop otherwise (good enough to tell two ISPs apart, and said so in the evidence).
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from .netutil import ip_kind
from .probes.icmp import C_ENV

_TTL_REPLY = re.compile(r"^From (\S+?):?\s.*(?:Time to live exceeded|Time exceeded)", re.I | re.M)
_ECHO_REPLY = re.compile(r"^\d+ bytes from (\S+?):", re.M)
REACHED = "reached"  # the destination itself answered: the path is now shorter than the old one

Prober = Callable[[str, int], "str | None"]


def parse_ttl_reply(text: str) -> str | None:
    """Address that answered a TTL-limited ping, REACHED if the target answered, None if silent."""
    m = _TTL_REPLY.search(text)
    if m:
        return m.group(1)
    if _ECHO_REPLY.search(text):
        return REACHED
    return None


def ttl_probe(target: str, ttl: int, timeout: float = 1.0) -> str | None:
    cmd = ["ping", "-n", "-c", "1", "-W", str(max(1, round(timeout))), "-t", str(ttl), target]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3, env=C_ENV).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_ttl_reply(out)


class PathWatch:
    """Watches the router at the ISP's distance. `check()` is True once a change is confirmed."""

    def __init__(self, expected: str, ttl: int, targets: list[str], known: set[str] | None = None,
                 confirm: int = 2, probe: Prober = ttl_probe):
        self.expected, self.ttl, self.targets = expected, ttl, targets[:2]
        self.known = {expected} | (known or set())   # routers already seen for this provider (ECMP)
        self.confirm, self.probe = confirm, probe
        self.strikes = 0
        self.last: str | None = None

    def check(self) -> bool:
        got = None
        for target in self.targets:
            got = self.probe(target, self.ttl)
            if got:
                break
        self.last = got
        if got is None:          # nobody answered: unknown, neither confirms nor clears
            return False
        if got in self.known:
            self.strikes = 0
            return False
        self.strikes += 1
        return self.strikes >= self.confirm


# ------------------------------------------------------------------ providers

@dataclass
class Provider:
    asn: str | None
    net16: str | None     # /16 of the first public hop of the ISP segment
    name: str             # what people read: AS name, or the hop's network
    hop: str | None       # first public hop of the ISP segment

    def to_dict(self) -> dict:
        return {"asn": self.asn, "net16": self.net16, "name": self.name, "hop": self.hop}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Provider | None":
        if not d or not (d.get("asn") or d.get("net16")):
            return None
        return cls(d.get("asn"), d.get("net16"), d.get("name") or "", d.get("hop"))

    def same_as(self, other: "Provider") -> bool:
        if self.asn and other.asn:
            return self.asn == other.asn
        return bool(self.net16) and self.net16 == other.net16


def _net16(ip: str | None) -> str | None:
    if not ip or ip_kind(ip) != "public":
        return None
    try:
        return str(ipaddress.ip_network(f"{ip}/16", strict=False))
    except ValueError:
        return None


def provider_of(snapshot: dict) -> Provider | None:
    """The provider the traffic leaves through, from a discovery snapshot (network_to_dict)."""
    path = snapshot.get("path") or []
    isp = [p for p in path if p.get("segment") == "isp" and p.get("host") not in (None, "???")]
    public = next((p for p in isp if ip_kind(p["host"]) == "public"), None)
    hop = public["host"] if public else (snapshot.get("isp_hop") if ip_kind(snapshot.get("isp_hop") or "") == "public" else None)
    asn = snapshot.get("isp_asn") or (public or {}).get("asn")
    net16 = _net16(hop)
    if not asn and not net16:
        return None
    name = snapshot.get("isp_name") or (public or {}).get("as_name") or ""
    if not name:
        name = asn or net16 or ""
    return Provider(asn, net16, name, hop)


def isp_ttl(snapshot: dict) -> int | None:
    """Distance (hops) of the ISP's first responding router: where the watch pings."""
    hop = snapshot.get("isp_hop")
    for p in snapshot.get("path") or []:
        if p.get("host") == hop:
            return int(p["index"])
    return None


@dataclass
class Change:
    kind: str                 # failover | failback | none | learn
    current: Provider | None
    primary: Provider | None
    evidence: list[str] = field(default_factory=list)


def compare(snapshot: dict, primary: Provider | None) -> Change:
    cur = provider_of(snapshot)
    if cur is None:
        return Change("none", None, primary)
    if primary is None:
        return Change("learn", cur, None)
    if cur.same_as(primary):
        return Change("failback", cur, primary)   # the caller only acts on it if a failover is open
    how = "ASN" if cur.asn and primary.asn else "/16"
    ev = [f"provider: {primary.name} -> {cur.name}",
          f"ISP first hop: {primary.hop or '?'} -> {cur.hop or '?'}"]
    if how == "/16":
        ev.append("no ASN dataset: providers compared by network (/16)")
    return Change("failover", cur, primary, ev)
