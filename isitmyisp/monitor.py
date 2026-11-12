"""Continuous monitoring: verdict per window, incidents with hysteresis, evidence capture.

Kept free of I/O decisions so it can be tested with synthetic measurements:
the caller feeds `step()` and injects how evidence is captured.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import asn
from .failover import Change, Provider, compare as compare_provider
from .classifier import Measurements, Verdict, assess, classify
from .config import Tunnel
from .probes.icmp import WindowStats
from .probes.mtr import MtrError, analyze_path, path_to_dict, run_mtr
from .stats import Baseline, Hysteresis, Transition
from .store import Store
from .services import CHECK_EVERY, FAILS_TO_DOWN, OKS_TO_UP, Check, Service, state as service_state
from .tunnels import TunnelVerdict, classify_tunnel

CaptureFn = Callable[[str, int], None]  # (target, incident_id)


TunnelSample = tuple[Tunnel, "WindowStats | None", "WindowStats | None"]  # (tunnel, underlay, overlay)

INTERNET_OK = ("ok", "remote", "dns")  # your own connection works in these states


@dataclass
class StepResult:
    verdict: Verdict
    transition: Transition
    incident_id: int | None
    tunnels: list[tuple[TunnelVerdict, Transition]] = field(default_factory=list)


class _TunnelState:
    def __init__(self, open_after: int, close_after: int):
        self.hyst = Hysteresis(open_after=open_after, close_after=close_after)
        self.incident_id: int | None = None
        self.ever_answered = False


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
        self._last_prune = 0.0
        self._open_after, self._close_after = open_after, close_after
        self._tunnels: dict[str, _TunnelState] = {}
        self._services: dict[str, int | None] = {}  # service name -> open incident id
        self._devices: dict[str, int | None] = {}   # device name -> open incident id

    def _merge_details(self, new: dict) -> None:
        """Across the whole incident, a cause is ruled out only if every window ruled it out."""
        old = getattr(self, "_details", None) or new
        ruled = [c for c in old["ruled_out"] if c in new["ruled_out"]]
        not_ruled = list(dict.fromkeys(old["not_ruled_out"] + new["not_ruled_out"]
                                       + [c for c in old["ruled_out"] if c not in new["ruled_out"]]))
        links = [d for d in (old.get("link"), new.get("link")) if d]
        peak = max(links, key=lambda d: max(d.get("down_pct") or 0, d.get("up_pct") or 0)) if links else None
        self._details = {"ruled_out": ruled, "not_ruled_out": not_ruled, "link": peak,
                         **({"intermittent": True} if old.get("intermittent") else {})}
        self.store.set_incident_details(self.incident_id, self._details)

    def observe_network(self, snapshot: dict, now: float | None = None) -> Change:
        """After every discovery: are we leaving through the main ISP? Opens/closes the failover incident.

        The main ISP is learned the first time one is seen (stored without bumping the settings
        version, so learning it doesn't restart the measuring session)."""
        now = now or time.time()
        primary = Provider.from_dict(self.store.get_setting("primary_isp"))
        change = compare_provider(snapshot, primary)
        if change.kind == "learn":
            self.store.set_settings({"primary_isp": change.current.to_dict()}, bump=False)
            return change
        open_ = [i for i in self.store.active_incidents() if i.scope == "failover"]
        if change.kind == "failover" and not open_:
            iid = self.store.open_incident("failover", change.evidence, ts=now, scope="failover")
            self.store.set_incident_details(iid, {"primary": primary.to_dict(), "backup": change.current.to_dict()})
        elif change.kind == "failback":
            for inc in open_:
                self.store.close_incident(inc.id, ts=now)
            if primary and not primary.asn and change.current.asn:  # ASN dataset arrived: remember the ASN too
                self.store.set_settings({"primary_isp": {**primary.to_dict(), "asn": change.current.asn,
                                                         "name": change.current.name}}, bump=False)
        return change

    def resume(self) -> None:
        """Close incidents left open by a previous run (crash, reboot, upgrade).
        A failover stays open: the first discovery after the restart decides whether it's still on."""
        self.store.close_dangling()
        # what's normal for each target, from the last day's healthy windows: after a restart the
        # latency is judged at once, and a slow spell going on right now isn't learned as normal
        for target, values in self.store.healthy_rtts(time.time() - 86400).items():
            b = self.baselines.setdefault(target, Baseline())
            for v in values:
                b.update(v, healthy=True)

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

    def step(self, m: Measurements, rows: list[tuple[str, WindowStats]], now: float | None = None,
             tunnels: list[TunnelSample] = (), services: list[tuple[Service, list[Check]]] = (),
             devices: list = (),
             suppress: bool = False) -> StepResult:
        """`suppress`: a speed test filled the link during this window. Its samples are kept (they show
        the latency under load) but it gets no verdict of its own: no incident opens or closes, no
        baseline learns from it, and it counts neither as healthy nor as a problem."""
        now = now or time.time()
        if suppress:
            for role, st in rows:
                self.store.add_window(role, st, ts=now)
            self.store.add_window_verdict("speedtest", self.window, ts=now)
            if m.link is not None:
                self.store.add_link_usage(now, m.link)
            self.store.commit()
            return StepResult(Verdict("speedtest"), Transition(), self.incident_id)
        v = classify(m, self.baselines)
        for role, st in rows:
            self.store.add_window(role, st, ts=now)
            self.baselines.setdefault(st.target, Baseline()).update(st.rtt_median, healthy=v.code == "ok")
        self.store.add_window_verdict(v.code, self.window, ts=now, evidence=v.evidence if v.code != "ok" else None)
        if m.link is not None:
            self.store.add_link_usage(now, m.link)
        if now - self._last_prune > 3600:  # retention, once an hour
            self._last_prune = now
            self.store.prune(now=now)

        tr = self.hyst.update(v.code)
        # Timestamps mark the END of each window. An incident started when the first of its bad
        # windows started, and ended when the first of the good windows started.
        opened = now - self.window * tr.since
        if tr.closed and self.incident_id is not None:
            ended = opened if tr.opened else now - self.window * tr.clean
            self.store.close_incident(self.incident_id, ts=ended)
            self.incident_id = None
        if tr.opened:
            self.incident_id = self.store.open_incident(tr.opened, v.evidence, ts=opened)
            self._details = assess(m, v, self.baselines)
            if tr.intermittent:
                self._details["intermittent"] = True    # it came and went: the report and alerts say so
            self.store.set_incident_details(self.incident_id, self._details)
            self._capture(m, now, force=True)
        elif self.incident_id is not None:
            self._capture(m, now)
        if self.incident_id is not None:
            self.store.bump_peak_loss(self.incident_id, self.worst_loss(m, self.hyst.active or v.code))
            if v.code != "ok" and self.hyst.group(v.code) == self.hyst.group(self.hyst.active or v.code):
                self._merge_details(assess(m, v, self.baselines))
        tunnel_results = [self._step_tunnel(t, under, over, v.code in INTERNET_OK, now)
                          for t, under, over in tunnels]
        for svc, checks in services:
            self._step_service(svc, checks, v.code in INTERNET_OK, now)
        for dev, checks in devices:                 # your own network is fine unless the verdict says so
            self._step_device(dev, checks, v.code != "local", now)
        self.store.commit()
        return StepResult(v, tr, self.incident_id, tunnel_results)

    def _step_service(self, svc: Service, checks: list[Check], internet_ok: bool, now: float) -> None:
        # Checks run every 30 s, so a short window may contain none: look back far enough that every
        # window has at least one result (otherwise the service blinks to "no data" on the dashboard).
        recent = [c for c in checks if c.ts > now - max(self.window, CHECK_EVERY * 1.5)]
        if recent:  # one sample row per window, so the dashboard and /metrics can show the service
            times = sorted(c.ms for c in recent if c.ok and c.ms is not None)
            med = times[len(times) // 2] if times else None
            ok_count = sum(1 for c in recent if c.ok)
            self.store.add_window(f"service:{svc.name}", WindowStats(
                svc.target, len(recent), ok_count, times[0] if times else None, med,
                times[-1] if times else None, None, med), ts=now)
        st = service_state(checks)
        iid = self._services.get(svc.name)
        if st == "down" and iid is None and internet_ok:
            last = checks[-1]
            evidence = [f"{svc.target}: {last.detail} ({FAILS_TO_DOWN}/{FAILS_TO_DOWN} checks failed)",
                        "your internet: OK at the same time"]
            iid = self.store.open_incident("service_down", evidence, ts=checks[-FAILS_TO_DOWN].ts,
                                           scope=f"service:{svc.name}")
            self._services[svc.name] = iid
            if self.capture is not None:
                host = urlparse(svc.target).hostname if svc.kind == "http" else svc.target.rpartition(":")[0]
                if host:
                    self.capture(host, iid)
        elif st == "up" and iid is not None:
            self.store.close_incident(iid, ts=checks[-OKS_TO_UP].ts)
            self._services[svc.name] = None

    def _step_device(self, dev, checks: list[Check], lan_ok: bool, now: float) -> None:
        """A device on your network: down when it stops answering while your router still does."""
        recent = [c for c in checks if c.ts > now - max(self.window, CHECK_EVERY * 1.5)]
        if recent:
            times = sorted(c.ms for c in recent if c.ok and c.ms is not None)
            med = times[len(times) // 2] if times else None
            self.store.add_window(f"device:{dev.name}", WindowStats(
                dev.endpoint, len(recent), sum(1 for c in recent if c.ok), times[0] if times else None, med,
                times[-1] if times else None, None, med), ts=now)
        st = service_state(checks)
        iid = self._devices.get(dev.name)
        if st == "down" and iid is None and lan_ok:
            evidence = [f"{dev.endpoint} ({dev.how}): {checks[-1].detail} ({FAILS_TO_DOWN}/{FAILS_TO_DOWN} checks failed)",
                        "your network: OK at the same time (your router answered)"]
            self._devices[dev.name] = self.store.open_incident("device_down", evidence, ts=checks[-FAILS_TO_DOWN].ts,
                                                               scope=f"device:{dev.name}")
        elif st == "up" and iid is not None:
            self.store.close_incident(iid, ts=checks[-OKS_TO_UP].ts)
            self._devices[dev.name] = None

    def _step_tunnel(self, t: Tunnel, under: WindowStats | None, over: WindowStats | None,
                     internet_ok: bool, now: float) -> tuple[TunnelVerdict, Transition]:
        st = self._tunnels.setdefault(t.name, _TunnelState(self._open_after, self._close_after))
        for role, s in (("tunnel_under", under), ("tunnel_over", over)):
            if s is not None:
                self.store.add_window(f"{role}:{t.name}", s, ts=now)
        if under is not None and under.received:
            st.ever_answered = True
        tv = classify_tunnel(t, under, over, internet_ok, st.ever_answered)
        code = "ok" if tv.code in ("up", "no_data") else tv.code
        tr = st.hyst.update(code)
        opened = now - self.window * tr.since
        if tr.closed and st.incident_id is not None:
            self.store.close_incident(st.incident_id, ts=opened if tr.opened else now - self.window * tr.clean)
            st.incident_id = None
        if tr.opened:
            st.incident_id = self.store.open_incident(tr.opened, tv.evidence, ts=opened, scope=f"tunnel:{t.name}")
            if self.capture is not None:  # evidence of the path to the far end, outside the tunnel
                self.capture(t.underlay, st.incident_id)
        if st.incident_id is not None and over is not None:
            self.store.bump_peak_loss(st.incident_id, over.loss)
        return tv, tr

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
