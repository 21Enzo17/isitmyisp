"""Tunnel mode: did the tunnel drop because of its configuration or because of the path?

For each tunnel we measure at the same time:
  underlay -> the far end's public IP, outside the tunnel (is the path healthy?)
  overlay  -> an address reached through the tunnel (is the tunnel passing traffic?)

  overlay OK                                   -> up
  overlay bad, underlay bad, your internet bad -> path_local   (your connection / your ISP)
  overlay bad, underlay bad, your internet OK  -> path_remote  (the far site's connection or the path to it)
  overlay bad, underlay clean                  -> config       (DPD, lifetimes/rekey, NAT-T, MTU...)
  overlay bad, underlay never answers ICMP     -> unknown      (can't tell: peer filters ICMP)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .config import Tunnel
from .probes.icmp import WindowStats
from .stats import loss_is_significant

TUNNEL_CODES = ("up", "path_local", "path_remote", "config", "unknown", "no_data")
TUNNEL_PROBLEMS = ("path_local", "path_remote", "config", "unknown")


@dataclass
class TunnelVerdict:
    name: str
    code: str
    evidence: list[str] = field(default_factory=list)


def _bad(s: WindowStats | None) -> bool:
    return s is not None and loss_is_significant(s.lost, s.sent)


def _desc(s: WindowStats) -> str:
    return f"{s.loss}% loss ({s.lost}/{s.sent})"


def classify_tunnel(t: Tunnel, underlay: WindowStats | None, overlay: WindowStats | None,
                    internet_ok: bool, underlay_ever_answered: bool = True) -> TunnelVerdict:
    """`underlay_ever_answered`: whether the far end's public IP has EVER replied to ICMP.
    If it never has, silence outside the tunnel proves nothing (it probably filters ping)."""
    if overlay is None or overlay.sent == 0:
        return TunnelVerdict(t.name, "no_data")
    if not _bad(overlay):
        return TunnelVerdict(t.name, "up")
    ev = [f"through the tunnel ({t.overlay}): {_desc(overlay)}"]
    if underlay is None or underlay.sent == 0:
        return TunnelVerdict(t.name, "unknown", ev + ["outside the tunnel: no data"])
    if underlay.received == 0 and not underlay_ever_answered:
        return TunnelVerdict(t.name, "unknown", ev + [f"outside the tunnel ({t.underlay}): never answers ICMP"])
    ev.append(f"outside the tunnel ({t.underlay}): {_desc(underlay) if underlay.lost else 'OK'}")
    if _bad(underlay):
        return TunnelVerdict(t.name, "path_remote" if internet_ok else "path_local", ev)
    return TunnelVerdict(t.name, "config", ev)


def periodic_interval(starts: list[float], min_events: int = 3, max_cv: float = 0.1) -> float | None:
    """If drops repeat at a regular interval (coefficient of variation <= 10%), return it in seconds.

    Regular drops with a clean path are the fingerprint of mismatched IKE/IPsec lifetimes or rekey.
    """
    if len(starts) < min_events:
        return None
    starts = sorted(starts)
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    mean = statistics.fmean(gaps)
    if mean <= 0:
        return None
    cv = statistics.pstdev(gaps) / mean if len(gaps) > 1 else 0.0
    return mean if cv <= max_cv else None
