"""Route changes: record the path to each destination and say when the ISP changes it (#97).

"It's the ISP" is half the answer; the other half is what the ISP did. The thing they most often do
without telling anyone is move your traffic to another path: slower, or one that no longer reaches a
network you need (a site-to-site VPN drops because there is no route between the two networks).

How a path is read
  * Every ROUND seconds, and right away when an incident opens, each destination is traced with mtr
    (ICMP, a few cycles): the internet destinations, each tunnel's far end, each service's host.
    ICMP echo keeps the same flow on the routers that balance load, and answers on more hops than
    UDP or TCP probes do.
  * A path is the hops that answered, per TTL, by /24 (routers in parallel on one link usually share
    it). Your own network (the home segment) is left out: it is not the ISP's route.
  * A destination has a few known paths. Load balancing adds members at the same TTL of the same
    path, and a hop that answers in one trace and not in the next proves nothing either way.

Comparing a trace with a known path (`compare`)
  same      every TTL where both answered has a /24 already seen there, and it gets as far
  cut       nothing conflicts, but it stops well before where that path used to stop (an outage)
  diverged  a hop where another router used to be, or the destination at another distance

A different path counts once it is seen in CONFIRM traces in a row. That makes an event: `changed`, or
`restored` when it is back on the usual path (the one it has been on the longest in the last days).
Then, IMPACT_AFTER seconds later, the latency and loss before and after are compared: a change that made
things clearly worse opens an incident of its own (scope `route:<group>`), so it gets alerted.
When any other incident opens, the paths it depends on are traced at once and compared with the last
good one: that is the diagnosis the alert, the dashboard and the report show (`diagnosis_lines`).
"""

from __future__ import annotations

import ipaddress
import math
import re
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import asn
from .probes.mtr import Hop, MtrError, run_mtr

ROUND = 600.0          # seconds between traces of every destination
CYCLES = 3             # mtr cycles per trace: enough to see the hops, cheap enough to run often
CONFIRM = 2            # traces in a row on a different path before it counts
MAX_KNOWN = 6          # known paths kept per destination
HALF_LIFE = 3.5 * 86400  # time on a path fades with this half-life: "usual" means lately
UNSTABLE = (3, 7200)   # this many changes within this many seconds: the path keeps coming and going
IMPACT_AFTER = 900.0   # how long after a change its impact is judged
RECENT = 1800.0        # a change this long before an incident is part of its diagnosis
MAX_TARGETS = 12
CUT_MARGIN = 2         # hops short of where a path used to stop before a trace counts as cut


# ------------------------------------------------------------------ what is traced

@dataclass(frozen=True)
class Target:
    key: str            # "anchor:1.1.1.1", "tunnel:<name>", "service:<name>"
    host: str
    group: str          # the incident scope it explains: "internet", "tunnel:<name>", "service:<name>"
    label: str          # what the user calls it
    role: str           # samples role with its latency ("anchor", "tunnel_under:<name>", "service:<name>")
    sample_target: str  # samples target of that role


def targets(anchors: list[str], tunnels: list = (), services: list = ()) -> list[Target]:
    out = [Target(f"anchor:{a}", a, "internet", a, "anchor", a) for a in anchors]
    out += [Target(f"tunnel:{t.name}", t.underlay, f"tunnel:{t.name}", t.name, f"tunnel_under:{t.name}", t.underlay)
            for t in tunnels]
    for s in services:
        host = urlparse(s.target).hostname if s.kind == "http" else s.target.rpartition(":")[0].strip("[]")
        if host:
            out.append(Target(f"service:{s.name}", host, f"service:{s.name}", s.name, f"service:{s.name}", s.target))
    return out[:MAX_TARGETS]


# ------------------------------------------------------------------ one trace

