"""The periodic re-discovery runs beside the probes: the monitor keeps measuring through it."""

import threading
import unittest

from isitmyisp.cli import BackgroundDiscovery, probe_key

SNAP = {"gateway": "192.168.1.1", "interface": "eth0", "wireless": False, "home_routers": ["192.168.1.1"],
        "isp_hop": "181.89.4.100", "isp_asn": 7303, "dns_servers": ["192.168.1.1"],
        "path": [{"index": 1, "host": "192.168.1.1"}], "isp_name": "Telecom"}


class ProbeKey(unittest.TestCase):
    def test_path_details_do_not_restart_the_session(self):
        newer = dict(SNAP, path=[], isp_name="Telecom Argentina", cgnat=True)
        self.assertEqual(probe_key(newer), probe_key(SNAP))

    def test_anything_probed_does(self):
        for field, value in (("gateway", "10.0.0.1"), ("isp_hop", "181.89.4.1"), ("isp_asn", 22927),
                             ("dns_servers", ["1.1.1.1"]), ("home_routers", ["192.168.1.1", "10.0.0.1"]),
                             ("wireless", True), ("interface", "wlan0")):
            with self.subTest(field=field):
                self.assertNotEqual(probe_key(dict(SNAP, **{field: value})), probe_key(SNAP))


class Background(unittest.TestCase):
    def test_runs_without_blocking_and_reports(self):
        gate = threading.Event()
        job = BackgroundDiscovery(lambda: gate.wait(5) and "net")
        self.assertFalse(job.done())   # the loop goes on measuring meanwhile
        gate.set()
        job._thread.join(5)
        self.assertTrue(job.done())
        self.assertEqual(job.result, "net")

    def test_a_failure_is_kept_not_raised(self):
        job = BackgroundDiscovery(lambda: 1 / 0)
        job._thread.join(5)
        self.assertIsNone(job.result)
        self.assertIsInstance(job.error, ZeroDivisionError)


if __name__ == "__main__":
    unittest.main()
