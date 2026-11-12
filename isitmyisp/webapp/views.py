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
from .. import mos as mos_mod

ROLE_ORDER = {"home": 0, "isp": 1, "anchor": 2, "voip": 3, "tcp": 4, "dns": 5}
CAUSE_CLASS = {"ok": "ok", "local": "warn", "access": "bad", "isp": "bad", "remote": "info", "dns": "info",
               "no_data": "muted", "stale": "muted", "config": "warn", "path_local": "bad",
               "path_remote": "info", "unknown": "muted", "saturation": "warn", "speedtest": "muted"}


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
class Point:
    """One row of "your network, point by point", grouped the way a technician reads it:
    each internet destination with its ping AND its TCP handshake, all DNS servers in one row."""
    kind: str                    # home | isp | internet | voip | dns
    target: str                  # address, or the list of DNS servers
    median: float | None         # ms (DNS: the slowest server)
    loss: float                  # % (DNS: the worst server)
    status: str                  # ok | warn | bad
    history: object = None       # charts.Plot, 6 h of latency
    worst: float | None = None   # worst loss in those 6 h
    tcp_ms: float | None = None  # internet destinations: TCP handshake to port 443
    tcp_loss: float | None = None
    count: int = 1               # DNS: how many servers


def _worse(a: str, b: str) -> str:
    order = {"ok": 0, "warn": 1, "bad": 2}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def build_points(targets: list) -> list[Point]:
    tcp = {c.target[len("tcp://"):].rsplit(":", 1)[0]: c for c in targets if c.role == "tcp"}
    out: list[Point] = []
    for c in targets:
        if c.role in ("home", "isp", "voip"):
            out.append(Point(c.role, c.target, c.median, c.loss, c.status, c.history, c.worst))
        elif c.role == "anchor":
            t = tcp.get(c.target)
            status = _worse(c.status, t.status) if t else c.status
            out.append(Point("internet", c.target, c.median, c.loss, status, c.history, c.worst,
                             t.median if t else None, t.loss if t else None))
    dns = [c for c in targets if c.role == "dns"]
    if dns:
        slowest = max(dns, key=lambda c: (c.median is None, c.median or 0))
        status = "ok"
        for c in dns:
            status = _worse(status, c.status)
        out.append(Point("dns", ", ".join(c.target[len("dns://"):] for c in dns), slowest.median,
                         max(c.loss for c in dns), status, slowest.history,
                         max((c.worst or 0) for c in dns), count=len(dns)))
    return out


