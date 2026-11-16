import tempfile
import time
import unittest
from pathlib import Path

from isitmyisp import doctor
from isitmyisp.discovery import Network, PathHop
from isitmyisp.doctor import Facts, Mtu, grade, probe_mtu, run_checks
from isitmyisp.lan import LanStats
from isitmyisp.probes.mtr import Hop
from isitmyisp.texts import DOCTOR, DOCTOR_NAME, doctor_text


def net(**kw):
    n = Network(gateway="192.168.1.1", interface="eth0", dns_servers=["192.168.1.1"],
                path=[PathHop(Hop(1, "192.168.1.1", 0.0, 5, 1.0, 1.0, 1.0, 0.0), "home")])
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def healthy(**kw):
    f = Facts(net=net(), dns_ms={"192.168.1.1": [12.0, 9.0, None]}, dns_trapped=False,
              mtu=Mtu(iface=1500, path=1500), speed_mbps=1000, duplex="full", errors_before=3, errors_after=3,
              plan_mbps=300, router_uptime_s=9 * 86400, lan=LanStats(0, 15, ["aa:bb:cc:dd:ee:ff"], 0, 4.0, 4.0),
              seconds=15)
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def by_id(f):
    return {c.id: c for c in run_checks(f)}


class Checks(unittest.TestCase):
    def test_healthy_network_is_all_green_and_an_A(self):
        checks = run_checks(healthy())
        self.assertEqual({c.status for c in checks}, {"ok"})
        self.assertEqual(grade(checks), "A")

    def test_each_check_says_its_scope(self):
        c = by_id(healthy())
        self.assertEqual({k for k, v in c.items() if v.scope == "probe"}, {"link_speed", "nic_errors", "wifi"})

    def test_cgnat_and_double_nat_are_yellow(self):
        c = by_id(healthy(net=net(cgnat=True, double_nat=True, nat_hops=["192.168.0.1", "100.64.0.1"],
                                  home_routers=["192.168.1.1", "192.168.0.1"])))
        self.assertEqual((c["cgnat"].status, c["cgnat"].params["hops"]), ("warn", "100.64.0.1"))
        self.assertEqual(c["double_nat"].status, "warn")

    def test_no_path_means_skip_not_green(self):
        c = by_id(healthy(net=net(path=[])))
        self.assertEqual((c["cgnat"].status, c["double_nat"].status), ("skip", "skip"))

    def test_ipv6_announced_but_broken_is_red(self):
        self.assertEqual(by_id(healthy(net=net(ipv6_global=True)))["ipv6"].status, "bad")
        self.assertEqual(by_id(healthy(net=net(ipv6_global=True, ipv6_works=True)))["ipv6"].status, "ok")
        self.assertEqual(by_id(healthy())["ipv6"].key, "ipv6_none")

    def test_dns(self):
        dns = lambda d: by_id(healthy(dns_ms=d))["dns"]
        self.assertEqual(dns({}).key, "dns_none")
        self.assertEqual(dns({"1.1.1.1": [None, None]}).status, "bad")
        self.assertEqual(dns({"1.1.1.1": [None], "8.8.8.8": [20.0]}).key, "dns_some_dead")
        self.assertEqual(dns({"1.1.1.1": [200.0, 220.0]}).status, "warn")
        self.assertEqual(dns({"1.1.1.1": [600.0, 500.0]}).status, "bad")
        self.assertIn("1.1.1.1 12 ms", dns({"1.1.1.1": [12.0]}).params["ms"])

    def test_dns_interception(self):
        self.assertEqual(by_id(healthy(dns_trapped=True))["dns_trap"].status, "warn")
        self.assertEqual(by_id(healthy(dns_trapped=None))["dns_trap"].status, "skip")

    def test_mtu(self):
        mtu = lambda m: by_id(healthy(mtu=m))["mtu"]
        self.assertEqual(mtu(Mtu(1500, 1492, signalled=True)).key, "mtu_lower")
        self.assertEqual(mtu(Mtu(1500, 1400, blackhole=True)).status, "bad")
        self.assertEqual(mtu(Mtu(1500, no_icmp=True)).status, "skip")

    def test_router_restart(self):
        c = by_id(healthy(router_uptime_s=2 * 3600))["router_uptime"]
        self.assertEqual((c.status, c.params["ago"]), ("warn", "2 h"))
        self.assertEqual(by_id(healthy(router_uptime_s=None))["router_uptime"].status, "skip")

    def test_loop(self):
        storm = LanStats(dups=6, replies=20, mcast_pps=3000, mcast_base=5)
        c = by_id(healthy(lan=storm))["loop"]
        self.assertEqual(c.status, "bad")
        self.assertIn("duplicate replies", c.params["signals"])
        self.assertEqual(by_id(healthy(lan=LanStats()))["loop"].status, "skip")   # nothing could be read

    def test_link_speed(self):
        ls = lambda **kw: by_id(healthy(**kw))["link_speed"]
        self.assertEqual(ls(speed_mbps=100).key, "link_speed_below_plan")       # 100 Mb/s card, 300 Mb/s plan
        self.assertEqual(ls(speed_mbps=100, plan_mbps=0).key, "link_speed_slow")
        self.assertEqual(ls(speed_mbps=100, plan_mbps=50).status, "ok")
        self.assertEqual(ls(duplex="half").status, "bad")
        self.assertEqual(ls(net=net(wireless=True)).status, "skip")

    def test_nic_errors_must_grow_during_the_run(self):
        self.assertEqual(by_id(healthy(errors_before=3, errors_after=3))["nic_errors"].status, "ok")
        c = by_id(healthy(errors_before=3, errors_after=40))["nic_errors"]
        self.assertEqual((c.status, c.params["n"]), ("bad", 37))

    def test_wifi_probe_is_yellow(self):
        self.assertEqual(by_id(healthy(net=net(wireless=True, interface="wlan0")))["wifi"].status, "warn")

    def test_grade(self):
        mk = lambda *st: [doctor.Check("x", "network", s, "wifi_no") for s in st]
        self.assertEqual(grade(mk("ok", "skip")), "A")
        self.assertEqual(grade(mk("warn")), "B")
        self.assertEqual(grade(mk("bad")), "C")
        self.assertEqual(grade(mk("bad", "bad")), "D")
        self.assertEqual(grade(mk("bad", "bad", "bad")), "F")

    def test_round_trip(self):
        checks = run_checks(healthy(lan=LanStats(dups=6, replies=20)))
        d = doctor.to_dict(checks, ts=100.0)
        self.assertEqual((d["ts"], d["grade"]), (100.0, grade(checks)))
        self.assertEqual(doctor.from_dict(d), checks)


