"""Machine-readable views of the store: Prometheus metrics and JSON status."""

from __future__ import annotations

import time

from . import __version__, mos
from .store import Store

VERDICT_CODES = ("ok", "local", "access", "isp", "remote", "dns", "no_data", "speedtest")
GRADES = ("A", "B", "C", "D", "F")
CHECK_LEVEL = {"ok": 0, "warn": 1, "bad": 2}      # "skip" (not measured) is left out
LINK_FRESH_S = 600                                 # older SNMP readings are not "now" any more


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
    metric("jitter_ms", "Mean variation between consecutive round-trip times in the last window.", "gauge",
           [({"role": s["role"], "target": s["target"]}, round(s["jitter"], 3)) for s in samples
            if s.get("jitter") is not None])
    voip = [s for s in samples if s["role"] == "voip"]
    source = "voip" if any(s["received"] for s in voip) else "anchors"
    q = mos.window_quality(voip if source == "voip" else [s for s in samples if s["role"] == "anchor"])
    metric("call_quality_mos", "Estimated call quality of the last window (MOS 1-4.5, ITU-T G.107 E-model).",
           "gauge", [({"source": source}, q.mos)] if q else [])
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
    metric("incident_seconds_total", "Time spent in incidents, by scope and cause (open ones up to now).", "counter",
           [({"scope": sc, "code": c}, round(v, 1)) for (sc, c), v in sorted(store.incident_seconds(now).items())])
    metric("route_changes_total", "Times the route to a watched destination changed.", "counter",
           [({}, store.route_change_count())])

    st = store.latest_speedtest()
    if st:
        for name, key, help_ in (("speedtest_download_mbps", "down_mbps", "Download speed of the latest speed test."),
                                 ("speedtest_upload_mbps", "up_mbps", "Upload speed of the latest speed test."),
                                 ("speedtest_idle_latency_ms", "idle_ms", "Latency before the latest speed test."),
                                 ("speedtest_loaded_latency_ms", "loaded_ms",
                                  "Latency during the latest speed test's download (minus idle = bufferbloat).")):
            metric(name, help_, "gauge", [({}, round(st[key], 2))] if st.get(key) is not None else [])
        metric("speedtest_timestamp_seconds", "Unix time of the latest speed test.", "gauge", [({}, round(st["ts"], 3))])

    lu = store.latest_link_usage()
    if lu and now - lu[0] <= LINK_FRESH_S:
        _, down, up, down_pct, up_pct, cpu = lu
        metric("link_mbps", "Traffic on the router's internet link, read over SNMP.", "gauge",
               [({"direction": d}, round(v, 2)) for d, v in (("down", down), ("up", up)) if v is not None])
        metric("link_utilization_ratio", "Share of the plan's speed in use on the internet link (0-1).", "gauge",
               [({"direction": d}, round(v / 100, 4)) for d, v in (("down", down_pct), ("up", up_pct))
                if v is not None])
        metric("router_cpu_ratio", "Router CPU load, read over SNMP (0-1).", "gauge",
               [({}, round(cpu / 100, 4))] if cpu is not None else [])

    doc = store.last_doctor()
    if doc:
        metric("doctor_grade", "1 for the grade of the latest check-up of the network (A best, F worst).", "gauge",
               [({"grade": g}, 1 if g == doc.get("grade") else 0) for g in GRADES])
        metric("doctor_check", "Latest check-up, per check: 0 ok, 1 to look at, 2 bad.", "gauge",
               [({"check": c["id"], "scope": c.get("scope", "network")}, CHECK_LEVEL[c["status"]])
                for c in doc.get("checks", []) if c.get("status") in CHECK_LEVEL])
        metric("doctor_timestamp_seconds", "Unix time of the latest check-up.", "gauge", [({}, round(doc["ts"], 3))])

    metric("build_info", "Version of isitmyisp that serves these metrics.", "gauge", [({"version": __version__}, 1)])
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
