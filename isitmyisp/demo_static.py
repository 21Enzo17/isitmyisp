"""The demo as a static site (for Netlify or any file host): every page, every scenario, both languages.

The web UI has no JavaScript (even the chart hover is CSS), so each page can be rendered once and
served as a file. Pages are rendered through the real app in demo mode, then their links are
rewritten to the static layout:

    /<lang>/<scenario>/                 dashboard
    /<lang>/<scenario>/incidents/ …     the other pages
    /<lang>/<scenario>/report/          the evidence report (HTML; no PDF on a static host)
    /static/…                           shared CSS, fonts, icons

`_headers` gives every page the same strict CSP the app sends (the report keeps its inline styles,
as in the app). Nothing here measures anything: it is the synthetic data from demo.py.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path

from .demo import SCENARIOS, build

LANGS = ("es", "en")
PAGES = [("", "/"), ("incidents/", "/incidents"), ("tunnels/", "/tunnels"), ("reports/", "/reports"),
         ("settings/", "/settings"), ("report/", "/report?since=1d")]
ROUTES = {"/": "", "/incidents": "incidents/", "/tunnels": "tunnels/", "/reports": "reports/",
          "/settings": "settings/", "/report": "report/", "/report.pdf": "report/"}
DEFAULT = ("es", "isp")

APP_CSP = ("default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; manifest-src 'self'; "
           "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
REPORT_CSP = APP_CSP.replace("style-src 'self'", "style-src 'unsafe-inline'")
COMMON = ["X-Content-Type-Options: nosniff", "X-Frame-Options: DENY", "Referrer-Policy: no-referrer"]

_HREF = re.compile(r'(href|action)="([^"]*)"')


def rewrite(html: str, lang: str, scenario: str, page: str, langs=LANGS) -> str:
    """Point every app link at its static file (language links only to languages that were exported)."""
    base = f"/{lang}/{scenario}/"

    def fix(m: re.Match) -> str:
        attr, url = m.group(1), m.group(2)
        if url.startswith(("http://", "https://", "mailto:", "#", "/static/", "data:")):
            return m.group(0)
        if url.startswith("?lang="):                         # language switch: same page, other language
            other = url.split("=", 1)[1].split("&")[0]
            return f'{attr}="/{other if other in langs else lang}/{scenario}/{page}"'
        path, _, frag = url.partition("#")
        path = path.split("?", 1)[0]
        if path == "/favicon.ico":
            return f'{attr}="/static/favicon-32.png"'
        if re.fullmatch(r"/(es|en)/[a-z]+/.*", path):        # already static (the scenario switcher)
            return m.group(0)
        if path in ROUTES:
            return f'{attr}="{base}{ROUTES[path]}' + (f'#{frag}' if frag else "") + '"'
        return f'{attr}="{base}"'                             # anything else (POST targets): the dashboard
    return _HREF.sub(fix, html)


def export(out: Path, langs=LANGS, scenarios=SCENARIOS, hours: float = 24.0) -> list[str]:
    """Render the site into `out` (replaced). Returns the page paths written."""
    from .webapp import create_app
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(Path(__file__).parent / "webapp" / "static", out / "static")
    written: list[str] = []
    with tempfile.TemporaryDirectory(prefix="isitmyisp-static-") as tmp:
        for scenario in scenarios:
            for lang in langs:
                work = Path(tmp) / f"{lang}-{scenario}"
                work.mkdir()
                sim = build(work / "demo.db", hours=hours, scenario=scenario, lang=lang, speed=True)
                app = create_app(sim.store, data_dir=work, default_lang=lang, demo=True)
                app.config["DEMO_STATIC"] = {"scenario": scenario, "scenarios": list(scenarios)}
                client = app.test_client()
                for page, url in PAGES:
                    resp = client.get(url + ("&" if "?" in url else "?") + f"lang={lang}")
                    if resp.status_code != 200:
                        raise RuntimeError(f"{lang}/{scenario}{url}: HTTP {resp.status_code}")
                    html = rewrite(resp.get_data(as_text=True), lang, scenario, page, langs)
                    target = out / lang / scenario / page / "index.html"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(html, encoding="utf-8")
                    written.append(f"/{lang}/{scenario}/{page}")
                sim.store.close()
    lang, scenario = DEFAULT
    (out / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>isitmyisp demo</title>'
        f'<meta http-equiv="refresh" content="0; url=/{lang}/{scenario}/">'
        f'<p><a href="/{lang}/{scenario}/">isitmyisp demo</a></p>\n', encoding="utf-8")
    (out / "404.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>isitmyisp demo</title>'
        f'<p>Not found. <a href="/{lang}/{scenario}/">Open the demo</a>.</p>\n', encoding="utf-8")
    (out / "_headers").write_text(headers(written), encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    return written


def headers(pages: list[str]) -> str:
    """Netlify _headers: one block per page, so each gets exactly one CSP."""
    lines = []
    for path in ["/", "/404.html"] + pages:
        csp = REPORT_CSP if path.endswith("/report/") else APP_CSP
        lines += [path, f"  Content-Security-Policy: {csp}"] + [f"  {h}" for h in COMMON] + [""]
    lines += ["/static/*", "  Cache-Control: public, max-age=86400"] + [f"  {h}" for h in COMMON] + [""]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    t0 = time.time()
    pages = export(Path(sys.argv[1] if len(sys.argv) > 1 else "site"))
    print(f"{len(pages)} pages in {time.time() - t0:.0f} s")