@dataclass
class Obs:
    ts: float
    hops: list[dict]          # {"ttl", "host", "asn", "org", "seg", "best"} for hops that answered
    reached: bool             # the destination itself answered
    last: int = 0             # TTL of the last hop that answered

    def prefixes(self) -> dict[int, str]:
        return {h["ttl"]: prefix(h["host"]) for h in self.hops if h["seg"] != "home"}

    def to_dict(self) -> dict:
        return {"ts": self.ts, "reached": self.reached, "last": self.last,
                "hops": [[h["ttl"], h["host"], h.get("org"), h["seg"], h.get("best")] for h in self.hops]}

    @classmethod
    def from_dict(cls, d: dict) -> Obs:
        hops = [{"ttl": r[0], "host": r[1], "org": r[2], "seg": r[3], "best": r[4], "asn": None}
                for r in d.get("hops", [])]
        return cls(d.get("ts", 0.0), hops, bool(d.get("reached")), int(d.get("last") or 0))


def prefix(host: str) -> str:
    """The /24 (IPv4) or /48 (IPv6) a router sits in: parallel routers on one link usually share it."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    return str(ipaddress.ip_network(f"{ip}/{24 if ip.version == 4 else 48}", strict=False))


_SUFFIX = re.compile(r"[\s,]+(S\.?\s?A\.?(\s?U\.?)?|S\.?R\.?L\.?|Inc\.?|LLC|L\.?L\.?C\.?|Ltd\.?|Limited|Ltda\.?|"
                     r"Corp\.?|Corporation|Co\.?|GmbH|B\.?V\.?|AG|Company|Communications|Holdings?|"
                     r"Argentina|de C\.?V\.?)$", re.IGNORECASE)


def org_name(as_name: str | None, as_number: str | None) -> str | None:
    """'Telecom Argentina S.A.' -> 'Telecom'; 'Google LLC' -> 'Google'. Without a name, 'AS7303'."""
    if as_name:
        name = as_name.strip()
        for _ in range(3):
            shorter = _SUFFIX.sub("", name).strip(" ,.-")
            if not shorter or shorter == name:
                break
            name = shorter
        return name[:40].rstrip(" ,.-")
    return f"AS{as_number}" if as_number else None


def observe(hops: list[Hop], asn_info: dict[str, tuple[str, str]], ts: float | None = None) -> Obs:
    """An mtr trace, segmented (home / isp / beyond) and labeled with who runs each hop."""
    from .discovery import segment_path
    path = segment_path(hops, asn_info)
    isp_org = next((org_name(p.as_name, p.asn) for p in path if p.segment == "isp" and p.asn), None)
    out: list[dict] = []
    for p in path:
        if not p.hop.responds:
            continue
        org = org_name(p.as_name, p.asn) or (isp_org if p.segment == "isp" else None)
        out.append({"ttl": p.hop.index, "host": p.hop.host, "asn": p.asn, "org": org, "seg": p.segment,
                    "best": round(p.hop.best, 1)})
    reached = bool(hops) and hops[-1].responds
    return Obs(ts or time.time(), out, reached, out[-1]["ttl"] if out else 0)


def orgs(o: Obs) -> list[str]:
    """Who the path goes through, in order: ['Telecom', 'Arsat', 'Cloudflare']."""
    seen: list[str] = []
    for h in o.hops:
        if h["seg"] != "home" and h.get("org") and (not seen or seen[-1] != h["org"]):
            seen.append(h["org"])
    return seen


# ------------------------------------------------------------------ known paths

@dataclass
class Known:
    id: int
    ttls: dict[int, list[str]] = field(default_factory=dict)  # TTL -> /24s seen there
    reached: bool = False
    length: int | None = None    # TTL of the destination, when it answers
    lasts: list[int] = field(default_factory=list)  # last TTL that answered, recent traces
    weight: float = 0.0          # seconds on this path, fading with HALF_LIFE
    stamp: float = 0.0           # when `weight` was last brought up to date
    sample: dict = field(default_factory=dict)  # the latest trace on it (Obs.to_dict)

    @property
    def reach_end(self) -> int:
        """Where this path usually stops: low end of the recent traces (an end hop can be quiet)."""
        if not self.lasts:
            return 0
        s = sorted(self.lasts)
        return s[len(s) // 4]

    def learn(self, o: Obs) -> None:
        for ttl, pfx in o.prefixes().items():
            seen = self.ttls.setdefault(ttl, [])
            if pfx not in seen:
                seen.append(pfx)
                del seen[:-8]
        if o.reached:
            self.reached, self.length = True, o.last
        self.lasts = (self.lasts + [o.last])[-10:]
        self.sample = o.to_dict()

    def to_dict(self) -> dict:
        return {"id": self.id, "ttls": {str(k): v for k, v in self.ttls.items()}, "reached": self.reached,
                "length": self.length, "lasts": self.lasts, "weight": self.weight, "stamp": self.stamp,
                "sample": self.sample}

    @classmethod
    def from_dict(cls, d: dict) -> Known:
        return cls(int(d["id"]), {int(k): list(v) for k, v in d.get("ttls", {}).items()}, bool(d.get("reached")),
                   d.get("length"), list(d.get("lasts", [])), float(d.get("weight", 0.0)),
                   float(d.get("stamp", 0.0)), d.get("sample") or {})


def compare(k: Known, o: Obs) -> str:
    """same | cut | diverged (see the module docstring)."""
    if not k.ttls:
        return "same"
    top = max(k.ttls)
    for ttl, pfx in o.prefixes().items():
        if ttl in k.ttls and pfx not in k.ttls[ttl]:
            return "diverged"
        if ttl > top + 1 and not k.reached:
            return "diverged"            # it goes on past where this path ever answered
    if o.reached and k.reached and k.length is not None and o.last != k.length:
        return "diverged"                # the destination is now at another distance
    if k.reached and not o.reached and o.last < k.reach_end - CUT_MARGIN:
        return "cut"
    if not k.reached and o.last < k.reach_end - CUT_MARGIN:
        return "cut"
    return "same"


def known_from(o: Obs, kid: int) -> Known:
    k = Known(kid, stamp=o.ts)
    k.learn(o)
    return k


# ------------------------------------------------------------------ per destination

class Tracker:
    """The known paths of one destination, which one it's on, and a candidate waiting confirmation."""

    def __init__(self, state: dict | None = None):
        state = state or {}
        self.known = [Known.from_dict(k) for k in state.get("known", [])]
        self.current: int | None = state.get("current")
        self.pending: dict | None = state.get("pending")    # {"id": int | None, "obs": dict, "count": int}
        self.changes: list[float] = list(state.get("changes", []))
        self.next_id = max([k.id for k in self.known], default=0) + 1

    def to_dict(self) -> dict:
        return {"known": [k.to_dict() for k in self.known], "current": self.current, "pending": self.pending,
                "changes": self.changes}

    def get(self, kid: int | None) -> Known | None:
        return next((k for k in self.known if k.id == kid), None)

    @property
    def usual(self) -> Known | None:
        return max(self.known, key=lambda k: k.weight, default=None)

    def _age(self, now: float) -> None:
        cur = self.get(self.current)
        for k in self.known:
            dt = max(0.0, now - k.stamp)
            k.weight *= math.exp(-dt * math.log(2) / HALF_LIFE)
            if k is cur:
                k.weight += min(dt, 2 * ROUND)   # time on it (a long gap, e.g. the monitor was off, counts little)
            k.stamp = now

    def observe(self, o: Obs) -> dict | None:
        """Feed one trace. Returns an event ({"kind", "from", "to", "unstable"}) when the path changed."""
        if not o.prefixes():
            return None                          # nothing past your own network answered: says nothing
        self._age(o.ts)
        cur = self.get(self.current)
        if cur is None:
            k = known_from(o, self.next_id)
            self.next_id += 1
            self.known.append(k)
            self.current, self.pending = k.id, None
            return None
        verdict = compare(cur, o)
        if verdict == "same":
            cur.learn(o)
            self.pending = None
            return None
        if verdict == "cut":
            return None                          # an outage on the usual path, not another path
        other = next((k for k in self.known if k.id != cur.id and compare(k, o) == "same"), None)
        cand = other.id if other else None
        p = self.pending
        if p and p["id"] == cand and (cand is not None or compare(known_from(Obs.from_dict(p["obs"]), 0), o) == "same"):
            p["count"] += 1
            p["more"] = (p.get("more") or []) + [o.to_dict()]
        else:
            p = self.pending = {"id": cand, "obs": o.to_dict(), "count": 1, "more": []}
        if p["count"] < CONFIRM:
            return None
        first = Obs.from_dict(p["obs"])
        if other is None:
            other = known_from(first, self.next_id)
            self.next_id += 1
            self.known.append(other)
        else:
            other.learn(first)
        for extra in p["more"]:
            other.learn(Obs.from_dict(extra))
        before = cur.sample
        self.current, self.pending = other.id, None
        self.changes = [t for t in self.changes if o.ts - t < UNSTABLE[1]] + [first.ts]
        if len(self.known) > MAX_KNOWN:
            drop = min((k for k in self.known if k.id != self.current), key=lambda k: k.weight)
            self.known.remove(drop)
        usual = self.usual
        kind = "restored" if usual is not None and usual.id == other.id and other.weight > 0 else "changed"
        return {"kind": kind, "ts": first.ts, "from": before, "to": other.sample,
                "unstable": len(self.changes) >= UNSTABLE[0]}


