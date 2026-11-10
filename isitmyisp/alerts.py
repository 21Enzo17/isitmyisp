"""Alerts: Telegram, email (SMTP) and webhooks (generic JSON, Discord, Slack). Standard library only.

Reliability rules:
  * an incident alerts once when it opens (after it has lasted `min_minutes`) and once when it closes;
  * the "already alerted" state lives in the database, so restarts never duplicate alerts;
  * incidents shorter than the threshold never alert at all (no "opened/closed" noise);
  * sending never blocks or crashes the monitor (background thread, timeouts, errors recorded).
"""

from __future__ import annotations

import json
import re
import smtplib
import ssl
import threading
import time
import urllib.request
from email.message import EmailMessage
from urllib.parse import urlparse

from . import __version__
from .store import Incident, Store
from .texts import ADVICE, VERDICT

DEFAULTS = {
    "min_minutes": 2,
    "notify_close": True,
    "public_url": "",
    "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    "email": {"enabled": False, "host": "", "port": 587, "security": "starttls", "username": "", "password": "",
              "sender": "", "to": ""},
    "webhook": {"enabled": False, "url": ""},
}
SECRET_FIELDS = {("telegram", "bot_token"), ("email", "password")}
TIMEOUT = 15

T = {
    "en": {"opened": "🔴 {what}", "closed": "✅ Resolved: {what}", "test": "isitmyisp test alert",
           "test_body": "If you can read this, alerts work.", "scope_tunnel": "Tunnel {name}",
           "scope_service": "Service {name}", "scope_internet": "Internet", "since": "Since", "lasted": "Lasted",
           "evidence": "Evidence", "todo": "What to do", "open_dash": "Dashboard"},
    "es": {"opened": "🔴 {what}", "closed": "✅ Resuelto: {what}", "test": "isitmyisp: alerta de prueba",
           "test_body": "Si leés esto, las alertas funcionan.", "scope_tunnel": "Túnel {name}",
           "scope_service": "Servicio {name}", "scope_internet": "Internet", "since": "Desde", "lasted": "Duró",
           "evidence": "Evidencia", "todo": "Qué hacer", "open_dash": "Panel"},
}


class AlertError(RuntimeError):
    pass


# ------------------------------------------------------------------ settings

def load(store: Store) -> dict:
    cfg = store.get_setting("alerts") or {}
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def masked(cfg: dict) -> dict:
    """Copy safe to render: secrets replaced by a hint of whether they are set."""
    view = json.loads(json.dumps(cfg))
    for section, field in SECRET_FIELDS:
        value = view[section].get(field) or ""
        view[section][field] = ""
        view[section][field + "_set"] = bool(value)
    return view


EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


