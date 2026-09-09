"""How long a retry waits.

Shared by every kind of work the worker retries, so a rate-limited render,
a failed publish and a failed planning call all back off the same way
instead of each inventing its own arithmetic — or, worse, retrying with no
delay at all and hammering whatever just refused them.
"""

from __future__ import annotations

import random
from datetime import timedelta

BASE = timedelta(minutes=5)
CEILING = timedelta(hours=6)

#: Spread, so several jobs failing together do not all wake in the same
#: second and repeat the burst that broke them.
JITTER = (0.8, 1.2)


#: Doubling past this reaches the ceiling anyway, and going further
#: overflows timedelta rather than producing a bigger number.
MAX_DOUBLINGS = 20


def delay_for(attempts: int, *, base: timedelta = BASE) -> timedelta:
    """Exponential with jitter, capped.

    `attempts` is how many tries have happened, so the first retry waits
    roughly `base` rather than twice it.
    """
    steps = min(max(0, attempts - 1), MAX_DOUBLINGS)
    delay = base * (2**steps)
    return min(delay * random.uniform(*JITTER), CEILING)