class Texts(unittest.TestCase):
    def test_every_key_exists_in_both_languages(self):
        self.assertEqual(set(DOCTOR["en"]), set(DOCTOR["es"]))
        self.assertEqual(set(DOCTOR_NAME["en"]), {c(healthy()).id for c in doctor.CHECKS})
        self.assertEqual(set(DOCTOR_NAME["es"]), set(DOCTOR_NAME["en"]))

    def test_all_reachable_keys_format(self):
        for f in (healthy(), healthy(net=net(cgnat=True, double_nat=True, ipv6_global=True, path=[])),
                  healthy(lan=LanStats(dups=6, replies=20), speed_mbps=10, errors_after=9, dns_trapped=True)):
            for c in run_checks(f):
                for lang in ("en", "es"):
                    text, _ = doctor_text(c.key, c.params, lang)
                    self.assertNotIn("{", text, c.key)

    def test_loop_evidence_in_spanish(self):
        c = by_id(healthy(lan=LanStats(dups=6, replies=20)))["loop"]
        self.assertIn("respuestas duplicadas", doctor_text(c.key, c.params, "es")[0])


class MtuProbe(unittest.TestCase):
    def fake(self, limit, hint=None, icmp=True):
        def ping(size):
            if size + 28 <= limit:
                return icmp, None
            return False, hint
        return ping

    def test_full_size_goes_through(self):
        self.assertEqual(probe_mtu(1500, self.fake(1500)), Mtu(1500, 1500))

    def test_too_big_is_reported(self):
        self.assertEqual(probe_mtu(1500, self.fake(1492, hint=1492)), Mtu(1500, 1492, signalled=True))

    def test_black_hole_is_found(self):
        m = probe_mtu(1500, self.fake(1400))
        self.assertTrue(m.blackhole)
        self.assertTrue(1392 <= m.path <= 1400)

    def test_no_icmp(self):
        self.assertTrue(probe_mtu(1500, self.fake(1500, icmp=False)).no_icmp)


