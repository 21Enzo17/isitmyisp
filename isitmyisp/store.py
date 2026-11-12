"""SQLite storage: probe windows, per-window verdicts, incidents and their evidence.

Thread-safe: incident evidence (mtr) is captured in background threads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .probes.icmp import WindowStats

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    target TEXT NOT NULL,
    sent INTEGER NOT NULL,
    received INTEGER NOT NULL,
    rtt_min REAL, rtt_avg REAL, rtt_max REAL, jitter REAL,
    rtt_median REAL
);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);

-- one row per measurement window: the raw verdict (before hysteresis)
CREATE TABLE IF NOT EXISTS windows (
    ts REAL NOT NULL,
    seconds REAL NOT NULL,
    code TEXT NOT NULL,
    evidence TEXT                -- JSON list, only for non-ok windows
);
CREATE INDEX IF NOT EXISTS windows_ts ON windows(ts);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    opened REAL NOT NULL,
    closed REAL,
    code TEXT NOT NULL,
    evidence TEXT NOT NULL,      -- JSON list of strings, from the window that opened it
    peak_loss REAL NOT NULL DEFAULT 0,
    scope TEXT NOT NULL DEFAULT 'internet',  -- 'internet', 'tunnel:<name>' or 'service:<name>'
    alerted INTEGER NOT NULL DEFAULT 0,      -- 'opened' alert sent
    close_alerted INTEGER NOT NULL DEFAULT 0,-- 'closed' alert sent
    details TEXT                             -- JSON: what the evidence rules out / can't rule out
);
CREATE INDEX IF NOT EXISTS incidents_opened ON incidents(opened);

CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY,
    incident_id INTEGER,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,          -- 'mtr'
    target TEXT NOT NULL,
    data TEXT NOT NULL           -- JSON
);
CREATE INDEX IF NOT EXISTS captures_incident ON captures(incident_id);

-- network context (ISP, CGNAT, path...) each time it is discovered
CREATE TABLE IF NOT EXISTS networks (
    ts REAL NOT NULL,
    data TEXT NOT NULL           -- JSON
);

-- WAN usage read from the router (SNMP), one row per window
CREATE TABLE IF NOT EXISTS link_usage (
    ts REAL NOT NULL,
    down_mbps REAL, up_mbps REAL, down_pct REAL, up_pct REAL, cpu_pct REAL
);
CREATE INDEX IF NOT EXISTS link_usage_ts ON link_usage(ts);

-- settings edited from the web UI (JSON values); 'version' changes on every write
CREATE TABLE IF NOT EXISTS speedtests (
    ts REAL NOT NULL,
    data TEXT NOT NULL           -- JSON (speedtest.Result)
);
CREATE INDEX IF NOT EXISTS speedtests_ts ON speedtests (ts);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,   -- argon2id
    created REAL NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',      -- admin | viewer
    disabled INTEGER NOT NULL DEFAULT 0
);

-- one-time links to join (new user) or to set a new password (existing user); only the hash is kept
CREATE TABLE IF NOT EXISTS invites (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    user_id INTEGER,               -- set: password reset for this user; NULL: a new account
    expires REAL NOT NULL
);
"""


def data_dir() -> Path:
    base = os.environ.get("ISITMYISP_DATA") or os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "isitmyisp"
    )
    return Path(base)


def default_path() -> Path:
    return data_dir() / "data.db"


@dataclass
class Incident:
    id: int
    opened: float
    closed: float | None
    code: str
    evidence: list[str]
    peak_loss: float
    scope: str = "internet"
    details: dict | None = None

    @property
    def tunnel(self) -> str | None:
        return self.scope[len("tunnel:"):] if self.scope.startswith("tunnel:") else None

    def duration(self, now: float | None = None) -> float:
        return (self.closed or now or time.time()) - self.opened