def validate(form: dict, current: dict) -> dict:
    """Validate the settings form; empty secret fields keep the stored secret."""
    new = json.loads(json.dumps(current))
    try:
        new["min_minutes"] = int(form.get("min_minutes", current["min_minutes"]))
    except (TypeError, ValueError) as exc:
        raise AlertError("minutes must be a whole number") from exc
    if not 0 <= new["min_minutes"] <= 240:
        raise AlertError("minutes must be between 0 and 240")
    new["notify_close"] = bool(form.get("notify_close"))
    url = (form.get("public_url") or "").strip()
    if url and urlparse(url).scheme not in ("http", "https"):
        raise AlertError("public URL must start with http:// or https://")
    new["public_url"] = url.rstrip("/")

    tg = new["telegram"]
    tg["enabled"] = bool(form.get("telegram_enabled"))
    if form.get("telegram_bot_token"):
        tg["bot_token"] = form["telegram_bot_token"].strip()
    tg["chat_id"] = (form.get("telegram_chat_id") or "").strip()
    if tg["enabled"]:
        if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", tg["bot_token"] or ""):
            raise AlertError("Telegram bot token looks wrong (it's like 123456789:AA...)")
        if not re.fullmatch(r"-?\d+|@[A-Za-z0-9_]{5,}", tg["chat_id"]):
            raise AlertError("Telegram chat id must be a number (e.g. 123456789 or -100...) or @channel")

    em = new["email"]
    em["enabled"] = bool(form.get("email_enabled"))
    for f in ("host", "username", "sender", "to"):
        em[f] = (form.get(f"email_{f}") or "").strip()
    if form.get("email_password"):
        em["password"] = form["email_password"]
    em["security"] = form.get("email_security", "starttls")
    if em["security"] not in ("starttls", "ssl", "none"):
        raise AlertError("email security must be starttls, ssl or none")
    try:
        em["port"] = int(form.get("email_port") or 587)
    except ValueError as exc:
        raise AlertError("SMTP port must be a number") from exc
    if em["enabled"]:
        if not em["host"]:
            raise AlertError("SMTP server is required")
        if not EMAIL_RE.match(em["sender"]):
            raise AlertError("sender must be an email address")
        recipients = [r.strip() for r in em["to"].split(",") if r.strip()]
        if not recipients or not all(EMAIL_RE.match(r) for r in recipients):
            raise AlertError("recipients must be email addresses separated by commas")

    wh = new["webhook"]
    wh["enabled"] = bool(form.get("webhook_enabled"))
    wh["url"] = (form.get("webhook_url") or "").strip()
    if wh["enabled"] and urlparse(wh["url"]).scheme not in ("http", "https"):
        raise AlertError("webhook URL must start with http:// or https://")
    return new


def save(store: Store, cfg: dict) -> None:
    store.set_settings({"alerts": cfg}, bump=False)  # alerts don't need the probes to restart


# ------------------------------------------------------------------ messages

def _fmt_duration(seconds: float) -> str:
    from .report import fmt_duration
    return fmt_duration(seconds)


def describe(inc: Incident, kind: str, lang: str, public_url: str = "", now: float | None = None) -> tuple[str, str]:
    """(title, body) in plain language: what happened, where, evidence, what to do."""
    now = now or time.time()
    t, verdict, advice = T[lang], VERDICT[lang], ADVICE[lang]
    if inc.scope.startswith("tunnel:"):
        where = t["scope_tunnel"].format(name=inc.scope.split(":", 1)[1])
    elif inc.scope.startswith("service:"):
        where = t["scope_service"].format(name=inc.scope.split(":", 1)[1])
    else:
        where = t["scope_internet"]
    what = f"{where} · {verdict.get(inc.code, inc.code)}"
    title = t["opened" if kind == "opened" else "closed"].format(what=what)
    lines = []
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(inc.opened))
    if kind == "opened":
        lines.append(f"{t['since']}: {when}")
        if inc.evidence:
            lines.append(f"{t['evidence']}: " + "; ".join(inc.evidence[:3]))
        if inc.code in advice:
            lines.append(f"{t['todo']}: {advice[inc.code]}")
    else:
        lines.append(f"{t['lasted']}: {_fmt_duration(inc.duration(now))} ({when})")
    if public_url:
        lines.append(f"{t['open_dash']}: {public_url}/")
    return title, "\n".join(lines)


# ------------------------------------------------------------------ channels

