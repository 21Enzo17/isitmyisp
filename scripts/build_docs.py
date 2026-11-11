"""Build the documentation site: docs/site/<lang>/*.md -> <out>/docs/<lang>/<slug>/index.html.

    pip install markdown
    python3 scripts/build_docs.py site          # next to the static demo (Netlify does this on deploy)

Same look as the app (its fonts and colours), no JavaScript, light and dark. Every page exists in
every language with the same slug, so the language switch always lands on the same page. The order
and grouping of the sidebar is NAV below; a page missing from it fails the build, so nothing gets
lost.
"""

from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "site"
LANGS = ("es", "en")
DEMO = {"es": "/es/isp/", "en": "/en/isp/"}
REPO = "https://github.com/21Enzo17/isitmyisp"

# (group, [slugs]); the first page of the first group is the docs home
NAV = [
    ("start", ["index", "install", "raspberry-pi", "first-steps"]),
    ("use", ["dashboard", "features", "alerts", "report"]),
    ("inside", ["verdict", "privacy", "security"]),
    ("help", ["faq"]),
]
UI = {
    "es": {"start": "Empezar", "use": "Usarlo", "inside": "Por dentro", "help": "Ayuda", "docs": "Documentación",
           "demo": "Ver la demo", "prev": "Anterior", "next": "Siguiente", "toc": "En esta página",
           "menu": "Menú", "edit": "Editar esta página", "skip": "Saltar al contenido", "other": "English"},
    "en": {"start": "Get started", "use": "Using it", "inside": "How it works", "help": "Help", "docs": "Docs",
           "demo": "Live demo", "prev": "Previous", "next": "Next", "toc": "On this page",
           "menu": "Menu", "edit": "Edit this page", "skip": "Skip to content", "other": "Español"},
}
CSP = ("default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")


def read(path: Path) -> tuple[dict, str]:
    """Front matter (title, description) and the Markdown body."""
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    if text.startswith("---\n"):
        head, text = text[4:].split("\n---\n", 1)
        for line in head.splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    for key in ("title", "description"):
        if not meta.get(key):
            raise SystemExit(f"{path}: front matter needs '{key}'")
    return meta, text


def render(md_text: str, lang: str) -> tuple[str, list[tuple[str, str]]]:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "attr_list", "md_in_html"],
                           extension_configs={"toc": {"permalink": False}})
    body = md.convert(md_text)
    def flat(tokens):
        for t in tokens:
            yield t
            yield from flat(t["children"])
    toc = [(t["id"], t["name"]) for t in flat(md.toc_tokens) if t["level"] == 2]
    # links between pages are written as (slug.md) or (slug.md#x): point them at the built pages
    body = re.sub(r'href="([a-z0-9-]+)\.md(#[^"]*)?"',
                  lambda m: f'href="/docs/{lang}/{"" if m.group(1) == "index" else m.group(1) + "/"}{m.group(2) or ""}"', body)
    # external links open normally but say they leave the site
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a class="ext" rel="noopener" href="\1"', body)
    # wide tables scroll on their own instead of the page
    body = body.replace("<table>", '<div class="table"><table>').replace("</table>", "</table></div>")
    return body, toc


def url(lang: str, slug: str) -> str:
    return f"/docs/{lang}/" if slug == "index" else f"/docs/{lang}/{slug}/"


