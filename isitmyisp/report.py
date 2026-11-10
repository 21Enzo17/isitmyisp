"""Evidence report: one self-contained HTML file (inline CSS + SVG, no JS, no external assets).

Written for two readers at once:
  * you, in plain language: what happened and whose fault it was;
  * your ISP's support/NOC: timestamps, where loss starts, mtr captures, methodology.
Print it to PDF from any browser, or attach the HTML to your ticket.
"""

from __future__ import annotations

import html
import statistics
import time
from collections import defaultdict

from . import __version__
from .store import Capture, Incident, Store
from .tunnels import periodic_interval

ISP_CODES = ("access", "isp")
TUNNEL_COLORS = {"path_local": "#d9534f", "path_remote": "#7b6fd0", "config": "#e0a526", "unknown": "#9aa0a6"}
COLORS = {
    "ok": "#3fa66b", "local": "#e0a526", "access": "#d9534f", "isp": "#b83a6e",
    "remote": "#7b6fd0", "dns": "#3b8ad9", "no_data": "#c9ccd1", "saturation": "#e07b26",
}

R = {
    "en": {
        "title": "Connection evidence report",
        "plural": lambda n: {"incidents": "incident" if n == 1 else "incidents", "were": "was" if n == 1 else "were"},
        "period": "Period", "generated": "Generated", "isp": "ISP", "connection": "Measured over",
        "wifi": "Wi-Fi", "cable": "cable", "cgnat": "CGNAT", "yes": "yes", "no": "no",
        "measured": "Time measured", "healthy": "Healthy", "incidents": "Incidents",
        "degraded": "Time with problems", "peak": "Worst loss",
        "hero_none": "No incidents in this period. Your connection was healthy {pct} of the time measured.",
        "hero_some": "{n} {incidents}, {dur} in total. {k} of them {were} inside your ISP's network.",
        "hero_home": "Most problems ({k} of {n}) were on your side (Wi-Fi, LAN or your router), not your ISP's.",
        "by_segment": "Where the problems were",
        "seg": {"local": "Your side (Wi-Fi, LAN, router)", "access": "ISP access network",
                "isp": "ISP backbone / upstream", "remote": "Remote destinations only", "dns": "DNS resolver",
                "saturation": "Link full: your own traffic"},
        "count": "Count", "duration": "Duration",
        "timeline": "Timeline", "status": "Status per window", "loss_chart": "Packet loss to the internet (%)",
        "lat_chart": "Latency to the internet (median, ms)",
        "legend": {"ok": "healthy", "local": "your side", "access": "ISP access", "isp": "ISP backbone",
                   "remote": "remote", "dns": "DNS", "saturation": "link full (yours)",
                   "no_data": "not measuring (start-up, re-discovery, settings change)"},
        "incident_list": "Incidents", "start": "Start", "end": "End", "where": "Where", "evidence": "Evidence",
        "ongoing": "ongoing", "capture": "mtr",
        "message": "Message for your ISP",
        "message_hint": "Copy and paste this into your support ticket. It only includes incidents inside the ISP's network.",
        "msg_none": "In this period there were no incidents attributable to the ISP's network.",
        "msg_intro": ("Hello. Between {start} and {end} my connection had {n} {incidents} that the evidence places "
                      "in your network, {dur} in total. They were measured continuously from my premises with isitmyisp: "
                      "loss was confirmed with both ICMP and TCP, several independent destinations were affected at once, "
                      "my own network (router and LAN) answered normally at the same time{sat}, and an mtr was captured "
                      "during each incident."),
        "msg_sat": ", and my link usage read from my router was below {pct}% of the contracted speed",
        "msg_item": "- {start} to {end} ({dur}): {where}{hop}.",
        "msg_hop": "; loss starts at hop {i} ({host}{asn})",
        "msg_outro": "Full report with every capture attached. Please escalate it to your network team.",
        "appendix": "Technical appendix: mtr captures",
        "appendix_none": "No captures in this period.",
        "hop": "Hop", "host": "Host", "loss": "Loss", "avg": "Avg", "result": "Result", "asn": "AS",
        "st": {"ok": "ok", "real_loss": "REAL LOSS", "icmp_deprioritized": "ignored: ICMP deprioritized",
               "no_reply": "no reply"},
        "cap_ok": "Destination reached with {l}% loss.",
        "cap_bad": "Real loss of {l}% to the destination, starting at hop {h} ({host}).",
        "cap_err": "Capture failed: {e}",
        "method": "Methodology",
        "method_items": [
            "Every few seconds the monitor pings your router(s), your ISP's first hop and three public anchors "
            "(1.1.1.1, 8.8.8.8, 9.9.9.9), opens TCP connections to port 443 of the anchors and queries your DNS resolvers.",
            "Loss counts only when it is statistically significant (95% Wilson interval above 1.5%). Latency is "
            "compared with each target's own baseline.",
            "An anchor is considered affected only if ICMP and TCP agree, so routers that deprioritize ICMP are not "
            "mistaken for loss.",
            "An incident opens after two consecutive bad windows and closes after two good ones.",
            "In mtr captures, loss on an intermediate hop is only real if it persists to the destination.",
            "A verdict places the problem in a segment of the path; it is strong evidence, not legal proof. Each "
            "ISP-side incident lists what the evidence rules out and what it cannot.",
        ],
        "tunnels": "Tunnels",
        "tun_cause": {"path_local": "Loss on your connection", "path_remote": "Far site or path to it",
                      "config": "Tunnel configuration (path was clean)", "unknown": "Undetermined (far end filters ICMP)"},
        "tun_none": "No tunnel drops in this period.",
        "speed": "Measured speed",
        "speed_plan": "Contracted: {down} Mbps down / {up} Mbps up. ",
        "speed_intro": "Tests against speed.cloudflare.com with several parallel streams. A test over Wi-Fi measures the Wi-Fi as well.",
        "speed_down": "Download", "speed_up": "Upload", "speed_loaded": "Latency under load", "speed_via": "Measured over",
        "speed_wifi": "Wi-Fi", "speed_cable": "cable",
        "calls": "Call quality",
        "calls_fit": "Fit for calls {pct} of the time measured. Periods when it wasn't:",
        "calls_all_fit": "Calls would have sounded acceptable or better the whole time.",
        "calls_worst_col": "Worst MOS",
        "calls_method": "Estimated with the ITU-T G.107 E-model (G.711 with loss concealment) from latency, jitter and loss; fit for calls means R >= 70 (MOS 3.6). It is an estimate from ping, not a measured call.",
        "failover": "Backup link in use",
        "fo_intro": "During these periods your router sent the traffic through the backup link because the main ISP was down or failing ({dur} in total). Measurements in those periods describe the backup link.",
        "fo_col": "Went out through",
        "services": "Your services: it wasn't your internet",
        "svc_intro": "These services were unreachable while your own connection was healthy: the problem was on their side.",
        "svc_col": "Service",
        "tun_periodic": ("{name}: drops repeat every {every} with a clean path. That is the fingerprint of "
                         "mismatched IKE/IPsec lifetimes or rekey timers between both ends: compare them."),
        "tun_config_hint": ("{name}: {k} drop(s) happened while the path outside the tunnel was clean. Check DPD "
                            "timeouts, IKE/IPsec lifetimes, NAT-T and MTU/MSS on both ends."),
        "footer": "Generated by isitmyisp {v} · open source · times shown in {tz}",
        "no_data": "No measurements in this period. Run `isitmyisp monitor` first.",
    },
    "es": {
        "title": "Informe de evidencia de conexión",
        "plural": lambda n: {"incidents": "incidente" if n == 1 else "incidentes", "were": "fue" if n == 1 else "fueron"},
        "period": "Período", "generated": "Generado", "isp": "ISP", "connection": "Medido por",
        "wifi": "Wi-Fi", "cable": "cable", "cgnat": "CGNAT", "yes": "sí", "no": "no",
        "measured": "Tiempo medido", "healthy": "Sana", "incidents": "Incidentes",
        "degraded": "Tiempo con problemas", "peak": "Peor pérdida",
        "hero_none": "Sin incidentes en este período. Tu conexión estuvo sana el {pct} del tiempo medido.",
        "hero_some": "{n} {incidents}, {dur} en total. {k} {were} dentro de la red de tu ISP.",
        "hero_home": "La mayoría de los problemas ({k} de {n}) fueron de tu lado (Wi-Fi, LAN o tu router), no de tu ISP.",
        "by_segment": "Dónde estuvieron los problemas",
        "seg": {"local": "Tu lado (Wi-Fi, LAN, router)", "access": "Red de acceso del ISP",
                "isp": "Red troncal / salida del ISP", "remote": "Solo destinos remotos", "dns": "Servidor DNS",
                "saturation": "Enlace lleno: tu propio tráfico"},
        "count": "Cantidad", "duration": "Duración",
        "timeline": "Línea de tiempo", "status": "Estado por ventana", "loss_chart": "Pérdida de paquetes hacia internet (%)",
        "lat_chart": "Latencia hacia internet (mediana, ms)",
        "legend": {"ok": "sana", "local": "tu lado", "access": "acceso ISP", "isp": "troncal ISP",
                   "remote": "remoto", "dns": "DNS", "saturation": "enlace lleno (tuyo)",
                   "no_data": "sin medir (arranque, redescubrimiento, cambio de configuración)"},
        "incident_list": "Incidentes", "start": "Inicio", "end": "Fin", "where": "Dónde", "evidence": "Evidencia",
        "ongoing": "en curso", "capture": "mtr",
        "message": "Mensaje para tu ISP",
        "message_hint": "Copialo y pegalo en tu reclamo. Solo incluye los incidentes dentro de la red del ISP.",
        "msg_none": "En este período no hubo incidentes atribuibles a la red del ISP.",
        "msg_intro": ("Hola. Entre el {start} y el {end} mi conexión tuvo {n} {incidents} que la evidencia ubica "
                      "en su red, {dur} en total. Los medí de forma continua desde mis instalaciones con isitmyisp: la "
                      "pérdida se confirmó por ICMP y por TCP, fallaban varios destinos independientes a la vez, mi propia "
                      "red (router y LAN) respondía normal al mismo tiempo{sat}, y se capturó un mtr durante cada incidente."),
        "msg_sat": ", y el uso de mi enlace leído de mi router estaba por debajo del {pct}% de la velocidad contratada",
        "msg_item": "- {start} a {end} ({dur}): {where}{hop}.",
        "msg_hop": "; la pérdida empieza en el salto {i} ({host}{asn})",
        "msg_outro": "Adjunto el informe completo con todas las capturas. Les pido que lo escalen al área de red.",
        "appendix": "Anexo técnico: capturas mtr",
        "appendix_none": "No hay capturas en este período.",
        "hop": "Salto", "host": "Host", "loss": "Pérdida", "avg": "Prom.", "result": "Resultado", "asn": "AS",
        "st": {"ok": "ok", "real_loss": "PÉRDIDA REAL", "icmp_deprioritized": "ignorado: ICMP despriorizado",
               "no_reply": "no responde"},
        "cap_ok": "El destino llega con {l}% de pérdida.",
        "cap_bad": "Pérdida real de {l}% hasta el destino, empezando en el salto {h} ({host}).",
        "cap_err": "La captura falló: {e}",
        "method": "Metodología",
        "method_items": [
            "Cada pocos segundos se hace ping a tu(s) router(s), al primer salto de tu ISP y a tres destinos públicos "
            "(1.1.1.1, 8.8.8.8, 9.9.9.9), se abren conexiones TCP al puerto 443 de esos destinos y se consultan tus DNS.",
            "La pérdida solo cuenta si es estadísticamente significativa (intervalo de Wilson al 95% por encima de 1,5%). "
            "La latencia se compara con la línea base propia de cada destino.",
            "Un destino se considera afectado solo si ICMP y TCP coinciden, así los routers que despriorizan ICMP "
            "no se confunden con pérdida.",
            "Un incidente se abre tras dos ventanas malas seguidas y se cierra tras dos buenas.",
            "En las capturas mtr, la pérdida en un salto intermedio solo es real si sigue hasta el destino.",
            "Un veredicto ubica el problema en un tramo del camino: es evidencia sólida, no una prueba legal. Cada "
            "incidente atribuido al ISP indica qué descarta la evidencia y qué no puede descartar.",
        ],
        "tunnels": "Túneles",
        "tun_cause": {"path_local": "Pérdida en tu conexión", "path_remote": "Sitio remoto o camino hacia él",
                      "config": "Configuración del túnel (camino limpio)", "unknown": "Indeterminado (el otro extremo filtra ICMP)"},
        "tun_none": "Sin caídas de túneles en este período.",
        "speed": "Velocidad medida",
        "speed_plan": "Contratado: {down} Mbps de bajada / {up} Mbps de subida. ",
        "speed_intro": "Pruebas contra speed.cloudflare.com con varias conexiones en paralelo. Una prueba por Wi-Fi mide también el Wi-Fi.",
        "speed_down": "Bajada", "speed_up": "Subida", "speed_loaded": "Latencia con carga", "speed_via": "Medido por",
        "speed_wifi": "Wi-Fi", "speed_cable": "cable",
        "calls": "Calidad para llamadas",
        "calls_fit": "Apta para llamadas el {pct} del tiempo medido. Períodos en que no lo fue:",
        "calls_all_fit": "Las llamadas se habrían escuchado aceptable o mejor todo el tiempo.",
        "calls_worst_col": "Peor MOS",
        "calls_method": "Estimado con el modelo E de la UIT (G.107, G.711 con ocultamiento de pérdidas) a partir de latencia, jitter y pérdida; apta para llamadas significa R >= 70 (MOS 3,6). Es una estimación a partir de ping, no una llamada medida.",
        "failover": "Enlace de respaldo en uso",
        "fo_intro": "En estos períodos tu router mandó el tráfico por el enlace de respaldo porque el ISP principal estaba caído o fallando ({dur} en total). Las mediciones de esos períodos describen al respaldo.",
        "fo_col": "Salió por",
        "services": "Tus servicios: no era tu internet",
        "svc_intro": "Estos servicios no respondían mientras tu propia conexión andaba bien: el problema era de ellos.",
        "svc_col": "Servicio",
        "tun_periodic": ("{name}: las caídas se repiten cada {every} con el camino limpio. Esa es la huella de "
                         "lifetimes o timers de rekey IKE/IPsec distintos en los dos extremos: comparalos."),
        "tun_config_hint": ("{name}: {k} caída(s) ocurrieron con el camino por fuera del túnel limpio. Revisá timeouts "
                            "de DPD, lifetimes IKE/IPsec, NAT-T y MTU/MSS en ambos extremos."),
        "footer": "Generado por isitmyisp {v} · código abierto · horarios en {tz}",
        "no_data": "No hay mediciones en este período. Corré `isitmyisp monitor` primero.",
    },
}


