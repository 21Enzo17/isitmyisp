"""The documentation site: every page in every language, no broken links, no scripts."""

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("markdown"), "needs the markdown package (pip install markdown)")
class DocsSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_docs
        cls.bd = build_docs
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.pages = build_docs.build(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def html(self, url):
        path = self.out / url.lstrip("/") / "index.html"
        return path.read_text(encoding="utf-8")

    def test_same_pages_in_every_language(self):
        slugs = [s for _, group in self.bd.NAV for s in group]
        self.assertEqual(len(self.pages), len(slugs) * len(self.bd.LANGS))
        for lang in self.bd.LANGS:
            for slug in slugs:
                self.assertIn(self.bd.url(lang, slug), self.pages)

    def test_no_broken_internal_links_or_anchors(self):
        broken = []
        for url in self.pages:
            page = self.html(url)
            for href in re.findall(r'(?:href|src)="(/[^"]*)"', page):
                path, _, frag = href.partition("#")
                if re.match(r"/(es|en)/[a-z]+/$", path):          # demo pages, exported separately
                    continue
                target = self.out / path.lstrip("/")
                target = target / "index.html" if path.endswith("/") else target
                if not target.exists():
                    broken.append((url, href))
                elif frag and f'id="{frag}"' not in target.read_text(encoding="utf-8"):
                    broken.append((url, href))
        self.assertEqual(broken, [])

    def test_no_javascript_and_a_strict_csp(self):
        for url in self.pages:
            self.assertNotIn("<script", self.html(url))
        self.assertIn("default-src 'none'", self.bd.headers())
        self.assertNotIn("script-src", self.bd.headers())

    def test_language_switch_lands_on_the_same_page(self):
        page = self.html("/docs/es/alerts/")
        self.assertIn('href="/docs/en/alerts/" hreflang="en"', page)
        self.assertIn('aria-current="page">Alertas<', page)

    def test_spanish_pages_use_spanish_screenshots(self):
        for slug in ("", "dashboard/", "report/"):
            imgs = re.findall(r'<img[^>]+src="(/docs/img/[^"]+)"', self.html(f"/docs/es/{slug}"))
            self.assertTrue(imgs and all(i.startswith("/docs/img/es/") for i in imgs), (slug, imgs))

    def test_the_deploy_builds_it(self):
        toml = (ROOT / "netlify.toml").read_text()
        self.assertIn("scripts/build_docs.py site", toml)
        self.assertIn("markdown", toml)
