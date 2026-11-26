"""Build the documentation site: docs/site/<lang>/*.md -> <out>/docs/<lang>/<slug>/index.html.

    pip install markdown
    python3 scripts/build_docs.py site          # next to the static demo (Netlify does this on deploy)

Same look as the app (its fonts and colours), light and dark, and it works with JavaScript off. Every page exists in
every language with the same slug, so the language switch always lands on the same page. The order
and grouping of the sidebar is NAV below; a page missing from it fails the build, so nothing gets
lost.

Search: the site has no server, so a query can't be answered by one. The build writes a search page
(/docs/<lang>/search/) that lists every page and every section with its anchor and a short summary:
with JavaScript off that page is the index, searched with the browser's own find (Ctrl+F). With it on,
docs.js (one small file, no inline code) filters that same list as you type and opens it with Ctrl+K.
"""

from __future__ import annotations

import html
import re
import shutil
import sys
import unicodedata
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
    ("use", ["dashboard", "features", "doctor", "device-check", "alerts", "report"]),
    ("inside", ["verdict", "privacy", "security"]),
    ("help", ["faq"]),
]
UI = {
    "es": {"start": "Empezar", "use": "Usarlo", "inside": "Por dentro", "help": "Ayuda", "docs": "Documentación",
           "demo": "Ver la demo", "prev": "Anterior", "next": "Siguiente", "toc": "En esta página",
           "menu": "Menú", "edit": "Editar esta página", "skip": "Saltar al contenido", "other": "English",
           "search": "Buscar", "search_title": "Buscar en la documentación",
           "search_desc": "Todas las páginas y secciones de la documentación de isitmyisp, para buscar.",
           "search_lead": "Todas las páginas y secciones de la documentación, en un solo lugar.",
           "search_ph": "Qué estás buscando: router, Telegram, informe…",
           "search_nojs": "Con JavaScript apagado, buscá con el buscador del navegador (Ctrl+F, o Cmd+F en Mac): "
                          "abajo está cada sección, página por página. En cualquier página, Alt+K (Alt+Mayús+K en Firefox) trae acá.",
           "search_n": "{n} resultados", "search_1": "1 resultado", "search_none": "No hay nada con «{q}». Probá con otra palabra."},
    "en": {"start": "Get started", "use": "Using it", "inside": "How it works", "help": "Help", "docs": "Docs",
           "demo": "Live demo", "prev": "Previous", "next": "Next", "toc": "On this page",
           "menu": "Menu", "edit": "Edit this page", "skip": "Skip to content", "other": "Español",
           "search": "Search", "search_title": "Search the docs",
           "search_desc": "Every page and section of the isitmyisp documentation, to search.",
           "search_lead": "Every page and section of the documentation, in one place.",
           "search_ph": "What are you looking for: router, Telegram, report…",
           "search_nojs": "With JavaScript off, use your browser's find (Ctrl+F, or Cmd+F on a Mac): every section is "
                          "below, page by page. From any page, Alt+K (Alt+Shift+K in Firefox) brings you here.",
           "search_n": "{n} results", "search_1": "1 result", "search_none": "Nothing about “{q}”. Try another word."},
}
# the stylesheet's URL carries a fingerprint of its content, so a new look is never stuck in a cache
import hashlib  # noqa: E402
CSS_V = hashlib.sha256((Path(__file__).resolve().parents[1] / "docs" / "site" / "docs.css").read_bytes()).hexdigest()[:10]
JS_V = hashlib.sha256((Path(__file__).resolve().parents[1] / "docs" / "site" / "docs.js").read_bytes()).hexdigest()[:10]
# the only script is /docs/docs.js (an improvement: everything works without it), never inline code
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
SEARCH = "search"   # the generated search page: same slug in every language, not in NAV
GLASS = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/>'
         '<path d="m15.5 15.5 5 5"/></svg>')


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


def plain(fragment: str) -> str:
    """Visible text of an HTML fragment, on one line."""
    text = re.sub(r"<(?:br|/(?:p|li|h\d|td|th|pre|blockquote|div))\b[^>]*>", " ", fragment)   # blocks end in a space,
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", "", text)).split())                    # inline tags don't
    return re.sub(r" ([,.;:)])", r"\1", text)