# ------------------------------------------------------------------ helpers

def _e(s: object) -> str:
    return html.escape(str(s))


def _dt(ts: float, with_date: bool = True) -> str:
    return time.strftime("%Y-%m-%d %H:%M" if with_date else "%H:%M", time.localtime(ts))


def _dt_html(ts: float) -> str:
    """Date on top (small), time below: fits narrow table columns."""
    lt = time.localtime(ts)
    return f'<small>{time.strftime("%Y-%m-%d", lt)}</small><br>{time.strftime("%H:%M", lt)}'


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min" + (f" {s} s" if s and m < 10 else "")
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} h {m} min" if m else f"{h} h"
    d, h = divmod(h, 24)
    return f"{d} d {h} h" if h else f"{d} d"


def _anchor_series(samples: list[dict]) -> list[tuple[float, float, float | None]]:
    """[(ts, mean loss % across anchors, median latency)] per window."""
    by_ts: dict[float, list[dict]] = defaultdict(list)
    for s in samples:
        by_ts[s["ts"]].append(s)
    out = []
    for ts in sorted(by_ts):
        rows = [r for r in by_ts[ts] if r["sent"]]
        if not rows:
            continue
        loss = statistics.fmean(100.0 * (r["sent"] - r["received"]) / r["sent"] for r in rows)
        lats = [r["rtt_median"] for r in rows if r["rtt_median"] is not None]
        out.append((ts, loss, statistics.median(lats) if lats else None))
    return out


