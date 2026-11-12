"""Command line interface: discover, status, mtr, monitor, report, update-asn."""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__, asn
from .classifier import Measurements, Verdict, classify
from .discovery import ANCHORS_V4, Network, default_route, discover
from .i18n import pick
from .probes.icmp import IcmpProber, WindowStats
from .probes.mtr import MtrError, PathAnalysis, analyze_path, run_mtr
from .probes.sockets import SocketProber
from .stats import loss_is_significant
from .config import ConfigError, load as load_config
from .store import Store, data_dir
from .timeutil import parse_when as _parse_when
from .tunnels import classify_tunnel

MAX_DNS = 3


def _fmt(v: float | None, unit: str = "") -> str:
    return "—" if v is None else f"{v:.1f}{unit}"


# ---------------------------------------------------------------- output

def print_network(net: Network, t: dict, engine: str | None = None) -> None:
    print(f"\n{t['net']}")
    print(f"  {t['gateway']:<22} {net.gateway or '—'}")
    print(f"  {t['iface']:<22} {net.interface or '—'} ({t['wireless'] if net.wireless else t['wired']})")
    print(f"  {t['dns_srv']:<22} {', '.join(net.dns_servers) or '—'}")
    if net.public_ipv4:
        print(f"  {t['pubip']:<22} {net.public_ipv4}")
    if net.isp_name:
        print(f"  {t['isp_name']:<22} {net.isp_asn} {net.isp_name}")
    print(f"  {t['isphop']:<22} {net.isp_hop or '—'}")
    print(f"  {t['cgnat']:<22} {t['yes'] if net.cgnat else t['no']}")
    print(f"  {t['dnat']:<22} {t['yes'] if net.double_nat else t['no']}")
    v6 = t["v6works"] if net.ipv6_works else (t["v6broken"] if net.ipv6_global else t["v6none"])
    print(f"  {t['ipv6']:<22} {v6}")
    if engine:
        print(f"  {t['engine']:<22} {engine}")
    if net.cgnat:
        print(f"\n  ⚠️  {t['cgnat_warn'].format(hops=', '.join(h for h in net.nat_hops if h.startswith('100.')))}")
    if net.double_nat:
        print(f"\n  ⚠️  {t['dnat_warn'].format(hops=', '.join(net.home_routers))}")
    if net.asn_source == "none":
        print(f"\n  💡 {t['asn_hint']}")


def print_path(p: PathAnalysis, t: dict, asn_info: dict, segments: dict[str, str] | None = None) -> None:
    label = {"ok": t["hop_ok"], "real_loss": t["hop_real"], "icmp_deprioritized": t["hop_icmp"], "no_reply": t["hop_none"]}
    print()
    for ha in p.hops:
        h = ha.hop
        a = asn_info.get(h.host)
        seg = (segments or {}).get(h.host)
        seg_txt = f"[{t['seg_' + seg]}] " if seg else ""
        a_txt = f"  {a[0]} {a[1][:40]}" if a else ""
        print(f"  {h.index:>2}. {seg_txt:<9}{h.host:<16} {h.loss:>5.1f}%  {h.avg:>6.1f} ms  {label[ha.status]}{a_txt}")
    print()
    if not p.reached:
        print("  " + t["path_unreach"])
    elif p.loss_starts_at is not None:
        hop = next(ha.hop for ha in p.hops if ha.hop.index == p.loss_starts_at)
        a = asn_info.get(hop.host)
        print("  " + t["path_bad"].format(l=p.destination_loss, h=hop.index, host=hop.host,
                                         asn=f", {a[0]} {a[1]}" if a else ""))
    else:
        print("  " + t["path_ok"].format(l=p.destination_loss))


def print_verdict(v: Verdict, t: dict) -> None:
    print("\n" + t[v.code])
    for e in v.evidence:
        print(f"   · {e}")
    for h in v.hints:
        print(f"   💡 {t[h]}")


