"""Turn measurements into a verdict: whose fault is it?

Segments, from closest to farthest:
  local   -> your device, Wi-Fi or LAN, up to and including any router at home
  access  -> your ISP's first hop (access network / BNG / CGNAT)
  isp     -> every destination affected while the first hop is fine: ISP backbone or upstream
  remote  -> only some destinations affected: not your ISP's fault
  dns     -> pings and TCP are fine but your DNS resolver fails or is slow

A target is "degraded" if its loss is statistically significant (Wilson, see stats.py)
or its latency is abnormal against its own learned baseline. For anchors, ICMP and TCP
must agree: ICMP loss with clean TCP handshakes is ICMP being deprioritized, not a problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .probes.icmp import WindowStats
from .stats import Baseline, loss_is_significant

WIFI_LATENCY_MS = 15.0
JITTER_BAD_MS = 20.0


@dataclass
class Measurements:
    home: list[WindowStats] = field(default_factory=list)  # gateway first, then other home routers
    isp_hop: WindowStats | None = None
    anchors: list[WindowStats] = field(default_factory=list)  # ICMP
    anchors_tcp: dict[str, WindowStats] = field(default_factory=dict)  # anchor ip -> TCP stats
    dns: list[WindowStats] = field(default_factory=list)
    wireless: bool = False


@dataclass
class Verdict:
    code: str  # ok | local | access | isp | remote | dns | no_data
    evidence: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


def _has_data(s: WindowStats | None) -> bool:
    return s is not None and s.sent > 0


def _why(s: WindowStats, baselines: dict[str, Baseline]) -> str | None:
    """Return a short reason if `s` is degraded, else None."""
    if not _has_data(s):
        return None
    if loss_is_significant(s.lost, s.sent):
        return f"{s.loss}% loss ({s.lost}/{s.sent})"
    b = baselines.get(s.target)
    if b and b.is_spike(s.rtt_median):
        return f"latency {s.rtt_median:.0f} ms vs usual {b.value:.0f} ms"
    return None


def classify(m: Measurements, baselines: dict[str, Baseline] | None = None) -> Verdict:
    baselines = baselines or {}
    anchors = [a for a in m.anchors if _has_data(a)]
    if not any(_has_data(h) for h in m.home) and not anchors:
        return Verdict("no_data")

    hints: list[str] = []

    # 1) Home: your device, Wi-Fi, LAN and any router you own.
    for h in m.home:
        why = _why(h, baselines)
        if why:
            v = Verdict("local", evidence=[f"home router {h.target}: {why}"])
            if m.wireless:
                v.hints.append("wifi")
            return v

    # 2) Anchors: ICMP and TCP must agree.
    bad: list[tuple[WindowStats, str]] = []
    for a in anchors:
        icmp_why = _why(a, baselines)
        tcp = m.anchors_tcp.get(a.target)
        tcp_why = _why(tcp, baselines) if _has_data(tcp) else None
        if icmp_why and _has_data(tcp) and not tcp_why:
            hints.append("icmp_only")  # ICMP looks bad, real traffic is fine
            continue
        if icmp_why or tcp_why:
            bad.append((a, icmp_why or f"TCP/443 {tcp_why}"))

    isp_why = _why(m.isp_hop, baselines) if m.isp_hop else None
    if anchors and len(bad) == len(anchors):
        ev = [f"{a.target}: {why}" for a, why in bad]
        if isp_why:
            v = Verdict("access", evidence=[f"ISP first hop {m.isp_hop.target}: {isp_why}", *ev])
        else:
            v = Verdict("isp", evidence=ev + ([f"ISP first hop {m.isp_hop.target}: OK"] if _has_data(m.isp_hop) else []))
    elif bad:
        bad_targets = {a.target for a, _ in bad}
        v = Verdict("remote", evidence=[f"{a.target}: {why}" for a, why in bad]
                    + [f"{a.target}: OK" for a in anchors if a.target not in bad_targets])
    else:
        dns_bad = [(d, _why(d, baselines)) for d in m.dns]
        dns_bad = [(d, w) for d, w in dns_bad if w]
        if dns_bad and len(dns_bad) == len([d for d in m.dns if _has_data(d)]):
            v = Verdict("dns", evidence=[f"{d.target}: {w}" for d, w in dns_bad])
        else:
            v = Verdict("ok")
            if dns_bad:
                hints.append("dns_partial")
        if isp_why:
            hints.append("isp_hop_icmp")  # first hop "loses" replies but everything behind it is fine

    # Quality hints that don't change the verdict.
    gw = m.home[0] if m.home else None
    if m.wireless and gw and gw.rtt_avg and gw.rtt_avg > WIFI_LATENCY_MS and "wifi" not in v.hints:
        hints.append("wifi_latency")
    jitters = [a.jitter for a in anchors if a.jitter is not None]
    if jitters and max(jitters) > JITTER_BAD_MS:
        hints.append("jitter")
    v.hints += [h for h in dict.fromkeys(hints) if h not in v.hints]
    return v