def _downsample(points: list[tuple], buckets: int) -> list[tuple]:
    if len(points) <= buckets:
        return points
    size = len(points) / buckets
    out = []
    for i in range(buckets):
        chunk = points[int(i * size):int((i + 1) * size)] or [points[-1]]
        ts = chunk[len(chunk) // 2][0]
        loss = max(p[1] for p in chunk)  # keep spikes visible
        lats = [p[2] for p in chunk if p[2] is not None]
        out.append((ts, loss, statistics.median(lats) if lats else None))
    return out


# ------------------------------------------------------------------ SVG charts

W, PAD_L, PAD_R = 920, 46, 12


def _x(ts: float, start: float, end: float) -> float:
    return PAD_L + (ts - start) / max(1.0, end - start) * (W - PAD_L - PAD_R)


def _time_axis(start: float, end: float, y: float) -> str:
    """Interior ticks only (edges would collide with neighbours). Dates appear when the span is long."""
    span = end - start
    long_span = span > 86400 * 1.5
    ticks = 6
    parts = []
    for i in range(1, ticks):
        ts = start + span * i / ticks
        label = time.strftime("%m-%d %H:%M" if long_span else "%H:%M", time.localtime(ts))
        parts.append(f'<text x="{_x(ts, start, end):.1f}" y="{y}" text-anchor="middle" class="axis">{_e(label)}</text>')
    return "".join(parts)


def svg_status_strip(windows: list[tuple[float, float, str]], start: float, end: float,
                     labels: dict[str, str] | None = None) -> str:
    """Verdict per window. `labels` (code -> text) adds a hover tooltip to every stretch, no JS needed."""
    h = 26
    # Merge consecutive windows with the same verdict into one rectangle (a day is ~2,880 windows).
    runs: list[list] = []  # [begin, end, code]
    for ts, secs, code in windows:
        begin = ts - secs
        if runs and 0 <= begin - runs[-1][1] <= secs:  # contiguous (small gaps are measurement overhead)
            if runs[-1][2] == code:
                runs[-1][1] = ts
                continue
            begin = runs[-1][1]
        runs.append([begin, ts, code])
    rects = []
    for begin, finish, code in runs:
        x0, x1 = _x(begin, start, end), _x(finish, start, end)
        tip = ""
        if labels:
            tip = (f'<title>{_e(_dt(begin, False))}–{_e(_dt(finish, False))} · '
                   f'{_e(labels.get(code, code))} ({fmt_duration(finish - begin)})</title>')
        rects.append(f'<rect x="{x0:.2f}" y="0" width="{max(0.6, x1 - x0):.2f}" height="{h}" '
                     f'fill="{COLORS.get(code, COLORS["no_data"])}">{tip}</rect>')
    if labels and "no_data" in labels:  # make the gaps explain themselves too
        rects.insert(0, f'<rect x="{PAD_L}" y="0" width="{W - PAD_L - PAD_R}" height="{h}" fill="transparent">'
                        f'<title>{_e(labels["no_data"])}</title></rect>')
    return (f'<svg viewBox="0 0 {W} {h + 18}" class="chart" role="img">'
            f'<rect x="{PAD_L}" y="0" width="{W - PAD_L - PAD_R}" height="{h}" fill="{COLORS["no_data"]}" opacity=".35"/>'
            + "".join(rects) + _time_axis(start, end, h + 14) + "</svg>")


def svg_line(points: list[tuple[float, float]], start: float, end: float, color: str,
             y_max: float | None = None, unit: str = "") -> str:
    h, top, bottom = 120, 8, 20
    if not points:
        return ""
    ymax = y_max or max(1.0, max(p[1] for p in points) * 1.15)
    def y(v: float) -> float:
        return top + (1 - min(v, ymax) / ymax) * (h - top - bottom)
    grid = []
    for frac in (0, 0.5, 1):
        val = ymax * frac
        grid.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(val):.1f}" y2="{y(val):.1f}" class="grid"/>'
                    f'<text x="{PAD_L - 6}" y="{y(val) + 4:.1f}" text-anchor="end" class="axis">'
                    f'{val:.{0 if ymax >= 10 else 1}f}{unit}</text>')
    pts = " ".join(f"{_x(ts, start, end):.1f},{y(v):.1f}" for ts, v in points)
    area = f"{_x(points[0][0], start, end):.1f},{y(0):.1f} {pts} {_x(points[-1][0], start, end):.1f},{y(0):.1f}"
    return (f'<svg viewBox="0 0 {W} {h}" class="chart" role="img">' + "".join(grid)
            + f'<polygon points="{area}" fill="{color}" opacity=".12"/>'
            + f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round"/>'
            + _time_axis(start, end, h - 4) + "</svg>")