def page(lang: str, slug: str, meta: dict, body: str, toc, titles: dict, order: list[str]) -> str:
    t = UI[lang]
    other = "en" if lang == "es" else "es"
    nav = []
    for group, slugs in NAV:
        items = "".join(
            f'<li><a href="{url(lang, s)}"{" aria-current=\"page\"" if s == slug else ""}>{html.escape(titles[s])}</a></li>'
            for s in slugs)
        nav.append(f'<p class="nav-group">{t[group]}</p><ul>{items}</ul>')
    i = order.index(slug)
    prev_ = order[i - 1] if i > 0 else None
    next_ = order[i + 1] if i + 1 < len(order) else None
    pager = '<nav class="pager" aria-label="pager">'
    if prev_:
        pager += f'<a class="prev" href="{url(lang, prev_)}"><span>{t["prev"]}</span>{html.escape(titles[prev_])}</a>'
    if next_:
        pager += f'<a class="next" href="{url(lang, next_)}"><span>{t["next"]}</span>{html.escape(titles[next_])}</a>'
    pager += "</nav>"
    toc_html = ""
    if len(toc) > 1:
        toc_html = (f'<aside class="toc" aria-label="{t["toc"]}"><p>{t["toc"]}</p><ul>'
                    + "".join(f'<li><a href="#{i_}">{n}</a></li>' for i_, n in toc) + "</ul></aside>")
    title = meta["title"] if slug == "index" else f'{meta["title"]} · isitmyisp'
    side = "".join(nav)
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(meta['description'])}">
<link rel="alternate" hreflang="{other}" href="{url(other, slug)}">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/static/favicon-32.png" sizes="32x32" type="image/png">
<link rel="stylesheet" href="/docs/docs.css">
</head>
<body>
<a class="skip" href="#content">{t["skip"]}</a>
<header class="top">
  <a class="brand" href="{url(lang, 'index')}"><img src="/static/favicon.svg" alt="" width="28" height="28"><span>isitmyisp</span><span class="brand-docs">{t["docs"]}</span></a>
  <nav class="top-links">
    <a class="btn" href="{DEMO[lang]}">{t["demo"]}</a>
    <a href="{REPO}">GitHub</a>
    <a href="{url(other, slug)}" hreflang="{other}" lang="{other}">{t["other"]}</a>
  </nav>
</header>
<div class="layout">
  <details class="menu"><summary>{t["menu"]}</summary><nav>{side}</nav></details>
  <nav class="side" aria-label="{t["docs"]}">{side}</nav>
  <main id="content">
    <article class="doc">
{body}
    </article>
    <p class="edit"><a href="{REPO}/edit/main/docs/site/{lang}/{slug}.md">{t["edit"]}</a></p>
    {pager}
  </main>
  {toc_html}
</div>
</body>
</html>
"""


def build(out: Path) -> list[str]:
    out = Path(out)
    dest = out / "docs"
    if dest.exists():
        shutil.rmtree(dest)
    order = [s for _, slugs in NAV for s in slugs]
    written = []
    for lang in LANGS:
        files = {p.stem: p for p in (SRC / lang).glob("*.md")}
        missing, extra = set(order) - set(files), set(files) - set(order)
        if missing or extra:
            raise SystemExit(f"docs/site/{lang}: missing {sorted(missing)}, not in NAV {sorted(extra)}")
        pages = {s: read(files[s]) for s in order}
        titles = {s: pages[s][0].get("nav", pages[s][0]["title"]) for s in order}
        for slug in order:
            meta, text = pages[slug]
            body, toc = render(text, lang)
            target = dest / lang / ("" if slug == "index" else slug) / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page(lang, slug, meta, body, toc, titles, order), encoding="utf-8")
            written.append(url(lang, slug))
    shutil.copy(SRC / "docs.css", dest / "docs.css")
    shutil.copytree(ROOT / "docs" / "screenshots", dest / "img")
    (dest / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>isitmyisp docs</title>'
        '<meta http-equiv="refresh" content="0; url=/docs/es/"><p><a href="/docs/es/">Documentación</a> · '
        '<a href="/docs/en/">Docs</a></p>\n', encoding="utf-8")
    if not (out / "static").exists():      # building the docs alone (the demo export copies these)
        shutil.copytree(ROOT / "isitmyisp" / "webapp" / "static", out / "static")
    return written


def headers() -> str:
    """Netlify _headers lines for the docs (appended to the demo's)."""
    common = ["X-Content-Type-Options: nosniff", "X-Frame-Options: DENY", "Referrer-Policy: no-referrer"]
    return "\n".join(["/docs/*", f"  Content-Security-Policy: {CSP}"] + [f"  {h}" for h in common]) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
    pages = build(out)
    with open(out / "_headers", "a", encoding="utf-8") as f:
        f.write("\n" + headers())
    print(f"{len(pages)} doc pages in {out}/docs")