# ------------------------------------------------------------------ impact

def impact(store, t: Target, at: float, now: float) -> dict | None:
    """Median latency and loss of the destination in the hour before a change and since then."""
    def stats(rows) -> tuple[float | None, float | None, int]:
        rows = [r for r in rows if r["target"] == t.sample_target]
        rtts = [r["rtt_median"] for r in rows if r["rtt_median"] is not None]
        sent = sum(r["sent"] for r in rows)
        loss = 100.0 * (sent - sum(r["received"] for r in rows)) / sent if sent else None
        return (statistics.median(rtts) if rtts else None), loss, len(rtts)

    b_ms, b_loss, nb = stats(store.samples_between(at - 3600, at - 60, role=t.role))
    a_ms, a_loss, na = stats(store.samples_between(at + 60, now, role=t.role))
    if nb < 5 or na < 5 or b_ms is None or a_ms is None:
        return None
    return {"before_ms": round(b_ms, 1), "after_ms": round(a_ms, 1),
            "before_loss": round(b_loss or 0.0, 1), "after_loss": round(a_loss or 0.0, 1)}


def severity(imp: dict | None) -> str:
    """none | worse | much_worse. Worse: +15 ms and +25 %, or 1 point more loss."""
    if not imp:
        return "none"
    b, a = imp["before_ms"], imp["after_ms"]
    dloss = imp["after_loss"] - imp["before_loss"]
    if (a - b >= 30 and a >= 2 * b) or dloss >= 2.0:
        return "much_worse"
    if (a - b >= 15 and a >= 1.25 * b) or dloss >= 1.0:
        return "worse"
    return "none"


