"""Synthetic data for demos, screenshots and development. NOTHING here is a real measurement.

A day of 30-second windows with one Wi-Fi problem, two ISP backbone incidents, two hours on a backup
link (failover), an ERP outage while the internet was fine, and an IPsec/L2TP tunnel that drops
every 2 hours with a clean path (a rekey/lifetime mismatch). Addresses are documentation ranges
(RFC 5737) and services use .example domains: nothing points at a real network.

`Simulator` builds the history and can keep feeding windows live, so a demo never goes stale;
the scenario decides how the history ends and what keeps happening (healthy, isp, failover, wifi, loop).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from . import settings as settings_mod
from .classifier import Measurements
from .config import Tunnel
from .devices import Device
from .lan import LanStats
from .monitor import Monitor
from .probes.icmp import WindowStats
from .services import Check, Service
from .snmp import LinkUsage
from .store import Store

ANCHORS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
WIN = 30.0
SCENARIOS = ("healthy", "isp", "failover", "wifi", "loop")
TAIL = {"isp": 40, "wifi": 24, "failover": 140, "loop": 30}  # windows at the end of the history in that state

DEVICES = {
    "en": [("Card terminal, till 1", "pos", "192.168.1.60", None), ("Fiscal printer", "printer", "192.168.1.70", 9100),
           ("Camera recorder", "camera", "192.168.1.80", 554)],
    "es": [("Posnet caja 1", "pos", "192.168.1.60", None), ("Impresora fiscal", "printer", "192.168.1.70", 9100),
           ("Cámaras (grabador)", "camera", "192.168.1.80", 554)],
}

SERVICES = {
    "en": [("Online banking", "http", "https://bank.example"), ("ERP", "tcp", "erp.example:443")],
    "es": [("Home banking", "http", "https://banco.example"), ("Facturación electrónica", "tcp", "facturacion.example:443")],
}


def w(target: str, n: int, received: int, med: float) -> WindowStats:
    ok = received > 0
    return WindowStats(target, n, received, med if ok else None, med if ok else None, med if ok else None,
                       0.6 if ok else None, med if ok else None)


def _net(hop: str, asn: str, name: str) -> dict:
    return {"isp_hop": hop, "isp_asn": asn, "isp_name": name, "wireless": True, "cgnat": False,
            "tunnels": ["branch-office"], "home_routers": ["192.168.1.1"], "path": [
                {"index": 1, "host": "192.168.1.1", "segment": "home", "asn": None, "as_name": None},
                {"index": 2, "host": hop, "segment": "isp", "asn": asn, "as_name": name}]}


MAIN = _net("203.0.113.1", "AS64500", "Example ISP S.A.")
BACKUP = _net("198.51.100.1", "AS64501", "Backup Wireless S.R.L.")


@dataclass
class State:
    isp_bad: bool = False
    wifi_bad: bool = False
    erp_down: bool = False
    pos_down: bool = False
    rekey_drop: bool = False
    path_drop: bool = False
    backup: bool = False
    loop: bool = False      # a cable closing a circle between two switches


class Simulator:
    def __init__(self, store: Store, lang: str = "en", seed: int = 7):
        self.store = store
        self.rng = random.Random(seed)
        self.tunnel = Tunnel("branch-office", "198.51.100.20", "10.10.0.1", "ipsec-l2tp")
        self.services = [Service(*s) for s in SERVICES.get(lang, SERVICES["en"])]
        self.checks: dict[str, list[Check]] = {s.name: [] for s in self.services}
        self.devices = [Device(*d) for d in DEVICES.get(lang, DEVICES["en"])]
        self.dev_checks: dict[str, list[Check]] = {d.name: [] for d in self.devices}
        self.clock = 0.0
        self.on_backup = False
        self.mon = Monitor(store, WIN, capture=self._capture, recapture_every=600)
        # synthetic data in a throwaway file: no need to wait for the disk on each of ~3,000 commits per day
        store.db.execute("PRAGMA synchronous = OFF")
        store.set_settings({"_demo": True}, bump=False)   # reports built from this database say so on every page
        from . import hours
        hours.save(store, {"enabled": True, "days": hours.SUGGESTED})   # a shop: Mon–Fri with siesta, Saturday morning
        settings_mod.save(store, {
            "lang": lang if lang in ("en", "es") else "en",
            "tunnels": [{"name": self.tunnel.name, "underlay": self.tunnel.underlay,
                         "overlay": self.tunnel.overlay, "type": self.tunnel.type}],
            "services": [{"name": s.name, "kind": s.kind, "target": s.target} for s in self.services],
            "devices": [{"name": d.name, "kind": d.kind, "target": d.target, "port": d.port} for d in self.devices],
            "link": {"enabled": True, "host": "192.168.1.1", "community": "demo-ro", "port": 161,
                     "interface": "ether1", "down_mbps": 300, "up_mbps": 100}})

    # ------------------------------------------------------------------ evidence
    def _capture(self, target: str, iid: int) -> None:
        loss = self.rng.choice([18.0, 26.7, 33.3])
        hops = [("192.168.1.1", 0, 1.6, "ok", None, None),
                ("203.0.113.1", 0, 4.4, "ok", "AS64500", "Example ISP S.A."),
                ("203.0.113.9", loss, 31.0, "real_loss", "AS64500", "Example ISP S.A."),
                ("???", 100, 0, "no_reply", None, None),
                ("198.51.100.7", loss, 36.0, "real_loss", "AS64500", "Example ISP S.A."),
                (target, loss, 33.0, "real_loss", "AS13335", "Cloudflare, Inc.")]
        self.store.add_capture(iid, "mtr", target, {
            "target": target, "reached": True, "destination_loss": loss, "loss_starts_at": 3,
            "hops": [{"index": i + 1, "host": h, "loss": lo, "sent": 30, "avg": a, "best": a * .9, "worst": a * 1.6,
                      "status": s, "asn": asn, "as_name": nm} for i, (h, lo, a, s, asn, nm) in enumerate(hops)]},
            ts=self.clock)

    # ------------------------------------------------------------------ one window
    def set_backup(self, on: bool, now: float) -> None:
        if on == self.on_backup:
            return
        self.on_backup = on
        net = BACKUP if on else MAIN
        self.store.add_network(net, ts=now)
        self.mon.observe_network(net, now=now)

    def step(self, now: float, st: State) -> None:
        self.clock = now
        rng, n = self.rng, 15
        self.set_backup(st.backup, now)
        lost_a = (round(n * rng.uniform(.25, .4)) if st.isp_bad else round(n * .35) if st.wifi_bad or st.loop
                  else (1 if rng.random() < .03 else 0))
        lost_h = round(n * .35) if st.wifi_bad else round(n * .3) if st.loop else 0
        lat = 30 + rng.gauss(0, 1.2) + (45 if st.isp_bad else 0) + (6 if st.backup else 0)
        home = [w("192.168.1.1", n, n - lost_h, 2.0 + (20 if st.wifi_bad else 0))]
        anchors = [w(a, n, n - lost_a, lat + rng.gauss(0, .6)) for a in ANCHORS]
        tcp = {a: w(f"tcp://{a}:443", 10, 10 - round(10 * lost_a / n), lat + 1) for a in ANCHORS}
        busy = 9 <= time.localtime(now).tm_hour < 19
        down = max(3.0, rng.gauss(110 if busy else 25, 30 if busy else 8))
        link = LinkUsage(round(down, 1), round(down * .18, 1), round(100 * down / 300, 1), round(18 * down / 100, 1),
                         round(rng.uniform(8, 22), 1))
        hop = BACKUP["isp_hop"] if st.backup else MAIN["isp_hop"]
        dns_ok = not st.wifi_bad
        dns = [w("dns://192.168.1.1", 6, 6 if dns_ok else 3, 3.5 + rng.gauss(0, .4)),
               w("dns://1.1.1.1", 6, 6 if dns_ok else 3, lat + 1.5)]
        mcast = rng.uniform(4800, 6200) if st.loop else rng.uniform(3, 9)
        lan = LanStats(dups=rng.randint(9, 14) if st.loop else 0, replies=30 if st.loop else 15,
                       macs=["04:18:92:7a:44:73"], mcast_pps=round(mcast, 1), mcast_base=6.0)
        m = Measurements(home, w(hop, n, n, 4.4), anchors, tcp, dns=dns, wireless=True, link=link, lan=lan)
        erp = self.services[-1].name
        for s in self.services:
            ok = not (s.name == erp and st.erp_down)
            self.checks[s.name].append(Check(now, ok, (180 if s.kind == "http" else 45) + rng.gauss(0, 8) if ok else None,
                                             "HTTP 200" if ok else "timeout"))
            self.checks[s.name] = self.checks[s.name][-10:]
        pos = self.devices[0].name
        for dv in self.devices:                  # the card terminal drops once while the internet is fine
            ok = not (dv.name == pos and st.pos_down) and not st.wifi_bad
            self.dev_checks[dv.name].append(Check(now, ok, (1.5 if dv.port is None else 3.0) + rng.random() if ok else None,
                                                  "ping OK" if ok else "no reply to ping"))
            self.dev_checks[dv.name] = self.dev_checks[dv.name][-10:]
        rows = ([("home", home[0]), ("isp", m.isp_hop)] + [("anchor", a) for a in anchors]
                + [("tcp", t) for t in tcp.values()] + [("dns", d) for d in dns])   # like a real monitor
        under = w(self.tunnel.underlay, n, n - (round(n * .5) if st.path_drop else 0), 41.0)
        over = w(self.tunnel.overlay, n, 0 if st.rekey_drop else (n - round(n * .5) if st.path_drop else n), 43.0)
        self.mon.step(m, rows, now=now, tunnels=[(self.tunnel, under, over)],
                      services=[(s, list(self.checks[s.name])) for s in self.services],
                      devices=[(d, list(self.dev_checks[d.name])) for d in self.devices])

    # ------------------------------------------------------------------ a whole day
    def history(self, hours: float = 24.0, scenario: str = "healthy", end: float | None = None) -> float:
        """Fill `hours` of windows ending at `end` (default: now). Returns the last timestamp."""
        end = end or time.time()
        t0 = end - hours * 3600
        self.store.add_network(MAIN, ts=t0)
        self.mon.observe_network(MAIN, now=t0)
        total = int(hours * 3600 / WIN)
        tail = TAIL.get(scenario, 0)
        now = t0
        for i in range(total):
            now = t0 + (i + 1) * WIN
            f = i / total
            minute = (i * WIN) / 60
            flaky = 0.12 <= f < 0.14 and i % 3 == 0     # half an hour of a link that drops and comes back
            st = State(isp_bad=0.58 <= f < 0.66 or 0.86 <= f < 0.94 or flaky, wifi_bad=0.26 <= f < 0.285,
                       erp_down=0.72 <= f < 0.75, pos_down=0.79 <= f < 0.81, rekey_drop=minute % 120 < 2.5 and minute > 5,
                       path_drop=0.40 <= f < 0.42, backup=0.47 <= f < 0.55)
            if i >= total - tail:
                st = self.scenario_state(scenario, now)
            self.step(now, st)
        return now

    def scenario_state(self, scenario: str, now: float) -> State:
        """What keeps happening live in each scenario (the tunnel keeps its rekey drops)."""
        minute = (now / 60) % 120
        base = State(rekey_drop=minute < 2.5)
        if scenario == "isp":
            base.isp_bad = True
        elif scenario == "wifi":
            base.wifi_bad = True
        elif scenario == "failover":
            base.backup = True
        elif scenario == "loop":
            base.loop = True
        return base


def add_speed_result(store: Store, now: float | None = None) -> None:
    """One finished speed test, so the demo shows that section (it never runs a real one)."""
    from . import speedtest as sp
    now = now or time.time()
    servers = [{"host": "speedtest.example-isp.net", "port": 5201, "where": "auto"},
               {"host": "vps.example.org", "port": 5201, "where": "auto"}]
    settings_mod.save(store, {"speedtest": {"enabled": True, "accepted": True, "servers": servers}})
    store.add_speedtest(sp.Result(ts=now - 2 * 86400, down_mbps=262.4, up_mbps=91.8, idle_ms=29.6, loaded_ms=71.2,
                                  bytes_used=412_000_000, seconds=15.2, wan_down_mbps=281.0, trigger="scheduled"))
    # the next evening: fine up to the ISP, slow past it (its exit, not the access)
    store.add_speedtest(sp.Result(
        ts=now - 86400, down_mbps=58.3, up_mbps=44.1, idle_ms=31.2, loaded_ms=64.8, bytes_used=731_000_000,
        seconds=46.8, wan_down_mbps=72.5, trigger="manual", servers=[
            {"name": "speedtest.example-isp.net", "where": "inside", "forced": False, "asn": "AS64500",
             "as_name": "Example ISP S.A.", "down_mbps": 286.9, "up_mbps": 94.2, "bytes": 402_000_000, "error": None},
            {"name": "vps.example.org", "where": "outside", "forced": False, "asn": "AS64510",
             "as_name": "Example Hosting", "down_mbps": 41.7, "up_mbps": 38.9, "bytes": 77_000_000, "error": None}]))


def add_doctor_run(store: Store, now: float | None = None) -> None:
    """One check-up of the demo network: on Wi-Fi and with a slow DNS, the rest fine."""
    from . import doctor
    from .discovery import Network, PathHop
    from .probes.mtr import Hop
    now = now or time.time()
    net = Network(gateway="192.168.1.1", interface="wlan0", wireless=True, dns_servers=["192.168.1.1"],
                  home_routers=["192.168.1.1"], isp_hop="203.0.113.1",
                  path=[PathHop(Hop(1, "192.168.1.1", 0.0, 5, 2.1, 1.8, 3.0, 0.3), "home"),
                        PathHop(Hop(2, "203.0.113.1", 0.0, 5, 6.4, 5.9, 7.2, 0.4), "isp")])
    facts = doctor.Facts(net=net, dns_ms={"192.168.1.1": [182.0, 171.0, 210.0]},
                         dns_trapped=False, mtu=doctor.Mtu(1500, 1500), plan_mbps=300, router_uptime_s=12 * 86400,
                         lan=LanStats(0, 15, ["04:18:92:7a:44:73"], 0, 5.0, 5.0), seconds=15)
    store.add_doctor(doctor.to_dict(doctor.run_checks(facts), ts=now - 5 * 3600))


def add_device_checks(store: Store, now: float | None = None) -> None:
    """Two "Check from this device" results: a phone with weak Wi-Fi, and a PC where all is fine."""
    from . import devcheck
    now = now or time.time()
    ok = [(now, 30.0, "ok")] * 2
    tcp = [{"role": "tcp", "target": f"tcp://{a}:443", "received": 10} for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")]
    phone = {"lan": [38, 210, None, 95, 160, None, 44, 300, 120, None, 80, 260, 52, 140, None, 70, 230, 99, 180, 61],
             "down_mbps": 3.2, "up_mbps": 1.4, "inet": {a: [140, 260, None, 190, 220] for a in ("1.1.1.1", "8.8.8.8")}}
    pc = {"lan": [2.1, 1.8, 2.4, 2.0, 1.9] * 4, "down_mbps": 912.0, "up_mbps": 880.0,
          "inet": {a: [9.8, 10.4, 9.9, 11.0, 10.1] for a in ("1.1.1.1", "8.8.8.8", "9.9.9.9")}}
    for ago, label, dev in ((26 * 60, "Android · Chrome", phone), (3 * 3600, "Windows · Edge", pc)):
        rec = devcheck.cross(dev, ok, tcp)
        rec.update(ts=now - ago, seconds=15.0, device=label, key=label, user="demo")
        store.add_device_check(rec)


def build(path, hours: float = 24.0, seed: int = 7, scenario: str = "healthy", lang: str = "en",
          speed: bool = False) -> Simulator:
    store = Store(path)
    sim = Simulator(store, lang=lang, seed=seed)
    sim.history(hours, scenario)
    add_doctor_run(store)
    add_device_checks(store)
    if speed:
        add_speed_result(store)
    return sim