# ------------------------------------------------------------------ report

EVIDENCE_ES = [
    ("home router", "router de tu casa"), ("ISP first hop", "primer salto del ISP"),
    ("% loss", "% de pérdida"), ("latency", "latencia"), ("vs usual", "vs. habitual"),
    ("your internet: OK at the same time", "tu internet: bien al mismo tiempo"), ("checks failed", "chequeos fallidos"),
    ("DNS failure", "falla de DNS"), ("timeout", "sin respuesta (timeout)"), ("connection refused", "conexión rechazada"),
    ("TLS error", "error de TLS"), ("through the tunnel", "por dentro del túnel"), ("outside the tunnel", "por fuera del túnel"),
    ("never answers ICMP", "nunca responde ICMP"), ("all anchors degraded (worst", "todos los destinos afectados (peor"),
    (": OK", ": bien"),
]


def localize_evidence(line: str, lang: str) -> str:
    if lang == "es":
        for en, es in EVIDENCE_ES:
            line = line.replace(en, es)
    return line


def describe_link(link: dict | None) -> str:
    if not link:
        return ""
    def part(mbps, pct):
        return f"{mbps:.0f} Mbps" + (f" ({pct:.0f}%)" if pct is not None else "")
    return f"↓ {part(link['down_mbps'], link.get('down_pct'))} · ↑ {part(link['up_mbps'], link.get('up_pct'))}"


def ruled_out_html(inc: Incident, lang: str) -> str:
    """'What the evidence rules out / can't rule out' for ISP-side incidents."""
    from .texts import NOT_RULED, RULED
    d = inc.details or {}
    if inc.code not in ISP_CODES or not d:
        return ""
    link = d.get("link") or {}
    ok = [RULED[lang][c].format(link=describe_link(link), cpu=link.get("cpu_pct", "?"))
          for c in d.get("ruled_out", []) if c in RULED[lang]]
    no = [NOT_RULED[lang][c] for c in d.get("not_ruled_out", []) if c in NOT_RULED[lang]]
    out = ""
    if ok:
        out += '<div class="ruled">' + "".join(f"<div>✓ {_e(x)}</div>" for x in ok) + "</div>"
    if no:
        out += '<div class="notruled">' + "".join(f"<div>? {_e(x)}</div>" for x in no) + "</div>"
    return out


