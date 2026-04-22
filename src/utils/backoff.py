import random

BACKOFF_STEPS = [1, 2, 5, 15, 30, 60]
JITTER_RATIO = 0.2


def get_reconnect_delay(attempt: int) -> float:
    idx = min(max(attempt, 0), len(BACKOFF_STEPS) - 1)
    base = BACKOFF_STEPS[idx]
    jitter = base * JITTER_RATIO * (random.random() * 2 - 1)
    return max(0.1, base + jitter)


def get_timestamp_utc_ms() -> str:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