def print_table(rows: list[tuple[str, WindowStats]], t: dict) -> None:
    print(f"\n  {t['role']:<9} {t['target']:<24} {t['loss']:>12} {t['med']:>9} {t['jit']:>9}")
    for role, s in rows:
        flag = " ⚠" if loss_is_significant(s.lost, s.sent) else ""
        loss = f"{s.loss:.1f}% ({s.lost}/{s.sent})"
        print(f"  {role:<9} {s.target:<24} {loss:>12} {_fmt(s.rtt_median, ' ms'):>9} {_fmt(s.jitter, ' ms'):>9}{flag}")


# ---------------------------------------------------------------- measuring

class Session:
    """Everything probed for one discovered network, with the current settings."""

    def __init__(self, net: Network, interval: float, socket_interval: float, engine: str | None = None,
                 anchors: list[str] | None = None, tunnels: list | None = None, services: list | None = None,
                 link: dict | None = None, voip: str = "", devices: list | None = None):
        from .devices import check as check_device
        from .services import ServiceProber
        self.net = net
        self.link = None
        if link and link.get("enabled"):
            from .snmp import LinkMonitor, SnmpClient
            self.link = LinkMonitor(SnmpClient(link["host"], link["community"], int(link["port"])),
                                    link["interface"], link["down_mbps"], link["up_mbps"])
        self.services = ServiceProber(list(services or []))
        self.last_services: list = []
        self.devices = ServiceProber(list(devices or []), checker=check_device)   # same rhythm, LAN checks
        self.last_devices: list = []
        self.anchors = list(anchors or ANCHORS_V4)
        self.tunnels = list(tunnels or [])
        self.roles: list[tuple[str, str]] = [("home", r) for r in net.home_routers]
        if net.isp_hop:
            self.roles.append(("isp", net.isp_hop))
        self.roles += [("anchor", a) for a in self.anchors]
        if voip and voip not in [ip for _, ip in self.roles]:  # your SIP provider / cloud PBX: calls are judged against it
            self.roles.append(("voip", voip))
        tunnel_targets = [ip for t in self.tunnels for ip in (t.underlay, t.overlay)]
        self.last_tunnels: list = []
        self.icmp = IcmpProber([ip for _, ip in self.roles] + tunnel_targets, interval=interval, engine=engine)
        self.sockets = SocketProber(tcp=self.anchors, dns=net.dns_servers[:MAX_DNS], interval=socket_interval)

    def __enter__(self) -> "Session":
        self.icmp.__enter__()
        self.sockets.__enter__()
        self.services.__enter__()
        self.devices.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.devices.__exit__()
        self.services.__exit__()
        self.sockets.__exit__()
        self.icmp.__exit__()

    def measure(self, seconds: float) -> tuple[Measurements, list[tuple[str, WindowStats]]]:
        icmp = self.icmp.window(seconds)
        socks = self.sockets.window(seconds)
        m = Measurements(
            home=[icmp[r] for r in self.net.home_routers],
            isp_hop=icmp.get(self.net.isp_hop) if self.net.isp_hop else None,
            anchors=[icmp[a] for a in self.anchors],
            anchors_tcp={a: socks[SocketProber.tcp_name(a)] for a in self.anchors},
            dns=[socks[SocketProber.dns_name(s)] for s in self.net.dns_servers[:MAX_DNS]],
            wireless=self.net.wireless,
            link=self.link.sample() if self.link else None,
        )
        rows = [(role, icmp[ip]) for role, ip in self.roles]
        rows += [("tcp", socks[SocketProber.tcp_name(a)]) for a in self.anchors]
        rows += [("dns", d) for d in m.dns]
        self.last_tunnels = [(t, icmp.get(t.underlay), icmp.get(t.overlay)) for t in self.tunnels]
        self.last_services = [(sv, self.services.recent(sv.name)) for sv in self.services.services]
        self.last_devices = [(dv, self.devices.recent(dv.name)) for dv in self.devices.services]
        return m, rows


def _settings(args, store: Store | None = None):
    """Live settings: SQLite (web UI) when a store is given, defaults otherwise; TOML tunnels win."""
    from . import settings as settings_mod
    try:
        if store is not None:
            return settings_mod.load(store, args.config, data_dir(), default_lang=args.lang)
        s = settings_mod.Settings()
        cfg = load_config(args.config, data_dir())
        if cfg.path:
            s.tunnels, s.tunnels_from_file = cfg.tunnels, cfg.path
        return s
    except ConfigError as exc:
        raise SystemExit(f"config: {exc}")


