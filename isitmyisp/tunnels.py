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
from itertools import pairwise

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


# ------------------------------------------------------------------ instability (#99)
#
# A tunnel can be "up" by the incident rules and still be useless: it drops for one window, comes back,
# drops again. Each drop alone is too short for an incident (two bad windows in a row), so nothing was
# left behind. Here every run of bad windows inside the tunnel is a drop, incident or not, and a run of
# drops close together is an unstable stretch. The cause uses the same reading as `classify_tunnel`.

DROP_GAP = 1.5          # bad windows closer than this many windows apart are one drop
CALM = 3600.0           # this long without a drop and the tunnel has calmed down
UNSTABLE_DROPS = 3      # this many drops, each less than CALM after the last, is an unstable stretch
PERIODIC_SPAN = 48 * 3600.0     # how far back periodic drops are looked for (8 h lifetimes need 3 of them)
PERIODIC_MIN = 600.0    # shorter than this is not a timer, it's just dropping
ROUTE_BEFORE = 1800.0   # a path change this long before the stretch started may have caused it
UNSTABLE_CAUSES = ("rekey", "config", "path_local", "path_remote", "unknown")


@dataclass
class Drop:
    start: float
    end: float
    windows: int
    outside: str        # bad | clean | silent (far end never answers ICMP) | none (no data)
    internet_ok: bool


@dataclass
class Instability:
    name: str
    drops: list[Drop]               # the last PERIODIC_SPAN, oldest first
    stretch: list[Drop]             # the drops of the current (or last) stretch
    unstable: bool                  # the stretch is still going and has enough drops
    since: float | None             # when the stretch started
    every: float | None             # the drops repeat at this interval (a timer)
    cause: str | None               # one of UNSTABLE_CAUSES
    micro: int                      # drops in the stretch too short to open an incident
    route_event: dict | None = None  # a path change of this tunnel just before the stretch (#97)
    calm: float = CALM              # this long without a drop and the stretch is over