def recovered(imp: dict | None) -> bool:
    return imp is not None and severity(imp) == "none"


# ------------------------------------------------------------------ the background job

Tracer = Callable[[str], list[Hop]]


class Watcher:
    """Traces every destination each ROUND, and right away when an incident opens."""

    def __init__(self, store, targets_fn: Callable[[], list[Target]], data_dir: Path | None = None,
                 asn_online: bool = False, every: float = ROUND, tracer: Tracer | None = None):
        self.store = store
        self.targets_fn = targets_fn
        self.data_dir, self.asn_online = data_dir, asn_online
        self.every = every
        self.tracer = tracer or (lambda host: run_mtr(host, cycles=CYCLES))
        self.trackers = {k: Tracker(v) for k, v in (store.get_setting("_routes") or {}).items()}
        self._urgent: list[tuple[str, int]] = []      # (group, incident id)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_round = 0.0

    # -- control
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="routes")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def incident_opened(self, group: str, incident_id: int) -> None:
        """Called by the monitor: trace what this incident depends on, now."""
        with self._lock:
            self._urgent.append((group, incident_id))
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - a bad trace must never stop route tracking
                print(f"routes: {exc}")
            self._wake.wait(timeout=30)
            self._wake.clear()

    # -- work (synchronous: the tests call these directly)
    def tick(self, now: float | None = None) -> None:
        with self._lock:
            urgent, self._urgent = self._urgent, []
        for group, iid in urgent:
            self.diagnose(group, iid)
        now = now or time.time()
        if now - self._last_round >= self.every:
            self._last_round = now
            self.round(now)

    def _trace(self, t: Target, now: float | None = None) -> Obs | None:
        try:
            hops = self.tracer(t.host)
        except MtrError:
            return None
        info = asn.lookup([h.host for h in hops], data_dir=self.data_dir, online=self.asn_online)
        return observe(hops, info, ts=now or time.time())

    def _feed(self, t: Target, o: Obs, incident_id: int | None = None) -> dict | None:
        tr = self.trackers.setdefault(t.key, Tracker())
        ev = tr.observe(o)
        if ev is not None:
            ev.update({"label": t.label, "host": t.host, "impact": None})
            ev["id"] = self.store.add_route_event(ev["ts"], t.key, t.group, ev["kind"], ev, incident_id=incident_id)
        return ev

    def _save(self) -> None:
        keep = {t.key for t in self.targets_fn()}
        self.store.set_settings({"_routes": {k: tr.to_dict() for k, tr in self.trackers.items() if k in keep}},
                                bump=False)

    def round(self, now: float | None = None) -> None:
        now = now or time.time()
        for t in self.targets_fn():
            o = self._trace(t, now)
            if o is not None:
                self._feed(t, o)
        self.judge(now)
        self._save()

    def diagnose(self, group: str, incident_id: int, now: float | None = None) -> dict | None:
        """Trace what an incident depends on, twice, and compare with the path before it opened."""
        now = now or time.time()
        ts = [t for t in self.targets_fn() if t.group == group]
        if not ts:
            return None
        rows = []
        for t in ts:
            tr = self.trackers.setdefault(t.key, Tracker())
            before = tr.get(tr.current)
            before_sample = dict(before.sample) if before else None
            obs = [o for o in (self._trace(t, now), self._trace(t, now + 1)) if o is not None]
            if not obs:
                continue
            last = obs[-1]
            verdict = compare(before, last) if before is not None else "unknown"
            for o in obs:
                self._feed(t, o, incident_id=incident_id)
            rows.append({"target": t.key, "label": t.label, "host": t.host, "verdict": verdict,
                         "before": before_sample, "now": last.to_dict()})
        opened = next((i.opened for i in self.store.active_incidents() if i.id == incident_id), now)
        recent = [e for e in self.store.route_events_between(opened - RECENT, opened, group=group)
                  if e["kind"] in ("changed", "restored") and e["incident_id"] is None]
        data = {"incident_id": incident_id, "group": group, "rows": rows,
                "recent": [e["id"] for e in recent]}
        if rows or recent:
            self.store.add_route_event(now, f"group:{group}", group, "diagnosis", data, incident_id=incident_id)
        self._save()
        return data

    def judge(self, now: float | None = None) -> None:
        """Impact of recent changes; an incident for a change that made things clearly worse."""
        now = now or time.time()
        by_key = {t.key: t for t in self.targets_fn()}
        open_ = {i.scope: i for i in self.store.active_incidents()}
        for e in self.store.route_events_between(now - 4 * IMPACT_AFTER, now - IMPACT_AFTER):
            if e["kind"] not in ("changed", "restored") or e["data"].get("impact") is not None:
                continue
            t = by_key.get(e["target"])
            if t is None:
                continue
            imp = impact(self.store, t, e["ts"], now)
            if imp is None:
                continue
            e["data"]["impact"] = imp
            e["data"]["severity"] = severity(imp)
            self.store.update_route_event(e["id"], e["data"])
            scope = f"route:{t.group}"
            if e["data"]["severity"] != "none" and t.group not in open_ and scope not in open_:
                iid = self.store.open_incident("route_slower", evidence_lines(e["data"]), ts=e["ts"], scope=scope)
                self.store.set_incident_details(iid, {"route_event": e["id"], "target": t.key})
                open_[scope] = next(i for i in self.store.active_incidents() if i.id == iid)
        for scope, inc in open_.items():
            if not scope.startswith("route:"):
                continue
            ev = self.store.route_event((inc.details or {}).get("route_event")) if inc.details else None
            t = by_key.get((inc.details or {}).get("target", ""))
            if t is None or ev is None:
                self.store.close_incident(inc.id, ts=now)
                continue
            imp = impact(self.store, t, ev["ts"], now)
            later = [e for e in self.store.route_events_between(ev["ts"] + 1, now)
                     if e["target"] == t.key and e["kind"] in ("changed", "restored")]
            recent_imp = None
            if imp is not None:
                recent = impact(self.store, t, now - IMPACT_AFTER, now)    # the last minutes alone
                recent_imp = {**imp, "after_ms": recent["after_ms"] if recent else imp["after_ms"],
                              "after_loss": recent["after_loss"] if recent else imp["after_loss"]}
            if any(e["kind"] == "restored" for e in later) or (recent_imp is not None and recovered(recent_imp)):
                self.store.close_incident(inc.id, ts=later[-1]["ts"] if later else now)
        self.store.commit()