def print_tunnels(results, t: dict) -> None:
    if not results:
        return
    print(f"\n{t['tunnels']}")
    for tv in results:
        print(f"  {tv.name:<20} {t['tun_' + tv.code]}")
        for e in tv.evidence:
            print(f"     · {e}")


def _discover(args) -> Network:
    return discover(data_dir=data_dir(), asn_online=args.asn_online, want_public_ip=args.public_ip)


# ---------------------------------------------------------------- commands

def cmd_discover(args, t) -> int:
    net = _discover(args)
    print_network(net, t)
    if net.path:
        segs = {p.hop.host: p.segment for p in net.path}
        info = {p.hop.host: (p.asn, p.as_name) for p in net.path if p.asn}
        print_path(analyze_path(ANCHORS_V4[0], [p.hop for p in net.path]), t, info, segs)
    return 0


def cmd_status(args, t) -> int:
    net = _discover(args)
    cfg = _settings(args, Store(args.db) if args.db or default_db_exists() else None)
    with Session(net, args.interval, socket_interval=2.0, engine=args.engine,
                 anchors=cfg.anchors, tunnels=cfg.tunnels) as s:
        print_network(net, t, engine=s.icmp.name)
        end = time.time() + args.seconds
        while (left := end - time.time()) > 0:
            print(f"\r⏱  {t['measuring'].format(s=args.seconds)} … {int(left):>3}s ", end="", flush=True)
            time.sleep(min(1.0, left))
        time.sleep(1.2)  # let in-flight packets settle
        m, rows = s.measure(args.seconds)
    print("\r" + " " * 50, end="\r")
    print_table(rows, t)
    v = classify(m)
    print_verdict(v, t)
    print_tunnels([classify_tunnel(tun, under, over, v.code in ("ok", "remote", "dns"))
                   for tun, under, over in s.last_tunnels], t)
    if v.code in ("access", "isp", "remote"):
        worst = max(m.anchors, key=lambda a: a.loss)
        _mtr(worst.target, 20, t, args)
    return 0 if v.code == "ok" else 1


def _mtr(target: str, cycles: int, t: dict, args) -> int:
    try:
        hops = run_mtr(target, cycles=cycles)
    except MtrError as exc:
        print(f"mtr: {exc}", file=sys.stderr)
        return 2
    p = analyze_path(target, hops)
    info = asn.lookup([h.host for h in hops], data_dir=data_dir(), online=args.asn_online)
    print_path(p, t, info)
    return 1 if p.degraded else 0


def cmd_mtr(args, t) -> int:
    return _mtr(args.target, args.cycles, t, args)


def _start_web(store: Store, args, t):
    try:
        from .webapp import WebServer, create_app, setup_token_if_needed
    except ImportError:
        print("🌐 web UI disabled: install it with pip install 'isitmyisp[web]' (the Docker image includes it)")
        return None
    app = create_app(store, data_dir=data_dir(), toml_path=args.config, bind=args.web,
                     secure_cookies=os.environ.get("ISITMYISP_SECURE_COOKIES") == "1",
                     default_lang=_lang_code(args, t))
    server = WebServer(app, args.web).start()
    print(f"🌐 http://{args.web}")
    token = setup_token_if_needed(store, args.config, data_dir())
    if token:
        print(f"🔑 {t['setup_token']}: {token}")
        print(f"   http://{args.web}/setup?token={token}")
    return server