def _window_len(rows: list[dict], default: float = 30.0) -> float:
    gaps = sorted(b["ts"] - a["ts"] for a, b in pairwise(rows) if b["ts"] > a["ts"])
    return gaps[len(gaps) // 2] if gaps else default


def find_drops(store, name: str, start: float, end: float) -> list[Drop]:
    """Every run of bad windows inside the tunnel between start and end, oldest first."""
    over = [r for r in store.samples_between(start, end, role=f"tunnel_over:{name}") if r["sent"]]
    if not over:
        return []
    under = {round(r["ts"]): r for r in store.samples_between(start, end, role=f"tunnel_under:{name}")}
    answered = any(r["received"] for r in under.values()) or any(
        r["received"] for r in store.samples_between(end - 30 * 86400, start, role=f"tunnel_under:{name}"))
    inet = {round(ts): code for ts, _, code in store.windows_between(start, end)}
    w = _window_len(over)
    drops: list[Drop] = []
    outs: list[list[str]] = []
    for r in over:
        if not loss_is_significant(r["sent"] - r["received"], r["sent"]):
            continue
        u = under.get(round(r["ts"]))
        if u is None or not u["sent"]:
            out = "none"
        elif u["received"] == 0 and not answered:
            out = "silent"
        else:
            out = "bad" if loss_is_significant(u["sent"] - u["received"], u["sent"]) else "clean"
        ok = inet.get(round(r["ts"]), "ok") in ("ok", "remote", "dns", "no_data", "speedtest")
        if drops and r["ts"] - drops[-1].end <= DROP_GAP * w:
            d = drops[-1]
            d.end, d.windows, d.internet_ok = r["ts"], d.windows + 1, d.internet_ok and ok
            outs[-1].append(out)
        else:
            drops.append(Drop(r["ts"] - w, r["ts"], 1, out, ok))
            outs.append([out])
    for d, o in zip(drops, outs):     # outside the tunnel during the drop: bad wins, then clean
        d.outside = next((x for x in ("bad", "clean", "silent") if x in o), "none")
    return drops


def _timer(drops: list[Drop], open_after: int) -> float | None:
    """The interval the drops repeat at, if any. Short drops scattered between the ones on a timer would
    hide it, so the drops long enough for an outage are also tried on their own."""
    for ds in (drops, [d for d in drops if d.windows >= open_after]):
        every = periodic_interval([d.start for d in ds])
        if every is not None and every >= PERIODIC_MIN:
            return every
    return None


def _cause(stretch: list[Drop], every: float | None) -> str:
    known = [d for d in stretch if d.outside in ("bad", "clean")]
    if not known:
        return "unknown"
    bad = [d for d in known if d.outside == "bad"]
    if 2 * len(bad) > len(known):
        return "path_remote" if sum(d.internet_ok for d in bad) * 2 > len(bad) else "path_local"
    return "rekey" if every else "config"


def instability(store, name: str, now: float, open_after: int = 2) -> Instability:
    """The tunnel's drops of the last two days, and whether they make an unstable stretch right now."""
    drops = find_drops(store, name, now - PERIODIC_SPAN, now)
    every = _timer(drops, open_after)
    calm = max(CALM, 1.5 * every) if every else CALM
    stretch: list[Drop] = []
    for d in reversed(drops):
        if stretch and stretch[0].start - d.end > calm:
            break
        stretch.insert(0, d)
    going = bool(stretch) and now - stretch[-1].end <= calm
    unstable = going and len(stretch) >= UNSTABLE_DROPS
    since = stretch[0].start if stretch else None
    if every is None and len(stretch) >= UNSTABLE_DROPS:     # a timer seen only within the stretch
        every = _timer(stretch, open_after)
    route_event = None
    if since is not None:
        for e in store.route_events_between(since - ROUTE_BEFORE, since + 300):
            if e["target"] == f"tunnel:{name}" and e["kind"] == "changed":
                route_event = e
    return Instability(name, drops, stretch, unstable, since, every,
                       _cause(stretch, every) if stretch else None,
                       sum(1 for d in stretch if d.windows < open_after), route_event, calm)


def hourly(drops: list[Drop], now: float, hours: int = 24) -> list[int]:
    """Drops per hour, the oldest hour first."""
    out = [0] * hours
    for d in drops:
        k = int((now - d.start) // 3600)
        if 0 <= k < hours:
            out[hours - 1 - k] += 1
    return out


def fmt_every(seconds: float) -> str:
    """3600 -> '1 h', 5400 -> '1.5 h', 1200 -> '20 min'."""
    if seconds >= 3600:
        h = round(seconds / 3600, 1)
        return f"{h:g} h"
    return f"{round(seconds / 60)} min"


def instability_details(ins: Instability, t: Tunnel) -> tuple[str, list[str], dict]:
    """Incident code, evidence lines (English, like every other incident) and details for an unstable stretch."""
    st = ins.stretch
    outside = {"bad": 0, "clean": 0, "silent": 0, "none": 0}
    for d in st:
        outside[d.outside] += 1
    evidence = [f"{len(st)} drops inside the tunnel since the stretch started"
                + (f", {ins.micro} too short to count as an outage" if ins.micro else "")]
    if ins.every:
        evidence.append(f"they repeat every {fmt_every(ins.every)} (within 10%)")
    if outside["clean"]:
        evidence.append(f"{t.underlay} (outside the tunnel): clean during {outside['clean']} of them")
    if outside["bad"]:
        evidence.append(f"{t.underlay} (outside the tunnel): losing too during {outside['bad']} of them")
    if outside["silent"]:
        evidence.append(f"{t.underlay} never answers ping outside the tunnel")
    if ins.route_event:
        evidence.append("the path to the far site changed just before it started")
    details = {"cause": ins.cause, "every": ins.every, "drops": len(st), "micro": ins.micro,
               "since": ins.since, "last": st[-1].end if st else None,
               "route_event": ins.route_event["id"] if ins.route_event else None}
    return f"unstable_{ins.cause}", evidence, details