# ------------------------------------------------------------------ words

T = {
    "en": {
        "arrow": " → ", "unknown_path": "unknown", "stop": "{org} ({host})", "stop_host": "{host}",
        "changed": "The path to {label} changed: before {before}; now {now}.",
        "changed_cut": "The path to {label} changed and no longer gets there: before {before}; now {now}, "
                       "it stops after {stop}.",
        "cut_isp": "The path to {label} is the usual one, and it stops after {stop}, inside your ISP's network.",
        "cut_beyond": "The path to {label} is the usual one, and it stops after {stop}, past your ISP: "
                      "the problem is on the far side.",
        "cut_home": "The path to {label} stops in your own network.",
        "same_reached": "The path to {label} is the usual one and it gets there.",
        "same": "The path to {label} is the usual one.",
        "recent": "Your ISP changed the path to {label} at {hhmm}, {mins} min before.",
        "slower": "{label}: {before_ms:.0f} ms → {after_ms:.0f} ms after the path changed at {hhmm}",
        "slower_loss": "{label}: loss {before_loss:.1f} % → {after_loss:.1f} % after the path changed at {hhmm}",
        "kind_changed": "Your ISP changed the path", "kind_restored": "Back on the usual path",
        "kind_unstable": "The path keeps changing",
    },
    "es": {
        "arrow": " → ", "unknown_path": "desconocido", "stop": "{org} ({host})", "stop_host": "{host}",
        "changed": "El camino hacia {label} cambió: antes {before}; ahora {now}.",
        "changed_cut": "El camino hacia {label} cambió y ya no llega: antes {before}; ahora {now}, "
                       "se corta después de {stop}.",
        "cut_isp": "El camino hacia {label} es el de siempre y se corta después de {stop}, dentro de la red de "
                   "tu proveedor.",
        "cut_beyond": "El camino hacia {label} es el de siempre y se corta después de {stop}, pasando tu "
                      "proveedor: el problema está del otro lado.",
        "cut_home": "El camino hacia {label} se corta en tu propia red.",
        "same_reached": "El camino hacia {label} es el de siempre y llega.",
        "same": "El camino hacia {label} es el de siempre.",
        "recent": "Tu proveedor cambió el camino hacia {label} a las {hhmm}, {mins} min antes.",
        "slower": "{label}: {before_ms:.0f} ms → {after_ms:.0f} ms después de que cambió el camino a las {hhmm}",
        "slower_loss": "{label}: pérdida {before_loss:.1f} % → {after_loss:.1f} % después de que cambió el camino "
                       "a las {hhmm}",
        "kind_changed": "Tu proveedor cambió el camino", "kind_restored": "Volvió el camino de siempre",
        "kind_unstable": "El camino cambia una y otra vez",
    },
}


