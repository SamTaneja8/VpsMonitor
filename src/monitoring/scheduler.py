from __future__ import annotations

import time
from collections.abc import Callable


def run_forever(task: Callable[[], None], interval_minutes: int) -> None:
    interval_seconds = max(interval_minutes, 1) * 60
    while True:
        task()
        time.sleep(interval_seconds)
