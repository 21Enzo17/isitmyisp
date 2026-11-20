"""Route changes (#97): read a path, know when the ISP changes it, judge the impact, diagnose incidents."""

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from isitmyisp import alerts, routes
from isitmyisp.config import Tunnel
from isitmyisp.probes.icmp import WindowStats
from isitmyisp.probes.mtr import Hop
from isitmyisp.store import Store
from tests._web import HAVE_WEB
from tests.test_webapp import WebAppBase

ASN = {"181.96.60.1": ("7303", "Telecom Argentina S.A."), "181.96.60.162": ("7303", "Telecom Argentina S.A."),
       "181.89.51.39": ("7303", "Telecom Argentina S.A."),
       "200.16.1.1": ("4270", "Red de Interconexion Universitaria"), "200.16.9.9": ("4270", "Red de Interconexion Universitaria"),
       "190.103.1.1": ("52361", "ARSAT - Empresa Argentina de Soluciones Satelitales S.A."),
       "1.1.1.1": ("13335", "Cloudflare, Inc."), "172.70.1.1": ("13335", "Cloudflare, Inc."),
       "172.70.9.9": ("13335", "Cloudflare, Inc.")}


def hops(*hosts: str) -> list[Hop]:
    """mtr hops; '???' is a hop that never answers. RTT grows along the path."""
    return [Hop(i, h, 100.0 if h == "???" else 0.0, 3, 1.0 + 3 * i, 1.0 + 3 * i, 2.0 + 3 * i, 0.1)
            for i, h in enumerate(hosts, 1)]


USUAL = ("192.168.1.1", "181.96.60.1", "???", "181.96.60.162", "190.103.1.1", "172.70.1.1", "1.1.1.1")
OTHER = ("192.168.1.1", "181.96.60.1", "???", "181.89.51.39", "200.16.1.1", "200.16.9.9", "172.70.1.1", "1.1.1.1")
CUT_ISP = ("192.168.1.1", "181.96.60.1", "???", "181.96.60.162", "???", "???", "???")


def obs(path, ts=0.0):
    return routes.observe(hops(*path), ASN, ts=ts)


class OrgNames(unittest.TestCase):
    def test_suffixes_go(self):
        self.assertEqual(routes.org_name("Telecom Argentina S.A.", "7303"), "Telecom")
        self.assertEqual(routes.org_name("Cloudflare, Inc.", "13335"), "Cloudflare")
        self.assertEqual(routes.org_name("Google LLC", "15169"), "Google")
        self.assertEqual(routes.org_name(None, "7303"), "AS7303")
        self.assertIsNone(routes.org_name(None, None))


class Reading(unittest.TestCase):
    def test_home_is_left_out_and_orgs_in_order(self):
        o = obs(USUAL)
        self.assertTrue(o.reached)
        self.assertNotIn(1, o.prefixes())
        self.assertEqual(routes.orgs(o), ["Telecom", "ARSAT - Empresa", "Cloudflare"][:1] + routes.orgs(o)[1:])
        self.assertEqual(routes.orgs(o)[0], "Telecom")
        self.assertEqual(routes.orgs(o)[-1], "Cloudflare")

    def test_compare(self):
        k = routes.known_from(obs(USUAL), 1)
        self.assertEqual(routes.compare(k, obs(USUAL)), "same")
        self.assertEqual(routes.compare(k, obs(OTHER)), "diverged")
        self.assertEqual(routes.compare(k, obs(CUT_ISP)), "cut")

    def test_a_quiet_hop_is_not_a_change(self):
        k = routes.known_from(obs(USUAL), 1)
        quiet = list(USUAL)
        quiet[4] = "???"
        self.assertEqual(routes.compare(k, obs(quiet)), "same")

    def test_load_balancing_on_the_same_link_is_not_a_change(self):
        k = routes.known_from(obs(USUAL), 1)
        ecmp = list(USUAL)
        ecmp[3] = "181.96.60.170"   # another router in the same /24
        self.assertEqual(routes.compare(k, obs(ecmp)), "same")

    def test_roundtrip(self):
        o = obs(OTHER, ts=5.0)
        back = routes.Obs.from_dict(o.to_dict())
        self.assertEqual(back.prefixes(), o.prefixes())
        self.assertEqual(routes.orgs(back), routes.orgs(o))