def path_text(sample: dict | None, lang: str = "en") -> str:
    """'Telecom → Arsat → Cloudflare' from a stored trace."""
    if not sample:
        return T[lang]["unknown_path"]
    names = orgs(Obs.from_dict(sample))
    return T[lang]["arrow"].join(names) if names else T[lang]["unknown_path"]


def stop_text(sample: dict, lang: str = "en") -> tuple[str, str]:
    """(where the trace stops, its segment)."""
    o = Obs.from_dict(sample)
    if not o.hops:
        return "", "home"
    h = o.hops[-1]
    t = T[lang]
    return (t["stop"].format(org=h["org"], host=h["host"]) if h.get("org") else t["stop_host"].format(host=h["host"]),
            h["seg"])


def change_line(ev: dict, lang: str = "en") -> str:
    t = T[lang]
    before, now = path_text(ev.get("from"), lang), path_text(ev.get("to"), lang)
    to = ev.get("to") or {}
    if before == now:   # same organizations, other routers inside them
        before, now = _routers(ev.get("from")), _routers(to)
    if not to.get("reached") and (ev.get("from") or {}).get("reached"):
        stop, _ = stop_text(to, lang)
        return t["changed_cut"].format(label=ev.get("label", ""), before=before, now=now, stop=stop)
    return t["changed"].format(label=ev.get("label", ""), before=before, now=now)


