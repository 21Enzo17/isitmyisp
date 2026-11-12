"""Statistics that keep the verdict honest.

Losing 1 packet out of 50 is "2% loss" but proves nothing. We only call loss
significant when we are confident it is above a floor (Wilson score interval),
we judge latency against each target's own baseline instead of a fixed number,
and we require consecutive bad windows before opening an incident (hysteresis).
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass

Z95 = 1.96
LOSS_FLOOR = 1.5  # % loss we must be 95% confident to exceed (1/50 and 2/50 lost are NOT significant)
MIN_SAMPLES = 10  # below this, we don't judge loss at all (except total outage)
MIN_FAILURES = 2  # one failure is never evidence (1/10 TCP connects has a Wilson low bound of 1.8%)


def wilson_interval(failures: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for a proportion, in percent."""
    if n <= 0:
        return 0.0, 100.0
    p = failures / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, 100 * (center - half)), min(100.0, 100 * (center + half))


def loss_is_significant(lost: int, sent: int, floor: float = LOSS_FLOOR) -> bool:
    """True if we're 95% confident the loss rate is above `floor` percent."""
    if sent <= 0:
        return False
    if lost == sent and sent >= 3:  # total outage: no statistics needed
        return True
    if sent < MIN_SAMPLES or lost < MIN_FAILURES:
        return False
    low, _ = wilson_interval(lost, sent)
    return low > floor


class Baseline:
    """Rolling median of a target's typical RTT, learned from healthy windows only."""

    def __init__(self, size: int = 60):
        self.values: deque[float] = deque(maxlen=size)

    def update(self, rtt_median: float | None, healthy: bool) -> None:
        if rtt_median is not None and healthy:
            self.values.append(rtt_median)

    @property
    def ready(self) -> bool:
        return len(self.values) >= 5

    @property
    def value(self) -> float | None:
        return statistics.median(self.values) if self.values else None

    def is_spike(self, rtt_median: float | None, factor: float = 2.0, min_extra_ms: float = 30.0) -> bool:
        """Latency is abnormal if it's both 2x the baseline and at least 30 ms above it."""
        if rtt_median is None or not self.ready:
            return False
        base = self.value or 0.0
        return rtt_median > base * factor and rtt_median - base > min_extra_ms


@dataclass
class Transition:
    opened: str | None = None  # code of an incident that just opened
    closed: str | None = None  # code of an incident that just closed
    since: int = 0             # the opened incident started this many windows ago (this one included)
    clean: int = 0             # the closed incident ended this many windows ago (the good ones after it)
    intermittent: bool = False # opened because the problem comes and goes, not because it's steady


# Verdicts that are the same problem as far as an incident goes: whether the ISP's first hop also
# looks bad can change from one window to the next while the outage is one and the same.
SAME_PROBLEM = {"access": "isp"}


class Hysteresis:
    """When a run of windows becomes an incident, and when it's over.

    Opens on `open_after` consecutive bad windows of the same problem (a steady outage), or on
    `intermittent_after` bad windows within the last `lookback` (a link that drops and comes back:
    bad, ok, bad, ok… never makes two in a row, and is exactly what an ISP has to hear about).
    Closes after `close_after` good windows in a row; an intermittent incident needs
    `intermittent_close` of them, or every quiet minute would close it and the next drop reopen it.
    """

    def __init__(self, open_after: int = 2, close_after: int = 2, lookback: int = 10,
                 intermittent_after: int = 3, intermittent_close: int = 6, same: dict | None = None):
        self.open_after, self.close_after = open_after, close_after
        self.intermittent_after, self.intermittent_close = intermittent_after, intermittent_close
        self.same = SAME_PROBLEM if same is None else same
        self.history: deque[str] = deque(maxlen=lookback)
        self.active: str | None = None
        self.intermittent = False
        self._good = 0

    def group(self, code: str) -> str:
        return self.same.get(code, code)

    def _steady(self) -> str | None:
        """The problem of the last `open_after` windows, when they're all bad and all the same one."""
        tail = list(self.history)[-self.open_after:]
        if len(tail) < self.open_after or "ok" in tail or len({self.group(c) for c in tail}) != 1:
            return None
        return tail[-1]

    def update(self, code: str) -> Transition:
        t = Transition()
        self.history.append(code)
        if code == "ok":
            if self.active:
                self._good += 1
                if self._good >= (self.intermittent_close if self.intermittent else self.close_after):
                    t.closed, t.clean = self.active, self._good
                    self._reset()
            return t
        self._good = 0
        if self.active:
            if self.group(code) == self.group(self.active):
                return t                                      # the same outage goes on
            steady = self._steady()
            if steady is None:
                return t                                      # one odd window inside an incident
            t.closed, t.clean = self.active, 0                # the cause changed: one ends, the next starts
            self._open(t, steady, self.open_after, False)
            return t
        steady = self._steady()
        if steady is not None:
            self._open(t, steady, self.open_after, False)
            return t
        bad = [(i, c) for i, c in enumerate(self.history) if c != "ok"]
        if len(bad) >= self.intermittent_after:
            groups = [self.group(c) for _, c in bad]
            top = max(set(groups), key=lambda g: (groups.count(g), max(i for i, (_, c) in enumerate(bad) if self.group(c) == g)))
            latest = next(c for _, c in reversed(bad) if self.group(c) == top)
            self._open(t, latest, len(self.history) - bad[0][0], True)
        return t

    def _open(self, t: Transition, code: str, since: int, intermittent: bool) -> None:
        t.opened, t.since, t.intermittent = code, since, intermittent
        self.active, self.intermittent, self._good = code, intermittent, 0

    def _reset(self) -> None:
        # what's left in the lookback belonged to the incident that just closed: it can't count again
        self.active, self.intermittent, self._good = None, False, 0
        self.history.clear()
