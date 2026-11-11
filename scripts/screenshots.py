"""Regenerate the README screenshots from SYNTHETIC data (never from a real network).

    python3 scripts/screenshots.py            # writes docs/screenshots/*.png
    python3 scripts/screenshots.py --lang es  # writes docs/screenshots/es/*.png (for the Spanish docs)

Needs the web extra (pip install -e '.[web]') and Docker (headless Chrome runs in the
zenika/alpine-chrome image). Each state is the demo database cut at a moment and shifted to
"now": healthy, during an ISP incident, and while running on the backup link.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import demo_data  # noqa: E402
from isitmyisp.report import build_report  # noqa: E402
from isitmyisp.store import Store  # noqa: E402
from isitmyisp.webapp import auth, create_app  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
CHROME = "zenika/alpine-chrome:124"
PASSWORD = "demo-password-123"
TABLES = {"samples": ["ts"], "windows": ["ts"], "captures": ["ts"], "link_usage": ["ts"],
          "networks": ["ts"], "incidents": ["opened", "closed"], "speedtests": ["ts"]}


def freeze(src: Path, dst: Path, fraction: float | None) -> None:
    """Copy the demo database, cut it at `fraction` of its span and shift it so the cut is now."""
    shutil.copy(src, dst)
    if fraction is None:
        return
    db = sqlite3.connect(dst)
    lo, hi = db.execute("SELECT MIN(ts), MAX(ts) FROM windows").fetchone()
    cut = lo + (hi - lo) * fraction
    for table in ("samples", "windows", "captures", "link_usage", "speedtests"):
        db.execute(f"DELETE FROM {table} WHERE ts > ?", (cut,))
    db.execute("DELETE FROM networks WHERE ts > ? AND ts > (SELECT MIN(ts) FROM networks)", (cut,))
    db.execute("DELETE FROM incidents WHERE opened > ?", (cut,))
    db.execute("UPDATE incidents SET closed = NULL WHERE closed > ?", (cut,))
    shift = time.time() - cut - 5
    for table, cols in TABLES.items():
        for col in cols:
            db.execute(f"UPDATE {table} SET {col} = {col} + ? WHERE {col} IS NOT NULL", (shift,))
    db.commit()
    db.close()


def add_speed_result(path: Path) -> None:
    from isitmyisp import settings as settings_mod
    from isitmyisp import speedtest as sp
    store = Store(path)
    settings_mod.save(store, {"speedtest": {"enabled": True, "accepted": True}})
    store.add_speedtest(sp.Result(ts=time.time() - 2 * 86400, down_mbps=262.4, up_mbps=91.8, idle_ms=29.6,
                                  loaded_ms=71.2, bytes_used=412_000_000, seconds=15.2, wan_down_mbps=281.0,
                                  trigger="scheduled"))
    store.close()


def render(db: Path, work: Path, path: str, lang: str = "en", css: str = "") -> Path:
    store = Store(db)
    if not store.user_count():
        store.add_user("admin", auth.hash_password(PASSWORD))
    store.set_settings({"wizard_done": True}, bump=False)   # a finished setup, without the reminder
    app = create_app(store, data_dir=db.parent, bind="127.0.0.1:8080", default_lang=lang)
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": PASSWORD})
    html = client.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").get_data(as_text=True)
    html = re.sub(r'<link rel="stylesheet" href="([^"]+)">',
                  lambda m: "<style>" + client.get(m.group(1)).get_data(as_text=True) + css + "</style>", html)
    html = html.replace('<meta http-equiv="refresh" content="30">', "")
    store.close()
    page = work / f"page-{abs(hash((str(db), path, css)))}.html"
    page.write_text(html)
    return page


def shoot(page: Path, out: Path, size: str, dark: bool) -> None:
    work = page.parent
    subprocess.run(["docker", "run", "--rm", "-v", f"{work}:/w", CHROME, "--no-sandbox", "--hide-scrollbars",
                    f"--blink-settings=preferredColorScheme={0 if dark else 1}", f"--window-size={size}",
                    f"--screenshot=/w/{out.name}", f"file:///w/{page.name}"], check=True, capture_output=True)
    shutil.move(work / out.name, out)
    print(out.relative_to(ROOT))


def main(lang: str = "en") -> None:
    out = OUT if lang == "en" else OUT / lang
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "fonts").mkdir()
        for f in (ROOT / "isitmyisp" / "webapp" / "static" / "fonts").glob("*.woff2"):
            shutil.copy(f, work / "fonts")
        base = work / "demo.db"
        demo_data.main(str(base), lang=lang)
        states = {}
        for name, fraction in (("healthy", None), ("isp", 0.62), ("failover", 0.52)):
            d = work / name
            d.mkdir()
            freeze(base, d / "demo.db", fraction)
            states[name] = d / "demo.db"
        add_speed_result(states["healthy"])

        only = lambda sel: f"\n.card:not({sel}) {{ display: none; }}"  # noqa: E731
        shots = [
            (states["healthy"], "/", "", "dashboard-dark.png", "1440,2500", True),
            (states["isp"], "/", "", "incident.png", "1440,1180", True),
            (states["failover"], "/", "", "failover.png", "1440,720", False),
            (states["healthy"], "/settings", only("#speed"), "speed-test-settings.png", "1440,1000", True),
            (states["isp"], "/", "", "mobile.png", "390,1500", True),
        ]
        for db, path, css, name, size, dark in shots:
            shoot(render(db, work, path, lang=lang, css=css), out / name, size, dark)

        store = Store(states["isp"])
        a, b = store.first_and_last_window()
        report = work / "report.html"
        report.write_text(build_report(store, a - 60, b + 60, lang=lang))
        store.close()
        shoot(report, out / "report.png", "1100,1500", False)


if __name__ == "__main__":
    main(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--lang" else "en")
