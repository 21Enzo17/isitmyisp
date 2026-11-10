"""Command line interface: discover, status, mtr, monitor, report, update-asn."""

from __future__ import annotations

import argparse
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
from .store import Store, data_dir

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
    """Everything probed for one discovered network."""

    def __init__(self, net: Network, interval: float, socket_interval: float, engine: str | None = None):
        self.net = net
        self.roles: list[tuple[str, str]] = [("home", r) for r in net.home_routers]
        if net.isp_hop:
            self.roles.append(("isp", net.isp_hop))
        self.roles += [("anchor", a) for a in ANCHORS_V4]
        self.icmp = IcmpProber([ip for _, ip in self.roles], interval=interval, engine=engine)
        self.sockets = SocketProber(tcp=ANCHORS_V4, dns=net.dns_servers[:MAX_DNS], interval=socket_interval)

    def __enter__(self) -> "Session":
        self.icmp.__enter__()
        self.sockets.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self.sockets.__exit__()
        self.icmp.__exit__()

    def measure(self, seconds: float) -> tuple[Measurements, list[tuple[str, WindowStats]]]:
        icmp = self.icmp.window(seconds)
        socks = self.sockets.window(seconds)
        m = Measurements(
            home=[icmp[r] for r in self.net.home_routers],
            isp_hop=icmp.get(self.net.isp_hop) if self.net.isp_hop else None,
            anchors=[icmp[a] for a in ANCHORS_V4],
            anchors_tcp={a: socks[SocketProber.tcp_name(a)] for a in ANCHORS_V4},
            dns=[socks[SocketProber.dns_name(s)] for s in self.net.dns_servers[:MAX_DNS]],
            wireless=self.net.wireless,
        )
        rows = [(role, icmp[ip]) for role, ip in self.roles]
        rows += [("tcp", socks[SocketProber.tcp_name(a)]) for a in ANCHORS_V4]
        rows += [("dns", d) for d in m.dns]
        return m, rows


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
    with Session(net, args.interval, socket_interval=2.0, engine=args.engine) as s:
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


def cmd_monitor(args, t) -> int:
    from .discovery import network_to_dict
    from .monitor import Monitor, mtr_capturer

    store = Store(args.db)
    mon = Monitor(store, window_seconds=args.window,
                  capture=mtr_capturer(store, data_dir(), asn_online=args.asn_online))
    mon.resume()
    print(f"💾 {store.path}  {t['stop_hint']}")
    try:
        while True:  # one iteration per discovered network; re-discover on route change or timer
            net = _discover(args)
            store.add_network(network_to_dict(net))
            route = default_route()
            with Session(net, args.interval, socket_interval=3.0, engine=args.engine) as s:
                print_network(net, t, engine=s.icmp.name)
                started = time.time()
                time.sleep(args.window + 1.5)
                while True:
                    m, rows = s.measure(args.window)
                    res = mon.step(m, rows)
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    if res.transition.closed:
                        print(f"\n[{stamp}] {t['closed']}: {res.transition.closed}")
                    if res.transition.opened:
                        print(f"\n[{stamp}] {t['opened']}", end="")
                        print_verdict(res.verdict, t)
                    time.sleep(args.window)
                    if default_route() != route or time.time() - started > args.rediscover * 60:
                        if default_route() != route:
                            print(f"\n{t['rediscover']}")
                        break
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
    return 0


def _parse_when(value: str) -> float:
    """'7d', '24h', '90m' (ago) or 'YYYY-MM-DD[ HH:MM]' (local time)."""
    units = {"d": 86400, "h": 3600, "m": 60}
    if value and value[-1] in units and value[:-1].isdigit():
        return time.time() - int(value[:-1]) * units[value[-1]]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(value, fmt))
        except ValueError:
            continue
    raise SystemExit(f"invalid date: {value!r} (use 7d, 24h or YYYY-MM-DD[ HH:MM])")


def cmd_report(args, t) -> int:
    from .report import build_report

    store = Store(args.db)
    start = _parse_when(args.since)
    end = _parse_when(args.until) if args.until else time.time()
    lang = args.lang or ("es" if t is pick("es") else "en")
    html_doc = build_report(store, start, end, lang=lang)
    store.close()
    out = args.out or f"isitmyisp-report-{time.strftime('%Y%m%d-%H%M')}.html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    print(f"📄 {out}")
    return 0


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
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("discover", help="show gateway, ISP, DNS, CGNAT, IPv6 and the path segments")

    s = sub.add_parser("status", help="measure for a while and give a verdict")
    s.add_argument("-s", "--seconds", type=int, default=30)
    s.add_argument("-i", "--interval", type=float, default=0.5)

    m = sub.add_parser("mtr", help="run mtr and separate real loss from ICMP noise")
    m.add_argument("target")
    m.add_argument("-c", "--cycles", type=int, default=20)

    mon = sub.add_parser("monitor", help="measure continuously and store results")
    mon.add_argument("-w", "--window", type=int, default=30, help="seconds per sample window")
    mon.add_argument("-i", "--interval", type=float, default=2.0, help="seconds between pings")
    mon.add_argument("--rediscover", type=int, default=15, help="re-discover the path every N minutes")
    mon.add_argument("--db", help="SQLite path (default: ~/.local/share/isitmyisp/data.db)")

    rep = sub.add_parser("report", help="write the HTML evidence report")
    rep.add_argument("--since", default="7d", help="7d, 24h, 90m or YYYY-MM-DD[ HH:MM] (default: 7d)")
    rep.add_argument("--until", help="same formats (default: now)")
    rep.add_argument("-o", "--out", help="output file (default: isitmyisp-report-<date>.html)")
    rep.add_argument("--db", help="SQLite path (default: ~/.local/share/isitmyisp/data.db)")

    sub.add_parser("update-asn", help="download the public IP-to-ASN dataset for offline lookups")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    t = pick(args.lang)
    handlers = {"discover": cmd_discover, "status": cmd_status, "mtr": cmd_mtr,
                "monitor": cmd_monitor, "report": cmd_report, "update-asn": cmd_update_asn}
    return handlers[args.cmd](args, t)


if __name__ == "__main__":
    sys.exit(main())
