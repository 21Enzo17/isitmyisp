"""Read-only web dashboard, Prometheus metrics and JSON status. Standard library only.

    /             dashboard (auto-refresh every 30 s, no JavaScript)
    /report       evidence report (?since=7d&until=...&lang=es)
    /report.pdf   same, as PDF (needs WeasyPrint: pip install isitmyisp[pdf])
    /metrics      Prometheus text format
    /api/status   current state as JSON

Binds to 127.0.0.1 by default. It has no authentication: only expose it on a network you trust.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .report import (COLORS, CSS, R, TUNNEL_COLORS, _anchor_series, _downsample, _dt, _e, build_report,
                     fmt_duration, svg_line, svg_status_strip)
from .store import Store
from .timeutil import parse_when

VERDICT_CODES = ("ok", "local", "access", "isp", "remote", "dns", "no_data")

W = {
    "en": {"title": "isitmyisp", "now": "Right now", "last24": "Last 24 hours", "active": "Active incident",
           "since": "since", "none_active": "No active incidents.", "targets": "Targets (last window)",
           "reports": "Reports", "r24": "Last 24 h", "r7": "Last 7 days", "pdf": "PDF",
           "tunnels": "Tunnels", "updated": "Updated", "no_data": "No measurements yet. Is `isitmyisp monitor` running?",
           "verdict": {"ok": "Healthy", "local": "Problem on your side", "access": "ISP access network problem",
                       "isp": "ISP backbone / upstream problem", "remote": "Only some destinations affected",
                       "dns": "DNS problem", "no_data": "No data"},
           "tun": {"up": "up", "down": "down", "no_data": "no data"}},
    "es": {"title": "isitmyisp", "now": "Ahora", "last24": "Últimas 24 horas", "active": "Incidente activo",
           "since": "desde", "none_active": "Sin incidentes activos.", "targets": "Destinos (última ventana)",
           "reports": "Informes", "r24": "Últimas 24 h", "r7": "Últimos 7 días", "pdf": "PDF",
           "tunnels": "Túneles", "updated": "Actualizado", "no_data": "Todavía no hay mediciones. ¿Está corriendo `isitmyisp monitor`?",
           "verdict": {"ok": "Sana", "local": "Problema de tu lado", "access": "Problema en el acceso del ISP",
                       "isp": "Problema en la red troncal / salida del ISP", "remote": "Solo algunos destinos fallan",
                       "dns": "Problema de DNS", "no_data": "Sin datos"},
           "tun": {"up": "arriba", "down": "caído", "no_data": "sin datos"}},
}


# ------------------------------------------------------------------ content

def dashboard_html(store: Store, lang: str = "en", now: float | None = None) -> str:
    t, r = W.get(lang, W["en"]), R.get(lang, R["en"])
    now = now or time.time()
    last = store.last_window()
    head = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta http-equiv="refresh" content="30"><title>isitmyisp</title><style>{CSS}'
            f'.big{{font-size:22px}} .links a{{margin-right:14px}}</style></head><body><main>'
            f'<header><div class="brand">isitmyisp</div></header>')
    if not last:
        return head + f'<div class="hero" style="--c:{COLORS["no_data"]}">{_e(t["no_data"])}</div></main></body></html>'

    code = last[2]
    stale = now - last[0] > 5 * max(30.0, last[1])
    color = COLORS["no_data"] if stale else COLORS.get(code, COLORS["no_data"])
    label = t["verdict"]["no_data"] if stale else t["verdict"].get(code, code)
    out = [head, f'<h2>{_e(t["now"])}</h2><div class="hero big" style="--c:{color}">{_e(label)}</div>']

    active = [i for i in store.active_incidents() if i.scope == "internet"]
    if active:
        inc = active[-1]
        out.append(f'<p><b>{_e(t["active"])}:</b> {_e(r["seg"].get(inc.code, inc.code))} · {_e(t["since"])} '
                   f'{_e(_dt(inc.opened))} ({fmt_duration(now - inc.opened)})<br>'
                   + "<br>".join(_e(e) for e in inc.evidence[:3]) + "</p>")
    else:
        out.append(f'<p class="muted">{_e(t["none_active"])}</p>')

    # last 24 h
    start = now - 86400
    windows = store.windows_between(start, now)
    if windows:
        start = max(start, windows[0][0] - windows[0][1])
        series = _downsample(_anchor_series(store.samples_between(start, now, role="anchor")), 360)
        out.append(f'<h2>{_e(t["last24"])}</h2>' + svg_status_strip(windows, start, now))
        if series:
            out.append(f'<div class="label">{_e(r["loss_chart"])}</div>'
                       + svg_line([(ts, l) for ts, l, _ in series], start, now, COLORS["access"], unit="%"))
            lat = [(ts, v) for ts, _, v in series if v is not None]
            out.append(f'<div class="label">{_e(r["lat_chart"])}</div>' + svg_line(lat, start, now, COLORS["dns"]))

    # tunnels
    samples = store.latest_samples()
    tun_rows = []
    active_tun = {i.tunnel: i for i in store.active_incidents() if i.tunnel}
    for s in samples:
        if s["role"].startswith("tunnel_over:"):
            name = s["role"].split(":", 1)[1]
            inc = active_tun.get(name)
            if inc:
                state, color = f'{t["tun"]["down"]}: {r["tun_cause"].get(inc.code, inc.code)}', TUNNEL_COLORS.get(inc.code)
            elif s["sent"]:
                state, color = t["tun"]["up"], COLORS["ok"]
            else:
                state, color = t["tun"]["no_data"], COLORS["no_data"]
            tun_rows.append(f'<tr><td>{_e(name)}</td><td><span class="dot" style="background:{color}"></span>'
                            f'{_e(state)}</td></tr>')
    if tun_rows:
        out.append(f'<h2>{_e(t["tunnels"])}</h2><table><tbody>{"".join(tun_rows)}</tbody></table>')

    # targets
    rows = []
    for s in samples:
        if s["role"].startswith("tunnel_"):
            continue
        loss = 100.0 * (s["sent"] - s["received"]) / s["sent"] if s["sent"] else 0.0
        med = "—" if s["rtt_median"] is None else f'{s["rtt_median"]:.1f} ms'
        rows.append(f'<tr><td>{_e(s["role"])}</td><td class="mono">{_e(s["target"])}</td>'
                    f'<td class="num">{loss:.1f}%</td><td class="num">{med}</td></tr>')
    out.append(f'<h2>{_e(t["targets"])}</h2><table><tbody>{"".join(rows)}</tbody></table>')

    out.append(f'<h2>{_e(t["reports"])}</h2><p class="links">'
               f'<a href="/report?since=24h&lang={lang}">{_e(t["r24"])}</a>'
               f'<a href="/report?since=7d&lang={lang}">{_e(t["r7"])}</a>'
               f'<a href="/report.pdf?since=7d&lang={lang}">{_e(t["r7"])} ({t["pdf"]})</a></p>')
    out.append(f'<footer>{_e(t["updated"])}: {_e(_dt(last[0]))} · isitmyisp {__version__}</footer></main></body></html>')
    return "".join(out)


def _prom_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def metrics_text(store: Store, now: float | None = None) -> str:
    now = now or time.time()
    lines = []

    def metric(name: str, help_: str, kind: str, values: list[tuple[dict, float]]) -> None:
        lines.append(f"# HELP isitmyisp_{name} {help_}")
        lines.append(f"# TYPE isitmyisp_{name} {kind}")
        for labels, value in values:
            lab = ",".join(f'{k}="{_prom_escape(str(v))}"' for k, v in labels.items())
            lines.append(f"isitmyisp_{name}{{{lab}}} {value}" if lab else f"isitmyisp_{name} {value}")

    samples = store.latest_samples()
    metric("loss_ratio", "Packet/probe loss in the last window (0-1).", "gauge",
           [({"role": s["role"], "target": s["target"]}, round((s["sent"] - s["received"]) / s["sent"], 4))
            for s in samples if s["sent"]])
    metric("rtt_median_ms", "Median round-trip time in the last window.", "gauge",
           [({"role": s["role"], "target": s["target"]}, round(s["rtt_median"], 3)) for s in samples
            if s["rtt_median"] is not None])
    last = store.last_window()
    current = last[2] if last else "no_data"
    metric("verdict", "1 for the current verdict of the last window.", "gauge",
           [({"code": c}, 1 if c == current else 0) for c in VERDICT_CODES])
    metric("last_window_timestamp_seconds", "Unix time of the last measurement window.", "gauge",
           [({}, round(last[0], 3) if last else 0)])
    active = store.active_incidents()
    metric("incident_active", "1 if an incident is open for this scope.", "gauge",
           [({"scope": i.scope, "code": i.code}, 1) for i in active] or [({"scope": "internet", "code": "none"}, 0)])
    metric("incidents_total", "Incidents recorded, by scope and cause.", "counter",
           [({"scope": sc, "code": c}, n) for (sc, c), n in sorted(store.incident_counts().items())])
    return "\n".join(lines) + "\n"


def status_json(store: Store, now: float | None = None) -> dict:
    now = now or time.time()
    last = store.last_window()
    return {
        "version": __version__,
        "verdict": last[2] if last else "no_data",
        "last_window": last[0] if last else None,
        "stale": bool(last and now - last[0] > 5 * max(30.0, last[1])),
        "active_incidents": [{"scope": i.scope, "code": i.code, "opened": i.opened, "evidence": i.evidence}
                             for i in store.active_incidents()],
        "targets": store.latest_samples(),
    }


# ------------------------------------------------------------------ server

def _parse_since(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return parse_when(value)
    except ValueError:
        return default


def make_handler(store: Store, default_lang: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"isitmyisp/{__version__}"

        def log_message(self, fmt, *args) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            lang = q.get("lang") if q.get("lang") in ("en", "es") else default_lang
            now = time.time()
            try:
                if url.path == "/":
                    self._send(200, dashboard_html(store, lang, now).encode(), "text/html; charset=utf-8")
                elif url.path in ("/report", "/report.pdf"):
                    start = _parse_since(q.get("since"), now - 7 * 86400)
                    end = _parse_since(q.get("until"), now)
                    doc = build_report(store, start, end, lang=lang, now=now)
                    if url.path == "/report":
                        self._send(200, doc.encode(), "text/html; charset=utf-8")
                    else:
                        from .pdf import PdfUnavailable, html_to_pdf
                        try:
                            pdf = html_to_pdf(doc)
                        except PdfUnavailable as exc:
                            self._send(501, str(exc).encode(), "text/plain; charset=utf-8")
                            return
                        self._send(200, pdf, "application/pdf",
                                   {"Content-Disposition": f'inline; filename="isitmyisp-report-{time.strftime("%Y%m%d")}.pdf"'})
                elif url.path == "/metrics":
                    self._send(200, metrics_text(store, now).encode(), "text/plain; version=0.0.4; charset=utf-8")
                elif url.path == "/api/status":
                    self._send(200, json.dumps(status_json(store, now)).encode(), "application/json")
                else:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
            except Exception as exc:  # never kill the monitor because of a web request
                self._send(500, f"internal error: {type(exc).__name__}".encode(), "text/plain; charset=utf-8")

    return Handler


def parse_bind(bind: str) -> tuple[str, int]:
    host, _, port = bind.rpartition(":")
    return (host or "127.0.0.1"), int(port)


def start_server(store: Store, bind: str = "127.0.0.1:8080", lang: str = "en") -> ThreadingHTTPServer:
    host, port = parse_bind(bind)
    httpd = ThreadingHTTPServer((host, port), make_handler(store, lang))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
