"""Run mtr and read it the way a NOC engineer would.

The key rule: packet loss on an intermediate hop only counts if it persists
all the way to the destination. Routers routinely rate-limit or deprioritize
ICMP replies to themselves, which shows up as "loss" on that hop while traffic
through it is perfectly fine. Reading that as an ISP problem is the most common
mistake people make with mtr/traceroute.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from ..netutil import ip_kind

# Loss (in %) at or above which we treat a path as degraded.
LOSS_THRESHOLD = 2.0


@dataclass
class Hop:
    index: int
    host: str
    loss: float
    sent: int
    avg: float
    best: float
    worst: float
    stdev: float

    @property
    def responds(self) -> bool:
        return self.host != "???" and self.loss < 100.0

    @property
    def kind(self) -> str:
        return ip_kind(self.host)


@dataclass
class HopAnalysis:
    hop: Hop
    persistent_loss: float  # loss that this hop "explains": min loss from here to destination
    status: str  # ok | real_loss | icmp_deprioritized | no_reply
    asn: str | None = None
    as_name: str | None = None


@dataclass
class PathAnalysis:
    target: str
    hops: list[HopAnalysis] = field(default_factory=list)
    destination_loss: float = 0.0
    loss_starts_at: int | None = None  # hop index where real loss begins
    reached: bool = True

    @property
    def degraded(self) -> bool:
        return self.destination_loss >= LOSS_THRESHOLD or not self.reached


class MtrError(RuntimeError):
    pass


def mtr_available() -> bool:
    return shutil.which("mtr") is not None


def run_mtr(target: str, cycles: int = 10, timeout: float | None = None) -> list[Hop]:
    """Run `mtr --json` against target and return the parsed hops."""
    if not mtr_available():
        raise MtrError("mtr is not installed (apt install mtr-tiny)")
    cmd = ["mtr", "-n", "-r", "-c", str(cycles), "--json", target]
    timeout = timeout or cycles * 2 + 30
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False,
                             env={**os.environ, "LC_ALL": "C", "LANG": "C"})
    except subprocess.TimeoutExpired as exc:
        raise MtrError(f"mtr timed out after {timeout}s") from exc
    if out.returncode != 0:
        raise MtrError(out.stderr.strip() or f"mtr exited with {out.returncode}")
    return parse_mtr_json(out.stdout)


def parse_mtr_json(raw: str | dict) -> list[Hop]:
    data = json.loads(raw) if isinstance(raw, str) else raw
    hops = []
    for hub in data["report"]["hubs"]:
        hops.append(
            Hop(
                index=int(hub["count"]),
                host=str(hub["host"]),
                loss=float(hub["Loss%"]),
                sent=int(hub.get("Snt", 0)),
                avg=float(hub.get("Avg", 0.0)),
                best=float(hub.get("Best", 0.0)),
                worst=float(hub.get("Wrst", 0.0)),
                stdev=float(hub.get("StDev", 0.0)),
            )
        )
    return hops


def analyze_path(target: str, hops: list[Hop], threshold: float = LOSS_THRESHOLD) -> PathAnalysis:
    """Classify each hop and find where real loss (if any) starts."""
    result = PathAnalysis(target=target)
    if not hops:
        result.reached = False
        return result

    last = hops[-1]
    result.reached = last.responds
    result.destination_loss = last.loss if last.responds else 100.0

    # persistent loss of hop i = min loss among responding hops from i to the end.
    # If a later hop has less loss, the extra loss on hop i is just ICMP handling on that router.
    persistent = [0.0] * len(hops)
    running = None
    for i in range(len(hops) - 1, -1, -1):
        h = hops[i]
        if h.responds:
            running = h.loss if running is None else min(running, h.loss)
        persistent[i] = running if running is not None else 100.0

    for i, h in enumerate(hops):
        if not h.responds:
            status = "no_reply"
        elif persistent[i] >= threshold:
            status = "real_loss"
        elif h.loss >= threshold:
            status = "icmp_deprioritized"
        else:
            status = "ok"
        result.hops.append(HopAnalysis(hop=h, persistent_loss=persistent[i], status=status))

    if result.destination_loss >= threshold:
        for ha in result.hops:
            if ha.status == "real_loss":
                result.loss_starts_at = ha.hop.index
                break
    return result


def path_to_dict(p: PathAnalysis, asn_info: dict[str, tuple[str, str]] | None = None) -> dict:
    """JSON-friendly form of an analyzed path, stored as incident evidence."""
    asn_info = asn_info or {}
    return {
        "target": p.target,
        "reached": p.reached,
        "destination_loss": p.destination_loss,
        "loss_starts_at": p.loss_starts_at,
        "hops": [
            {
                "index": ha.hop.index, "host": ha.hop.host, "loss": ha.hop.loss, "sent": ha.hop.sent,
                "avg": ha.hop.avg, "best": ha.hop.best, "worst": ha.hop.worst, "status": ha.status,
                "asn": (asn_info.get(ha.hop.host) or (None, None))[0],
                "as_name": (asn_info.get(ha.hop.host) or (None, None))[1],
            }
            for ha in p.hops
        ],
    }
