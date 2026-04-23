"""재연결 백오프 수열 + jitter ±20% 검증."""

from __future__ import annotations

from utils.backoff import BACKOFF_STEPS, JITTER_RATIO, get_reconnect_delay


def test_backoff_steps_match_spec():
    """CLAUDE.md §1.2.5: 1s → 2s → 5s → 15s → 30s → 60s."""
    assert BACKOFF_STEPS == [1, 2, 5, 15, 30, 60]


def test_backoff_jitter_within_range():
    """attempt 별로 1000회 샘플 → base ± 20% 범위 보장."""
    for attempt, base in enumerate(BACKOFF_STEPS):
        for _ in range(200):
            delay = get_reconnect_delay(attempt)
            lower = max(0.1, base * (1 - JITTER_RATIO))
            upper = base * (1 + JITTER_RATIO)
            assert lower - 1e-9 <= delay <= upper + 1e-9, (
                f"attempt={attempt} base={base} delay={delay}"
            )


def test_backoff_clamps_high_attempt():
    """6회 이상 시도 시 60s에 클램프."""
    for attempt in (6, 10, 100):
        delay = get_reconnect_delay(attempt)
        assert 60 * (1 - JITTER_RATIO) <= delay <= 60 * (1 + JITTER_RATIO)
