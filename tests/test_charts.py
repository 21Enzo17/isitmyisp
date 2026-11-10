import unittest

try:  # the chart code is plain Python, but it lives in the web package (needs the [web] extra)
    from isitmyisp.webapp import charts
except ImportError:
    charts = None

T0 = 1_700_000_000.0


def windows(codes, secs=30.0, start=T0):
    return [(start + (i + 1) * secs, secs, c) for i, c in enumerate(codes)]


@unittest.skipIf(charts is None, "web extra not installed")
class Plot(unittest.TestCase):
    def test_coordinates_live_in_the_1000x100_box(self):
        p = charts.plot([(T0, 0.0), (T0 + 50, 5.0), (T0 + 100, 10.0)], T0, T0 + 100, unit="%")
        self.assertTrue(p.line.startswith("M0.0,100.0"))
        self.assertIn("1000.0,", p.line)
        self.assertEqual(p.ymax, 20)                      # 10 * 1.1 rounded up to a nice step
        self.assertEqual(p.ticks, ["20%", "10%", "0%"])

    def test_gaps_break_the_line_instead_of_bridging_them(self):
        pts = [(T0 + i * 30, 1.0) for i in range(5)] + [(T0 + 3000 + i * 30, 1.0) for i in range(5)]
        self.assertEqual(charts.plot(pts, T0, T0 + 3200).line.count("M"), 2)

    def test_threshold_and_fixed_scale(self):
        p = charts.plot([(T0, 40.0), (T0 + 30, 50.0)], T0, T0 + 30, ymax=100, threshold=85)
        self.assertAlmostEqual(p.threshold, 15.0)

    def test_too_few_points_is_empty(self):
        self.assertTrue(charts.plot([(T0, 1.0)], T0, T0 + 30).empty)


@unittest.skipIf(charts is None, "web extra not installed")
class Timeline(unittest.TestCase):
    def test_bucket_keeps_the_most_serious_verdict_and_average_loss(self):
        codes = ["ok"] * 28 + ["isp"] * 2              # 15 minutes: two ISP windows at the end
        series = [(ts, 0.0 if c == "ok" else 30.0, 20.0) for ts, _, c in windows(codes)]
        tl = charts.timeline(windows(codes), series, T0, T0 + 900, n=1)
        b = tl.buckets[0]
        self.assertEqual((b.code, b.group), ("isp", "isp"))
        self.assertAlmostEqual(b.loss, 2.0)              # average, not the 30% of one window
        self.assertEqual(tl.groups, ["good", "isp"])

    def test_runs_merge_and_responsibility_groups(self):
        tl = charts.timeline(windows(["ok", "ok", "local", "saturation", "dns"]), [], T0, T0 + 150, n=5)
        self.assertEqual([(g, c) for _, _, g, c in tl.strip],
                         [("good", "ok"), ("you", "local"), ("you", "saturation"), ("other", "dns")])
        self.assertEqual(tl.groups, ["good", "you", "other"])

    def test_tooltips_flip_on_the_right_third_and_table_is_hourly(self):
        tl = charts.timeline(windows(["ok"] * 2880), [], T0, T0 + 86400)
        self.assertEqual(len(tl.buckets), 96)
        self.assertFalse(tl.buckets[63].flip)
        self.assertTrue(tl.buckets[64].flip)
        self.assertEqual(len(tl.hourly), 24)
        self.assertNotIn("none", tl.groups)              # fully measured: no "not measuring" key

    def test_gaps_are_reported(self):
        tl = charts.timeline(windows(["ok"] * 10), [], T0, T0 + 3600, n=12)
        self.assertIn("none", tl.groups)


if __name__ == "__main__":
    unittest.main()