def cmd_monitor(args, t) -> int:
    from .discovery import network_to_dict
    from .failover import PathWatch, isp_ttl, provider_of
    from .speedtest import Runner as SpeedRunner
    from .monitor import Monitor, mtr_capturer

    store = Store(args.db)
    cfg = _settings(args, store)
    mon = Monitor(store, window_seconds=args.window or cfg.window,
                  capture=mtr_capturer(store, data_dir(), asn_online=args.asn_online))
    mon.resume()
    from .alerts import Alerter
    alerter = Alerter(store, lambda: _settings(args, store).lang)
    from .monthly import Reporter
    monthly = Reporter(store, lambda: _settings(args, store).lang)   # off unless enabled in Settings
    server = _start_web(store, args, t) if args.web and args.web != "off" else None
    if cfg.tunnels_from_file:
        print(f"⚙️  {cfg.tunnels_from_file}: {len(cfg.tunnels)} tunnel(s)")
    print(f"💾 {store.path}  {t['stop_hint']}")
    hops_by_provider: dict[str, set[str]] = {}  # ISP routers already seen per provider (ECMP is not a failover)
    speed = SpeedRunner(store)                  # off unless enabled in Settings (it fills the link)
    speed_seen = max((r["ts"] for r in store.speedtests_between(time.time() - 86400, 2e10)), default=0.0)
    try:
        while True:  # one session per (network, settings); rebuilt on route change, timer or new settings
            cfg = _settings(args, store)
            window = args.window or cfg.window
            interval = args.interval or cfg.interval
            mon.window = window
            net = _discover(args)
            snapshot = network_to_dict(net)
            snapshot["tunnels"] = [tun.name for tun in cfg.tunnels]
            store.add_network(snapshot)
            was_on_backup = any(i.scope == "failover" for i in store.active_incidents())
            change = mon.observe_network(snapshot)
            if change.kind == "learn":
                print(t["primary_learned"].format(main=change.current.name))
            elif change.kind == "failover":
                print(t["failover_on"].format(to=change.current.name, main=change.primary.name))
            elif change.kind == "failback" and was_on_backup:
                print(t["failover_off"].format(main=change.primary.name))
            watch = None
            ttl, provider = isp_ttl(snapshot), provider_of(snapshot)
            if net.isp_hop and ttl:
                seen = hops_by_provider.setdefault((provider.asn or provider.net16) if provider else "?", set())
                seen.add(net.isp_hop)
                watch = PathWatch(net.isp_hop, ttl, cfg.anchors, known=seen)
            route = default_route()
            with Session(net, interval, socket_interval=3.0, engine=args.engine,
                         anchors=cfg.anchors, tunnels=cfg.tunnels, services=cfg.services, devices=cfg.devices, link=cfg.link,
                         voip=cfg.voip_target) as s:
                print_network(net, t, engine=s.icmp.name)
                started = time.time()
                time.sleep(window + 1.5)
                while True:
                    m, rows = s.measure(window)
                    res = mon.step(m, rows, tunnels=s.last_tunnels, services=s.last_services, devices=s.last_devices,
                                   suppress=speed.suppress(time.time(), window))
                    cfg_now = _settings(args, store)
                    what = speed.tick(cfg_now.speedtest, time.time(), wireless=net.wireless,
                                      on_backup=any(i.scope == "failover" for i in store.active_incidents()),
                                      incident=mon.incident_id is not None,
                                      link_busy_pct=m.link.peak_pct if m.link else None,
                                      counters=s.link.counters if s.link else None)
                    if what == "started":
                        print(f"\n{t['speed_started']}")
                    for r in store.speedtests_between(speed_seen + 0.001, 2e10):
                        speed_seen = r["ts"]
                        print(f"\n{t['speed_done'].format(down=r.get('down_mbps') or 0, up=r.get('up_mbps') or 0, err=r.get('error') or '')}")
                    alerter.tick()
                    monthly.tick()
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    if res.transition.closed:
                        print(f"\n[{stamp}] {t['closed']}: {res.transition.closed}")
                    if res.transition.opened:
                        print(f"\n[{stamp}] {t['opened']}", end="")
                        print_verdict(res.verdict, t)
                    for tv, ttr in res.tunnels:
                        if ttr.opened:
                            print(f"\n[{stamp}] {t['opened']} · {tv.name}: {t['tun_' + tv.code]}")
                        if ttr.closed:
                            print(f"\n[{stamp}] {t['closed']} · {tv.name}")
                    time.sleep(window)
                    if watch is not None and watch.check():
                        print(f"\n{t['path_changed']}")
                        break
                    if store.settings_version() != cfg.version:
                        print(f"\n{t['settings_changed']}")
                        break
                    if default_route() != route or time.time() - started > args.rediscover * 60:
                        if default_route() != route:
                            print(f"\n{t['rediscover']}")
                        break
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.stop()
        store.close()
    return 0


