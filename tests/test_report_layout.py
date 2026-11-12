"""The evidence report reads in two parts: a summary for the owner, then the detail for the ISP."""

import tempfile
import unittest
from pathlib import Path

from isitmyisp.demo import build
from isitmyisp.report import build_report


class Layout(unittest.TestCase):
    def test_summary_first_then_the_technical_annex(self):
        with tempfile.TemporaryDirectory() as d:
            sim = build(Path(d) / "r.db", hours=24, scenario="isp", lang="es")
            a, b = sim.store.first_and_last_window()
            doc = build_report(sim.store, a - 60, b + 60, lang="es")
            sim.store.close()
        summary, annex, message = (doc.index("Resumen para vos"), doc.index("Anexo técnico</h2>"),
                                   doc.index('<pre class="message">'))
        self.assertLess(summary, annex)
        self.assertLess(annex, message)                       # the ready message opens the annex
        self.assertLess(message, doc.index("Dónde estuvieron los problemas"))
        for owner_part in ("Funcionó bien", "Los cortes que más te afectaron", "Qué hacer."):
            self.assertIn(owner_part, doc[:annex])
        self.assertIn("dejó de responder", doc[:annex])        # the card terminal, said plainly
        for gone in ("Peor pérdida</div>", "Datos para reclamar", "ENACOM", "Cómo reclamar"):
            self.assertNotIn(gone, doc)