def compress_evidence(lines: list[str]) -> list[str]:
    """'1.1.1.1: 33.3% loss (5/15)', '8.8.8.8: 33.3% loss (5/15)' -> '1.1.1.1, 8.8.8.8: 33.3% loss (5/15)'."""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for line in lines:
        target, sep, why = line.partition(": ")
        key = why if sep and " " not in target else line
        if key not in groups:
            groups[key], _ = [], order.append(key)
        if sep and " " not in target:
            groups[key].append(target)
    return [f"{', '.join(groups[k])}: {k}" if groups[k] else k for k in order]


def _capture_summary(c: Capture, t: dict) -> tuple[int | None, str, str]:
    """(hop index where loss starts, host, asn text) for the ISP message."""
    d = c.data
    i = d.get("loss_starts_at")
    if i is None:
        return None, "", ""
    hop = next((h for h in d.get("hops", []) if h["index"] == i), None)
    if not hop:
        return None, "", ""
    asn_txt = f", {hop['asn']} {hop['as_name']}" if hop.get("asn") else ""
    return i, hop["host"], asn_txt


def _capture_table(c: Capture, t: dict) -> str:
    d = c.data
    head = f'<h3 id="cap-{c.id}">{_e(t["capture"])} → {_e(c.target)} · {_e(_dt(c.ts))}</h3>'
    if "error" in d:
        return head + f'<p class="muted">{_e(t["cap_err"].format(e=d["error"]))}</p>'
    rows = []
    for h in d.get("hops", []):
        cls = {"real_loss": "bad", "icmp_deprioritized": "muted", "no_reply": "muted"}.get(h["status"], "")
        asn = f'{h["asn"]} {h["as_name"] or ""}' if h.get("asn") else ""
        rows.append(f'<tr class="{cls}"><td>{h["index"]}</td><td class="mono">{_e(h["host"])}</td>'
                    f'<td class="num">{h["loss"]:.1f}%</td><td class="num">{h["avg"]:.1f} ms</td>'
                    f'<td>{_e(t["st"].get(h["status"], h["status"]))}</td><td>{_e(asn)}</td></tr>')
    if d.get("loss_starts_at") is not None:
        hop = next((h for h in d["hops"] if h["index"] == d["loss_starts_at"]), {"host": "?"})
        verdict = t["cap_bad"].format(l=d["destination_loss"], h=d["loss_starts_at"], host=hop["host"])
    else:
        verdict = t["cap_ok"].format(l=d.get("destination_loss", 0))
    return (head + f'<table class="mtr"><thead><tr><th>{t["hop"]}</th><th>{t["host"]}</th><th>{t["loss"]}</th>'
            f'<th>{t["avg"]}</th><th>{t["result"]}</th><th>{t["asn"]}</th></tr></thead><tbody>'
            + "".join(rows) + f'</tbody></table><p class="verdict-line">{_e(verdict)}</p>')