@dataclass
class Capture:
    id: int
    incident_id: int | None
    ts: float
    kind: str
    target: str
    data: dict


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.db.executescript(SCHEMA)
            cols = {r[1] for r in self.db.execute("PRAGMA table_info(samples)")}
            if "rtt_median" not in cols:  # databases created by v0.1.0.dev0
                self.db.execute("ALTER TABLE samples ADD COLUMN rtt_median REAL")
            wcols = {r[1] for r in self.db.execute("PRAGMA table_info(windows)")}
            if "evidence" not in wcols:
                self.db.execute("ALTER TABLE windows ADD COLUMN evidence TEXT")
            icols = {r[1] for r in self.db.execute("PRAGMA table_info(incidents)")}
            if "scope" not in icols:  # databases created before tunnel mode
                self.db.execute("ALTER TABLE incidents ADD COLUMN scope TEXT NOT NULL DEFAULT 'internet'")
            for col in ("alerted", "close_alerted"):  # databases created before alerts
                if col not in icols:
                    self.db.execute(f"ALTER TABLE incidents ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
            if "details" not in icols:
                self.db.execute("ALTER TABLE incidents ADD COLUMN details TEXT")
            ucols = {r[1] for r in self.db.execute("PRAGMA table_info(users)")}
            if "role" not in ucols:  # databases created before roles: everyone stays an admin
                self.db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
            if "disabled" not in ucols:
                self.db.execute("ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0")

    # ------------------------------------------------------------ writes

    def add_window(self, role: str, s: WindowStats, ts: float | None = None) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO samples (ts, role, target, sent, received, rtt_min, rtt_avg, rtt_max, jitter, rtt_median)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts or time.time(), role, s.target, s.sent, s.received,
                 s.rtt_min, s.rtt_avg, s.rtt_max, s.jitter, s.rtt_median),
            )

    def add_window_verdict(self, code: str, seconds: float, ts: float | None = None,
                           evidence: list[str] | None = None) -> None:
        with self._lock:
            self.db.execute("INSERT INTO windows (ts, seconds, code, evidence) VALUES (?,?,?,?)",
                            (ts or time.time(), seconds, code, json.dumps(evidence) if evidence else None))

    def open_incident(self, code: str, evidence: list[str], ts: float | None = None,
                      scope: str = "internet") -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO incidents (opened, code, evidence, scope) VALUES (?,?,?,?)",
                                  (ts or time.time(), code, json.dumps(evidence), scope))
            self.db.commit()
            return int(cur.lastrowid)

    def bump_peak_loss(self, incident_id: int, loss: float) -> None:
        with self._lock:
            self.db.execute("UPDATE incidents SET peak_loss = MAX(peak_loss, ?) WHERE id = ?", (loss, incident_id))

    def close_incident(self, incident_id: int, ts: float | None = None) -> None:
        with self._lock:
            self.db.execute("UPDATE incidents SET closed = ? WHERE id = ?", (ts or time.time(), incident_id))
            self.db.commit()

    def close_dangling(self, ts: float | None = None) -> None:
        """Incidents left open by a crash/restart are closed at the last window we have."""
        with self._lock:
            last = self.db.execute("SELECT MAX(ts) FROM windows").fetchone()[0]
            self.db.execute("UPDATE incidents SET closed = ? WHERE closed IS NULL AND scope != 'failover'",
                            (last or ts or time.time(),))
            self.db.commit()

    def add_capture(self, incident_id: int | None, kind: str, target: str, data: dict,
                    ts: float | None = None) -> None:
        with self._lock:
            self.db.execute("INSERT INTO captures (incident_id, ts, kind, target, data) VALUES (?,?,?,?,?)",
                            (incident_id, ts or time.time(), kind, target, json.dumps(data)))
            self.db.commit()

    def add_network(self, data: dict, ts: float | None = None) -> None:
        with self._lock:
            self.db.execute("INSERT INTO networks VALUES (?,?)", (ts or time.time(), json.dumps(data)))
            self.db.commit()

    def commit(self) -> None:
        with self._lock:
            self.db.commit()

    def prune(self, samples_days: int = 35, windows_days: int = 400, now: float | None = None) -> int:
        """Retention. Per-target samples (the bulk: ~32k rows/day) are kept 35 days, enough for a
        monthly report. Window verdicts, incidents and their mtr evidence are small and kept ~13 months."""
        now = now or time.time()
        with self._lock:
            n = self.db.execute("DELETE FROM samples WHERE ts < ?", (now - samples_days * 86400,)).rowcount
            n += self.db.execute("DELETE FROM link_usage WHERE ts < ?", (now - samples_days * 86400,)).rowcount
            for table in ("windows", "networks", "speedtests"):
                n += self.db.execute(f"DELETE FROM {table} WHERE ts < ?", (now - windows_days * 86400,)).rowcount
            # incidents closed that long ago go too, with their mtr evidence (one still open never does)
            cutoff = now - windows_days * 86400
            n += self.db.execute("DELETE FROM captures WHERE incident_id IN "
                                 "(SELECT id FROM incidents WHERE closed IS NOT NULL AND closed < ?)", (cutoff,)).rowcount
            n += self.db.execute("DELETE FROM incidents WHERE closed IS NOT NULL AND closed < ?", (cutoff,)).rowcount
            n += self.db.execute("DELETE FROM captures WHERE incident_id IS NULL AND ts < ?", (cutoff,)).rowcount
            self.db.commit()
        return n

    def close(self) -> None:
        with self._lock:
            self.db.commit()
            self.db.close()

    # ------------------------------------------------------------ reads (used by the report)

    def windows_between(self, start: float, end: float) -> list[tuple[float, float, str]]:
        with self._lock:
            return self.db.execute("SELECT ts, seconds, code FROM windows WHERE ts BETWEEN ? AND ? ORDER BY ts",
                                   (start, end)).fetchall()

    def brief_events(self, start: float, end: float) -> list[dict]:
        """Bad windows that never became an incident (hysteresis filtered them): short blips.
        Consecutive windows with the same verdict are merged."""
        with self._lock:
            rows = self.db.execute("SELECT ts, seconds, code, evidence FROM windows WHERE ts BETWEEN ? AND ?"
                                   " AND code NOT IN ('ok', 'no_data', 'speedtest') ORDER BY ts", (start, end)).fetchall()
        incidents = self.incidents_between(start, end)
        def in_incident(ts: float, secs: float) -> bool:
            return any(i.opened - 1 <= ts - secs and ts <= (i.closed or end) + 1 for i in incidents)
        events: list[dict] = []
        for ts, secs, code, ev in rows:
            if in_incident(ts, secs):
                continue
            if events and events[-1]["code"] == code and ts - secs - events[-1]["end"] <= secs:
                events[-1]["end"] = ts
                continue
            events.append({"start": ts - secs, "end": ts, "code": code, "evidence": json.loads(ev) if ev else []})
        return events

    def samples_between(self, start: float, end: float, role: str | None = None) -> list[sqlite3.Row]:
        q = ("SELECT ts, role, target, sent, received, rtt_median, jitter FROM samples WHERE ts BETWEEN ? AND ?"
             + (" AND role = ?" if role else "") + " ORDER BY ts")
        with self._lock:
            cur = self.db.execute(q, (start, end, role) if role else (start, end))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def incidents_between(self, start: float, end: float, scope: str | None = "internet") -> list[Incident]:
        """scope='internet' (default), 'tunnel:<name>', 'tunnels' (any tunnel) or None (everything)."""
        q = ("SELECT id, opened, closed, code, evidence, peak_loss, scope, details FROM incidents"
             " WHERE opened <= ? AND (closed IS NULL OR closed >= ?)")
        args: list = [end, start]
        if scope == "tunnels":
            q += " AND scope LIKE 'tunnel:%'"
        elif scope is not None:
            q += " AND scope = ?"
            args.append(scope)
        with self._lock:
            rows = self.db.execute(q + " ORDER BY opened", args).fetchall()
        return [Incident(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5], r[6], json.loads(r[7]) if r[7] else None)
                for r in rows]

    def set_incident_details(self, incident_id: int, details: dict) -> None:
        with self._lock:
            self.db.execute("UPDATE incidents SET details = ? WHERE id = ?", (json.dumps(details), incident_id))

    def add_link_usage(self, ts: float, u) -> None:
        with self._lock:
            self.db.execute("INSERT INTO link_usage VALUES (?,?,?,?,?,?)",
                            (ts, u.down_mbps, u.up_mbps, u.down_pct, u.up_pct, u.cpu_pct))

    def add_speedtest(self, result) -> None:
        with self._lock:
            self.db.execute("INSERT INTO speedtests (ts, data) VALUES (?, ?)", (result.ts, json.dumps(result.__dict__)))
            self.db.commit()

    def speedtests_between(self, start: float, end: float) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT data FROM speedtests WHERE ts BETWEEN ? AND ? ORDER BY ts",
                                   (start, end)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def speed_bytes_since(self, start: float) -> int:
        return sum(int(r.get("bytes_used") or 0) for r in self.speedtests_between(start, 2e10))

    def link_usage_between(self, start: float, end: float) -> list[tuple]:
        with self._lock:
            return self.db.execute("SELECT ts, down_mbps, up_mbps, down_pct, up_pct, cpu_pct FROM link_usage"
                                   " WHERE ts BETWEEN ? AND ? ORDER BY ts", (start, end)).fetchall()

    def incidents_to_alert(self) -> tuple[list[Incident], list[Incident]]:
        """(open incidents not alerted yet, closed incidents whose 'opened' alert went out but not the 'closed' one)."""
        cols = "id, opened, closed, code, evidence, peak_loss, scope"
        with self._lock:
            opened = self.db.execute(f"SELECT {cols} FROM incidents WHERE closed IS NULL AND alerted = 0").fetchall()
            closed = self.db.execute(f"SELECT {cols} FROM incidents WHERE closed IS NOT NULL AND alerted = 1"
                                     " AND close_alerted = 0").fetchall()
        mk = lambda r: Incident(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5], r[6])  # noqa: E731
        return [mk(r) for r in opened], [mk(r) for r in closed]

    def mark_alerted(self, incident_id: int, which: str) -> None:
        col = "alerted" if which == "opened" else "close_alerted"
        with self._lock:
            self.db.execute(f"UPDATE incidents SET {col} = 1 WHERE id = ?", (incident_id,))
            self.db.commit()

    def skip_close_alerts_for_unalerted(self) -> None:
        """Incidents shorter than the alert threshold closed without an 'opened' alert: never alert them."""
        with self._lock:
            self.db.execute("UPDATE incidents SET close_alerted = 1 WHERE closed IS NOT NULL AND alerted = 0")
            self.db.commit()

    def active_incidents(self) -> list[Incident]:
        with self._lock:
            rows = self.db.execute("SELECT id, opened, closed, code, evidence, peak_loss, scope FROM incidents"
                                   " WHERE closed IS NULL ORDER BY opened").fetchall()
        return [Incident(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5], r[6]) for r in rows]

    def last_window(self) -> tuple[float, float, str] | None:
        with self._lock:
            return self.db.execute("SELECT ts, seconds, code FROM windows ORDER BY ts DESC LIMIT 1").fetchone()

    def latest_samples(self) -> list[dict]:
        """The targets of the most recent window only: a target removed from the settings
        (or from the path after a re-discovery) must not linger on the dashboard or in /metrics."""
        with self._lock:
            cur = self.db.execute(
                "SELECT ts, role, target, sent, received, rtt_median, jitter FROM samples"
                " WHERE ts = (SELECT MAX(ts) FROM samples) ORDER BY role, target")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def incident_counts(self) -> dict[tuple[str, str], int]:
        with self._lock:
            rows = self.db.execute("SELECT scope, code, COUNT(*) FROM incidents GROUP BY scope, code").fetchall()
        return {(r[0], r[1]): r[2] for r in rows}

    def captures_for(self, incident_ids: list[int]) -> dict[int, list[Capture]]:
        if not incident_ids:
            return {}
        marks = ",".join("?" * len(incident_ids))
        with self._lock:
            rows = self.db.execute(f"SELECT id, incident_id, ts, kind, target, data FROM captures"
                                   f" WHERE incident_id IN ({marks}) ORDER BY ts", incident_ids).fetchall()
        out: dict[int, list[Capture]] = {}
        for r in rows:
            out.setdefault(r[1], []).append(Capture(r[0], r[1], r[2], r[3], r[4], json.loads(r[5])))
        return out

    def network_at(self, ts: float) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT data FROM networks WHERE ts <= ? ORDER BY ts DESC LIMIT 1", (ts,)).fetchone()
            if not row:
                row = self.db.execute("SELECT data FROM networks ORDER BY ts LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------ settings & users

    def get_setting(self, key: str, default=None):
        with self._lock:
            row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_settings(self, values: dict, bump: bool = True) -> None:
        """bump=False for internal secrets: they must not make the monitor reload its configuration."""
        with self._lock:
            for k, v in values.items():
                self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
            if not bump:
                self.db.commit()
                return
            version = (self.get_setting("_version", 0) or 0) + 1
            self.db.execute("INSERT INTO settings (key, value) VALUES ('_version', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(version),))
            self.db.commit()

    def settings_version(self) -> int:
        return int(self.get_setting("_version", 0) or 0)

    def user_count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def add_user(self, username: str, password_hash: str, role: str = "admin") -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO users (username, password_hash, created, role) VALUES (?,?,?,?)",
                                  (username, password_hash, time.time(), role))
            self.db.commit()
            return int(cur.lastrowid)

    def user_info(self, user_id: int) -> dict | None:
        with self._lock:
            r = self.db.execute("SELECT id, username, role, disabled, created FROM users WHERE id = ?",
                                (user_id,)).fetchone()
        return {"id": r[0], "username": r[1], "role": r[2], "disabled": bool(r[3]), "created": r[4]} if r else None

    def list_users(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id, username, role, disabled, created FROM users ORDER BY id").fetchall()
        return [{"id": r[0], "username": r[1], "role": r[2], "disabled": bool(r[3]), "created": r[4]} for r in rows]

    def set_user(self, user_id: int, *, role: str | None = None, disabled: bool | None = None) -> None:
        with self._lock:
            if role is not None:
                self.db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            if disabled is not None:
                self.db.execute("UPDATE users SET disabled = ? WHERE id = ?", (int(disabled), user_id))
            self.db.commit()

    def active_admins(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0").fetchone()[0]

    def add_invite(self, token_hash: str, username: str, role: str, expires: float,
                   user_id: int | None = None) -> None:
        with self._lock:
            self.db.execute("DELETE FROM invites WHERE username = ? OR expires < ?", (username, time.time()))
            self.db.execute("INSERT INTO invites (token_hash, username, role, user_id, expires) VALUES (?,?,?,?,?)",
                            (token_hash, username, role, user_id, expires))
            self.db.commit()

    def get_invite(self, token_hash: str) -> dict | None:
        with self._lock:
            r = self.db.execute("SELECT username, role, user_id, expires FROM invites WHERE token_hash = ?",
                                (token_hash,)).fetchone()
        if not r or r[3] < time.time():
            return None
        return {"username": r[0], "role": r[1], "user_id": r[2], "expires": r[3]}

    def delete_invite(self, token_hash: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM invites WHERE token_hash = ?", (token_hash,))
            self.db.commit()

    def pending_invites(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT username, role, user_id, expires FROM invites WHERE expires >= ? "
                                   "ORDER BY expires", (time.time(),)).fetchall()
        return [{"username": r[0], "role": r[1], "user_id": r[2], "expires": r[3]} for r in rows]

    def get_user(self, *, user_id: int | None = None, username: str | None = None) -> tuple | None:
        q, arg = ("id = ?", user_id) if user_id is not None else ("username = ?", username)
        with self._lock:
            return self.db.execute(f"SELECT id, username, password_hash FROM users WHERE {q}", (arg,)).fetchone()

    def set_password_hash(self, user_id: int, password_hash: str) -> None:
        with self._lock:
            self.db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            self.db.commit()

    def first_and_last_window(self) -> tuple[float | None, float | None]:
        with self._lock:
            return self.db.execute("SELECT MIN(ts), MAX(ts) FROM windows").fetchone()