def _routers(sample: dict | None) -> str:
    """Where two paths through the same networks part: the routers, '181.96.60.162 → 181.89.51.39'."""
    if not sample:
        return "?"
    hops = [h for h in Obs.from_dict(sample).hops if h["seg"] != "home"]
    return " → ".join(h["host"] for h in hops[:6]) or "?"


def row_line(row: dict, lang: str = "en") -> str:
    """One line of an incident's diagnosis, for one destination."""
    t = T[lang]
    label = row.get("label", "")
    if row["verdict"] == "diverged":
        return change_line({"label": label, "from": row.get("before"), "to": row.get("now")}, lang)
    if row["verdict"] == "cut":
        stop, seg = stop_text(row["now"], lang)
        return t[{"home": "cut_home", "isp": "cut_isp"}.get(seg, "cut_beyond")].format(label=label, stop=stop)
    if row["verdict"] == "same":
        if (row.get("now") or {}).get("reached"):
            return t["same_reached"].format(label=label)
        stop, seg = stop_text(row["now"], lang)
        if stop and seg != "home":
            return t["cut_beyond" if seg == "beyond" else "cut_isp"].format(label=label, stop=stop)
        return t["same"].format(label=label)
    return ""


def evidence_lines(ev: dict, lang: str = "en") -> list[str]:
    """Evidence of a route_slower incident: the latency (or loss) before and after, and both paths."""
    t, imp = T[lang], ev.get("impact") or {}
    hhmm = time.strftime("%H:%M", time.localtime(ev.get("ts", 0)))
    lines = []
    if imp:
        if imp["after_loss"] - imp["before_loss"] >= 1.0:
            lines.append(t["slower_loss"].format(label=ev.get("label", ""), hhmm=hhmm, **imp))
        else:
            lines.append(t["slower"].format(label=ev.get("label", ""), hhmm=hhmm, **imp))
    lines.append(change_line(ev, lang))
    return lines


def diagnosis_lines(store, incident, lang: str = "en", limit: int = 3) -> list[str]:
    """What the paths say about an incident: changed before it, changed now, or usual and cut where."""
    lang = lang if lang in T else "en"
    t = T[lang]
    if incident.scope.startswith("route:"):
        return []                                 # its evidence already is the diagnosis
    diag = [e for e in store.route_events_for([incident.id]).get(incident.id, []) if e["kind"] == "diagnosis"]
    lines: list[str] = []
    if diag:
        d = diag[-1]["data"]
        for eid in d.get("recent", []):
            e = store.route_event(eid)
            if e is not None:
                mins = max(0, round((incident.opened - e["ts"]) / 60))
                hhmm = time.strftime("%H:%M", time.localtime(e["ts"]))
                lines.append(t["recent"].format(label=e["data"].get("label", ""), hhmm=hhmm, mins=mins))
        rows = d.get("rows", [])
        # several internet destinations saying the same: one line for the worst (diverged > cut > same)
        order = {"diverged": 0, "cut": 1, "same": 2, "unknown": 3}
        for row in sorted(rows, key=lambda r: order.get(r["verdict"], 9)):
            line = row_line(row, lang)
            if line and line not in lines:
                lines.append(line)
            if incident.scope == "internet" and len(lines) >= 2:
                break
    return lines[:limit]
