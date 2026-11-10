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


class Hysteresis:
    """Open an incident after `open_after` consecutive bad windows, close after `close_after` good ones."""

    def __init__(self, open_after: int = 2, close_after: int = 2):
        self.open_after, self.close_after = open_after, close_after
        self.active: str | None = None
        self._candidate: str | None = None
        self._streak = 0
        self._good = 0

    def update(self, code: str) -> Transition:
        t = Transition()
        if code == "ok":
            self._candidate, self._streak = None, 0
            if self.active:
                self._good += 1
                if self._good >= self.close_after:
                    t.closed, self.active, self._good = self.active, None, 0
            return t
        self._good = 0
        if self.active == code:
            return t
        if code == self._candidate:
            self._streak += 1
        else:
            self._candidate, self._streak = code, 1
        if self._streak >= self.open_after:
            if self.active:
                t.closed = self.active
            t.opened, self.active = code, code
            self._candidate, self._streak = None, 0
        return t