def fold(text: str) -> str:
    """What the search compares: lower case, no accents, no hyphens, so "wifi" finds "Wi-Fi" (docs.js does the
    same to the query)."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c) and c != "-")


def summary(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def sections(body: str) -> tuple[str, list[tuple[str, str, str]]]:
    """A rendered page split at its <h2>s: the text before the first one, and (id, title, text) for each."""
    parts = re.split(r'<h2 id="([^"]+)">(.*?)</h2>', body)
    intro = re.sub(r"<h1[^>]*>.*?</h1>", "", parts[0], flags=re.DOTALL)
    return plain(intro), [(parts[i], plain(parts[i + 1]), plain(parts[i + 2])) for i in range(1, len(parts), 3)]


def search_body(lang: str, entries: list[tuple[str, dict, str, list]], titles: dict) -> str:
    """The search page: the form (shown by docs.js) and the full index, which is the result list."""
    t = UI[lang]
    out = [f'<h1>{t["search_title"]}</h1>', f'<p>{t["search_lead"]}</p>',
           (f'<form class="search-form" method="get" action="{url(lang, SEARCH)}" role="search" hidden>'
            f'<label for="q">{GLASS}<span class="sr">{t["search"]}</span></label>'
            f'<input id="q" name="q" type="search" placeholder="{html.escape(t["search_ph"])}" autocomplete="off" '
            f'spellcheck="false" aria-describedby="search-count">'
            f'<kbd class="search-esc" aria-hidden="true">Esc</kbd></form>'),
           (f'<p id="search-count" class="search-count" aria-live="polite" hidden '
            f'data-n="{html.escape(t["search_n"])}" data-one="{html.escape(t["search_1"])}" '
            f'data-none="{html.escape(t["search_none"])}"></p>'),
           f'<noscript><blockquote><p>{t["search_nojs"]}</p></blockquote></noscript>',
           '<div class="search-index" id="search-index">']
    for slug, meta, intro, secs in entries:
        href = url(lang, slug)
        title = html.escape(titles[slug])          # the sidebar's name for it
        rows = [(f'<li data-t="{html.escape(fold(meta["title"] + " " + meta["description"] + " " + intro))}">'
                 f'<a href="{href}"><b>{title}</b></a><p>{html.escape(meta["description"])}</p></li>')]
        rows += [f'<li data-t="{html.escape(fold(name + " " + text))}"><a href="{href}#{sid}"><b>{html.escape(name)}</b>'
                 f'<span>{title}</span></a><p>{html.escape(summary(text))}</p></li>' for sid, name, text in secs]
        out.append(f'<section><h2>{title}</h2><ul>{"".join(rows)}</ul></section>')
    out.append("</div>")
    return "\n".join(out)


def url(lang: str, slug: str) -> str:
    return f"/docs/{lang}/" if slug == "index" else f"/docs/{lang}/{slug}/"


def page(lang: str, slug: str, meta: dict, body: str, toc, titles: dict, order: list[str]) -> str:
    t = UI[lang]
    other = "en" if lang == "es" else "es"
    nav = []
    current = ' aria-current="page"'           # (no backslashes inside f-strings: Python 3.10 and 3.11)
    for group, slugs in NAV:
        items = "".join(
            f'<li><a href="{url(lang, s)}"{current if s == slug else ""}>{html.escape(titles[s])}</a></li>'
            for s in slugs)
        nav.append(f'<p class="nav-group">{t[group]}</p><ul>{items}</ul>')
    pager = ""
    if slug in order:                         # a Markdown page: the pager and the edit link
        i = order.index(slug)
        prev_ = order[i - 1] if i > 0 else None
        next_ = order[i + 1] if i + 1 < len(order) else None
        pager = '<nav class="pager" aria-label="pager">'
        if prev_:
            pager += f'<a class="prev" href="{url(lang, prev_)}"><span>{t["prev"]}</span>{html.escape(titles[prev_])}</a>'
        if next_:
            pager += f'<a class="next" href="{url(lang, next_)}"><span>{t["next"]}</span>{html.escape(titles[next_])}</a>'
        pager += "</nav>"
        pager = f'<p class="edit"><a href="{REPO}/edit/main/docs/site/{lang}/{slug}.md">{t["edit"]}</a></p>\n    {pager}'
    here = ' aria-current="page"' if slug == SEARCH else ""
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
<link rel="stylesheet" href="/docs/docs.css?v={CSS_V}">
<script src="/docs/docs.js?v={JS_V}" defer></script>
</head>
<body>
<a class="skip" href="#content">{t["skip"]}</a>
<header class="top">
  <a class="brand" href="{url(lang, 'index')}"><svg viewBox="0 0 64 64" aria-hidden="true"><path d="M17 32H24.5M39.5 32H47" stroke="currentColor" stroke-width="4" stroke-linecap="round" fill="none" opacity=".55"/><circle cx="32" cy="32" r="12" fill="#3b82f6" opacity=".22"/><circle cx="11" cy="32" r="6" fill="none" stroke="currentColor" stroke-width="4"/><circle cx="53" cy="32" r="6" fill="none" stroke="currentColor" stroke-width="4"/><circle cx="32" cy="32" r="7.5" fill="#3b82f6"/></svg><span>isitmyisp</span><span class="brand-docs">{t["docs"]}</span></a>
  <nav class="top-links">
    <a class="search-link" href="{url(lang, SEARCH)}" accesskey="k"{here}>{GLASS}<span>{t["search"]}</span><kbd hidden>Ctrl K</kbd></a>
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
        entries = []
        for slug in order:
            meta, text = pages[slug]
            body, toc = render(text, lang)
            target = dest / lang / ("" if slug == "index" else slug) / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page(lang, slug, meta, body, toc, titles, order), encoding="utf-8")
            written.append(url(lang, slug))
            entries.append((slug, meta, *sections(body)))
        meta = {"title": UI[lang]["search_title"], "description": UI[lang]["search_desc"]}
        target = dest / lang / SEARCH / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page(lang, SEARCH, meta, search_body(lang, entries, titles), [], titles, order), encoding="utf-8")
        written.append(url(lang, SEARCH))
    shutil.copy(SRC / "docs.css", dest / "docs.css")
    shutil.copy(SRC / "docs.js", dest / "docs.js")
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
