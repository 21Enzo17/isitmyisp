"""Generate a SYNTHETIC database for screenshots and report development.

A day of 30-second windows: one Wi-Fi problem, two ISP backbone incidents and an
IPsec/L2TP tunnel that drops every 2 hours with a clean path (a rekey/lifetime mismatch).
Nothing here is a real measurement: never publish a report built from it as real evidence.

    python3 scripts/demo_data.py /tmp/demo.db
    isitmyisp report --db /tmp/demo.db --since 2026-01-01 -o demo.html
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isitmyisp.classifier import Measurements  # noqa: E402
from isitmyisp.config import Tunnel  # noqa: E402
from isitmyisp.monitor import Monitor  # noqa: E402
from isitmyisp.probes.icmp import WindowStats  # noqa: E402
from isitmyisp import settings as settings_mod  # noqa: E402
from isitmyisp.services import Check, Service  # noqa: E402
from isitmyisp.snmp import LinkUsage  # noqa: E402
from isitmyisp.store import Store  # noqa: E402

ANCHORS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
WIN = 30.0


def w(target: str, n: int, received: int, med: float) -> WindowStats:
    ok = received > 0
    return WindowStats(target, n, received, med if ok else None, med if ok else None, med if ok else None,
                       0.6 if ok else None, med if ok else None)


def main(path: str, hours: float = 24.0, seed: int = 7) -> None:
    random.seed(seed)
    store = Store(path)
    t0 = time.time() - hours * 3600
    store.add_network({"isp_name": "Example ISP S.A.", "isp_asn": "AS64500", "wireless": True, "cgnat": False,
                       "tunnels": ["branch-office"]}, ts=t0)
    tunnel = Tunnel("branch-office", "198.51.100.20", "10.10.0.1", "ipsec-l2tp")
    services = [Service("Banking portal", "http", "https://bank.example"), Service("ERP", "tcp", "erp.example:443")]
    settings_mod.save(store, {
        "tunnels": [{"name": tunnel.name, "underlay": tunnel.underlay, "overlay": tunnel.overlay, "type": tunnel.type}],
        "services": [{"name": s.name, "kind": s.kind, "target": s.target} for s in services],
        "link": {"enabled": True, "host": "192.168.1.1", "community": "demo-ro", "port": 161, "interface": "ether1",
                 "down_mbps": 300, "up_mbps": 100}})
    checks: dict[str, list[Check]] = {s.name: [] for s in services}

    clock = {"now": t0}

    def capture(target: str, iid: int) -> None:
        loss = random.choice([18.0, 26.7, 33.3])
        hops = [("192.168.1.1", 0, 1.6, "ok", None, None),
                ("203.0.113.1", 0, 4.4, "ok", "AS64500", "Example ISP S.A."),
                ("203.0.113.9", loss, 31.0, "real_loss", "AS64500", "Example ISP S.A."),
                ("???", 100, 0, "no_reply", None, None),
                ("198.51.100.7", loss, 36.0, "real_loss", "AS64500", "Example ISP S.A."),
                (target, loss, 33.0, "real_loss", "AS13335", "Cloudflare, Inc.")]
        store.add_capture(iid, "mtr", target, {
            "target": target, "reached": True, "destination_loss": loss, "loss_starts_at": 3,
            "hops": [{"index": i + 1, "host": h, "loss": l, "sent": 30, "avg": a, "best": a * .9, "worst": a * 1.6,
                      "status": s, "asn": asn, "as_name": nm} for i, (h, l, a, s, asn, nm) in enumerate(hops)]},
            ts=clock["now"])

    mon = Monitor(store, WIN, capture=capture, recapture_every=600)
    n_windows = int(hours * 3600 / WIN)
    for i in range(n_windows):
        now = t0 + (i + 1) * WIN
        clock["now"] = now
        n = 15
        isp_bad = 0.58 * n_windows <= i < 0.66 * n_windows or 0.86 * n_windows <= i < 0.94 * n_windows
        wifi_bad = 0.26 * n_windows <= i < 0.285 * n_windows
        lost_a = (round(n * random.uniform(.25, .4)) if isp_bad else round(n * .35) if wifi_bad
                  else (1 if random.random() < .03 else 0))
        lost_h = round(n * .35) if wifi_bad else 0
        lat = 30 + random.gauss(0, 1.2) + (45 if isp_bad else 0)
        home = [w("192.168.1.1", n, n - lost_h, 2.0 + (20 if wifi_bad else 0))]
        anchors = [w(a, n, n - lost_a, lat + random.gauss(0, .6)) for a in ANCHORS]
        tcp = {a: w(f"tcp://{a}:443", 10, 10 - round(10 * lost_a / n), lat + 1) for a in ANCHORS}
        hour = time.localtime(now).tm_hour
        busy = 9 <= hour < 19
        down = max(3.0, random.gauss(110 if busy else 25, 30 if busy else 8))
        link = LinkUsage(round(down, 1), round(down * .18, 1), round(100 * down / 300, 1), round(18 * down / 100, 1),
                         round(random.uniform(8, 22), 1))
        m = Measurements(home, w("203.0.113.1", n, n, 4.4), anchors, tcp, wireless=True, link=link)
        erp_down = 0.72 * n_windows <= i < 0.75 * n_windows   # the ERP vendor's outage while internet is fine
        for s in services:
            ok = not (s.name == "ERP" and erp_down)
            checks[s.name].append(Check(now, ok, (180 if s.kind == "http" else 45) + random.gauss(0, 8) if ok else None,
                                        "HTTP 200" if ok else "timeout"))
            checks[s.name] = checks[s.name][-10:]
        rows = [("home", home[0]), ("isp", m.isp_hop)] + [("anchor", a) for a in anchors]
        minute = (i * WIN) / 60
        rekey_drop = minute % 120 < 2.5 and minute > 5          # ~2.5 min down every 2 h, path clean
        path_drop = 0.40 * n_windows <= i < 0.42 * n_windows    # far site's link losing packets
        under = w(tunnel.underlay, n, n - (round(n * .5) if path_drop else 0), 41.0)
        over = w(tunnel.overlay, n, 0 if rekey_drop else (n - round(n * .5) if path_drop else n), 43.0)
        mon.step(m, rows, now=now, tunnels=[(tunnel, under, over)],
                 services=[(s, list(checks[s.name])) for s in services])
    store.close()
    print(f"synthetic demo data written to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
