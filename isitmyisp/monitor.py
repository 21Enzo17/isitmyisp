"""Continuous monitoring: verdict per window, incidents with hysteresis, evidence capture.

Kept free of I/O decisions so it can be tested with synthetic measurements:
the caller feeds `step()` and injects how evidence is captured.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import asn
from .classifier import Measurements, Verdict, classify
from .probes.icmp import WindowStats
from .probes.mtr import MtrError, analyze_path, path_to_dict, run_mtr
from .stats import Baseline, Hysteresis, Transition
from .store import Store

CaptureFn = Callable[[str, int], None]  # (target, incident_id)


@dataclass
class StepResult:
    verdict: Verdict
    transition: Transition
    incident_id: int | None


class Monitor:
    def __init__(self, store: Store, window_seconds: float, capture: CaptureFn | None = None,
                 recapture_every: float = 600.0, open_after: int = 2, close_after: int = 2):
        self.store = store
        self.window = window_seconds
        self.capture = capture
        self.recapture_every = recapture_every
        self.baselines: dict[str, Baseline] = {}
        self.hyst = Hysteresis(open_after=open_after, close_after=close_after)
        self.incident_id: int | None = None
        self._last_capture = 0.0

    def resume(self) -> None:
        """Close incidents left open by a previous run (crash, reboot, upgrade)."""
        self.store.close_dangling()

    @staticmethod
    def evidence_target(m: Measurements) -> str:
        """Where to point mtr: the worst anchor (fall back to the first one)."""
        anchors = [a for a in m.anchors if a.sent]
        if not anchors:
            return "1.1.1.1"
        return max(anchors, key=lambda a: (a.loss, a.rtt_median or 0)).target

    @staticmethod
    def worst_loss(m: Measurements, code: str) -> float:
        pool: list[WindowStats] = m.home if code == "local" else m.anchors
        pool = [s for s in pool if s.sent]
        return max((s.loss for s in pool), default=0.0)

    def step(self, m: Measurements, rows: list[tuple[str, WindowStats]], now: float | None = None) -> StepResult:
        now = now or time.time()
        v = classify(m, self.baselines)
        for role, st in rows:
            self.store.add_window(role, st, ts=now)
            self.baselines.setdefault(st.target, Baseline()).update(st.rtt_median, healthy=v.code == "ok")
        self.store.add_window_verdict(v.code, self.window, ts=now)

        tr = self.hyst.update(v.code)
        # Timestamps mark the END of each window. An incident started when the first of its bad
        # windows started, and ended when the first of the good windows started.
        opened = now - self.window * self.hyst.open_after
        if tr.closed and self.incident_id is not None:
            ended = opened if tr.opened else now - self.window * self.hyst.close_after
            self.store.close_incident(self.incident_id, ts=ended)
            self.incident_id = None
        if tr.opened:
            self.incident_id = self.store.open_incident(tr.opened, v.evidence, ts=opened)
            self._capture(m, now, force=True)
        elif self.incident_id is not None:
            self._capture(m, now)
        if self.incident_id is not None:
            self.store.bump_peak_loss(self.incident_id, self.worst_loss(m, self.hyst.active or v.code))
        self.store.commit()
        return StepResult(v, tr, self.incident_id)

    def _capture(self, m: Measurements, now: float, force: bool = False) -> None:
        if self.capture is None or self.incident_id is None:
            return
        if force or now - self._last_capture >= self.recapture_every:
            self._last_capture = now
            self.capture(self.evidence_target(m), self.incident_id)


def mtr_capturer(store: Store, data_dir: Path | None, asn_online: bool = False, cycles: int = 30) -> CaptureFn:
    """Real capture: run mtr in a background thread and store the analyzed path."""

    def run(target: str, incident_id: int) -> None:
        def job() -> None:
            ts = time.time()
            try:
                hops = run_mtr(target, cycles=cycles)
            except MtrError as exc:
                store.add_capture(incident_id, "mtr", target, {"error": str(exc)}, ts=ts)
                return
            info = asn.lookup([h.host for h in hops], data_dir=data_dir, online=asn_online)
            store.add_capture(incident_id, "mtr", target, path_to_dict(analyze_path(target, hops), info), ts=ts)

        threading.Thread(target=job, daemon=True).start()

    return run
