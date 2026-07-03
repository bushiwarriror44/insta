"""Human-like timing primitives.

Real users do not pause for ``random.randint(5, 15)`` seconds — their delay
distribution is heavy-tailed (lots of short pauses, occasional long ones).
We approximate that with a lognormal distribution and add hard caps so we
never freeze a worker indefinitely.
"""
from __future__ import annotations

import math
import random
import time

from app.logging_setup import get_logger

logger = get_logger(__name__)


def lognormal_delay(median_sec: float, sigma: float = 0.55, max_sec: float | None = None) -> float:
    """Return a lognormal-distributed delay clamped at ``max_sec`` if given."""
    if median_sec <= 0:
        return 0.0
    mu = math.log(median_sec)
    value = random.lognormvariate(mu, sigma)
    if max_sec is not None:
        value = min(value, max_sec)
    return max(0.0, value)


def think(median_sec: float, sigma: float = 0.55, max_sec: float | None = None) -> float:
    """Sleep for a lognormal-distributed think-time. Returns seconds slept."""
    delay = lognormal_delay(median_sec, sigma=sigma, max_sec=max_sec)
    if delay > 0:
        logger.debug("humanizer.sleep", delay=round(delay, 2), median=median_sec)
        time.sleep(delay)
    return delay


def coin_flip(probability: float) -> bool:
    return random.random() < probability


def jitter_seconds(base_sec: float, spread: float = 0.25) -> float:
    """Symmetric uniform jitter ±spread around base."""
    if base_sec <= 0:
        return 0.0
    delta = base_sec * spread
    return max(0.0, random.uniform(base_sec - delta, base_sec + delta))