def fit(items: list, cap: int, state=lambda x: "good", tick: int = 0) -> tuple[list, dict, dict | None]:
    """At most `cap` lines for a fixed-size panel. Items with problems are pinned (they never rotate
    away); the rest rotate one page per `tick` (the board refreshes every 30 s, so no JavaScript).
    Returns (shown in their original order, {"bad", "none", "good"} counts of what's hidden right now,
    rotation {"page", "pages", "shown", "total"} or None when everything fits)."""
    hidden = {"bad": 0, "none": 0, "good": 0}
    if len(items) <= cap:
        return items, hidden, None
    room = cap - 1                     # one line says what's going on
    pinned = [i for i in items if state(i) == "bad"][:room]
    pinned_ids = set(map(id, pinned))
    rest = [i for i in items if id(i) not in pinned_ids]
    slots = room - len(pinned)
    page, pages, window = 0, 1, []
    if slots > 0 and rest:
        pages = -(-len(rest) // slots)
        page = tick % pages
        # the last page wraps to the first items, so the panel keeps the same number of rows
        window = [rest[(page * slots + k) % len(rest)] for k in range(min(slots, len(rest)))]
    keep = pinned_ids | set(map(id, window))
    for i in items:
        if id(i) not in keep:
            hidden[state(i) if state(i) in hidden else "good"] += 1
    shown = [i for i in items if id(i) in keep]
    return shown, hidden, {"page": page + 1, "pages": pages, "shown": len(shown), "total": len(items)}


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
    kpi: dict = field(default_factory=dict)   # availability, time without outages, latency: value, delta, spark
    incidents_24h: int = 0
    worst_24h: str = "0.0%"
    timeline: object = None
    path: list[Hop] = field(default_factory=list)
    anchors: list[TargetCard] = field(default_factory=list)
    isp_name: str = ""
    day: dict = field(default_factory=dict)   # {"n", "dur", "by": {group: count}}
    targets: list[TargetCard] = field(default_factory=list)
    points: list = field(default_factory=list)   # build_points(targets)
    tunnels: list = field(default_factory=list)
    brief: list = field(default_factory=list)
    services: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    link: dict | None = None
    link_enabled: bool = False
    recent: list = field(default_factory=list)
    failover: dict | None = None   # on the backup link right now
    calls: dict | None = None      # estimated call quality (E-model)
    speed: dict | None = None      # speed test state and last results


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
        measured = sum(w[1] for w in windows if w[2] != "speedtest")
        healthy = sum(w[1] for w in windows if w[2] == "ok")
        d.healthy_pct = f"{100 * healthy / measured:.1f}%" if measured else "—"
        incs = store.incidents_between(start, now)
        d.incidents_24h = len(incs)
        d.worst_24h = f"{max((i.peak_loss for i in incs), default=0.0):.1f}%"
        by: dict[str, int] = {}
        for i in incs:
            g = charts.GROUP.get(i.code, "other")
            by[g] = by.get(g, 0) + 1
        d.day = {"n": len(incs), "dur": fmt_duration(sum(i.duration(now) for i in incs)), "by": by, "hours": False}
        from .. import hours as hours_mod
        bh = hours_mod.load(store)
        if hours_mod.active(bh):
            # downtime that fell while the business was open (each incident clipped to the last 24 h)
            in_s = sum(hours_mod.in_hours(bh, max(i.opened, now - 86400), i.closed or now) for i in incs)
            d.day |= {"hours": True, "open_s": in_s, "open_dur": fmt_duration(in_s)}
        end = last[0]  # draw up to the last finished window: the one in progress isn't "missing data"
        series = _anchor_series(store.samples_between(start, end, role="anchor"))
        backup = [(i.opened, i.closed or now) for i in store.incidents_between(start, now, scope="failover")]
        d.calls = call_summary(store, settings, start, end)
        d.timeline = charts.timeline(windows, series, start, end, backup=backup,
                                     calls=d.calls["series"] if d.calls else None)
        d.brief = list(reversed(store.brief_events(start, end)))[:12]
        d.kpi = kpis(store, windows, series, start, now)

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
    d.points = build_points(d.targets)
    net = store.network_at(now) or {}
    d.isp_name = net.get("isp_name") or ""
    d.path = _path(d, net)
    d.recent = recent_incidents(store, now)
    d.speed = speed_status(store, settings, now)
    fo = next((i for i in store.incidents_between(now - 400 * 86400, now, scope="failover") if i.closed is None), None)
    if fo:
        det = fo.details or {}
        d.failover = {"since": fo.opened, "for": fmt_duration(now - fo.opened),
                      "primary": (det.get("primary") or {}).get("name") or "",
                      "backup": (det.get("backup") or {}).get("name") or d.isp_name}
    d.tunnels = tunnel_cards(store, settings, now)
    d.services = service_cards(store, settings, now)
    d.devices = device_cards(store, settings, now)
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
    drops: int = 0      # an intermittent one: how many times it dropped and came back


def incident_rows(store: Store, t: dict, days: int = 30, now: float | None = None) -> list[IncidentRow]:
    now = now or time.time()
    rows = []
    for i in reversed(store.incidents_between(now - days * 86400, now, scope=None)):
        scope = t["scope_internet"] if i.scope == "internet" else (i.tunnel or i.scope.split(":", 1)[-1])
        rows.append(IncidentRow(i.id, i.details if i.code in ("access", "isp") else None, scope, i.code,
                                CAUSE_CLASS.get(i.code, "muted"), i.opened, i.closed,
                                fmt_duration(i.duration(now)), i.evidence[:3],
                                store.drops(i.opened, i.closed or now)
                                if (i.details or {}).get("intermittent") and i.scope == "internet" else 0))
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


def _healthy(windows) -> float | None:
    measured = sum(w[1] for w in windows if w[2] != "speedtest")
    return 100 * sum(w[1] for w in windows if w[2] == "ok") / measured if measured else None


def kpis(store: Store, windows, series, start: float, now: float) -> dict:
    """The three figures next to the verdict, each with the last 24 h as a small line and the change
    against the 24 h before (None when there's nothing to compare with)."""
    out: dict = {}
    # availability: share of measured time that was healthy, hour by hour
    hourly = []
    for h in range(24):
        a, b = now - 86400 + h * 3600, now - 86400 + (h + 1) * 3600
        v = _healthy([w for w in windows if a <= w[0] < b])
        if v is not None:
            hourly.append(((a + b) / 2, v))
    pct = _healthy(windows)
    prev = _healthy(store.windows_between(now - 2 * 86400, now - 86400))
    out["avail"] = {"value": pct, "delta": (pct - prev) if pct is not None and prev is not None else None,
                    # scaled to the day's own range, so a good day still shows its dips
                    "spark": charts.plot(hourly, now - 86400, now, unit="%", ymax=100, floor=10,
                                         ymin=max(0.0, 10 * (min((v for _, v in hourly), default=90) // 10) - 10))}
    # time without outages: since the last internet incident ended (or since measuring started)
    incs = store.incidents_between(now - 400 * 86400, now)
    ongoing = any(i.closed is None for i in incs)
    last_end = max((i.closed for i in incs if i.closed is not None), default=None)
    first = store.first_and_last_window()[0] or start
    healthy_s, acc = 0.0, []
    for w in sorted(windows):                    # healthy hours piling up over the day
        if w[2] == "ok":
            healthy_s += w[1]
        acc.append((w[0], healthy_s / 3600))
    out["uptime"] = {"ongoing": ongoing, "since": None if ongoing else (last_end or first),
                     "value": None if ongoing else fmt_duration(now - (last_end or first)),
                     "spark": charts.plot(acc[::10], start, now, unit=" h", floor=1)}
    # latency: median to the internet destinations, now vs the day before
    lats = [v for _, _, v in series if v is not None]
    lat = statistics.median(lats) if lats else None
    prev_s = [r["rtt_median"] for r in store.samples_between(now - 2 * 86400, now - 86400, role="anchor")
              if r["rtt_median"] is not None]
    plat = statistics.median(prev_s) if prev_s else None
    out["lat"] = {"value": lat, "delta": (lat - plat) if lat is not None and plat is not None else None,
                  "spark": charts.plot([(ts, v) for ts, _, v in series if v is not None], start, now, unit=" ms", floor=5)}
    return out


def device_cards(store: Store, settings: Settings, now: float | None = None) -> list[ServiceCard]:
    """Devices on your network, in the same shape as the services (kind is the device kind)."""
    now = now or time.time()
    latest = {s["role"]: s for s in store.latest_samples() if s["role"].startswith("device:")}
    active = {i.scope.split(":", 1)[1]: i for i in store.active_incidents() if i.scope.startswith("device:")}
    cards = []
    for dv in settings.devices:
        sample = latest.get(f"device:{dv.name}")
        inc = active.get(dv.name)
        if inc:
            cards.append(ServiceCard(dv.name, dv.kind, dv.endpoint, "down", "bad", None,
                                     fmt_duration(now - inc.opened), inc.evidence[0] if inc.evidence else ""))
        elif sample and sample["sent"] and now - sample["ts"] < 600:
            ok = sample["received"] > 0
            cards.append(ServiceCard(dv.name, dv.kind, dv.endpoint, "up" if ok else "down", "ok" if ok else "warn",
                                     sample["rtt_median"]))
        else:
            cards.append(ServiceCard(dv.name, dv.kind, dv.endpoint, "no_data", "muted", None))
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
    drops: int = 0    # for an intermittent one: how many times it dropped and came back


def recent_incidents(store: Store, now: float | None = None, limit: int = 6, days: int = 30) -> list[RecentIncident]:
    """Latest incidents of any kind, newest first. Repeats of the same thing in the same place
    (a tunnel that drops at every rekey) fold into one row with a count, so they don't bury the rest."""
    now = now or time.time()
    out: list[RecentIncident] = []
    seen: dict[tuple, RecentIncident] = {}
    for i in reversed(store.incidents_between(now - days * 86400, now, scope=None)):
        key = (i.scope, i.code, bool((i.details or {}).get("intermittent")))   # steady and intermittent apart
        if key in seen:
            seen[key].count += 1
            continue
        if len(out) == limit:
            continue
        kind, _, name = i.scope.partition(":")
        row = RecentIncident(i.code, charts.GROUP.get(i.code, "other"), kind, name, i.opened,
                             fmt_duration(i.duration(now)), i.closed is None)
        if (i.details or {}).get("intermittent") and kind == "internet":
            row.drops = store.drops(i.opened, i.closed or now)
        seen[key] = row
        out.append(row)
    return out


def isp_status(store: Store, data_dir, job: dict | None = None, now: float | None = None) -> dict:
    """Main ISP vs the one in use, and the state of the ASN dataset (settings page)."""
    from .. import asn
    from ..failover import Provider, provider_of
    now = now or time.time()
    primary = Provider.from_dict(store.get_setting("primary_isp"))
    current = provider_of(store.network_at(now) or {})
    path = asn.db_path(data_dir) if data_dir is not None else None
    have = bool(path and path.exists())
    return {"primary": primary, "current": current,
            "on_backup": bool(primary and current and not current.same_as(primary)),
            "asn_installed": have, "asn_date": path.stat().st_mtime if have else None,
            "asn_running": bool(job and job.get("running")), "asn_error": (job or {}).get("error"),
            "asn_available": data_dir is not None}


def call_summary(store: Store, settings: Settings, start: float, end: float) -> dict | None:
    """Estimated call quality per window over [start, end]: against your calls destination when
    one is set (and answering), otherwise against the internet destinations."""
    rows = store.samples_between(start, end, role="voip") if settings.voip_target else []
    source = "voip" if any(r["received"] for r in rows) else "anchors"
    if source == "anchors":
        rows = store.samples_between(start, end, role="anchor")
    series, fit, worst = [], 0, None
    marks = mos_mod.quality_series(rows)
    for ts, q in marks:
        series.append((ts, q.mos))
        fit += q.fit
        if worst is None or q.mos < worst[1]:
            worst = (ts, q.mos)
    if not series:
        return None
    last = marks[-1][1]
    return {"now": last, "series": series, "fit_pct": round(100 * fit / len(series), 1),
            "worst": worst, "source": source, "target": settings.voip_target}


def speed_status(store: Store, settings: Settings, now: float | None = None) -> dict:
    """Everything the speed test card shows: state, budget, last results, next run."""
    from .. import speedtest as sp
    now = now or time.time()
    cfg = {**sp.DEFAULTS, **(settings.speedtest or {})}
    on = bool(cfg["enabled"] and cfg["accepted"])
    month = store.speedtests_between(sp.month_start(now), now)
    history = list(reversed(store.speedtests_between(now - 90 * 86400, now)))[:6]
    slot = sp.last_slot(cfg, now)
    nxt = None
    if on and slot is not None:
        nxt = slot + (86400 if cfg["schedule"] == "daily" else 7 * 86400)
    used = sum(int(r.get("bytes_used") or 0) for r in month)
    contract_down = float(settings.link.get("down_mbps") or 0)
    contract_up = float(settings.link.get("up_mbps") or 0)
    per_test = sp.per_test_bytes(cfg)
    # what one test really uses: the cap, or less if the plan can't move that much in the test time
    expected = per_test
    if contract_down:
        expected = min(per_test, int((contract_down * sp.DOWN_SECONDS + (contract_up or contract_down) * sp.UP_SECONDS) * 1e6 / 8))
    blocked = store.get_setting("_speed_blocked")
    if blocked and now - blocked.get("ts", 0) > 3600:
        blocked = None
    requested = store.get_setting("_speed_request") or 0
    pending = bool(requested and now - requested < 120 and not any(r["ts"] >= requested for r in month))
    return {"cfg": cfg, "on": on, "last": history[0] if history else None, "history": history,
            "used": used, "budget": cfg["budget_gb"] * 1e9, "per_test": per_test, "expected": expected,
            "next": nxt, "contract_down": contract_down, "contract_up": contract_up,
            "blocked": blocked, "pending": pending, "weekdays": sp.WEEKDAYS}


@dataclass
class Conn:
    """A service or a tunnel, as one row of a fixed-size panel."""
    kind: str          # service | tunnel
    name: str
    sub: str           # tunnel type, or ""
    ms: float | None
    state: str         # services: up | down | no_data; tunnels: up | down | no_data
    since: str
    st: str            # good | bad | none


BOARD_POINTS, BOARD_CONNS, BOARD_RECENT = 6, 5, 5


def board(d: Dashboard, now: float | None = None) -> dict:
    """What each fixed-size panel of the TV board shows; nothing can push the 24 h timeline out.
    Long lists rotate on every refresh; whatever is failing is pinned and also named in the header."""
    tick = int((now or time.time()) // 30)
    conns = [Conn("service", c.name, "", c.ms, c.state, c.since,
                  "good" if c.state == "up" else "bad" if c.state == "down" else "none") for c in d.services]
    conns += [Conn("device", c.name, c.kind, c.ms, c.state, c.since,
                   "good" if c.state == "up" else "bad" if c.state == "down" else "none") for c in d.devices]
    conns += [Conn("tunnel", c.name, c.type, None, c.state, c.since,
                   "good" if c.state == "up" else "bad" if c.state == "down" else "none") for c in d.tunnels]
    points, p_hidden, p_rot = fit(d.points, BOARD_POINTS, state=lambda p: "good" if p.status == "ok" else "bad", tick=tick)
    shown, c_hidden, c_rot = fit(conns, BOARD_CONNS, state=lambda c: c.st, tick=tick)
    return {"points": points, "points_hidden": p_hidden, "points_rot": p_rot,
            "conns": shown, "conns_hidden": c_hidden, "conns_rot": c_rot,
            "alarms": [c for c in conns if c.st == "bad"],
            "points_alarm": any(p.status == "bad" for p in d.points),
            "recent": d.recent[:BOARD_RECENT]}
