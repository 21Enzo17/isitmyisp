"""Synthetic data for demos, screenshots and development. NOTHING here is a real measurement.

A day of 30-second windows with one Wi-Fi problem, two ISP backbone incidents, two hours on a backup
link (failover), an ERP outage while the internet was fine, and an IPsec/L2TP tunnel that drops
every 2 hours with a clean path (a rekey/lifetime mismatch). Addresses are documentation ranges
(RFC 5737) and services use .example domains: nothing points at a real network.

`Simulator` builds the history and can keep feeding windows live, so a demo never goes stale;
the scenario decides how the history ends and what keeps happening (healthy, isp, failover, wifi).
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from . import settings as settings_mod
from .classifier import Measurements
from .config import Tunnel
from .monitor import Monitor
from .probes.icmp import WindowStats
from .services import Check, Service
from .snmp import LinkUsage
from .store import Store

ANCHORS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
WIN = 30.0
SCENARIOS = ("healthy", "isp", "failover", "wifi")
TAIL = {"isp": 40, "wifi": 24, "failover": 140}  # windows at the end of the history in that state

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
    rekey_drop: bool = False
    path_drop: bool = False
    backup: bool = False


class Simulator:
    def __init__(self, store: Store, lang: str = "en", seed: int = 7):
        self.store = store
        self.rng = random.Random(seed)
        self.tunnel = Tunnel("branch-office", "198.51.100.20", "10.10.0.1", "ipsec-l2tp")
        self.services = [Service(*s) for s in SERVICES.get(lang, SERVICES["en"])]
        self.checks: dict[str, list[Check]] = {s.name: [] for s in self.services}
        self.clock = 0.0
        self.on_backup = False
        self.mon = Monitor(store, WIN, capture=self._capture, recapture_every=600)
        store.set_settings({"_demo": True}, bump=False)   # reports built from this database say so on every page
        settings_mod.save(store, {
            "lang": lang if lang in ("en", "es") else "en",
            "tunnels": [{"name": self.tunnel.name, "underlay": self.tunnel.underlay,
                         "overlay": self.tunnel.overlay, "type": self.tunnel.type}],
            "services": [{"name": s.name, "kind": s.kind, "target": s.target} for s in self.services],
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
        lost_a = (round(n * rng.uniform(.25, .4)) if st.isp_bad else round(n * .35) if st.wifi_bad
                  else (1 if rng.random() < .03 else 0))
        lost_h = round(n * .35) if st.wifi_bad else 0
        lat = 30 + rng.gauss(0, 1.2) + (45 if st.isp_bad else 0) + (6 if st.backup else 0)
        home = [w("192.168.1.1", n, n - lost_h, 2.0 + (20 if st.wifi_bad else 0))]
        anchors = [w(a, n, n - lost_a, lat + rng.gauss(0, .6)) for a in ANCHORS]
        tcp = {a: w(f"tcp://{a}:443", 10, 10 - round(10 * lost_a / n), lat + 1) for a in ANCHORS}
        busy = 9 <= time.localtime(now).tm_hour < 19
        down = max(3.0, rng.gauss(110 if busy else 25, 30 if busy else 8))
        link = LinkUsage(round(down, 1), round(down * .18, 1), round(100 * down / 300, 1), round(18 * down / 100, 1),
                         round(rng.uniform(8, 22), 1))
        hop = BACKUP["isp_hop"] if st.backup else MAIN["isp_hop"]
        m = Measurements(home, w(hop, n, n, 4.4), anchors, tcp, wireless=True, link=link)
        erp = self.services[-1].name
        for s in self.services:
            ok = not (s.name == erp and st.erp_down)
            self.checks[s.name].append(Check(now, ok, (180 if s.kind == "http" else 45) + rng.gauss(0, 8) if ok else None,
                                             "HTTP 200" if ok else "timeout"))
            self.checks[s.name] = self.checks[s.name][-10:]
        rows = [("home", home[0]), ("isp", m.isp_hop)] + [("anchor", a) for a in anchors]
        under = w(self.tunnel.underlay, n, n - (round(n * .5) if st.path_drop else 0), 41.0)
        over = w(self.tunnel.overlay, n, 0 if st.rekey_drop else (n - round(n * .5) if st.path_drop else n), 43.0)
        self.mon.step(m, rows, now=now, tunnels=[(self.tunnel, under, over)],
                      services=[(s, list(self.checks[s.name])) for s in self.services])

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
            st = State(isp_bad=0.58 <= f < 0.66 or 0.86 <= f < 0.94, wifi_bad=0.26 <= f < 0.285,
                       erp_down=0.72 <= f < 0.75, rekey_drop=minute % 120 < 2.5 and minute > 5,
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
        return base


def add_speed_result(store: Store, now: float | None = None) -> None:
    """One finished speed test, so the demo shows that section (it never runs a real one)."""
    from . import speedtest as sp
    now = now or time.time()
    settings_mod.save(store, {"speedtest": {"enabled": True, "accepted": True}})
    store.add_speedtest(sp.Result(ts=now - 2 * 86400, down_mbps=262.4, up_mbps=91.8, idle_ms=29.6, loaded_ms=71.2,
                                  bytes_used=412_000_000, seconds=15.2, wan_down_mbps=281.0, trigger="scheduled"))


def build(path, hours: float = 24.0, seed: int = 7, scenario: str = "healthy", lang: str = "en",
          speed: bool = False) -> Simulator:
    store = Store(path)
    sim = Simulator(store, lang=lang, seed=seed)
    sim.history(hours, scenario)
    if speed:
        add_speed_result(store)
    return sim