def cmd_report(args, t) -> int:
    from .report import build_report

    try:
        start = _parse_when(args.since)
        end = _parse_when(args.until) if args.until else time.time()
    except ValueError as exc:
        raise SystemExit(str(exc))
    store = Store(args.db)
    html_doc = build_report(store, start, end, lang=_lang_code(args, t))
    store.close()
    ext = "pdf" if args.pdf else "html"
    out = args.out or f"isitmyisp-report-{time.strftime('%Y%m%d-%H%M')}.{ext}"
    if args.pdf:
        from .pdf import PdfUnavailable, html_to_pdf
        try:
            data = html_to_pdf(html_doc)
        except PdfUnavailable as exc:
            raise SystemExit(str(exc))
        with open(out, "wb") as fh:
            fh.write(data)
    else:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html_doc)
    print(f"📄 {out}")
    return 0


def _lang_code(args, t) -> str:
    return args.lang or ("es" if t is pick("es") else "en")


def cmd_demo(args, t) -> int:
    """The full UI on synthetic data, live, read-only: for showing the product without a network."""
    import shutil
    import tempfile
    import threading
    from pathlib import Path

    try:
        from .webapp import WebServer, create_app
    except ImportError:
        raise SystemExit("the demo needs the web UI: pip install 'isitmyisp[web]' (the Docker image includes it)")
    from .demo import WIN, build

    if args.static:   # render every page to files instead of serving (static hosting, e.g. Netlify)
        from .demo_static import export
        pages = export(Path(args.static))
        print(t["demo_static"].format(n=len(pages), path=args.static))
        return 0
    lang = _lang_code(args, t)
    work = Path(tempfile.mkdtemp(prefix="isitmyisp-demo-"))
    print(t["demo_building"])
    sim = build(work / "demo.db", scenario=args.scenario, lang=lang, speed=True)
    stop = threading.Event()

    def feed():  # one synthetic window every 30 s, so the demo never goes stale
        while not stop.wait(WIN):
            now = time.time()
            sim.step(now, sim.scenario_state(args.scenario, now))
    threading.Thread(target=feed, daemon=True, name="demo-feed").start()
    server = WebServer(create_app(sim.store, data_dir=work, bind=args.bind, default_lang=lang, demo=True),
                       args.bind).start()
    host, _, _ = args.bind.rpartition(":")
    print(t["demo_ready"].format(url=f"http://{host or '127.0.0.1'}:{server.port}", scenario=args.scenario))
    print(t["stop_hint"])
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.stop()
        sim.store.close()
        shutil.rmtree(work, ignore_errors=True)
    return 0


def cmd_web(args, t) -> int:
    store = Store(args.db)
    args.web = args.bind
    server = _start_web(store, args, t)
    if server is None:
        return 2
    print(t["stop_hint"])
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        store.close()
    return 0


def cmd_admin(args, t) -> int:
    """Recovery from the console: works even when you are locked out of the web UI."""
    import getpass

    from . import settings as settings_mod
    store = Store(args.db)
    try:
        if args.action == "auth-mode":
            settings_mod.save(store, {"auth_mode": args.value})
            print(f"auth_mode = {args.value}")
        elif args.action == "setup-token":
            print(settings_mod.issue_setup_token(store))
        elif args.action in ("create-user", "reset-password"):
            from .webapp import auth
            name = args.value
            pw = getpass.getpass("password: ")
            problem = auth.password_problem(pw, getpass.getpass("confirm: "))
            if problem:
                raise SystemExit(t["pw_" + problem] if "pw_" + problem in t else problem)
            row = store.get_user(username=name)
            if args.action == "create-user":
                if row:
                    raise SystemExit(f"user {name!r} already exists")
                store.add_user(name, auth.hash_password(pw))
            else:
                if not row:
                    raise SystemExit(f"no user {name!r}")
                store.set_password_hash(row[0], auth.hash_password(pw))
            print("ok")
    except settings_mod.SettingsError as exc:
        raise SystemExit(str(exc))
    finally:
        store.close()
    return 0


def default_db_exists() -> bool:
    from .store import default_path
    return default_path().exists()


def cmd_update_asn(args, t) -> int:
    print(t["asn_downloading"])
    path = asn.download(data_dir())
    print(t["asn_done"].format(p=path))
    return 0


