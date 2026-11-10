"""Call quality: what a voice call would sound like over this connection, from what we measure.

ITU-T G.107 E-model, simplified the usual way for network monitoring (Cole & Rosenbluth, 2001):

  one-way delay  d  = RTT/2 + jitter buffer (2 x jitter) + 20 ms codec and packetization
  delay impairment  Id = 0.024 d + 0.11 (d - 177.3) H(d - 177.3)
  loss impairment   Ie = 95 p / (p + 25.1)       G.711 with packet-loss concealment, random loss
  R  = 93.2 - Id - Ie         (0..100)
  MOS = 1 + 0.035 R + 7e-6 R (R - 60) (100 - R)   (1..4.5)

It is an ESTIMATE from ping, not a measured call: pings go every 2 s while a call sends a packet
every 20 ms, so short bursts of loss or jitter between pings are not seen. Loss is pooled over a
rolling 5 minutes (one lost ping out of 15 is not a 6.7 % loss rate for a call). The bands are the
ITU-T G.109 user-satisfaction categories; "fit for calls" means R >= 70 (MOS ~3.6).
"""

from __future__ import annotations

from dataclasses import dataclass

CODEC_MS = 20.0
FIT_R = 70.0           # below this, "many users dissatisfied" (G.109)
BANDS = ((90.0, "excellent"), (80.0, "good"), (70.0, "fair"), (60.0, "poor"), (0.0, "bad"))


@dataclass
class CallQuality:
    r: float
    mos: float
    band: str          # excellent | good | fair | poor | bad

    @property
    def fit(self) -> bool:
        return self.r >= FIT_R


MOS_BANDS = ((4.34, "excellent"), (4.03, "good"), (3.6, "fair"), (3.1, "poor"), (0.0, "bad"))  # R 90/80/70/60


def band_of(mos: float) -> str:
    return next(name for floor, name in MOS_BANDS if mos >= floor)


def r_factor(rtt_ms: float, jitter_ms: float | None, loss_pct: float) -> float:
    d = rtt_ms / 2 + 2 * (jitter_ms or 0.0) + CODEC_MS
    i_d = 0.024 * d + (0.11 * (d - 177.3) if d > 177.3 else 0.0)
    p = max(0.0, min(100.0, loss_pct))
    i_e = 95.0 * p / (p + 25.1) if p > 0 else 0.0
    return max(0.0, min(100.0, 93.2 - i_d - i_e))


def mos_from_r(r: float) -> float:
    if r <= 0:
        return 1.0
    if r >= 100:
        return 4.5
    return 1 + 0.035 * r + 7e-6 * r * (r - 60) * (100 - r)


def call_quality(rtt_ms: float | None, jitter_ms: float | None, loss_pct: float) -> CallQuality | None:
    """None when there is no latency to judge (nothing answered: no call possible either way)."""
    if rtt_ms is None:
        return None if loss_pct < 100 else CallQuality(0.0, 1.0, "bad")
    r = r_factor(rtt_ms, jitter_ms, loss_pct)
    band = next(name for floor, name in BANDS if r >= floor)
    return CallQuality(round(r, 1), round(mos_from_r(r), 2), band)


def window_quality(samples: list[dict]) -> CallQuality | None:
    """One window's quality from the rows of its destinations (VoIP target, or the anchors):
    median latency, mean jitter and mean loss across them."""
    rows = [s for s in samples if s["sent"]]
    if not rows:
        return None
    loss = sum(100.0 * (s["sent"] - s["received"]) / s["sent"] for s in rows) / len(rows)
    rtts = sorted(s["rtt_median"] for s in rows if s["rtt_median"] is not None)
    jits = [s["jitter"] for s in rows if s["jitter"] is not None]
    rtt = rtts[len(rtts) // 2] if rtts else None
    return call_quality(rtt, sum(jits) / len(jits) if jits else None, loss)


ROLLING_WINDOWS = 10   # 5 minutes of 30-second windows


def rolling(windows: list[tuple[float, list[dict]]], span: int = ROLLING_WINDOWS) -> list[tuple[float, CallQuality]]:
    """[(ts, rows of that window)] sorted by time -> [(ts, quality)] where each point pools the
    `span` windows centred on it (the last point only has the past): total loss rate, median
    latency, mean jitter. Centred, so a bad stretch starts and ends where the loss did."""
    out = []
    half = span // 2
    for i, (ts, _) in enumerate(windows):
        pool = [r for _, rows in windows[max(0, i - half):i + half + 1] for r in rows if r["sent"]]
        if not pool:
            continue
        sent = sum(r["sent"] for r in pool)
        loss = 100.0 * (sent - sum(r["received"] for r in pool)) / sent
        rtts = sorted(r["rtt_median"] for r in pool if r["rtt_median"] is not None)
        jits = [r["jitter"] for r in pool if r["jitter"] is not None]
        q = call_quality(rtts[len(rtts) // 2] if rtts else None, sum(jits) / len(jits) if jits else None, loss)
        if q is not None:
            out.append((ts, q))
    return out


def quality_series(rows: list[dict]) -> list[tuple[float, CallQuality]]:
    by_ts: dict[float, list[dict]] = {}
    for r in rows:
        by_ts.setdefault(r["ts"], []).append(r)
    return rolling(sorted(by_ts.items()))