def send_telegram(cfg: dict, title: str, body: str) -> None:
    data = json.dumps({"chat_id": cfg["chat_id"], "text": f"{title}\n\n{body}",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage", data=data,
                                 headers={"Content-Type": "application/json", "User-Agent": f"isitmyisp/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise AlertError(f"Telegram answered {resp.status}")
    except urllib.error.HTTPError as exc:  # don't echo the URL: it contains the bot token
        raise AlertError(f"Telegram answered {exc.code}: check the bot token and chat id") from None
    except OSError as exc:
        raise AlertError(f"Telegram unreachable: {type(exc).__name__}") from None


def send_email(cfg: dict, title: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(r.strip() for r in cfg["to"].split(",") if r.strip())
    msg.set_content(body + "\n\n-- isitmyisp")
    try:
        if cfg["security"] == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=TIMEOUT,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=TIMEOUT)
        with server:
            if cfg["security"] == "starttls":
                server.starttls(context=ssl.create_default_context())
            if cfg.get("username"):
                server.login(cfg["username"], cfg.get("password", ""))
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise AlertError(f"email failed: {type(exc).__name__}: {exc}") from None


def webhook_payload(url: str, title: str, body: str, extra: dict) -> dict:
    host = urlparse(url).hostname or ""
    text = f"{title}\n{body}"
    if host.endswith("discord.com") or host.endswith("discordapp.com"):
        return {"content": text[:1900]}
    if host.endswith("hooks.slack.com"):
        return {"text": text}
    return {"title": title, "message": body, **extra}


def send_webhook(cfg: dict, title: str, body: str, extra: dict) -> None:
    data = json.dumps(webhook_payload(cfg["url"], title, body, extra)).encode()
    req = urllib.request.Request(cfg["url"], data=data, headers={"Content-Type": "application/json",
                                                                 "User-Agent": f"isitmyisp/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status >= 300:
                raise AlertError(f"webhook answered {resp.status}")
    except urllib.error.HTTPError as exc:
        raise AlertError(f"webhook answered {exc.code}") from None
    except OSError as exc:
        raise AlertError(f"webhook unreachable: {type(exc).__name__}") from None


def send_all(cfg: dict, title: str, body: str, extra: dict | None = None) -> dict[str, str]:
    """Send through every enabled channel. Returns {channel: 'ok' | error message}."""
    results: dict[str, str] = {}
    channels = [("telegram", lambda: send_telegram(cfg["telegram"], title, body)),
                ("email", lambda: send_email(cfg["email"], title, body)),
                ("webhook", lambda: send_webhook(cfg["webhook"], title, body, extra or {}))]
    for name, fn in channels:
        if not cfg[name].get("enabled"):
            continue
        try:
            fn()
            results[name] = "ok"
        except AlertError as exc:
            results[name] = str(exc)
    return results


# ------------------------------------------------------------------ dispatcher

class Alerter:
    """Called after every monitor window: decides what to send, sends it in the background."""

    def __init__(self, store: Store, lang_getter, sender=send_all):
        self.store = store
        self.lang_getter = lang_getter
        self.sender = sender
        self._busy = threading.Lock()

    def tick(self, now: float | None = None, background: bool = True) -> None:
        cfg = load(self.store)
        if not any(cfg[c]["enabled"] for c in ("telegram", "email", "webhook")):
            return
        if not self._busy.acquire(blocking=False):  # previous batch still sending
            return
        job = lambda: self._run(cfg, now or time.time())  # noqa: E731
        if background:
            threading.Thread(target=self._guarded, args=(job,), daemon=True).start()
        else:
            self._guarded(job)

    def _guarded(self, job) -> None:
        try:
            job()
        finally:
            self._busy.release()

    def _run(self, cfg: dict, now: float) -> None:
        lang = self.lang_getter()
        self.store.skip_close_alerts_for_unalerted()
        opened, closed = self.store.incidents_to_alert()
        for inc in opened:
            if now - inc.opened < cfg["min_minutes"] * 60:
                continue
            self._send(cfg, inc, "opened", lang, now)
        for inc in closed:
            if cfg["notify_close"]:
                self._send(cfg, inc, "closed", lang, now)
            else:
                self.store.mark_alerted(inc.id, "closed")

    def _send(self, cfg: dict, inc: Incident, kind: str, lang: str, now: float) -> None:
        title, body = describe(inc, kind, lang, cfg.get("public_url", ""), now)
        extra = {"event": f"incident_{kind}", "scope": inc.scope, "code": inc.code, "opened": inc.opened,
                 "closed": inc.closed, "evidence": inc.evidence}
        results = self.sender(cfg, title, body, extra)
        if any(r == "ok" for r in results.values()):
            self.store.mark_alerted(inc.id, kind)
        errors = {k: v for k, v in results.items() if v != "ok"}
        self.store.set_settings({"_alerts_last": {"ts": now, "errors": errors}}, bump=False)