def tunnel_section(incidents: list[Incident], t: dict, now: float) -> str:
    parts = [f'<h2>{_e(t["tunnels"])}</h2>']
    if not incidents:
        return parts[0] + f'<p class="muted">{_e(t["tun_none"])}</p>'
    by_tunnel: dict[str, list[Incident]] = defaultdict(list)
    for inc in incidents:
        by_tunnel[inc.tunnel or "?"].append(inc)
    hints = []
    rows = []
    for name, incs in by_tunnel.items():
        agg: dict[str, list[Incident]] = defaultdict(list)
        for inc in incs:
            agg[inc.code].append(inc)
        for code, group in agg.items():
            color = TUNNEL_COLORS.get(code, "#9aa0a6")
            rows.append(f'<tr><td>{_e(name)}</td><td><span class="dot" style="background:{color}"></span>'
                        f'{_e(t["tun_cause"].get(code, code))}</td><td class="num">{len(group)}</td>'
                        f'<td class="num">{fmt_duration(sum(i.duration(now) for i in group))}</td></tr>')
        config = [i.opened for i in agg.get("config", [])]
        every = periodic_interval(config)
        if every:
            hints.append(t["tun_periodic"].format(name=name, every=fmt_duration(every)))
        elif config:
            hints.append(t["tun_config_hint"].format(name=name, k=len(config)))
    parts.append(f'<table><thead><tr><th></th><th></th><th class="num">{t["count"]}</th>'
                 f'<th class="num">{t["duration"]}</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
    parts += [f'<p class="verdict-line">{_e(h)}</p>' for h in hints]
    return "".join(parts)


def isp_message(incidents: list[Incident], captures: dict[int, list[Capture]], t: dict,
                start: float, end: float, now: float) -> str:
    isp = [i for i in incidents if i.code in ISP_CODES]
    if not isp:
        return t["msg_none"]
    total = sum(i.duration(now) for i in isp)
    sat_ok = all(i.details and "saturation" in i.details.get("ruled_out", []) for i in isp)
    from .classifier import CLEAN_LINK_PCT
    lines = [t["msg_intro"].format(start=_dt(start), end=_dt(end), n=len(isp), dur=fmt_duration(total),
                                 incidents=t["plural"](len(isp))["incidents"],
                                 sat=t["msg_sat"].format(pct=int(CLEAN_LINK_PCT)) if sat_ok else ""), ""]
    for inc in isp:
        hop_txt = ""
        for c in captures.get(inc.id, []):
            i, host, asn_txt = _capture_summary(c, t)
            if i is not None:
                hop_txt = t["msg_hop"].format(i=i, host=host, asn=asn_txt)
                break
        end_txt = _dt(inc.closed) if inc.closed else t["ongoing"]
        lines.append(t["msg_item"].format(start=_dt(inc.opened), end=end_txt, dur=fmt_duration(inc.duration(now)),
                                          where=t["seg"][inc.code], hop=hop_txt))
    lines += ["", t["msg_outro"]]
    return "\n".join(lines)


CSS = """
:root { --ink:#1d2330; --muted:#6b7280; --line:#e5e7eb; --bg:#ffffff; --soft:#f6f7f9; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font: 14px/1.5 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 24px 48px; }
header .brand { font-weight:700; letter-spacing:.02em; color:var(--muted); font-size:12px; text-transform:uppercase; }
h1 { font-size: 26px; margin: 4px 0 12px; }
h2 { font-size: 17px; margin: 32px 0 10px; padding-bottom:6px; border-bottom:1px solid var(--line); }
h3 { font-size: 14px; margin: 22px 0 6px; }
.meta { display:flex; flex-wrap:wrap; gap:6px 22px; color:var(--muted); font-size:13px; }
.meta b { color:var(--ink); font-weight:600; }
.hero { margin:20px 0 6px; padding:16px 18px; border-radius:10px; background:var(--soft); border-left:5px solid var(--c); font-size:16px; font-weight:600; }
.tiles { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
.tile { flex:1 1 140px; border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
.tile .k { color:var(--muted); font-size:12px; }
.tile .v { font-size:20px; font-weight:700; font-variant-numeric: tabular-nums; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:12px; }
td.num, th.num { text-align:right; font-variant-numeric: tabular-nums; }
td.num { white-space:nowrap; }
td.dt { text-align:right; font-variant-numeric: tabular-nums; line-height:1.3; }
td.dt small { color:var(--muted); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:12.5px; }
.dot { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; }
.chart { width:100%; height:auto; display:block; margin:4px 0 2px; }
.chart .axis { font-size:10.5px; fill:var(--muted); }
.chart .grid { stroke:var(--line); stroke-width:1; }
.legend { display:flex; flex-wrap:wrap; gap:4px 16px; font-size:12px; color:var(--muted); margin:2px 0 10px; }
.label { font-size:12px; color:var(--muted); margin-top:12px; }
pre.message { white-space:pre-wrap; background:var(--soft); border:1px solid var(--line); border-radius:8px; padding:14px; font: 13px/1.55 ui-monospace, Menlo, Consolas, monospace; }
tr.bad td { color:#b42318; font-weight:600; }
table.incidents { table-layout:fixed; }
table.incidents td.ev { font-size:12px; overflow-wrap:anywhere; }
tr.muted td, .muted { color:var(--muted); }
.verdict-line { font-weight:600; margin:6px 0 0; }
ul.method li { margin:4px 0; }
.ruled { margin-top:6px; color:#1f7a4d; } .notruled { margin-top:4px; color:#8a5a00; }
footer { margin-top:36px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:10px; }
@media print { main { padding: 0; } h2 { break-after: avoid; } table, svg, .tile { break-inside: avoid; } }
"""


def call_periods(store: Store, start: float, end: float, min_seconds: float = 120,
                 limit: int = 12) -> tuple[float, list[tuple[float, float, float]]] | None:
    """(% of windows fit for calls, [(start, end, worst MOS)] stretches that weren't, longest first).
    Judged against the calls provider when one was measured, otherwise against the anchors."""
    from .mos import quality_series
    rows = store.samples_between(start, end, role="voip")
    if not any(r["received"] for r in rows):
        rows = store.samples_between(start, end, role="anchor")
    marks = quality_series(rows)
    if not marks:
        return None
    step = statistics.median(b[0] - a[0] for a, b in zip(marks, marks[1:])) if len(marks) > 1 else 30.0
    bad: list[list[float]] = []
    for ts, q in marks:
        if q.fit:
            continue
        if bad and ts - bad[-1][1] <= 1.5 * step:
            bad[-1][1], bad[-1][2] = ts, min(bad[-1][2], q.mos)
        else:
            bad.append([ts - step, ts, q.mos])
    stretches = sorted((tuple(b) for b in bad if b[1] - b[0] >= min_seconds), key=lambda b: b[0] - b[1])[:limit]
    return 100.0 * sum(q.fit for _, q in marks) / len(marks), sorted(stretches)


def build_report(store: Store, start: float, end: float, lang: str = "en", now: float | None = None) -> str:
    t = R.get(lang, R["en"])
    now = now or time.time()
    windows = store.windows_between(start, end)
    incidents = store.incidents_between(start, end)
    captures = store.captures_for([i.id for i in incidents])
    net = store.network_at(end) or {}
    tz = time.strftime("%Z (UTC%z)", time.localtime(end))

    if windows:
        start = max(start, windows[0][0] - windows[0][1])
        end = min(end, windows[-1][0])
    measured = sum(w[1] for w in windows if w[2] != "speedtest")  # a speed test is neither healthy nor a problem
    healthy = sum(w[1] for w in windows if w[2] == "ok")
    pct = f"{100 * healthy / measured:.1f}%" if measured else "—"
    total_bad = sum(i.duration(now) for i in incidents)
    peak = max((i.peak_loss for i in incidents), default=0.0)

    meta = [f'<span>{t["period"]}: <b>{_e(_dt(start))} → {_e(_dt(end))}</b></span>',
            f'<span>{t["generated"]}: <b>{_e(_dt(now))}</b></span>']
    if net.get("isp_name"):
        meta.append(f'<span>{t["isp"]}: <b>{_e(net.get("isp_asn") or "")} {_e(net["isp_name"])}</b></span>')
    if net:
        meta.append(f'<span>{t["connection"]}: <b>{t["wifi"] if net.get("wireless") else t["cable"]}</b></span>')
        meta.append(f'<span>{t["cgnat"]}: <b>{t["yes"] if net.get("cgnat") else t["no"]}</b></span>')

    out = [f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{_e(t["title"])}</title><style>{CSS}</style></head><body><main>',
           f'<header><div class="brand">isitmyisp</div><h1>{_e(t["title"])}</h1>'
           f'<div class="meta">{"".join(meta)}</div></header>']

    if not windows:
        out.append(f'<div class="hero" style="--c:{COLORS["no_data"]}">{_e(t["no_data"])}</div>')
        out.append(f'<footer>{_e(t["footer"].format(v=__version__, tz=tz))}</footer></main></body></html>')
        return "".join(out)

    # ---- hero + tiles
    n = len(incidents)
    k_isp = sum(1 for i in incidents if i.code in ISP_CODES)
    k_home = sum(1 for i in incidents if i.code == "local")
    if n == 0:
        hero, color = t["hero_none"].format(pct=pct), COLORS["ok"]
    elif k_home > n / 2:
        hero, color = t["hero_home"].format(k=k_home, n=n), COLORS["local"]
    else:
        hero = t["hero_some"].format(n=n, dur=fmt_duration(total_bad), k=k_isp, incidents=t["plural"](n)["incidents"],
                                     were=t["plural"](k_isp)["were"])
        color = COLORS["isp"] if k_isp else COLORS["remote"]
    out.append(f'<div class="hero" style="--c:{color}">{_e(hero)}</div>')
    tiles = [(t["measured"], fmt_duration(measured)), (t["healthy"], pct), (t["incidents"], str(n)),
             (t["degraded"], fmt_duration(total_bad)), (t["peak"], f"{peak:.1f}%")]
    out.append('<div class="tiles">' + "".join(
        f'<div class="tile"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div></div>' for k, v in tiles) + "</div>")

    # ---- by segment
    if incidents:
        agg: dict[str, list[float]] = defaultdict(list)
        for i in incidents:
            agg[i.code].append(i.duration(now))
        rows = "".join(
            f'<tr><td><span class="dot" style="background:{COLORS[c]}"></span>{_e(t["seg"][c])}</td>'
            f'<td class="num">{len(agg[c])}</td><td class="num">{fmt_duration(sum(agg[c]))}</td></tr>'
            for c in ("local", "saturation", "access", "isp", "remote", "dns") if c in agg)
        out.append(f'<h2>{_e(t["by_segment"])}</h2><table><thead><tr><th></th><th class="num">{t["count"]}</th>'
                   f'<th class="num">{t["duration"]}</th></tr></thead><tbody>{rows}</tbody></table>')

    # ---- timeline
    series = _downsample(_anchor_series(store.samples_between(start, end, role="anchor")), 460)
    legend = "".join(f'<span><span class="dot" style="background:{COLORS[c]}"></span>{_e(lbl)}</span>'
                     for c, lbl in t["legend"].items())
    out.append(f'<h2>{_e(t["timeline"])}</h2><div class="label">{_e(t["status"])} · {_e(_dt(start))} → {_e(_dt(end))}</div>'
               + svg_status_strip(windows, start, end, labels=t["legend"]) + f'<div class="legend">{legend}</div>')
    if series:
        out.append(f'<div class="label">{_e(t["loss_chart"])}</div>'
                   + svg_line([(ts, l) for ts, l, _ in series], start, end, COLORS["access"], unit="%"))
        lat = [(ts, v) for ts, _, v in series if v is not None]
        out.append(f'<div class="label">{_e(t["lat_chart"])}</div>' + svg_line(lat, start, end, COLORS["dns"]))

    # ---- call quality (E-model estimate)
    calls = call_periods(store, start, end)
    if calls:
        fit_pct, bad = calls
        rows = "".join(f'<tr><td class="dt">{_dt_html(a)}</td><td class="dt">{_dt_html(b)}</td>'
                       f'<td class="num">{fmt_duration(b - a)}</td><td class="num">{m:.1f}</td></tr>' for a, b, m in bad)
        table = (f'<table><thead><tr><th class="num">{t["start"]}</th><th class="num">{t["end"]}</th>'
                 f'<th class="num">{t["duration"]}</th><th class="num">{t["calls_worst_col"]}</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>') if bad else f'<p>{_e(t["calls_all_fit"])}</p>'
        out.append(f'<h2>{_e(t["calls"])}</h2><p>{_e(t["calls_fit"].format(pct=f"{fit_pct:.1f}%"))}</p>{table}'
                   f'<p class="muted">{_e(t["calls_method"])}</p>')

    # ---- incidents
    if incidents:
        rows = []
        for idx, inc in enumerate(incidents, 1):
            caps = captures.get(inc.id, [])
            links = " ".join(f'<a href="#cap-{c.id}">{_e(t["capture"])} {_e(_dt(c.ts, False))}</a>' for c in caps)
            ev = "<br>".join(_e(localize_evidence(e, lang)) for e in compress_evidence(inc.evidence)[:3])
            ev += ruled_out_html(inc, lang)
            rows.append(
                f'<tr><td class="num">{idx}</td><td class="dt">{_dt_html(inc.opened)}</td>'
                f'<td class="dt">{_dt_html(inc.closed) if inc.closed else _e(t["ongoing"])}</td>'
                f'<td class="num">{fmt_duration(inc.duration(now))}</td>'
                f'<td class="where"><span class="dot" style="background:{COLORS[inc.code]}"></span>{_e(t["legend"][inc.code])}</td>'
                f'<td class="num">{inc.peak_loss:.1f}%</td><td class="ev">{ev}<br>{links}</td></tr>')
        out.append(f'<h2>{_e(t["incident_list"])}</h2><table class="incidents"><colgroup><col style="width:4%">'
                   f'<col style="width:12%"><col style="width:12%"><col style="width:10%"><col style="width:14%">'
                   f'<col style="width:10%"><col style="width:38%"></colgroup><thead><tr><th class="num">#</th>'
                   f'<th class="num">{t["start"]}</th><th class="num">{t["end"]}</th><th class="num">{t["duration"]}</th>'
                   f'<th>{t["where"]}</th><th class="num">{t["peak"]}</th><th>{t["evidence"]}</th></tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table>')

    # ---- tunnels
    tun_incidents = store.incidents_between(start, end, scope="tunnels")
    tun_captures = store.captures_for([i.id for i in tun_incidents])
    if tun_incidents or (net.get("tunnels")):
        out.append(tunnel_section(tun_incidents, t, now))

    # ---- your services (outages that were NOT your internet)
    svc_incidents = [i for i in store.incidents_between(start, end, scope=None) if i.scope.startswith("service:")]
    if svc_incidents:
        rows = "".join(
            f'<tr><td>{_e(i.scope.split(":", 1)[1])}</td><td class="dt">{_dt_html(i.opened)}</td>'
            f'<td class="dt">{_dt_html(i.closed) if i.closed else _e(t["ongoing"])}</td>'
            f'<td class="num">{fmt_duration(i.duration(now))}</td><td class="ev">{_e(i.evidence[0] if i.evidence else "")}</td></tr>'
            for i in svc_incidents)
        out.append(f'<h2>{_e(t["services"])}</h2><p class="muted">{_e(t["svc_intro"])}</p>'
                   f'<table class="incidents"><thead><tr><th>{t["svc_col"]}</th><th class="num">{t["start"]}</th>'
                   f'<th class="num">{t["end"]}</th><th class="num">{t["duration"]}</th><th>{t["evidence"]}</th></tr>'
                   f'</thead><tbody>{rows}</tbody></table>')

    # ---- measured speed (only if the user turned the speed test on)
    tests = [r for r in store.speedtests_between(start, end) if not r.get("error")]
    if tests:
        link = store.get_setting("link") or {}
        cd, cu = float(link.get("down_mbps") or 0), float(link.get("up_mbps") or 0)

        def pct(v, c):
            return f" ({100 * v / c:.0f}%)" if v and c else ""
        rows = "".join(
            f'<tr><td class="dt">{_dt_html(r["ts"])}</td><td class="num">{(r.get("down_mbps") or 0):.0f} Mbps{pct(r.get("down_mbps"), cd)}</td>'
            f'<td class="num">{(r.get("up_mbps") or 0):.0f} Mbps{pct(r.get("up_mbps"), cu)}</td>'
            f'<td class="num">{_e(str(round(r["loaded_ms"])) + " ms" if r.get("loaded_ms") is not None else "—")}</td>'
            f'<td>{_e(t["speed_wifi"] if r.get("wireless") else t["speed_cable"])}</td></tr>' for r in tests)
        plan = t["speed_plan"].format(down=f"{cd:.0f}", up=f"{cu:.0f}") if cd else ""
        out.append(f'<h2>{_e(t["speed"])}</h2><p class="muted">{_e(plan + t["speed_intro"])}</p>'
                   f'<table><thead><tr><th class="num">{t["start"]}</th><th class="num">{t["speed_down"]}</th>'
                   f'<th class="num">{t["speed_up"]}</th><th class="num">{t["speed_loaded"]}</th><th>{t["speed_via"]}</th></tr>'
                   f'</thead><tbody>{rows}</tbody></table>')

    # ---- backup link (failover): the main ISP was not carrying the traffic
    fo_incidents = store.incidents_between(start, end, scope="failover")
    if fo_incidents:
        total = sum(min(i.closed or now, end) - max(i.opened, start) for i in fo_incidents)
        rows = "".join(
            f'<tr><td class="dt">{_dt_html(i.opened)}</td>'
            f'<td class="dt">{_dt_html(i.closed) if i.closed else _e(t["ongoing"])}</td>'
            f'<td class="num">{fmt_duration(i.duration(now))}</td>'
            f'<td>{_e(((i.details or {}).get("backup") or {}).get("name", ""))}</td>'
            f'<td class="ev">{_e("; ".join(i.evidence[:2]))}</td></tr>'
            for i in fo_incidents)
        out.append(f'<h2>{_e(t["failover"])}</h2><p class="muted">{_e(t["fo_intro"].format(dur=fmt_duration(total)))}</p>'
                   f'<table class="incidents"><thead><tr><th class="num">{t["start"]}</th><th class="num">{t["end"]}</th>'
                   f'<th class="num">{t["duration"]}</th><th>{t["fo_col"]}</th><th>{t["evidence"]}</th></tr>'
                   f'</thead><tbody>{rows}</tbody></table>')

    # ---- message for the ISP
    out.append(f'<h2>{_e(t["message"])}</h2><p class="muted">{_e(t["message_hint"])}</p>'
               f'<pre class="message">{_e(isp_message(incidents, captures, t, start, end, now))}</pre>')

    # ---- appendix
    caps_all = [c for i in incidents for c in captures.get(i.id, [])]
    caps_all += [c for i in tun_incidents for c in tun_captures.get(i.id, [])]
    out.append(f'<h2>{_e(t["appendix"])}</h2>')
    out.append("".join(_capture_table(c, t) for c in caps_all) if caps_all
               else f'<p class="muted">{_e(t["appendix_none"])}</p>')

    # ---- methodology + footer
    out.append(f'<h2>{_e(t["method"])}</h2><ul class="method">'
               + "".join(f"<li>{_e(m)}</li>" for m in t["method_items"]) + "</ul>")
    out.append(f'<footer>{_e(t["footer"].format(v=__version__, tz=tz))}</footer></main></body></html>')
    return "".join(out)
