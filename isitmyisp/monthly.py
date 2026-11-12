"""The monthly report by email: last month's evidence report, sent on its own, with a short summary.

The owner shouldn't have to open the dashboard to know how the month went. On the chosen day and
hour, the monitor emails the previous calendar month: a plain-language summary in the body and the
evidence report attached (PDF when WeasyPrint is installed, HTML otherwise). It uses the SMTP server
already set up for alerts. What was sent is stored in the database, so a restart never sends the
same month twice; a failed send is retried on the next window and the error is shown in Settings.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from .store import Store

KEY = "monthly_report"
LAST = "_monthly_last"        # {"month": "YYYY-MM", "ts": sent at}
ERROR = "_monthly_error"      # {"ts", "error"} of the last failed attempt
DEFAULTS = {"enabled": False, "day": 1, "hour": 8, "to": ""}   # empty "to": the alert recipients
RETRY = 15 * 60               # after a failure, wait this long before trying again

MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                 "October", "November", "December"],
          "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                 "octubre", "noviembre", "diciembre"]}
T = {
    "en": {"subject": "isitmyisp · {month}: {headline}", "hello": "How your connection did in {month}.",
           "ok": "No incidents: healthy {pct} of the time measured.",
           "some": "{n} {inc}, {dur} in total. Healthy {pct} of the time measured.", "inc": ("incident", "incidents"),
           "by": {"isp": "{k} in your ISP's network", "you": "{k} on your side", "other": "{k} on other sites or DNS"},
           "open": "While the business was open: {bad} with problems out of {open} open.",
           "worst": "Worst day: {day}, {dur} with problems.",
           "calls": "Calls: fit {pct} of the time.",
           "speed": "Speed tests: median {down} / {up} Mbps ({pct} of your plan's download).",
           "backup": "On the backup link: {dur}.",
           "attached": "The full report with every incident and its evidence is attached ({kind}); you can forward it to your ISP.",
           "no_data": "There are no measurements for that month.",
           "head_ok": "no incidents", "head_some": "{n} {inc}, {dur}",
           "dash": "Dashboard: {url}/"},
    "es": {"subject": "isitmyisp · {month}: {headline}", "hello": "Así anduvo tu conexión en {month}.",
           "ok": "Sin incidentes: sana el {pct} del tiempo medido.",
           "some": "{n} {inc}, {dur} en total. Sana el {pct} del tiempo medido.", "inc": ("incidente", "incidentes"),
           "by": {"isp": "{k} en la red de tu ISP", "you": "{k} de tu lado", "other": "{k} en otros sitios o DNS"},
           "open": "Con el local abierto: {bad} con problemas, de {open} abierto.",
           "worst": "Peor día: {day}, {dur} con problemas.",
           "calls": "Llamadas: aptas el {pct} del tiempo.",
           "speed": "Tests de velocidad: mediana {down} / {up} Mbps ({pct} de la bajada contratada).",
           "backup": "En el enlace de respaldo: {dur}.",
           "attached": "Adjunto va el informe completo, con cada incidente y su evidencia ({kind}); se lo podés reenviar a tu ISP.",
           "no_data": "No hay mediciones de ese mes.",
           "head_ok": "sin incidentes", "head_some": "{n} {inc}, {dur}",
           "dash": "Panel: {url}/"},
}


class MonthlyError(ValueError):
    pass


def validate(raw: dict) -> dict:
    out = dict(DEFAULTS)
    out["enabled"] = bool(raw.get("enabled"))
    try:
        out["day"] = int(raw.get("day") or 1)
        out["hour"] = int(raw.get("hour") if raw.get("hour") not in (None, "") else 8)
    except (TypeError, ValueError) as exc:
        raise MonthlyError("day and hour must be whole numbers") from exc
    if not 1 <= out["day"] <= 28:
        raise MonthlyError("the day must be between 1 and 28 (every month has it)")
    if not 0 <= out["hour"] <= 23:
        raise MonthlyError("the hour must be between 0 and 23")
    to = ", ".join(r.strip() for r in str(raw.get("to") or "").split(",") if r.strip())
    from .alerts import EMAIL_RE
    if to and not all(EMAIL_RE.match(r) for r in to.split(", ")):
        raise MonthlyError("recipients must be email addresses separated by commas")
    out["to"] = to
    return out


def load(store: Store) -> dict:
    return {**DEFAULTS, **(store.get_setting(KEY) or {})}


def save(store: Store, raw: dict) -> dict:
    cfg = validate(raw)
    store.set_settings({KEY: cfg}, bump=False)
    return cfg


# ------------------------------------------------------------------ the month

def previous_month(now: float) -> tuple[float, float, str]:
    """(start, end, "YYYY-MM") of the calendar month before `now`, local time."""
    d = datetime.fromtimestamp(now)
    first_this = d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    y, m = (first_this.year, first_this.month - 1) if first_this.month > 1 else (first_this.year - 1, 12)
    first_prev = first_this.replace(year=y, month=m)
    return first_prev.timestamp(), first_this.timestamp(), f"{y:04d}-{m:02d}"


def due(cfg: dict, now: float, store: Store) -> str | None:
    """The month ("YYYY-MM") whose report should go out now, or None."""
    if not cfg.get("enabled"):
        return None
    d = datetime.fromtimestamp(now)
    send_at = d.replace(day=cfg["day"], hour=cfg["hour"], minute=0, second=0, microsecond=0)
    if d < send_at:
        return None
    month = previous_month(now)[2]
    if (store.get_setting(LAST) or {}).get("month") == month:
        return None
    err = store.get_setting(ERROR) or {}
    if err.get("month") == month and now - err.get("ts", 0) < RETRY:
        return None
    return month


def union(incidents, start: float, end: float) -> list[tuple[float, float]]:
    """The stretches with at least one problem, clipped to [start, end]: overlapping incidents count once."""
    spans = sorted((max(i.opened, start), min(i.closed or end, end)) for i in incidents)
    out: list[list[float]] = []
    for a, b in spans:
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def month_name(month: str, lang: str) -> str:
    y, m = month.split("-")
    return f"{MONTHS[lang][int(m) - 1]} {y}"


def summary(store: Store, start: float, end: float, lang: str, public_url: str = "") -> tuple[str, str, str]:
    """(subject, plain-text body, month label) for the period, in plain language."""
    from . import hours as hours_mod
    from .report import fmt_duration
    # whose side (same grouping as the dashboard; the core can't import the web extra)
    group = lambda code: "isp" if code in ("access", "isp") else ("you" if code in ("local", "saturation") else "other")  # noqa: E731
    t = T[lang]
    month = month_name(datetime.fromtimestamp(start).strftime("%Y-%m"), lang)
    windows = store.windows_between(start, end)
    lines = [t["hello"].format(month=month), ""]
    if not windows:
        lines.append(t["no_data"])
        return t["subject"].format(month=month, headline=t["no_data"].rstrip(".").lower()), "\n".join(lines), month
    # count only the stretch that was actually measured (a probe installed mid-month)
    start, end = max(start, windows[0][0] - windows[0][1]), min(end, windows[-1][0])
    measured = sum(w[1] for w in windows if w[2] != "speedtest")
    healthy = sum(w[1] for w in windows if w[2] == "ok")
    pct = f"{100 * healthy / measured:.1f}%" if measured else "—"
    incs = store.incidents_between(start, end)
    bad = union(incs, start, end)            # every minute with a problem counts once
    total = sum(b - a for a, b in bad)
    if not incs:
        lines.append(t["ok"].format(pct=pct))
        head = t["head_ok"]
    else:
        inc = t["inc"][0 if len(incs) == 1 else 1]
        lines.append(t["some"].format(n=len(incs), inc=inc, dur=fmt_duration(total), pct=pct))
        by: dict[str, int] = {}
        for i in incs:
            g = group(i.code)
            by[g] = by.get(g, 0) + 1
        parts = [t["by"][g].format(k=by[g]) for g in ("isp", "you", "other") if by.get(g)]
        if parts:
            lines.append("  " + ", ".join(parts) + ".")
        head = t["head_some"].format(n=len(incs), inc=inc, dur=fmt_duration(total))
        # the worst day: the one with the most time with problems
        per_day: dict[str, float] = {}
        for a, b in bad:
            while a < b:
                day_end = datetime.fromtimestamp(a).replace(hour=23, minute=59, second=59).timestamp() + 1
                per_day[datetime.fromtimestamp(a).strftime("%Y-%m-%d")] = per_day.get(
                    datetime.fromtimestamp(a).strftime("%Y-%m-%d"), 0) + min(b, day_end) - a
                a = day_end
        if per_day:
            day, secs = max(per_day.items(), key=lambda kv: kv[1])
            lines.append(t["worst"].format(day=day, dur=fmt_duration(secs)))
    bh = hours_mod.load(store)
    if hours_mod.active(bh):
        open_s = hours_mod.open_seconds(bh, start, end)
        bad_open = sum(hours_mod.in_hours(bh, a, b) for a, b in bad)
        lines.append(t["open"].format(bad=fmt_duration(bad_open), open=fmt_duration(open_s)))
    backup = sum(b - a for a, b in union(store.incidents_between(start, end, scope="failover"), start, end))
    if backup >= 60:
        lines.append(t["backup"].format(dur=fmt_duration(backup)))
    from .report import call_periods
    calls = call_periods(store, start, end)
    if calls:
        lines.append(t["calls"].format(pct=f"{calls[0]:.1f}%"))
    tests = [r for r in store.speedtests_between(start, end) if not r.get("error") and r.get("down_mbps")]
    if tests:
        import statistics
        down = statistics.median(r["down_mbps"] for r in tests)
        up = statistics.median(r.get("up_mbps") or 0 for r in tests)
        plan = float((store.get_setting("link") or {}).get("down_mbps") or 0)
        lines.append(t["speed"].format(down=f"{down:.0f}", up=f"{up:.0f}",
                                       pct=f"{100 * down / plan:.0f}%" if plan else "—"))
    if public_url:
        lines += ["", t["dash"].format(url=public_url)]
    return t["subject"].format(month=month, headline=head), "\n".join(lines), month


def build(store: Store, start: float, end: float, lang: str, public_url: str = "") -> tuple[str, str, list]:
    """(subject, body, attachments): the evidence report as PDF when possible, HTML otherwise."""
    from .report import build_report
    subject, body, month = summary(store, start, end, lang, public_url)
    html = build_report(store, start, end, lang=lang)
    stem = f"isitmyisp-{datetime.fromtimestamp(start).strftime('%Y-%m')}"
    try:
        from .pdf import html_to_pdf
        att = [(f"{stem}.pdf", "application", "pdf", html_to_pdf(html))]
        kind = "PDF"
    except Exception:                                   # WeasyPrint missing or failing: send the HTML
        att = [(f"{stem}.html", "text", "html", html.encode("utf-8"))]
        kind = "HTML"
    body += "\n\n" + T[lang]["attached"].format(kind=kind)
    return subject, body, att


def recipients(cfg: dict, email_cfg: dict) -> str:
    return cfg.get("to") or email_cfg.get("to", "")


def send(store: Store, cfg: dict, lang: str, now: float | None = None, mark: bool = True) -> str:
    """Email last month's report now. Returns the month sent; raises MonthlyError with a clear reason."""
    from . import alerts as alerts_mod
    now = now or time.time()
    acfg = alerts_mod.load(store)
    em = acfg["email"]
    if not (em.get("host") and em.get("sender")):
        raise MonthlyError("set up the email server first (Settings, Alerts, Email)")
    to = recipients(cfg, em)
    if not to:
        raise MonthlyError("no recipients: add them here or in the alert email settings")
    start, end, month = previous_month(now)
    subject, body, att = build(store, start, end, lang, acfg.get("public_url", ""))
    try:
        alerts_mod.send_email({**em, "to": to}, subject, body, attachments=att)
    except alerts_mod.AlertError as exc:
        store.set_settings({ERROR: {"ts": now, "month": month, "error": str(exc)}}, bump=False)
        raise MonthlyError(str(exc)) from None
    if mark:
        store.set_settings({LAST: {"month": month, "ts": now}, ERROR: None}, bump=False)
    return month


class Reporter:
    """Called after every monitor window, like the alerts: sends the month's report once, when due."""

    def __init__(self, store: Store, lang_getter):
        self.store = store
        self.lang_getter = lang_getter
        self._busy = threading.Lock()

    def tick(self, now: float | None = None, background: bool = True) -> None:
        now = now or time.time()
        cfg = load(self.store)
        if not due(cfg, now, self.store) or not self._busy.acquire(blocking=False):
            return

        def job():
            try:
                send(self.store, cfg, self.lang_getter(), now)
            except MonthlyError:
                pass                                    # recorded in ERROR, shown in Settings, retried later
            finally:
                self._busy.release()
        if background:
            threading.Thread(target=job, daemon=True).start()
        else:
            job()