class Tracking(unittest.TestCase):
    def feed(self, tr, path, n, t0):
        out = []
        for i in range(n):
            ev = tr.observe(obs(path, ts=t0 + i * routes.ROUND))
            if ev:
                out.append(ev)
        return out

    def test_change_needs_confirmation_then_restored(self):
        tr = routes.Tracker()
        self.assertEqual(self.feed(tr, USUAL, 30, 0), [])
        # one trace on another path is not enough
        self.assertIsNone(tr.observe(obs(OTHER, ts=30 * routes.ROUND)))
        self.assertIsNone(tr.observe(obs(USUAL, ts=31 * routes.ROUND)))
        evs = self.feed(tr, OTHER, 4, 32 * routes.ROUND)
        self.assertEqual([e["kind"] for e in evs], ["changed"])
        self.assertEqual(evs[0]["ts"], 32 * routes.ROUND)   # when it was first seen, not confirmed
        evs = self.feed(tr, USUAL, 3, 36 * routes.ROUND)
        self.assertEqual([e["kind"] for e in evs], ["restored"])

    def test_an_outage_on_the_usual_path_is_not_a_change(self):
        tr = routes.Tracker()
        self.feed(tr, USUAL, 10, 0)
        self.assertEqual(self.feed(tr, CUT_ISP, 5, 10 * routes.ROUND), [])

    def test_flapping_is_unstable(self):
        tr = routes.Tracker()
        self.feed(tr, USUAL, 10, 0)
        evs = []
        t = 10 * routes.ROUND
        for path in (OTHER, USUAL, OTHER):
            evs += self.feed(tr, path, 2, t)
            t += 2 * routes.ROUND
        self.assertEqual(len(evs), 3)
        self.assertTrue(evs[-1]["unstable"])

    def test_state_survives_a_restart(self):
        tr = routes.Tracker()
        self.feed(tr, USUAL, 5, 0)
        tr2 = routes.Tracker(tr.to_dict())
        self.assertIsNone(tr2.observe(obs(USUAL, ts=6 * routes.ROUND)))
        self.assertEqual(tr2.current, tr.current)

    def test_nothing_past_home_says_nothing(self):
        tr = routes.Tracker()
        self.assertIsNone(tr.observe(obs(("192.168.1.1", "???", "???"))))
        self.assertEqual(tr.known, [])


