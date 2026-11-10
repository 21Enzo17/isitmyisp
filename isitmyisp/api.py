"""Machine-readable views of the store: Prometheus metrics and JSON status."""

from __future__ import annotations

import time

from . import __version__
from .store import Store

VERDICT_CODES = ("ok", "local", "access", "isp", "remote", "dns", "no_data", "speedtest")


def is_stale(last: tuple | None, now: float) -> bool:
    return bool(last and now - last[0] > 5 * max(30.0, last[1]))


def _prom_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def metrics_text(store: Store, now: float | None = None) -> str:
    now = now or time.time()
    lines: list[str] = []

    def metric(name: str, help_: str, kind: str, values: list[tuple[dict, float]]) -> None:
        lines.append(f"# HELP isitmyisp_{name} {help_}")
        lines.append(f"# TYPE isitmyisp_{name} {kind}")
        for labels, value in values:
            lab = ",".join(f'{k}="{_prom_escape(str(v))}"' for k, v in labels.items())
            lines.append(f"isitmyisp_{name}{{{lab}}} {value}" if lab else f"isitmyisp_{name} {value}")

    samples = store.latest_samples()
    metric("loss_ratio", "Packet/probe loss in the last window (0-1).", "gauge",
           [({"role": s["role"], "target": s["target"]}, round((s["sent"] - s["received"]) / s["sent"], 4))
            for s in samples if s["sent"]])
    metric("rtt_median_ms", "Median round-trip time in the last window.", "gauge",
           [({"role": s["role"], "target": s["target"]}, round(s["rtt_median"], 3)) for s in samples
            if s["rtt_median"] is not None])
    last = store.last_window()
    current = last[2] if last else "no_data"
    metric("verdict", "1 for the current verdict of the last window.", "gauge",
           [({"code": c}, 1 if c == current else 0) for c in VERDICT_CODES])
    metric("last_window_timestamp_seconds", "Unix time of the last measurement window.", "gauge",
           [({}, round(last[0], 3) if last else 0)])
    active = store.active_incidents()
    metric("incident_active", "1 if an incident is open for this scope.", "gauge",
           [({"scope": i.scope, "code": i.code}, 1) for i in active] or [({"scope": "internet", "code": "none"}, 0)])
    metric("incidents_total", "Incidents recorded, by scope and cause.", "counter",
           [({"scope": sc, "code": c}, n) for (sc, c), n in sorted(store.incident_counts().items())])
    return "\n".join(lines) + "\n"


def status_json(store: Store, now: float | None = None) -> dict:
    now = now or time.time()
    last = store.last_window()
    return {
        "version": __version__,
        "verdict": last[2] if last else "no_data",
        "last_window": last[0] if last else None,
        "stale": is_stale(last, now),
        "active_incidents": [{"scope": i.scope, "code": i.code, "opened": i.opened, "evidence": i.evidence}
                             for i in store.active_incidents()],
        "targets": store.latest_samples(),
    }