# ---------------------------------------------------------------- entry point

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="isitmyisp", description="Is it your Wi-Fi, your router or your ISP?")
    p.add_argument("--version", action="version", version=f"isitmyisp {__version__}")
    p.add_argument("--lang", choices=["en", "es"], help="output language (default: from $LANG)")
    p.add_argument("--asn-online", action="store_true",
                   help="look up ASNs via Team Cymru whois (sends your path's public IPs to them)")
    p.add_argument("--public-ip", action="store_true", help="ask api.ipify.org for your public IPv4")
    p.add_argument("--engine", choices=["fping", "ping"], help="force an ICMP engine (default: fping if installed)")
    p.add_argument("--config", help="TOML config file (tunnels); default: <data dir>/config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("discover", help="show gateway, ISP, DNS, CGNAT, IPv6 and the path segments")

    s = sub.add_parser("status", help="measure for a while and give a verdict")
    s.add_argument("-s", "--seconds", type=int, default=30)
    s.add_argument("-i", "--interval", type=float, default=0.5)

    m = sub.add_parser("mtr", help="run mtr and separate real loss from ICMP noise")
    m.add_argument("target")
    m.add_argument("-c", "--cycles", type=int, default=20)

    mon = sub.add_parser("monitor", help="measure continuously and store results")
    mon.add_argument("-w", "--window", type=int, help="seconds per sample window (default: from settings, 30)")
    mon.add_argument("-i", "--interval", type=float, help="seconds between pings (default: from settings, 2)")
    mon.add_argument("--rediscover", type=int, default=15, help="re-discover the path every N minutes")
    mon.add_argument("--db", help="SQLite path (default: ~/.local/share/isitmyisp/data.db)")
    mon.add_argument("--web", default="127.0.0.1:8080",
                     help="dashboard address, or 'off' (default 127.0.0.1:8080; use 0.0.0.0:8080 to expose on your LAN)")

    rep = sub.add_parser("report", help="write the HTML evidence report")
    rep.add_argument("--since", default="7d", help="7d, 24h, 90m or YYYY-MM-DD[ HH:MM] (default: 7d)")
    rep.add_argument("--until", help="same formats (default: now)")
    rep.add_argument("-o", "--out", help="output file (default: isitmyisp-report-<date>.html)")
    rep.add_argument("--db", help="SQLite path (default: ~/.local/share/isitmyisp/data.db)")
    rep.add_argument("--pdf", action="store_true", help="write PDF instead of HTML (needs WeasyPrint)")

    web = sub.add_parser("web", help="serve the dashboard, /metrics and /api/status from an existing database")
    web.add_argument("--bind", default="127.0.0.1:8080")
    web.add_argument("--db", help="SQLite path (default: ~/.local/share/isitmyisp/data.db)")

    adm = sub.add_parser("admin", help="console recovery: auth mode, setup token, users")
    adm.add_argument("action", choices=["auth-mode", "setup-token", "create-user", "reset-password"])
    adm.add_argument("value", nargs="?", default="", help="mode (local/proxy/none) or username")
    adm.add_argument("--db", help="SQLite path (default: ~/.local/share/isitmyisp/data.db)")

    sub.add_parser("update-asn", help="download the public IP-to-ASN dataset for offline lookups")

    demo = sub.add_parser("demo", help="the full web UI on synthetic data, live and read-only (no network, no root)")
    demo.add_argument("--scenario", choices=["healthy", "isp", "failover", "wifi"], default="healthy",
                      help="what the network is doing right now in the demo")
    demo.add_argument("--bind", default="127.0.0.1:8090", help="where to serve it (default 127.0.0.1:8090)")
    demo.add_argument("--static", metavar="DIR", help="write the demo as a static site into DIR (every page, "
                      "scenario and language) instead of serving it")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    t = pick(args.lang)
    handlers = {"discover": cmd_discover, "status": cmd_status, "mtr": cmd_mtr,
                "monitor": cmd_monitor, "report": cmd_report, "web": cmd_web, "admin": cmd_admin,
                "update-asn": cmd_update_asn, "demo": cmd_demo}
    return handlers[args.cmd](args, t)


if __name__ == "__main__":
    sys.exit(main())
