"""Chart components for the web UI: plain data + resolution-independent SVG, hover done in CSS.

Why this shape: the dashboard ships no JavaScript and a CSP without inline styles. So:
- plots are SVG in a 0..1000 x 0..100 box stretched to the container (preserveAspectRatio="none"),
  with non-scaling strokes, so lines stay 2px and nothing is shrunk with the viewBox;
- every text (axis ticks, tooltips) is real HTML, so it is always legible and selectable;
- hover is a row of equal-width HTML columns over the plots (CSS grid), one per time bucket,
  each with its own tooltip: a crosshair and readout with zero script.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

BUCKETS = 96  # 24 h -> 15 min per column

# Who is responsible: this, not the 8 internal verdict codes, is what a colour means here.
GROUP = {"ok": "good", "local": "you", "saturation": "you", "access": "isp", "isp": "isp",
         "remote": "other", "dns": "other", "no_data": "none", "stale": "none",
         # tunnels and your own services
         "config": "you", "path_local": "you", "path_remote": "other", "unknown": "none", "service_down": "other",
         "failover": "other"}
SEVERITY = {"isp": 4, "you": 3, "other": 2, "good": 1, "none": 0}


@dataclass
class Bucket:
    start: float
    end: float
    code: str            # worst verdict seen in the bucket
    group: str
    loss: float | None   # mean loss in the bucket (%): what the verdict saw, not one unlucky window
    lat: float | None    # median latency (ms)
    flip: bool = False   # tooltip opens to the left (right third of the chart)
    backup: bool = False  # traffic was going out through the backup link


@dataclass
class Plot:
    """One single-series line chart in the 0..1000 x 0..100 box."""
    line: str = ""
    area: str = ""
    ymax: float = 1.0
    unit: str = ""
    threshold: float | None = None   # y of a reference line (0..100 box), e.g. saturation
    ticks: list[str] = field(default_factory=list)  # [top, middle, bottom] labels

    @property
    def empty(self) -> bool:
        return not self.line


@dataclass
class Timeline:
    start: float
    end: float
    buckets: list[Bucket]
    strip: list[tuple[float, float, str, str]]   # (x, width, group, code) runs in the 0..1000 box
    loss: Plot
    latency: Plot
    xticks: list[str]                            # labels at 1/6 .. 5/6
    groups: list[str]                            # responsibility groups present (legend)
    hourly: list[Bucket]                         # table view
    backup_runs: list[tuple[float, float]] = field(default_factory=list)  # (x, width): on the backup link


def _nice_max(v: float, floor: float) -> float:
    v = max(v * 1.1, floor)
    for step in (1, 2, 2.5, 5, 10):
        mag = 10 ** int(f"{v:e}".split("e")[1])
        if step * mag >= v:
            return step * mag
    return v


def _fmt(v: float) -> str:
    return f"{v:.0f}" if v >= 10 or v == int(v) else f"{v:.1f}"


def plot(points: list[tuple[float, float]], start: float, end: float, *, unit: str = "",
         floor: float = 1.0, ymax: float | None = None, threshold: float | None = None) -> Plot:
    """points: [(ts, value)] -> polyline/area strings. Gaps longer than 3 samples break the line."""
    pts = [(ts, v) for ts, v in points if v is not None and start <= ts <= end]
    if len(pts) < 2:
        return Plot(unit=unit)
    top = ymax or _nice_max(max(v for _, v in pts), floor)
    span = max(1.0, end - start)

    def xy(ts: float, v: float) -> tuple[float, float]:
        return 1000 * (ts - start) / span, 100 - 100 * min(v, top) / top

    step = statistics.median(b[0] - a[0] for a, b in zip(pts, pts[1:])) or 1
    segments, cur = [], [pts[0]]
    for a, b in zip(pts, pts[1:]):
        if b[0] - a[0] > 3 * step:
            segments.append(cur)
            cur = []
        cur.append(b)
    segments.append(cur)
    lines, areas = [], []
    for seg in segments:
        coords = [xy(ts, v) for ts, v in seg]
        if len(coords) == 1:
            coords.append((coords[0][0] + 1, coords[0][1]))
        lines.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords))
        areas.append(f"M{coords[0][0]:.1f},100 L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
                     + f" L{coords[-1][0]:.1f},100 Z")
    return Plot(" ".join(lines), " ".join(areas), top, unit,
                None if threshold is None else 100 - 100 * threshold / top,
                [f"{_fmt(top)}{unit}", f"{_fmt(top / 2)}{unit}", f"0{unit}"])


def strip_runs(windows: list[tuple[float, float, str]], start: float, end: float) -> list[tuple[float, float, str, str]]:
    """Merge consecutive windows with the same verdict; return runs in the 0..1000 box."""
    runs: list[list] = []
    for ts, secs, code in windows:
        begin = ts - secs
        if runs and 0 <= begin - runs[-1][1] <= secs:
            if runs[-1][2] == code:
                runs[-1][1] = ts
                continue
            begin = runs[-1][1]
        runs.append([begin, ts, code])
    span = max(1.0, end - start)
    out = []
    for begin, finish, code in runs:
        x0 = max(0.0, 1000 * (begin - start) / span)
        x1 = min(1000.0, 1000 * (finish - start) / span)
        if x1 > x0:
            out.append((round(x0, 2), round(max(0.8, x1 - x0), 2), GROUP.get(code, "none"), code))
    return out


def _buckets(windows, series, start: float, end: float, n: int) -> list[Bucket]:
    size = (end - start) / n
    out = [Bucket(start + i * size, start + (i + 1) * size, "no_data", "none", None, None, i >= n * 2 / 3)
           for i in range(n)]
    lats: list[list[float]] = [[] for _ in range(n)]
    losses: list[list[float]] = [[] for _ in range(n)]
    def index(t: float) -> int:  # -1 when outside the chart
        return min(n - 1, int((t - start) / size)) if start <= t <= end else -1

    for ts, secs, code in windows:  # a window is stamped at its end: file it under its middle
        i = index(ts - secs / 2)
        if i < 0:
            continue
        b, g = out[i], GROUP.get(code, "none")
        if SEVERITY[g] > SEVERITY[b.group]:
            b.code, b.group = code, g
    for ts, loss, lat in series:   # also end-stamped; nudge so a window ending on a boundary stays in its bucket
        i = index(ts - 1e-6)
        if i >= 0:
            losses[i].append(loss)
            if lat is not None:
                lats[i].append(lat)
    for b, values, ls in zip(out, lats, losses):
        b.lat = statistics.median(values) if values else None
        b.loss = statistics.fmean(ls) if ls else None
    return out


def _merge(buckets: list[Bucket], k: int) -> list[Bucket]:
    out = []
    for i in range(0, len(buckets), k):
        chunk = buckets[i:i + k]
        worst = max(chunk, key=lambda b: SEVERITY[b.group])
        losses = [b.loss for b in chunk if b.loss is not None]
        lats = [b.lat for b in chunk if b.lat is not None]
        out.append(Bucket(chunk[0].start, chunk[-1].end, worst.code, worst.group,
                          statistics.fmean(losses) if losses else None,
                          statistics.median(lats) if lats else None, backup=any(b.backup for b in chunk)))
    return out


def xticks(start: float, end: float) -> list[str]:
    fmt = "%d/%m %H:%M" if end - start > 86400 * 1.5 else "%H:%M"
    return [time.strftime(fmt, time.localtime(start + (end - start) * i / 6)) for i in range(1, 6)]


def timeline(windows: list[tuple[float, float, str]], series: list[tuple[float, float, float | None]],
             start: float, end: float, n: int = BUCKETS, backup: list[tuple[float, float]] = ()) -> Timeline:
    """windows: [(ts, seconds, code)]; series: [(ts, loss %, median latency ms)] per window;
    backup: [(start, end)] spans on the backup link (failover)."""
    buckets = _buckets(windows, series, start, end, n)
    span = max(1.0, end - start)
    backup_runs = []
    for b0, b1 in backup:
        b0, b1 = max(b0, start), min(b1, end)
        if b1 > b0:
            backup_runs.append((round(1000 * (b0 - start) / span, 2), round(max(0.8, 1000 * (b1 - b0) / span), 2)))
            for b in buckets:
                if b.start < b1 and b.end > b0:
                    b.backup = True
    runs = strip_runs(windows, start, end)
    present = {g for _, _, g, _ in runs}
    groups = [g for g in ("good", "you", "isp", "other") if g in present]
    if any(b.group == "none" for b in buckets[:-1]):
        groups.append("none")
    return Timeline(start, end, buckets, runs,
                    plot([(ts, loss) for ts, loss, _ in series], start, end, unit="%", floor=2),
                    plot([(ts, lat) for ts, _, lat in series], start, end, unit=" ms", floor=10),
                    xticks(start, end), groups, _merge(buckets, max(1, n // 24)), backup_runs)
