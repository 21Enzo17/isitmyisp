"""SQLite storage for probe windows."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from .probes.icmp import WindowStats

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    target TEXT NOT NULL,
    sent INTEGER NOT NULL,
    received INTEGER NOT NULL,
    rtt_min REAL, rtt_avg REAL, rtt_max REAL, jitter REAL
);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS verdicts (
    ts REAL NOT NULL,
    code TEXT NOT NULL,
    evidence TEXT
);
"""


def data_dir() -> Path:
    base = os.environ.get("ISITMYISP_DATA") or os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "isitmyisp"
    )
    return Path(base)


def default_path() -> Path:
    return data_dir() / "data.db"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)

    def add_window(self, role: str, s: WindowStats, ts: float | None = None) -> None:
        self.db.execute(
            "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?)",
            (ts or time.time(), role, s.target, s.sent, s.received, s.rtt_min, s.rtt_avg, s.rtt_max, s.jitter),
        )

    def add_verdict(self, code: str, evidence: list[str], ts: float | None = None) -> None:
        self.db.execute("INSERT INTO verdicts VALUES (?,?,?)", (ts or time.time(), code, " | ".join(evidence)))

    def commit(self) -> None:
        self.db.commit()

    def prune(self, keep_days: int = 30) -> None:
        cutoff = time.time() - keep_days * 86400
        self.db.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
