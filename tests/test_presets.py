import os
import unittest

from isitmyisp import presets
from isitmyisp.services import check_http, check_tcp, validate


class PresetData(unittest.TestCase):
    def test_every_preset_is_a_valid_service(self):
        items = presets.load("ar")
        self.assertGreaterEqual(len(items), 10)
        validate([{"name": p.name, "kind": p.kind, "target": p.target} for p in items])  # raises if not
        self.assertEqual(len({p.id for p in items}), len(items))
        self.assertEqual(len({p.target for p in items}), len(items))
        for p in items:
            self.assertTrue(p.what.get("es") and p.what.get("en"), p.id)        # says what is checked, both languages
            if p.kind == "tcp":
                self.assertIn("TCP", p.what["en"], f"{p.id}: say why it's checked over TCP")

    def test_grouped_keeps_file_order(self):
        groups = [g for g, _ in presets.grouped("ar")]
        self.assertEqual(groups[0], "ARCA (ex AFIP)")
        self.assertEqual(presets.load("xx"), ())


@unittest.skipUnless(os.environ.get("ISITMYISP_NETWORK_TESTS") == "1", "network test: set ISITMYISP_NETWORK_TESTS=1")
class PresetsAnswer(unittest.TestCase):
    """For whoever maintains the list: every preset must answer from a real connection."""

    def test_every_preset_answers(self):
        for p in presets.load("ar"):
            with self.subTest(preset=p.id):
                c = check_http(p.target) if p.kind == "http" else check_tcp(p.target)
                self.assertTrue(c.ok, f"{p.target}: {c.detail}")


if __name__ == "__main__":
    unittest.main()
