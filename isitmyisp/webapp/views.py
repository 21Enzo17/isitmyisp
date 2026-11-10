"""Data shaping for the web pages (no Flask here: easy to test)."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from ..report import _anchor_series, fmt_duration
from ..settings import Settings
from ..store import Store
from ..api import is_stale
from . import charts

ROLE_ORDER = {"home": 0, "isp": 1, "anchor": 2, "tcp": 3, "dns": 4}
CAUSE_CLASS = {"ok": "ok", "local": "warn", "access": "bad", "isp": "bad", "remote": "info", "dns": "info",
               "no_data": "muted", "stale": "muted", "config": "warn", "path_local": "bad",
               "path_remote": "info", "unknown": "muted", "saturation": "warn"}


@dataclass
class TargetCard:
    role: str
    target: str
    loss: float
    median: float | None
    status: str  # ok | warn | bad
    history: object = None       # charts.Plot: latency over the last 6 hours
    worst: float | None = None   # worst loss in those 6 hours (%)


@dataclass
class Hop:
    """One node of the path shown in the hero: your network -> your ISP -> the internet."""
    key: str             # home | isp | internet
    name: str            # IP, ISP name...
    detail: str          # second line
    median: float | None
    loss: float | None
    state: str           # good | warn | bad | none
    blamed: bool = False  # the current verdict points here


BLAME = {"local": "home", "saturation": "home", "access": "isp", "isp": "isp", "remote": "internet", "dns": "internet"}


@dataclass
class Dashboard:
    has_data: bool = False
    code: str = "no_data"
    css: str = "muted"
    group: str = "none"
    updated: float | None = None
    updated_ago: str = ""
    active: object = None
    active_for: str = ""
    healthy_pct: str = "—"
    incidents_24h: int = 0
    worst_24h: str = "0.0%"
    timeline: object = None
    path: list[Hop] = field(default_factory=list)
    anchors: list[TargetCard] = field(default_factory=list)
    isp_name: str = ""
    day: dict = field(default_factory=dict)   # {"n", "dur", "by": {group: count}}
    targets: list[TargetCard] = field(default_factory=list)
    tunnels: list = field(default_factory=list)
    brief: list = field(default_factory=list)
    services: list = field(default_factory=list)
    link: dict | None = None
    link_enabled: bool = False
    recent: list = field(default_factory=list)


def _sample_loss(s: dict) -> float:
    return 100.0 * (s["sent"] - s["received"]) / s["sent"] if s["sent"] else 0.0


def dashboard_data(store: Store, settings: Settings, now: float | None = None) -> Dashboard:
    now = now or time.time()
    d = Dashboard()
    last = store.last_window()
    if not last:
        return d
    d.has_data = True
    d.updated = last[0]
    d.updated_ago = fmt_duration(max(0, now - last[0]))
    d.code = "stale" if is_stale(last, now) else last[2]
    d.group = charts.GROUP.get(d.code, "none")
    d.css = CAUSE_CLASS.get(d.code, "muted")

    active = [i for i in store.active_incidents() if i.scope == "internet"]
    if active:
        d.active, d.active_for = active[-1], fmt_duration(now - active[-1].opened)

    start = now - 86400
    windows = store.windows_between(start, now)
    if windows:
        start = max(start, windows[0][0] - windows[0][1])
        measured = sum(w[1] for w in windows)
        healthy = sum(w[1] for w in windows if w[2] == "ok")
        d.healthy_pct = f"{100 * healthy / measured:.1f}%" if measured else "—"
        incs = store.incidents_between(start, now)
        d.incidents_24h = len(incs)
        d.worst_24h = f"{max((i.peak_loss for i in incs), default=0.0):.1f}%"
        by: dict[str, int] = {}
        for i in incs:
            g = charts.GROUP.get(i.code, "other")
            by[g] = by.get(g, 0) + 1
        d.day = {"n": len(incs), "dur": fmt_duration(sum(i.duration(now) for i in incs)), "by": by}
        end = last[0]  # draw up to the last finished window: the one in progress isn't "missing data"
        series = _anchor_series(store.samples_between(start, end, role="anchor"))
        d.timeline = charts.timeline(windows, series, start, end)
        d.brief = list(reversed(store.brief_events(start, end)))[:12]

    # the latest measurement of every target (they make up the path in the hero), with 6 h of history
    h_start = now - 6 * 3600
    history: dict[str, list] = {}
    for row in store.samples_between(h_start, now):
        history.setdefault(row["target"], []).append(row)
    for s in sorted(store.latest_samples(), key=lambda s: (ROLE_ORDER.get(s["role"], 9), s["target"])):
        if s["role"].startswith(("tunnel_", "service:")):
            continue
        loss = _sample_loss(s)
        status = "bad" if loss >= 5 else "warn" if loss > 0 else "ok"
        rows = history.get(s["target"], [])
        d.targets.append(TargetCard(s["role"], s["target"], loss, s["rtt_median"], status,
                                    charts.plot([(r["ts"], r["rtt_median"]) for r in rows], h_start, now,
                                                unit=" ms", floor=5),
                                    max((_sample_loss(r) for r in rows), default=None)))
    d.anchors = [c for c in d.targets if c.role == "anchor"]
    net = store.network_at(now) or {}
    d.isp_name = net.get("isp_name") or ""
    d.path = _path(d, net)
    d.recent = recent_incidents(store, now)
    d.tunnels = tunnel_cards(store, settings, now)
    d.services = service_cards(store, settings, now)
    d.link_enabled = bool(settings.link.get("enabled"))
    rows = store.link_usage_between(now - 3 * 3600, now)
    if rows:
        ts, down, up, dpct, upct, cpu = rows[-1]
        pct = dpct is not None
        d.link = {"down": down, "up": up, "down_pct": dpct, "up_pct": upct, "cpu": cpu, "pct": pct,
                  "plot": charts.plot([(r[0], r[3] if pct else r[1]) for r in rows], now - 3 * 3600, now,
                                      unit="%" if pct else " Mbps", ymax=100 if pct else None, floor=10,
                                      threshold=85 if pct else None),
                  "xticks": charts.xticks(now - 3 * 3600, now), "cols": _link_cols(rows, now - 3 * 3600, now)}
    return d


def _link_cols(rows: list[tuple], start: float, end: float, n: int = 36) -> list[dict]:
    """Hover columns for the link chart: peak download in each 5-minute slice."""
    size = (end - start) / n
    cols = [{"start": start + i * size, "end": start + (i + 1) * size, "down": None, "pct": None,
             "flip": i >= n * 2 / 3} for i in range(n)]
    for ts, down, _up, dpct, _upct, _cpu in rows:
        i = int((ts - start) / size)
        if 0 <= i < n and (cols[i]["down"] is None or down > cols[i]["down"]):
            cols[i]["down"], cols[i]["pct"] = down, dpct
    return cols


def _state(loss: float | None) -> str:
    return "none" if loss is None else "bad" if loss >= 5 else "warn" if loss > 0 else "good"


def _path(d: Dashboard, net: dict) -> list[Hop]:
    home = next((c for c in d.targets if c.role == "home"), None)
    isp = next((c for c in d.targets if c.role == "isp"), None)
    inet_loss = statistics.fmean(c.loss for c in d.anchors) if d.anchors else None
    meds = [c.median for c in d.anchors if c.median is not None]
    hops = [Hop("home", home.target if home else "—", "", home.median if home else None,
                home.loss if home else None, _state(home.loss if home else None)),
            Hop("isp", d.isp_name or (isp.target if isp else "—"), isp.target if isp and d.isp_name else "",
                isp.median if isp else None, isp.loss if isp else None, _state(isp.loss if isp else None)),
            Hop("internet", str(len(d.anchors)), "", statistics.median(meds) if meds else None,
                inet_loss, _state(inet_loss))]
    blamed = BLAME.get(d.code)
    for h in hops:
        h.blamed = h.key == blamed
        if d.code in ("stale", "no_data"):
            h.state = "none"
    return hops


@dataclass
class TunnelCard:
    name: str
    type: str
    underlay: str
    overlay: str
    state: str  # up | down | no_data
    cause: str | None
    css: str
    loss_inside: float | None
    loss_outside: float | None
    since: str = ""


def tunnel_cards(store: Store, settings: Settings, now: float | None = None) -> list[TunnelCard]:
    now = now or time.time()
    latest = {s["role"]: s for s in store.latest_samples() if s["role"].startswith("tunnel_")}
    active = {i.tunnel: i for i in store.active_incidents() if i.tunnel}
    cards = []
    for t in settings.tunnels:
        over, under = latest.get(f"tunnel_over:{t.name}"), latest.get(f"tunnel_under:{t.name}")
        inc = active.get(t.name)
        if inc:
            state, cause, css, since = "down", inc.code, CAUSE_CLASS.get(inc.code, "bad"), fmt_duration(now - inc.opened)
        elif over and over["sent"]:
            state, cause, css, since = "up", None, "ok", ""
        else:
            state, cause, css, since = "no_data", None, "muted", ""
        cards.append(TunnelCard(t.name, t.type, t.underlay, t.overlay, state, cause, css,
                                _sample_loss(over) if over else None, _sample_loss(under) if under else None, since))
    return cards


@dataclass
class IncidentRow:
    id: int
    details: dict | None
    scope: str
    code: str
    css: str
    opened: float
    closed: float | None
    duration: str
    evidence: list[str]


def incident_rows(store: Store, t: dict, days: int = 30, now: float | None = None) -> list[IncidentRow]:
    now = now or time.time()
    rows = []
    for i in reversed(store.incidents_between(now - days * 86400, now, scope=None)):
        scope = t["scope_internet"] if i.scope == "internet" else (i.tunnel or i.scope.split(":", 1)[-1])
        rows.append(IncidentRow(i.id, i.details if i.code in ("access", "isp") else None, scope, i.code,
                                CAUSE_CLASS.get(i.code, "muted"), i.opened, i.closed,
                                fmt_duration(i.duration(now)), i.evidence[:3]))
    return rows


@dataclass
class ServiceCard:
    name: str
    kind: str
    target: str
    state: str          # up | down | no_data
    css: str
    ms: float | None
    since: str = ""
    detail: str = ""


def service_cards(store: Store, settings: Settings, now: float | None = None) -> list[ServiceCard]:
    now = now or time.time()
    latest = {s["role"]: s for s in store.latest_samples() if s["role"].startswith("service:")}
    active = {i.scope.split(":", 1)[1]: i for i in store.active_incidents() if i.scope.startswith("service:")}
    cards = []
    for sv in settings.services:
        sample = latest.get(f"service:{sv.name}")
        inc = active.get(sv.name)
        if inc:
            cards.append(ServiceCard(sv.name, sv.kind, sv.target, "down", "bad", None,
                                     fmt_duration(now - inc.opened), inc.evidence[0] if inc.evidence else ""))
        elif sample and sample["sent"]:
            ok = sample["received"] > 0
            cards.append(ServiceCard(sv.name, sv.kind, sv.target, "up" if ok else "down", "ok" if ok else "warn",
                                     sample["rtt_median"]))
        else:
            cards.append(ServiceCard(sv.name, sv.kind, sv.target, "no_data", "muted", None))
    return cards


@dataclass
class RecentIncident:
    code: str
    group: str
    scope: str        # internet | tunnel | service
    name: str         # tunnel or service name ("" for the internet)
    opened: float     # of the latest occurrence
    duration: str
    ongoing: bool
    count: int = 1    # identical incidents (same place, same cause) folded into this row


def recent_incidents(store: Store, now: float | None = None, limit: int = 6, days: int = 30) -> list[RecentIncident]:
    """Latest incidents of any kind, newest first. Repeats of the same thing in the same place
    (a tunnel that drops at every rekey) fold into one row with a count, so they don't bury the rest."""
    now = now or time.time()
    out: list[RecentIncident] = []
    seen: dict[tuple, RecentIncident] = {}
    for i in reversed(store.incidents_between(now - days * 86400, now, scope=None)):
        key = (i.scope, i.code)
        if key in seen:
            seen[key].count += 1
            continue
        if len(out) == limit:
            continue
        kind, _, name = i.scope.partition(":")
        row = RecentIncident(i.code, charts.GROUP.get(i.code, "other"), kind, name, i.opened,
                             fmt_duration(i.duration(now)), i.closed is None)
        seen[key] = row
        out.append(row)
    return out