class Severity(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(routes.severity(None), "none")
        self.assertEqual(routes.severity({"before_ms": 20, "after_ms": 25, "before_loss": 0, "after_loss": 0}), "none")
        self.assertEqual(routes.severity({"before_ms": 20, "after_ms": 40, "before_loss": 0, "after_loss": 0}), "worse")
        self.assertEqual(routes.severity({"before_ms": 20, "after_ms": 60, "before_loss": 0, "after_loss": 0}), "much_worse")
        self.assertEqual(routes.severity({"before_ms": 20, "after_ms": 20, "before_loss": 0, "after_loss": 3}), "much_worse")


class Targets(unittest.TestCase):
    def test_from_settings(self):
        svc = [SimpleNamespace(name="ARCA", kind="http", target="https://auth.afip.gob.ar/x"),
               SimpleNamespace(name="DB", kind="tcp", target="203.0.113.5:5432")]
        ts = routes.targets(["1.1.1.1"], [Tunnel("HQ", "198.51.100.7", "10.0.0.1")], svc)
        self.assertEqual([(t.key, t.host, t.group) for t in ts], [
            ("anchor:1.1.1.1", "1.1.1.1", "internet"), ("tunnel:HQ", "198.51.100.7", "tunnel:HQ"),
            ("service:ARCA", "auth.afip.gob.ar", "service:ARCA"), ("service:DB", "203.0.113.5", "service:DB")])


def window(target, rtt, sent=10, received=10):
    return WindowStats(target, sent, received, rtt, rtt, rtt, 0.5, rtt)


class WatcherFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.addCleanup(self.store.close)
        self.path = USUAL
        self.target = routes.Target("anchor:1.1.1.1", "1.1.1.1", "internet", "1.1.1.1", "anchor", "1.1.1.1")
        patcher = mock.patch.object(routes.asn, "lookup", lambda ips, **kw: ASN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w = routes.Watcher(self.store, lambda: [self.target], tracer=lambda host: hops(*self.path))

    def latency(self, start, end, rtt):
        t = start
        while t < end:
            self.store.add_window("anchor", window("1.1.1.1", rtt), ts=t)
            t += 60
        self.store.commit()

    def test_slower_path_opens_an_incident_and_restore_closes_it(self):
        t0 = 1_800_000_000.0
        for i in range(6):
            self.w.round(t0 + i * routes.ROUND)
        t_change = t0 + 6 * routes.ROUND
        self.latency(t0, t_change, 20.0)
        self.path = OTHER
        self.w.round(t_change)
        self.w.round(t_change + routes.ROUND)
        evs = self.store.route_events_between(0, 2e10, kinds=("changed",))
        self.assertEqual(len(evs), 1)
        self.assertIn("Telecom", routes.change_line(evs[0]["data"], "en"))
        self.latency(t_change, t_change + 3 * routes.ROUND, 70.0)
        self.w.round(t_change + routes.IMPACT_AFTER - 1)
        self.assertEqual(self.store.active_incidents(), [])        # too soon to judge
        self.w.round(t_change + 2 * routes.ROUND)
        active = self.store.active_incidents()
        self.assertEqual([(i.scope, i.code) for i in active], [("route:internet", "route_slower")])
        self.assertIn("20 ms → 70 ms", active[0].evidence[0])
        title, _ = alerts.describe(active[0], "opened", "es")
        self.assertIn("Internet", title)
        self.assertIn("más lento", title)
        # back on the usual path
        self.path = USUAL
        self.w.round(t_change + 4 * routes.ROUND)
        self.w.round(t_change + 5 * routes.ROUND)
        self.assertEqual(self.store.active_incidents(), [])

    def test_a_harmless_change_opens_nothing(self):
        t0 = 1_800_000_000.0
        for i in range(4):
            self.w.round(t0 + i * routes.ROUND)
        t_change = t0 + 4 * routes.ROUND
        self.latency(t0, t_change + 4 * routes.ROUND, 20.0)
        self.path = OTHER
        for i in range(4):
            self.w.round(t_change + i * routes.ROUND)
        self.assertEqual(self.store.active_incidents(), [])
        ev = self.store.route_events_between(0, 2e10, kinds=("changed",))[0]
        self.assertEqual(ev["data"]["severity"], "none")

    def test_harmless_alternation_is_learned_as_one_path(self):
        # two paths that alternate and cost nothing are load balancing: after the first change is judged
        # harmless, going back and forth says nothing more (#102)
        t0 = 1_800_000_000.0
        for i in range(4):
            self.w.round(t0 + i * routes.ROUND)
        t = t0 + 4 * routes.ROUND
        self.latency(t0, t + 20 * routes.ROUND, 440.0)
        self.path = OTHER
        for i in range(3):
            self.w.round(t + i * routes.ROUND)
        self.assertEqual(len(self.store.route_events_between(0, 2e10, kinds=("changed", "restored"))), 1)
        ev = self.store.route_events_between(0, 2e10, kinds=("changed",))[0]
        self.assertEqual(ev["data"]["severity"], "none")
        self.assertTrue(ev["data"].get("merged"))
        t += 3 * routes.ROUND
        for k, path in enumerate((USUAL, USUAL, OTHER, OTHER, USUAL, USUAL)):
            self.path = path
            self.w.round(t + k * routes.ROUND)
        self.assertEqual(len(self.store.route_events_between(0, 2e10, kinds=("changed", "restored"))), 1)
        # and it survives a restart
        w2 = routes.Watcher(self.store, lambda: [self.target], tracer=lambda host: hops(*OTHER))
        for k in range(3):
            w2.round(t + (10 + k) * routes.ROUND)
        self.assertEqual(len(self.store.route_events_between(0, 2e10, kinds=("changed", "restored"))), 1)

    def test_diagnosis_of_an_incident(self):
        t0 = time.time() - 3600
        for i in range(4):
            self.w.round(t0 + i * 60)
        iid = self.store.open_incident("isp", ["loss"], ts=time.time(), scope="internet")
        self.path = CUT_ISP
        self.w.incident_opened("internet", iid)
        self.w._last_round = time.time()   # only the urgent work
        self.w.tick()
        inc = self.store.active_incidents()[0]
        lines = routes.diagnosis_lines(self.store, inc, "es")
        self.assertEqual(len(lines), 1)
        self.assertIn("es el de siempre y se corta después de Telecom (181.96.60.162)", lines[0])
        self.assertIn("dentro de la red de tu proveedor", lines[0])
        _, body = alerts.describe(inc, "opened", "es", path=lines)
        self.assertIn("Camino: El camino hacia 1.1.1.1", body)

    def test_diagnosis_names_a_change_just_before(self):
        t0 = time.time() - 3600
        for i in range(4):
            self.w.round(t0 + i * 60)
        self.path = OTHER
        self.w.round(time.time() - 300)
        self.w.round(time.time() - 240)
        iid = self.store.open_incident("isp", ["loss"], ts=time.time(), scope="internet")
        self.w.diagnose("internet", iid)
        lines = routes.diagnosis_lines(self.store, self.store.active_incidents()[0], "en")
        self.assertTrue(lines[0].startswith("Your ISP changed the path to 1.1.1.1 at"), lines)

    def test_state_is_saved_without_reloading_the_monitor(self):
        v = self.store.settings_version()
        self.w.round(1_800_000_000.0)
        self.assertIn("anchor:1.1.1.1", self.store.get_setting("_routes"))
        self.assertEqual(self.store.settings_version(), v)

    def test_old_events_are_pruned(self):
        self.store.add_route_event(1.0, "anchor:1.1.1.1", "internet", "changed", {})
        self.store.prune(now=500 * 86400)
        self.assertEqual(self.store.route_events_between(0, 2e10), [])


@unittest.skipUnless(HAVE_WEB, "web extra not installed")
class Diagram(unittest.TestCase):
    """Before and after as boxes, and where the change is (#97)."""

    def ev(self, a, b):
        return {"from": obs(a).to_dict(), "to": obs(b).to_dict()}

    def test_a_carrier_past_the_isp(self):
        g = routes.diagram(self.ev(USUAL, OTHER), "en")
        telecom, arsat, cf = routes.orgs(obs(USUAL))
        uni = routes.orgs(obs(OTHER))[1]
        self.assertEqual([n["name"] for n in g["before"]], [telecom, arsat, cf])
        self.assertEqual([n["state"] for n in g["before"]], ["same", "gone", "same"])
        self.assertEqual([n["state"] for n in g["after"]], ["same", "new", "same"])
        self.assertEqual(g["after"][1]["hops"], ["200.16.1.1", "200.16.9.9"])
        self.assertEqual(g["where"], f"Your ISP ({telecom}) now sends your traffic through {uni} instead of {arsat}.")
        self.assertEqual(g["side"], "middle")
        self.assertEqual(g["dest"], cf)
        f = g["fork"]
        self.assertEqual([n["name"] for n in f["head"]], [telecom])
        self.assertEqual([n["name"] for n in f["before"]], [arsat])
        self.assertEqual([n["name"] for n in f["after"]], [uni])
        self.assertEqual([n["name"] for n in f["tail"]], [cf])

    def test_other_routers_inside_the_isp(self):
        inside = ("192.168.1.1", "181.96.60.1", "181.89.51.39", "190.103.1.1", "172.70.1.1", "1.1.1.1")
        g = routes.diagram(self.ev(USUAL, inside), "es")
        self.assertEqual([n["state"] for n in g["after"]], ["changed", "same", "same"])
        self.assertEqual(g["before"][0]["state"], "changed")
        self.assertIn("dentro de la red de tu proveedor", g["where"])
        self.assertEqual(g["side"], "isp")
        self.assertEqual(g["fork"]["head"], [])

    def test_other_routers_at_the_far_end(self):
        far = ("192.168.1.1", "181.96.60.1", "181.96.60.162", "190.103.1.1", "172.70.9.9", "1.1.1.1")
        g = routes.diagram(self.ev(USUAL, far), "en", far="site")
        self.assertEqual(g["side"], "far")
        self.assertIn("other site's side", g["where"])

    def test_a_path_that_no_longer_gets_there(self):
        g = routes.diagram(self.ev(USUAL, CUT_ISP), "en")
        self.assertTrue(g["before_reached"])
        self.assertFalse(g["after_reached"])
        self.assertEqual(g["fork"]["tail"], [])
        self.assertIn("no longer gets there", g["where"])

    def test_nothing_to_compare(self):
        g = routes.diagram({}, "en")
        self.assertEqual((g["before"], g["after"], g["where"]), ([], [], ""))


class Pages(WebAppBase):
    """The dashboard, the incidents page and the report show the path changes and the diagnosis."""
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(routes.asn, "lookup", lambda ips, **kw: ASN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = USUAL
        target = routes.Target("anchor:1.1.1.1", "1.1.1.1", "internet", "1.1.1.1", "anchor", "1.1.1.1")
        w = routes.Watcher(self.store, lambda: [target], tracer=lambda host: hops(*self.path))
        now = time.time()
        self.store.add_window_verdict("ok", 30.0, ts=now - 7300)   # monitoring started before the change
        for i in range(4):
            w.round(now - 7200 + i * 60)
        self.path = OTHER
        w.round(now - 3000)
        w.round(now - 2940)
        ev = self.store.route_events_between(0, now, kinds=("changed",))[0]
        ev["data"].update({"impact": {"before_ms": 20.0, "after_ms": 70.0, "before_loss": 0.0, "after_loss": 0.0},
                           "severity": "much_worse"})
        self.store.update_route_event(ev["id"], ev["data"])
        iid = self.store.open_incident("isp", ["loss"], ts=now - 600, scope="internet")
        self.path = CUT_ISP
        w.diagnose("internet", iid)
        self.store.close_incident(iid, ts=now - 300)
        self.store.commit()
        self.create_admin()

    def test_dashboard_lists_the_change(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('class="rc ', html)
        self.assertIn("rfork", html)
        self.assertIn("Red de Interconexion", html)
        self.assertIn("route-mark", html)
        self.assertIn("rf-node new", html)
        self.assertIn("20 → 70 ms", html)

    def test_card_folds_and_remembers(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="routes" open', html)              # open until you minimize it
        r = self.client.get("/fold?card=routes&to=closed&next=/%23routes")
        self.assertEqual(r.status_code, 302)
        self.assertIn("fold_routes=closed", r.headers["Set-Cookie"])
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="routes" aria-labelledby', html)  # minimized: only the title row
        self.assertIn('to=open', html)                         # the button expands it again
        self.client.get("/fold?card=routes&to=open")
        self.assertIn('id="routes" open', self.client.get("/").get_data(as_text=True))
        r = self.client.get("/fold?card=nope&to=closed&next=//evil.com")
        self.assertNotIn("fold_", r.headers.get("Set-Cookie", ""))
        self.assertNotIn("evil", r.headers["Location"])

    def test_wall_screen_names_an_ongoing_change(self):
        self.store.set_settings({"tv_token": "tok"})
        tv = self.app.test_client().get("/tv/tok").get_data(as_text=True)
        self.assertIn('class="tvb-alarm route"', tv)
        self.assertIn("The path to 1.1.1.1 changed", tv)
        self.assertNotIn("rfork", tv)                         # one line, never the diagram
        self.assertNotIn("tvb-route-note", tv)
        simple = self.app.test_client().get("/tv/tok?layout=simple").get_data(as_text=True)
        self.assertNotIn("The path to 1.1.1.1 changed", simple)  # a shop counter can't act on it

    def test_the_page_language_wins_over_the_saved_one(self):
        self.store.set_settings({"lang": "es"})
        es = self.client.get("/").get_data(as_text=True)
        self.assertIn("El camino hacia", es)
        for url in ("/?lang=en", "/chart?lang=en"):
            with self.subTest(url=url):
                self.assertNotIn("El camino hacia", self.client.get(url).get_data(as_text=True))

    def test_wall_screen_keeps_an_outage_on_top(self):
        from isitmyisp import settings as settings_mod
        from isitmyisp.webapp import views
        d = views.dashboard_data(self.store, settings_mod.load(self.store))
        self.assertIsNotNone(views.board(d)["route_top"])
        d.code = "isp"                                        # your ISP is down right now
        b = views.board(d)
        self.assertIsNotNone(b["route"])
        self.assertIsNone(b["route_top"])

    def test_incidents_show_the_diagnosis(self):
        html = self.client.get("/incidents").get_data(as_text=True)
        self.assertIn("ev-path", html)
        self.assertIn("181.96.60.162", html)

    def test_report_has_the_path_changes(self):
        from isitmyisp.report import build_report
        now = time.time()
        html = build_report(self.store, now - 86400, now, lang="en", now=now)
        self.assertIn("Path changes", html)
        self.assertIn("20 → 70 ms", html)


class Cards(unittest.TestCase):
    """The dashboard card: changes grouped into events, still like that or not, the latency around them (#97)."""
    ANCHORS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "c.db")
        self.now = 1_800_000_000.0
        self.at = self.now - 3 * 3600
        self.targets = routes.targets(list(self.ANCHORS), [Tunnel("HQ", "198.51.100.7", "10.8.0.1", "wireguard")])

    def samples(self, role, target, before, after, at=None, until=None):
        at = at or self.at
        for t in range(int(at - 4 * 3600), int(self.now), 60):
            ms = after if at <= t < (until or self.now) else before
            self.store.add_window(role, window(target, ms), ts=t)

    def event(self, key, group, ts, kind="changed", a=USUAL, b=OTHER, **data):
        d = {"from": obs(a).to_dict(), "to": obs(b).to_dict(), "label": key.split(":", 1)[1], "impact": None, **data}
        self.store.add_route_event(ts, key, group, kind, d)

    def cards(self, lang="en"):
        self.store.commit()
        return routes.cards(self.store, self.targets, lang, now=self.now, overlays={"HQ": "10.8.0.1"})

    def test_one_event_for_several_destinations(self):
        for i, a in enumerate(self.ANCHORS[:2]):
            self.samples("anchor", a, 20, 60)
            self.event(f"anchor:{a}", "internet", self.at + 60 * i)
        self.samples("anchor", "9.9.9.9", 20, 20)
        (c,) = self.cards()
        self.assertEqual((c["case"], c["state"], c["n"], c["of"]), ("worse", "ongoing", 2, 3))
        self.assertIn("2 destinations", c["headline"])
        self.assertEqual(set(c["series"]), {"target", "others"})
        self.assertGreater(len(c["series"]["target"]), 50)

    def test_back_on_the_usual_path(self):
        self.samples("anchor", "1.1.1.1", 20, 60, until=self.at + 3600)
        self.event("anchor:1.1.1.1", "internet", self.at)
        self.event("anchor:1.1.1.1", "internet", self.at + 3600, kind="restored", a=OTHER, b=USUAL)
        back, change = self.cards()
        self.assertEqual((back["case"], back["quiet"]), ("restored", True))
        self.assertEqual((change["state"], change["until"]), ("back", self.at + 3600))
        self.assertLessEqual(change["window"][1], self.at + 3600 + 1800)

    def test_a_tunnel_slower_inside_and_out(self):
        self.samples("tunnel_under:HQ", "198.51.100.7", 40, 65)
        self.samples("tunnel_over:HQ", "10.8.0.1", 42, 67)
        for a in self.ANCHORS:
            self.samples("anchor", a, 20, 20)
        self.event("tunnel:HQ", "tunnel:HQ", self.at)
        (c,) = self.cards("es")
        self.assertEqual((c["scope"], c["case"]), ("tunnel", "worse"))
        self.assertTrue(c["only_site"])
        self.assertIn("«HQ»", c["headline"])
        self.assertIn("Dentro del túnel también: 42 → 67 ms.", c["lines"])
        self.assertIn("solo afecta a este túnel", " ".join(c["lines"]))
        self.assertEqual(set(c["series"]), {"inside", "outside", "internet"})

    def test_not_only_the_tunnel_when_the_internet_got_worse_too(self):
        self.samples("tunnel_under:HQ", "198.51.100.7", 40, 65)
        for a in self.ANCHORS:
            self.samples("anchor", a, 20, 60)
        self.event("tunnel:HQ", "tunnel:HQ", self.at)
        (c,) = self.cards()
        self.assertFalse(c["only_site"])

    def test_nothing_worse_is_folded(self):
        self.samples("anchor", "1.1.1.1", 20, 21)
        self.event("anchor:1.1.1.1", "internet", self.at)
        (c,) = self.cards()
        self.assertEqual((c["case"], c["quiet"], c["series"]), ("none", True, {}))

    def test_too_soon_to_tell(self):
        self.event("anchor:1.1.1.1", "internet", self.now - 300)
        (c,) = self.cards()
        self.assertEqual((c["case"], c["quiet"]), ("pending", True))   # nothing on screen until it matters (#102)
        self.assertTrue(any("5 min ago" in line for line in c["lines"]))

    def test_a_path_that_keeps_changing_is_one_event(self):
        self.samples("anchor", "1.1.1.1", 20, 60)
        for k in range(4):
            a, b = (USUAL, OTHER) if k % 2 == 0 else (OTHER, USUAL)
            self.event("anchor:1.1.1.1", "internet", self.at + 900 * k, a=a, b=b, unstable=k >= 2)
        cs = self.cards()
        self.assertEqual(cs[0]["case"], "unstable")
        self.assertTrue(any("times since" in line for line in cs[0]["lines"]))

    def test_going_back_and_forth_for_free_is_folded(self):
        # load balancing inside the ISP or a CDN: it alternates, latency doesn't move (#102)
        self.samples("anchor", "1.1.1.1", 440, 450)
        for k in range(4):
            a, b = (USUAL, OTHER) if k % 2 == 0 else (OTHER, USUAL)
            self.event("anchor:1.1.1.1", "internet", self.at + 900 * k, a=a, b=b, unstable=k >= 2)
        cs = self.cards()
        self.assertTrue(all(c["quiet"] for c in cs))
        self.assertNotIn("unstable", {c["case"] for c in cs})

    @unittest.skipUnless(HAVE_WEB, "web extra not installed")
    def test_only_changes_with_effect_go_on_the_chart(self):
        from isitmyisp.webapp import views
        self.event("anchor:1.1.1.1", "internet", self.at, severity="none")
        self.event("anchor:8.8.8.8", "internet", self.at + 60, severity="worse")
        self.event("anchor:9.9.9.9", "internet", self.at + 120, b=CUT_ISP, severity="none")
        self.store.commit()
        marks = views.route_marks(self.store, self.at - 1, self.now, "en")
        self.assertEqual([m[0] for m in marks], [self.at + 60, self.at + 120])


if __name__ == "__main__":
    unittest.main()
