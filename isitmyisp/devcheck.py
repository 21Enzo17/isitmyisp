"""Check from this device (#66): what a PC or phone measured, crossed with the probe's own windows.

The browser measures for ~15 s (see webapp/static/check.js): HTTP round trips to the probe (latency,
jitter, loss inside the LAN), a download and an upload to the probe, and HTTPS round trips to the
internet anchors. Here that is boiled down and set against what the probe saw in the same minutes:

- the probe saw a problem too       -> shared: the router or the ISP, the usual verdict applies;
- probe fine, device-to-probe bad   -> device_link: between the device and the router (Wi-Fi, cable, switch);
- probe fine, LAN fine, internet bad from the device only -> device_path: the device itself (VPN,
  firewall, proxy, browser);
- everything fine                   -> fine: the network is fine, it's the app or the service;
- no windows from the probe         -> no_probe: the monitor wasn't measuring, nothing to compare with.

Pure functions over plain dicts; the web layer validates the browser's JSON with `parse`.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import statistics

LAN_LOSS_BAD = 10.0      # % of HTTP round trips to the probe that never came back
LAN_MS_BAD = 100.0       # median HTTP round trip inside the LAN
LAN_JITTER_BAD = 50.0    # mean difference between consecutive round trips
LAN_MBPS_BAD = 5.0       # download or upload between the device and the probe
INET_LOSS_BAD = 20.0     # % of HTTPS requests to the anchors that failed

OK_CODES = {"ok", "no_data", "speedtest", "remote"}   # probe windows that are not a problem of this network
MAX_SAMPLES = 60
WINDOW_SLACK_S = 35
MAX_SECONDS = 600


def _num(v, lo: float = 0.0, hi: float = 1e6) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if lo <= v <= hi else None


def _series(v) -> list[float | None]:
    """A list of round trips in ms, None for a lost one; anything else is dropped."""
    if not isinstance(v, list):
        return []
    return [_num(x, 0, 60_000) if x is not None else None for x in v[:MAX_SAMPLES]]


def parse(raw: dict, anchors: list[str]) -> dict:
    """The browser's JSON, kept to what we expect: numbers in range, only the configured anchors."""
    if not isinstance(raw, dict):
        raise ValueError("expected an object")   # noqa: TRY004 (one error type for the web layer)
    inet = raw.get("inet") if isinstance(raw.get("inet"), dict) else {}
    out = {"lan": _series(raw.get("lan")),
           "down_mbps": _num(raw.get("down_mbps"), 0, 100_000),
           "up_mbps": _num(raw.get("up_mbps"), 0, 100_000),
           "inet": {a: _series(inet.get(a)) for a in anchors if a in inet},
           "seconds": _num(raw.get("seconds"), 1, MAX_SECONDS) or 15.0}
    if not out["lan"]:
        raise ValueError("no measurements")
    return out


def series_stats(rtts: list[float | None]) -> dict:
    got = [r for r in rtts if r is not None]
    loss = 100.0 * (len(rtts) - len(got)) / len(rtts) if rtts else None
    jitter = statistics.fmean(abs(a - b) for a, b in itertools.pairwise(got)) if len(got) > 1 else None
    return {"sent": len(rtts), "loss": loss, "ms": statistics.median(got) if got else None, "jitter": jitter}


def device_label(user_agent: str) -> str:
    """'Windows · Chrome', 'Android · Firefox', 'iPhone · Safari': enough to tell devices apart."""
    ua = user_agent or ""
    os_ = next((name for pat, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                       ("CrOS", "ChromeOS"), ("Windows", "Windows"), ("Mac OS X", "Mac"),
                                       ("Linux", "Linux")) if pat in ua), "?")
    browser = next((name for pat, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser", "Samsung"),
                                           ("Firefox/", "Firefox"), ("FxiOS", "Firefox"), ("CriOS", "Chrome"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari")) if pat in ua), "?")
    return f"{os_} · {browser}"


def device_key(remote_addr: str | None, user_agent: str) -> str:
    """Tells devices apart in the report ("checked from 3 devices") without storing the address."""
    return hashlib.sha256(f"{remote_addr}|{user_agent}".encode()).hexdigest()[:12]


def _probe_view(windows: list, samples: list) -> dict:
    codes = [w[2] for w in windows]
    bad = [c for c in codes if c not in OK_CODES]
    # anchors the probe itself reached over TCP 443: the only ones fair to judge the browser by
    reached = {re.sub(r"^tcp://|:443$", "", s["target"]) for s in samples
               if s["role"] == "tcp" and s["received"]}
    return {"windows": len([c for c in codes if c != "no_data"]),
            "bad": max(set(bad), key=bad.count) if bad else None,
            "bad_windows": len(bad), "reached": reached, "measured_tcp": any(s["role"] == "tcp" for s in samples)}


def cross(dev: dict, windows: list, samples: list) -> dict:
    """The verdict for one device check. `windows` are (ts, seconds, code) of the probe in the same
    minutes, `samples` its sample rows (role, target, received)."""
    probe = _probe_view(windows, samples)
    lan = series_stats(dev["lan"])
    inet_all = dev.get("inet") or {}
    fair = {a: s for a, s in inet_all.items() if not probe["measured_tcp"] or a in probe["reached"]}
    # an anchor that never answered while others did is most likely one browsers can't use
    # (no HTTPS on that address), not loss: leave it out
    if any(any(r is not None for r in s) for s in fair.values()):
        fair = {a: s for a, s in fair.items() if any(r is not None for r in s)}
    inet = series_stats([r for s in fair.values() for r in s])

    why: list[str] = []
    if lan["loss"] is not None and lan["loss"] >= LAN_LOSS_BAD:
        why.append("lan_loss")
    if lan["ms"] is not None and lan["ms"] >= LAN_MS_BAD:
        why.append("lan_ms")
    if lan["jitter"] is not None and lan["jitter"] >= LAN_JITTER_BAD:
        why.append("lan_jitter")
    for k in ("down_mbps", "up_mbps"):
        if dev.get(k) is not None and dev[k] < LAN_MBPS_BAD:
            why.append(k)
    inet_bad = inet["sent"] > 0 and inet["loss"] is not None and inet["loss"] >= INET_LOSS_BAD

    if not probe["windows"]:
        code = "no_probe"
    elif probe["bad"]:
        code = "shared"
    elif why:
        code = "device_link"
    elif inet_bad:
        code = "device_path"
    else:
        code = "fine"
    return {"code": code, "why": why, "lan": lan, "inet": inet, "anchors": sorted(fair),
            "down_mbps": dev.get("down_mbps"), "up_mbps": dev.get("up_mbps"),
            "probe": {"windows": probe["windows"], "bad": probe["bad"], "bad_windows": probe["bad_windows"]}}


def run(store, dev: dict, now: float, label: str, key: str, user: str | None = None) -> dict:
    """Cross a parsed device measurement with the probe's windows of the same minutes; returns the record."""
    # windows are stamped when they end: the one running when the check started ended up to a window later
    start = now - dev["seconds"] - WINDOW_SLACK_S
    windows = store.windows_between(start, now + 30)
    samples = store.samples_between(start, now + 30)
    rec = cross(dev, windows, samples)
    rec.update(ts=now, seconds=dev["seconds"], device=label, key=key, user=user)
    return rec
