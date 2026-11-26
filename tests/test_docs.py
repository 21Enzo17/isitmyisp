"""The documentation site: every page in every language, no broken links, a search that needs no JavaScript."""

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
        self.assertEqual(len(self.pages), (len(slugs) + 1) * len(self.bd.LANGS))      # + the search page
        for lang in self.bd.LANGS:
            for slug in slugs:
                self.assertIn(self.bd.url(lang, slug), self.pages)

    def test_no_broken_internal_links_or_anchors(self):
        broken = []
        for url in self.pages:
            page = self.html(url)
            for href in re.findall(r'(?:href|src)="(/[^"]*)"', page):
                path, _, frag = href.partition("#")
                path = path.split("?", 1)[0]
                if re.match(r"/(es|en)/isp/(tv/(simple/)?)?$", path):          # demo pages, exported separately
                    continue
                target = self.out / path.lstrip("/")
                target = target / "index.html" if path.endswith("/") else target
                if not target.exists():
                    broken.append((url, href))
                elif frag and f'id="{frag}"' not in target.read_text(encoding="utf-8"):
                    broken.append((url, href))
        self.assertEqual(broken, [])

    def test_only_the_external_script_and_a_strict_csp(self):
        js = f'<script src="/docs/docs.js?v={self.bd.JS_V}" defer></script>'
        for url in self.pages:
            page = self.html(url)
            self.assertEqual(page.count("<script"), 1, url)       # no inline code: the CSP wouldn't run it anyway
            self.assertIn(js, page)
        self.assertTrue((self.out / "docs" / "docs.js").exists())
        csp = self.bd.headers()
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self';", csp)
        self.assertNotIn("unsafe-inline", csp)

    def test_search_page_indexes_every_section_without_javascript(self):
        for lang in self.bd.LANGS:
            page = self.html(f"/docs/{lang}/search/")
            self.assertIn("<noscript>", page)                          # how to search with JS off
            self.assertIn('class="search-form" method="get"', page)    # shown by docs.js, hidden without it
            for md in (ROOT / "docs" / "site" / lang).glob("*.md"):
                slug = md.stem
                built = self.html(self.bd.url(lang, slug))
                for sid in re.findall(r'<h2 id="([^"]+)"', built):
                    self.assertIn(f'href="{self.bd.url(lang, slug)}#{sid}"', page, (lang, slug, sid))
            # every page leads to it, with a key that works with no script (accesskey)
            self.assertIn(f'href="/docs/{lang}/search/" accesskey="k"', self.html(f"/docs/{lang}/faq/"))

    def test_search_text_is_folded_like_docs_js(self):
        self.assertEqual(self.bd.fold("Configuración RÁPIDA"), "configuracion rapida")
        self.assertEqual(self.bd.fold("Wi-Fi"), "wifi")
        page = self.html("/docs/es/search/")
        self.assertIn("configuracion", page)
        self.assertNotIn('data-t="Preguntas', page)            # the searched text is lower case

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