class Sysfs(unittest.TestCase):
    def test_reads_speed_mtu_duplex_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d, "eth0", "statistics")
            st.mkdir(parents=True)
            for name, val in (("speed", "100"), ("mtu", "1500"), ("duplex", "full")):
                Path(d, "eth0", name).write_text(val + "\n")
            (st / "rx_errors").write_text("4\n")
            (st / "tx_errors").write_text("1\n")
            self.assertEqual(doctor.nic_link("eth0", d), (100, 1500, "full"))
            self.assertEqual(doctor.nic_errors("eth0", d), 5)
            Path(d, "eth0", "speed").write_text("-1\n")              # Wi-Fi / link down
            self.assertEqual(doctor.nic_link("eth0", d)[0], None)
            self.assertIsNone(doctor.nic_errors("wlan9", d))


class Stored(unittest.TestCase):
    T1, T2 = time.time() - 2 * 86400, time.time() - 3600

    def setUp(self):
        from isitmyisp.store import Store
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "d.db")
        bad = healthy(lan=LanStats(dups=6, replies=20), net=net(cgnat=True, nat_hops=["100.64.0.1"]))
        self.store.add_doctor(doctor.to_dict(run_checks(healthy()), ts=self.T1))
        self.store.add_doctor(doctor.to_dict(run_checks(bad), ts=self.T2))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_latest_run_up_to_a_moment(self):
        self.assertEqual(self.store.last_doctor()["ts"], self.T2)
        self.assertEqual(self.store.last_doctor(until=self.T2 - 60)["grade"], "A")
        self.assertIsNone(self.store.last_doctor(until=self.T1 - 60))

    def test_report_section(self):
        from isitmyisp.report import R, doctor_section
        self.assertEqual(doctor_section(None, R["en"], "en"), "")
        html = doctor_section(self.store.last_doctor(), R["es"], "es")
        self.assertIn("Revisado del lado del cliente", html)
        self.assertIn("respuestas duplicadas", html)
        self.assertIn("Solo esta máquina", html)

    def test_web_page(self):
        from isitmyisp.webapp import create_app
        app = create_app(self.store, data_dir=Path(self.tmp.name))
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.store.set_settings({"auth_mode": "none"})
        c = app.test_client()
        page = c.get("/doctor?lang=es").get_data(as_text=True)
        self.assertIn("Chequeo de la red", page)
        self.assertIn("Toda la red", page)
        self.assertIn("Loops y tormentas", page)
        self.assertIn("Qué hacer", page)          # the red loop line comes with advice

    def test_monitor_runs_it_once_a_day_or_when_asked(self):
        from isitmyisp import cli
        started = []
        orig = doctor.gather
        doctor.gather = lambda n, link, **kw: started.append(1) or healthy()
        try:
            self.assertIsNone(cli._doctor_if_due(self.store, net(), {}))                # ran an hour ago
            self.store.set_settings({"_doctor_request": self.T2 + 60}, bump=False)     # "Check now"
            cli._doctor_if_due(self.store, net(), {}).join(5)
            self.assertEqual(started, [1])
            self.assertGreater(self.store.last_doctor()["ts"], self.T2)
            self.assertIsNone(cli._doctor_if_due(self.store, net(), {}))          # just ran
        finally:
            doctor.gather = orig


if __name__ == "__main__":
    unittest.main()
