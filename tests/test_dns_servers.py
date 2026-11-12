"""Which DNS servers get measured: the real ones, not a local forwarder (Tailscale, systemd-resolved)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from isitmyisp import discovery
from isitmyisp import settings as settings_mod
from isitmyisp.store import Store


def detect(resolv: str, resolvectl: str = "", systemd: str | None = None, gateway: str = "192.168.1.1",
           answering=("192.168.1.1", "127.0.0.1")):
    files = {"/etc/resolv.conf": resolv, "/run/systemd/resolve/resolv.conf": systemd}

    def nameservers(path):
        text = files.get(path)
        return [] if text is None else [l.split()[1] for l in text.splitlines() if l.startswith("nameserver")]
    with mock.patch.object(discovery, "_nameservers", nameservers), \
            mock.patch.object(discovery, "_run", lambda cmd: resolvectl), \
            mock.patch.object(discovery, "_answers_dns", lambda server: server in answering):
        return discovery.dns_servers("eth0", gateway)


class Detection(unittest.TestCase):
    def test_plain_resolv_conf(self):
        self.assertEqual(detect("nameserver 192.168.1.1\nnameserver 8.8.8.8\n"), ["192.168.1.1", "8.8.8.8"])

    def test_tailscale_magicdns_is_not_your_dns(self):
        # what Tailscale writes: its own forwarder, and an IPv6 one
        ts = "nameserver 100.100.100.100\nnameserver fd7a:115c:a1e0::53\nsearch tail764ff5.ts.net\n"
        self.assertEqual(detect(ts), ["192.168.1.1"])                         # the router, as a last resort
        self.assertEqual(detect(ts, systemd="nameserver 192.168.1.22\n"), ["192.168.1.22"])

    def test_a_real_server_next_to_the_forwarder_is_kept(self):
        self.assertEqual(detect("nameserver 100.100.100.100\nnameserver 192.168.1.22\n"), ["192.168.1.22"])

    def test_systemd_resolved_stub(self):
        self.assertEqual(detect("nameserver 127.0.0.53\n", resolvectl="Link 2 (eth0): 192.168.1.1 1.1.1.1"),
                         ["192.168.1.1", "1.1.1.1"])

    def test_nothing_found_falls_back_to_the_router(self):
        self.assertEqual(detect(""), ["192.168.1.1"])

    def test_a_router_that_doesnt_answer_dns_is_not_measured(self):
        # many business routers and firewalls don't: measuring one would blame "your DNS" forever
        ts = "nameserver 100.100.100.100\n"
        self.assertEqual(detect(ts, answering=()), [])
        self.assertEqual(detect("", answering=()), [])

    def test_adguard_or_pihole_on_this_machine(self):
        self.assertEqual(detect("nameserver 127.0.0.1\n"), ["127.0.0.1"])
        # nothing listening there: not a resolver after all, so the router (if it answers)
        self.assertEqual(detect("nameserver 127.0.0.1\n", answering=("192.168.1.1",)), ["192.168.1.1"])

    def test_both_systemd_stubs(self):
        self.assertEqual(detect("nameserver 127.0.0.54\n", systemd="nameserver 10.0.0.1\n"), ["10.0.0.1"])

    def test_a_server_from_resolv_conf_is_not_checked(self):
        # the one this machine really uses: if it fails, that's a DNS problem worth reporting
        self.assertEqual(detect("nameserver 10.9.9.9\n", answering=()), ["10.9.9.9"])


class Setting(unittest.TestCase):
    def test_validation(self):
        ok = settings_mod.validate({"dns": ["127.0.0.1", "192.168.1.22", "192.168.1.22"]})
        self.assertEqual(ok["dns"], ["127.0.0.1", "192.168.1.22"])            # AdGuard on this machine is fine
        self.assertEqual(settings_mod.validate({"dns": []})["dns"], [])        # empty: automatic
        for bad in (["adguard.local"], ["fd7a::53"], ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"],
                    ["0.0.0.0"], ["224.0.0.251"], ["255.255.255.255"]):
            with self.assertRaises(settings_mod.SettingsError):
                settings_mod.validate({"dns": bad})

    def test_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "t.db")
            settings_mod.save(store, {"dns": ["192.168.1.22"]})
            self.assertEqual(settings_mod.load(store).dns, ["192.168.1.22"])
            store.close()

    def test_the_setting_wins_over_detection(self):
        from isitmyisp import cli
        net = discovery.Network(dns_servers=["100.100.100.100"])
        cfg = settings_mod.Settings(dns=["192.168.1.22"])
        with mock.patch.object(cli, "discover", lambda **kw: net):
            out = cli._discover(mock.Mock(asn_online=False, public_ip=False), cfg)
        self.assertEqual((out.dns_servers, out.dns_detected), (["192.168.1.22"], ["100.100.100.100"]))


if __name__ == "__main__":
    unittest.main()
