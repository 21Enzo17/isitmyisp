"""Web UI: dashboard, incidents, tunnels, reports and settings, behind real authentication.

Flask + Flask-Login (sessions) + Flask-WTF (CSRF) + argon2-cffi (password hashes) +
Flask-Limiter (login rate limit), served by Waitress. No JavaScript: plain HTML forms.
"""

from __future__ import annotations

import hmac
import mimetypes
import secrets
import threading
import time
from datetime import timedelta

mimetypes.add_type("font/woff2", ".woff2")  # slim images ship without it
mimetypes.add_type("application/manifest+json", ".webmanifest")
from pathlib import Path
from urllib.parse import urlparse

from flask import (Flask, Response, abort, flash, g, make_response, redirect, render_template, request,
                   send_from_directory, session, url_for)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user, login_user, logout_user
from flask_wtf.csrf import CSRFError, CSRFProtect

from .. import __version__
from .. import settings as settings_mod
from ..report import R as REPORT_STRINGS, build_report
from ..store import Store
from ..timeutil import parse_when
from . import auth, charts, views
from ..api import metrics_text, status_json
from .strings import S

PUBLIC_ENDPOINTS = {"static", "healthz", "favicon", "tv"}   # tv checks its own token
AUTH_ENDPOINTS = {"login", "setup", "invite"}
VIEWER_WRITES = {"logout", "settings_password"}   # the only POSTs a read-only user may make
INVITE_TTL = 48 * 3600


ASN_JOB: dict = {"running": False, "error": None, "lock": threading.Lock()}


