"""Data shaping for the web pages (no Flask here: easy to test)."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from ..report import (COLORS, _anchor_series, _downsample, fmt_duration, svg_line, svg_status_strip)
from ..settings import Settings
from ..store import Store
from ..api import is_stale

ROLE_ORDER = {"home": 0, "isp": 1, "anchor": 2, "tcp": 3, "dns": 4}
CAUSE_CLASS = {"ok": "ok", "local": "warn", "access": "bad", "isp": "bad", "remote": "info", "dns": "info",
               "no_data": "muted", "stale": "muted", "config": "warn", "path_local": "bad",
               "path_remote": "info", "unknown": "muted"}


def spark(values: list[float], css: str = "spark", w: int = 240, h: int = 44) -> str:
    """Tiny line chart without axes (latency over the last hours)."""
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    step = w / (len(values) - 1)
    if hi - lo < 0.05:  # flat line: draw it in the middle, not glued to the bottom
        coords = [(i * step, h / 2) for i, v in enumerate(values) if v is not None]
    else:
        coords = [(i * step, h - 4 - (v - lo) / (hi - lo) * (h - 8)) for i, v in enumerate(values) if v is not None]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"{coords[0][0]:.1f},{h} {line} {coords[-1][0]:.1f},{h}"
    return (f'<svg viewBox="0 0 {w} {h}" class="{css}" preserveAspectRatio="none" role="img">'
            f'<polygon points="{area}" class="spark-area"/><polyline points="{line}" class="spark-line"/></svg>')


@dataclass
class TargetCard:
    role: str
    target: str
    loss: float
    median: float | None
    status: str  # ok | warn | bad
    chart: str = ""


@dataclass
class Dashboard:
    has_data: bool = False
    code: str = "no_data"
    css: str = "muted"
    updated: float | None = None
    updated_ago: str = ""
    active: object = None
    active_for: str = ""
    healthy_pct: str = "—"
    incidents_24h: int = 0
    worst_24h: str = "0.0%"
    strip: str = ""
    loss_chart: str = ""
    latency_chart: str = ""
    targets: list[TargetCard] = field(default_factory=list)
    tunnels: list = field(default_factory=list)


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
        d.strip = svg_status_strip(windows, start, now)
        series = _downsample(_anchor_series(store.samples_between(start, now, role="anchor")), 360)
        if series:
            d.loss_chart = svg_line([(ts, l) for ts, l, _ in series], start, now, COLORS["access"], unit="%")
            d.latency_chart = svg_line([(ts, v) for ts, _, v in series if v is not None], start, now, "#9b8cff")

    # one card per measured target, with a 6-hour latency sparkline
    recent = store.samples_between(now - 6 * 3600, now)
    by_target: dict[str, list[dict]] = defaultdict(list)
    for s in recent:
        by_target[s["target"]].append(s)
    for s in sorted(store.latest_samples(), key=lambda s: (ROLE_ORDER.get(s["role"], 9), s["target"])):
        if s["role"].startswith("tunnel_"):
            continue
        loss = _sample_loss(s)
        status = "bad" if loss >= 5 else "warn" if loss > 0 else "ok"
        hist = by_target.get(s["target"], [])[-90:]
        d.targets.append(TargetCard(s["role"], s["target"], loss, s["rtt_median"], status,
                                    spark([h["rtt_median"] for h in hist])))
    d.tunnels = tunnel_cards(store, settings, now)
    return d


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
        scope = t["scope_internet"] if i.scope == "internet" else (i.tunnel or i.scope)
        rows.append(IncidentRow(i.id, scope, i.code, CAUSE_CLASS.get(i.code, "muted"), i.opened, i.closed,
                                fmt_duration(i.duration(now)), i.evidence[:3]))
    return rows