def create_app(store: Store, *, data_dir: Path | None = None, toml_path: str | None = None,
               bind: str = "127.0.0.1:8080", secure_cookies: bool = False, default_lang: str = "en",
               demo: bool = False) -> Flask:
    """`demo` (only from `isitmyisp demo`, never from data in the database): no login, everything
    read-only, every POST refused, and a banner on every page."""
    app = Flask(__name__)
    host = bind.rpartition(":")[0] or "127.0.0.1"
    app.config.update(
        SECRET_KEY=settings_mod.secret_key(store),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=secure_cookies,
        SESSION_COOKIE_NAME="isitmyisp_session",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SECURE=secure_cookies,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        WTF_CSRF_TIME_LIMIT=8 * 3600,
        MAX_CONTENT_LENGTH=64 * 1024,
        BIND=bind,
        DEMO=demo,
        LOOPBACK=auth.is_loopback(host),
    )
    CSRFProtect(app)
    limiter = Limiter(get_remote_address, app=app, storage_uri="memory://", default_limits=[])
    login_manager = LoginManager(app)
    login_manager.login_view = "login"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def _load(uid: str):
        return auth.load_local_user(store, uid)

    def current_settings() -> settings_mod.Settings:
        return settings_mod.load(store, toml_path, data_dir, default_lang=default_lang)

    # ---------------------------------------------------------------- gate

    @app.before_request
    def gate():
        g.settings = current_settings()
        lang = request.args.get("lang") or request.cookies.get("isitmyisp_lang")
        g.lang = lang if lang in S else g.settings.lang
        g.t = S[g.lang]
        g.readonly = False
        g.user = None
        if request.method == "POST":  # defence in depth on top of the CSRF token
            origin = request.headers.get("Origin")
            if origin and origin != "null" and urlparse(origin).netloc != request.host:
                abort(403)
        endpoint = request.endpoint or ""
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if app.config["DEMO"]:
            if request.method not in ("GET", "HEAD"):
                abort(403)
            g.user, g.readonly = auth.User("demo", "demo", "demo"), True
            return None
        if endpoint == "metrics" and auth.bearer_matches(request.headers.get("Authorization"),
                                                          settings_mod.metrics_token(store)):
            return None
        mode = g.settings.auth_mode
        if mode == "none":
            if not app.config["LOOPBACK"]:
                return render_template("message.html", message=g.t["none_denied"]), 403
            g.user, g.readonly = auth.User("none", "local", "none"), True
            return None
        if mode == "proxy":
            g.user = auth.proxy_user(request.remote_addr, request.headers, g.settings.proxy_header,
                                     g.settings.trusted_proxies)
            if g.user is None:
                return render_template("message.html", message=g.t["proxy_denied"]), 403
            return None
        # local accounts
        if store.user_count() == 0:
            return None if endpoint == "setup" else redirect(url_for("setup"))
        if endpoint in AUTH_ENDPOINTS:
            return None
        if not current_user.is_authenticated:
            if endpoint in ("metrics", "api_status"):
                return Response("authentication required\n", 401, {"WWW-Authenticate": 'Bearer realm="isitmyisp"'})
            return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
        g.user = current_user
        if not current_user.is_admin:
            # Enforced here, for every route, not only where a route remembers to check.
            g.readonly = True
            if request.method not in ("GET", "HEAD") and endpoint not in VIEWER_WRITES:
                abort(403)
        return None

    @app.after_request
    def security_headers(resp: Response) -> Response:
        # Reports are standalone documents with an inline <style>; everything else uses /static.
        style = "'self' 'unsafe-inline'" if request.endpoint in ("report",) else "'self'"
        resp.headers.setdefault("Content-Security-Policy",
                                f"default-src 'none'; style-src {style}; img-src 'self' data:; font-src 'self'; manifest-src 'self'; "
                                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        # URLs with a secret in them (TV, invitations) must not leak through the Referer header
        resp.headers["Referrer-Policy"] = "no-referrer" if request.endpoint in ("tv", "invite") else "same-origin"
        if request.endpoint not in PUBLIC_ENDPOINTS:
            resp.headers["Cache-Control"] = "no-store"
        if request.args.get("lang") in S:  # remember the language picked in the UI
            resp.set_cookie("isitmyisp_lang", request.args["lang"], max_age=365 * 86400, samesite="Lax",
                            httponly=True, secure=secure_cookies)
        return resp

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return render_template("message.html", message=str(e.description)), 400

    @app.template_filter("dt")
    def _dt_filter(ts):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""

    @app.template_filter("tm")
    def _tm_filter(ts):
        return time.strftime("%H:%M", time.localtime(ts)) if ts else ""

    @app.template_filter("ev")
    def _ev_filter(line):
        from ..report import localize_evidence
        return localize_evidence(str(line), g.get("lang", "en"))

    @app.template_filter("linktext")
    def _linktext_filter(link):
        from ..report import describe_link
        return describe_link(link)

    from ..mos import band_of
    app.jinja_env.globals["band_of"] = band_of

    @app.template_filter("size")
    def _size(n) -> str:
        n = float(n or 0)
        return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"

    @app.template_filter("group")
    def _group(code: str) -> str:
        return charts.GROUP.get(code, "none")

    @app.template_filter("css")
    def _css_filter(code):
        return views.CAUSE_CLASS.get(code, "muted")

    @app.template_filter("cause")
    def _cause_filter(code):
        t = g.get("t", S["en"])
        if code in t["verdict"]:
            return t["verdict"][code]
        return REPORT_STRINGS.get(g.get("lang", "en"), REPORT_STRINGS["en"])["tun_cause"].get(code, code)

    @app.context_processor
    def inject():
        return {"t": g.get("t", S["en"]), "lang": g.get("lang", "en"), "user": g.get("user"),
                "readonly": g.get("readonly", False), "version": __version__, "demo": app.config["DEMO"],
                "demo_static": app.config.get("DEMO_STATIC"),
                "auth_mode": g.settings.auth_mode if g.get("settings") else "local"}

    # ---------------------------------------------------------------- pages

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html", active="dashboard",
                               d=views.dashboard_data(store, g.settings))

    @app.get("/incidents")
    def incidents():
        return render_template("incidents.html", active="incidents", rows=views.incident_rows(store, g.t))

    @app.get("/tunnels")
    def tunnels():
        return render_template("tunnels.html", active="tunnels", tunnels=views.tunnel_cards(store, g.settings))

    @app.get("/reports")
    def reports():
        return render_template("reports.html", active="reports")

    def _period() -> tuple[float, float]:
        now = time.time()
        try:
            start = parse_when(request.args.get("since") or "7d")
            end = parse_when(request.args["until"]) if request.args.get("until") else now
        except ValueError:
            abort(400)
        return start, end

    @app.get("/report")
    def report():
        start, end = _period()
        return Response(build_report(store, start, end, lang=g.lang), mimetype="text/html")

    @app.get("/report.pdf")
    def report_pdf():
        from ..pdf import PdfUnavailable, html_to_pdf
        start, end = _period()
        try:
            data = html_to_pdf(build_report(store, start, end, lang=g.lang))
        except PdfUnavailable as exc:
            return Response(str(exc), 501, mimetype="text/plain")
        name = f"isitmyisp-report-{time.strftime('%Y%m%d')}.pdf"
        return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})

    # ---------------------------------------------------------------- settings

    def _presets_view():
        from .. import presets
        have = {sv.target for sv in g.settings.services} | {sv.name for sv in g.settings.services}
        return [(group, [(p, p.target in have or p.name in have) for p in items]) for group, items in presets.grouped("ar")]

    def _settings_page(error: str | None = None, status: int = 200, results: dict | None = None,
                       ifaces: list | None = None, invite: dict | None = None):
        from .. import alerts as alerts_mod
        token = settings_mod.metrics_token(store) if not g.readonly else None
        is_admin = (not g.readonly and g.settings.auth_mode == "local"
                    and bool(g.user and getattr(g.user, "is_admin", False)))
        return render_template("settings.html", active="settings", s=g.settings, error=error,
                               metrics_token=token, bind=app.config["BIND"],
                               alerts=alerts_mod.masked(alerts_mod.load(store)),
                               alerts_last=store.get_setting("_alerts_last"), test_results=results,
                               ifaces=ifaces, isp=views.isp_status(store, data_dir, ASN_JOB),
                               speed=views.speed_status(store, g.settings), invite=invite,
                               presets=_presets_view(),
                               users=store.list_users() if is_admin else [],
                               invites=store.pending_invites() if is_admin else [],
                               tv_url=(url_for("tv", token=store.get_setting("tv_token"), _external=True)
                                       if is_admin and store.get_setting("tv_token") else None)), status

    @app.get("/settings")
    def settings_page():
        return _settings_page()

    def _guard_write():
        if g.readonly:
            abort(403)

    def _save(values: dict):
        try:
            settings_mod.save(store, values)
        except settings_mod.SettingsError as exc:
            g.settings = current_settings()
            return _settings_page(str(exc), 400)
        flash(g.t["saved"])
        return redirect(url_for("settings_page"))

    @app.post("/settings/general")
    def settings_general():
        _guard_write()
        f = request.form
        return _save({"anchors": f.get("anchors", "").split(), "interval": f.get("interval"),
                      "window": f.get("window"), "lang": f.get("lang"), "voip_target": f.get("voip_target", "")})

    @app.post("/settings/tunnels/add")
    def tunnel_add():
        _guard_write()
        if g.settings.tunnels_from_file:
            abort(403)
        f = request.form
        current = [t.__dict__ for t in g.settings.tunnels]
        current.append({"name": f.get("name", "").strip(), "underlay": f.get("underlay", "").strip(),
                        "overlay": f.get("overlay", "").strip(), "type": f.get("type", "other")})
        return _save({"tunnels": current})

    @app.post("/settings/tunnels/delete")
    def tunnel_delete():
        _guard_write()
        if g.settings.tunnels_from_file:
            abort(403)
        name = request.form.get("name")
        return _save({"tunnels": [t.__dict__ for t in g.settings.tunnels if t.name != name]})

    @app.post("/settings/services/add")
    def service_add():
        _guard_write()
        f = request.form
        current = [sv.__dict__ for sv in g.settings.services]
        current.append({"name": f.get("name", "").strip(), "kind": f.get("kind", "http"),
                        "target": f.get("target", "").strip()})
        return _save({"services": current})

    @app.post("/settings/services/presets")
    def service_presets():
        """Add the ticked ready-made services (skipping the ones already there, by name or target)."""
        _guard_write()
        from .. import presets
        chosen = set(request.form.getlist("preset"))
        current = [sv.__dict__ for sv in g.settings.services]
        have = {(sv["name"]) for sv in current} | {sv["target"] for sv in current}
        for p in presets.load("ar"):
            if p.id in chosen and p.name not in have and p.target not in have:
                current.append({"name": p.name, "kind": p.kind, "target": p.target})
        return _save({"services": current})

    @app.post("/settings/services/delete")
    def service_delete():
        _guard_write()
        name = request.form.get("name")
        return _save({"services": [sv.__dict__ for sv in g.settings.services if sv.name != name]})

    @app.post("/settings/link")
    def settings_link():
        _guard_write()
        f = request.form
        values = {"enabled": bool(f.get("enabled")), "host": f.get("host", "").strip(),
                  # an empty community field keeps the stored one (it's a credential: never rendered back)
                  "community": f.get("community", "").strip() or g.settings.link.get("community", ""),
                  "port": f.get("port") or 161, "interface": f.get("interface", "").strip(),
                  "down_mbps": f.get("down_mbps") or 0, "up_mbps": f.get("up_mbps") or 0}
        if f.get("action") != "test":
            return _save({"link": values})
        # "List interfaces": read-only probe of the router, nothing is saved
        from ..snmp import SnmpClient, SnmpError, interfaces
        try:
            client = SnmpClient(values["host"], values["community"], int(values["port"]), timeout=2, retries=1)
            found = [name for _, name in interfaces(client)]
        except (SnmpError, ValueError, OSError) as exc:
            return _settings_page(f"{g.t['link_err']}: {exc}", 400)
        g.settings.link = {**g.settings.link, **{k: v for k, v in values.items() if k != "community"}}
        return _settings_page(ifaces=found)

    @app.post("/settings/speedtest")
    def settings_speedtest():
        """The speed test fills the link and uses data: it can only be turned on with the risks accepted."""
        _guard_write()
        f = request.form
        raw = {"enabled": bool(f.get("enabled")), "accepted": bool(f.get("accepted")),
               "schedule": f.get("schedule", "weekly"), "weekday": f.get("weekday", 6), "hour": f.get("hour", 3),
               "budget_gb": f.get("budget_gb", 5), "max_busy_pct": f.get("max_busy_pct", 30),
               "run_on_backup": bool(f.get("run_on_backup"))}
        return _save({"speedtest": raw, "_speed_current": g.settings.speedtest})

    @app.post("/speedtest/run")
    def speedtest_run():
        """'Test now': the monitor picks it up within one window (the web UI may be another process)."""
        _guard_write()
        if not request.form.get("confirm"):
            return _settings_page(g.t["speed_confirm_needed"], 400)
        if not (g.settings.speedtest.get("enabled") and g.settings.speedtest.get("accepted")):
            abort(403)
        store.set_settings({"_speed_request": time.time()}, bump=False)
        flash(g.t["speed_requested"])
        return redirect(request.form.get("back") == "dashboard" and url_for("dashboard") or url_for("settings_page") + "#speed")

    # ---------------------------------------------------------------- users (local accounts only)

    def _guard_admin():
        _guard_write()
        if g.settings.auth_mode != "local" or not (g.user and getattr(g.user, "is_admin", False)):
            abort(403)

    def _make_invite(username: str, role: str, user_id: int | None) -> dict:
        token = secrets.token_urlsafe(24)
        store.add_invite(auth.token_hash(token), username, role, time.time() + INVITE_TTL, user_id)
        return {"username": username, "url": url_for("invite", token=token, _external=True), "reset": user_id is not None}

    @app.post("/settings/users/invite")
    def users_invite():
        _guard_admin()
        name, role = request.form.get("username", "").strip(), request.form.get("role", "viewer")
        if role not in auth.ROLES:
            abort(400)
        if auth.username_problem(name):
            return _settings_page(g.t["users_bad_name"], 400)
        if store.get_user(username=name):
            return _settings_page(g.t["users_exists"].format(name=name), 400)
        return _settings_page(invite=_make_invite(name, role, None))

    @app.post("/settings/users/<int:uid>")
    def users_update(uid: int):
        _guard_admin()
        info = store.user_info(uid)
        if info is None:
            abort(404)
        action, me = request.form.get("action"), str(uid) == str(g.user.id)
        last_admin = info["role"] == "admin" and not info["disabled"] and store.active_admins() <= 1
        if action == "reset":
            return _settings_page(invite=_make_invite(info["username"], info["role"], uid))
        if action in ("disable", "enable"):
            if me:
                return _settings_page(g.t["users_not_self"], 400)
            if action == "disable" and last_admin:
                return _settings_page(g.t["users_last_admin"], 400)
            store.set_user(uid, disabled=action == "disable")
        elif action in auth.ROLES:
            if action == "viewer" and (me or last_admin):
                return _settings_page(g.t["users_not_self"] if me else g.t["users_last_admin"], 400)
            store.set_user(uid, role=action)
        else:
            abort(400)
        flash(g.t["saved"])
        return redirect(url_for("settings_page") + "#users")

    @app.route("/invite/<token>", methods=["GET", "POST"])
    @limiter.limit("10 per minute", methods=["POST"])
    def invite(token: str):
        """One-time link: a new account sets its password, or an existing one sets a new password."""
        if g.settings.auth_mode != "local":
            abort(404)
        th = auth.token_hash(token)
        inv = store.get_invite(th)
        if inv is None:
            return render_template("message.html", message=g.t["invite_invalid"]), 404
        error = None
        if request.method == "POST":
            f = request.form
            problem = auth.password_problem(f.get("password", ""), f.get("confirm", ""))
            if problem:
                error = g.t["pw_" + problem]
            elif inv["user_id"] is not None:
                store.set_password_hash(inv["user_id"], auth.hash_password(f["password"]))
                uid = inv["user_id"]
            elif store.get_user(username=inv["username"]):
                error = g.t["users_exists"].format(name=inv["username"])
            else:
                uid = store.add_user(inv["username"], auth.hash_password(f["password"]), role=inv["role"])
            if error is None:
                store.delete_invite(th)
                user = auth.load_local_user(store, str(uid))
                if user is None:      # the account was disabled meanwhile
                    return render_template("message.html", message=g.t["invite_invalid"]), 403
                session.clear()
                login_user(user)
                return redirect(url_for("dashboard"))
        return render_template("invite.html", inv=inv, error=error), (400 if error else 200)

    # ---------------------------------------------------------------- TV mode

    @app.get("/tv/<token>")
    @limiter.limit("120 per minute")
    def tv(token: str):
        """Read-only wall screen: large type, auto-refresh, no navigation, no login, revocable token."""
        expected = store.get_setting("tv_token")
        if not expected or not hmac.compare_digest(token.encode(), str(expected).encode()):
            abort(404)
        d = views.dashboard_data(store, g.settings)
        return render_template("tv.html", d=d, b=views.board(d), simple=request.args.get("layout") == "simple")

    @app.post("/settings/tv")
    def settings_tv():
        _guard_admin()
        action = request.form.get("action")
        if action == "rotate":
            store.set_settings({"tv_token": secrets.token_urlsafe(24)}, bump=False)
        elif action == "revoke":
            store.set_settings({"tv_token": None}, bump=False)
        else:
            abort(400)
        flash(g.t["saved"])
        return redirect(url_for("settings_page") + "#tv")

    @app.post("/settings/isp/primary")
    def isp_primary():
        """'This is my main ISP': the provider in use now becomes the main one (closes a failover)."""
        _guard_write()
        from ..failover import provider_of
        current = provider_of(store.network_at(time.time()) or {})
        if current is None:
            return _settings_page(g.t["isp_unknown"], 400)
        store.set_settings({"primary_isp": current.to_dict()}, bump=False)
        for inc in store.active_incidents():
            if inc.scope == "failover":
                store.close_incident(inc.id)
        flash(g.t["saved"])
        return redirect(url_for("settings_page") + "#isp")

    @app.post("/settings/isp/asn")
    def isp_asn_download():
        """Download the public IP-to-ASN dataset in the background (no per-IP lookups to anyone)."""
        _guard_write()
        if data_dir is None:
            abort(404)
        with ASN_JOB["lock"]:
            if not ASN_JOB["running"]:
                ASN_JOB.update(running=True, error=None)
                threading.Thread(target=_download_asn, daemon=True).start()
        flash(g.t["asn_started"])
        return redirect(url_for("settings_page") + "#isp")

    def _download_asn():
        from .. import asn
        try:
            path = asn.download(data_dir)
            asn._offline_cache.pop(path, None)
            store.set_settings({"_asn_updated": time.time()})  # bump: the monitor re-discovers with names now
        except Exception as exc:  # noqa: BLE001 - shown to the admin as is
            ASN_JOB["error"] = str(exc)
        finally:
            ASN_JOB["running"] = False

    @app.post("/settings/access")
    def settings_access():
        _guard_write()
        f = request.form
        mode = f.get("auth_mode")
        proxies = f.get("trusted_proxies", "").split()
        header = f.get("proxy_header", "Remote-User").strip()
        # Never let a settings change lock the admin out.
        if mode == "proxy" and auth.proxy_user(request.remote_addr, request.headers, header, proxies) is None:
            return _settings_page(g.t["proxy_denied"], 400)
        if mode == "none" and not app.config["LOOPBACK"]:
            return _settings_page(g.t["none_denied"], 400)
        return _save({"auth_mode": mode, "trusted_proxies": proxies, "proxy_header": header})

    @app.post("/settings/password")
    def settings_password():
        # readers may change their own password: no _guard_write() here, only "it's your own local account"
        if not g.user or g.user.source != "local":
            abort(403)
        f = request.form
        if auth.verify_password(store, g.user.username, f.get("password", "")) is None:
            return _settings_page(g.t["bad_login"], 400)
        problem = auth.password_problem(f.get("new_password", ""), f.get("confirm", ""))
        if problem:
            return _settings_page(g.t["pw_" + problem], 400)
        store.set_password_hash(int(g.user.id), auth.hash_password(f["new_password"]))
        flash(g.t["pw_changed"])
        return redirect(url_for("settings_page"))

    @app.post("/settings/alerts")
    def settings_alerts():
        from .. import alerts as alerts_mod
        _guard_write()
        try:
            cfg = alerts_mod.validate(request.form.to_dict(), alerts_mod.load(store))
        except alerts_mod.AlertError as exc:
            return _settings_page(str(exc), 400)
        alerts_mod.save(store, cfg)
        if request.form.get("action") == "test":
            title, body = alerts_mod.T[g.lang]["test"], alerts_mod.T[g.lang]["test_body"]
            results = alerts_mod.send_all(cfg, title, body, {"event": "test"})
            return _settings_page(results=results or {"-": g.t["alerts_none_enabled"]})
        flash(g.t["saved"])
        return redirect(url_for("settings_page") + "#alerts")

    @app.post("/settings/metrics-token")
    def settings_metrics_token():
        _guard_write()
        settings_mod.metrics_token(store, rotate=True)
        flash(g.t["rotated"])
        return redirect(url_for("settings_page"))

    # ---------------------------------------------------------------- auth pages

    @app.route("/login", methods=["GET", "POST"])
    @limiter.limit("10 per minute;50 per hour", methods=["POST"],
                   on_breach=lambda limit: make_response(render_template("login.html", error=g.t["too_many"]), 429))
    def login():
        if g.settings.auth_mode != "local":
            return redirect(url_for("dashboard"))
        error = None
        if request.method == "POST":
            user = auth.verify_password(store, request.form.get("username", ""), request.form.get("password", ""))
            if user:
                session.clear()
                session.permanent = True
                login_user(user)
                nxt = request.args.get("next") or ""
                safe = nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt
                return redirect(nxt if safe else url_for("dashboard"))
            error = g.t["bad_login"]
        return render_template("login.html", error=error), (401 if error else 200)

    @app.post("/logout")
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("login"))

    @app.route("/setup", methods=["GET", "POST"])
    @limiter.limit("10 per minute", methods=["POST"])
    def setup():
        if g.settings.auth_mode != "local" or store.user_count() > 0:
            abort(404)
        error = None
        if request.method == "POST":
            f = request.form
            if not settings_mod.check_setup_token(store, f.get("token", "").strip()):
                error = g.t["bad_token"]
            elif not f.get("username", "").strip():
                error = g.t["bad_login"]
            else:
                problem = auth.password_problem(f.get("password", ""), f.get("confirm", ""))
                if problem:
                    error = g.t["pw_" + problem]
                else:
                    uid = store.add_user(f["username"].strip(), auth.hash_password(f["password"]))
                    settings_mod.consume_setup_token(store)
                    session.clear()
                    session.permanent = True
                    login_user(auth.User(str(uid), f["username"].strip()))
                    return redirect(url_for("dashboard"))
        return render_template("setup.html", error=error, token=request.args.get("token", "")), (400 if error else 200)

    # ---------------------------------------------------------------- machine endpoints

    @app.get("/metrics")
    def metrics():
        return Response(metrics_text(store), mimetype="text/plain; version=0.0.4")

    @app.get("/api/status")
    def api_status():
        return status_json(store)

    @app.get("/favicon.ico")
    def favicon():
        """Browsers ask for it before reading the page's <link rel=icon>: answer with the PNG."""
        return send_from_directory(app.static_folder, "favicon-32.png", mimetype="image/png", max_age=86400)

    @app.get("/healthz")
    def healthz():
        st = status_json(store)
        ok = not st["stale"]
        return {"ok": ok}, (200 if ok else 503)

    return app


def setup_token_if_needed(store: Store, toml_path: str | None = None, data_dir: Path | None = None) -> str | None:
    """Issue a one-time setup token when local auth has no users yet (printed to the logs)."""
    s = settings_mod.load(store, toml_path, data_dir)
    if s.auth_mode == "local" and store.user_count() == 0:
        return settings_mod.issue_setup_token(store)
    return None


class WebServer:
    """Waitress (production WSGI server) in a background thread."""

    def __init__(self, app: Flask, bind: str):
        from waitress.server import create_server
        host, _, port = bind.rpartition(":")
        self.server = create_server(app, host=host or "127.0.0.1", port=int(port), threads=4,
                                    ident="isitmyisp", clear_untrusted_proxy_headers=True)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def port(self) -> int:
        return self.server.effective_port

    def start(self) -> "WebServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.close()
