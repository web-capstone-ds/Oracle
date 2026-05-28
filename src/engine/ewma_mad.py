"""EWMA + MAD dynamic threshold calculation.

Oracle 작업명세서 §2.1 / 오라클 2차 검증 기획안 §2 참조.

Phase 2 activates recipe-local dynamic boundaries. Histories are passed in
newest-to-oldest order; the calculation reverses them so newer values receive
the larger EWMA weight.
"""

from __future__ import annotations

from dataclasses import dataclass
import statistics


@dataclass(frozen=True)
class DynamicThreshold:
    """동적 임계값 결과 — rule_thresholds 갱신 후보."""

    metric: str
    recipe_id: str
    warning_min: float | None
    warning_max: float | None
    normal_min: float | None
    normal_max: float | None
    lot_basis: int
    ewma_mean: float
    ewma_std: float
    mad: float


def compute_dynamic_threshold(
    recipe_id: str,
    metric: str,
    *,
    history: list[float],
    smoothing_alpha: float = 0.3,
    sigma_multiplier: float = 2.0,
    direction: str = "two_sided",
) -> DynamicThreshold:
    """레시피별 metric 시계열로부터 동적 임계값을 산출한다.

    Parameters
    ----------
    recipe_id : 대상 레시피 ID. ``__default__`` 폴백 금지 (레시피 독립 학습).
    metric    : 대상 지표 (예: ``yield_pct``, ``side_et52_rate_pct``).
    history   : Historian에서 조회한 metric 시계열 (최신 → 과거 순).
    smoothing_alpha : EWMA 평활 계수 (0~1).
    sigma_multiplier: 정상 구간 너비 계수 (기본 2σ).

    Returns
    -------
    DynamicThreshold

    Raises
    ------
    ValueError
        If fewer than 5 LOTs are available.
    """
    if len(history) < 5:
        raise ValueError(f"EWMA 활성 조건 미달: {len(history)} < 5 LOT")
    if not 0 < smoothing_alpha <= 1:
        raise ValueError("smoothing_alpha must be in (0, 1]")

    ordered = [float(v) for v in reversed(history)]
    ewma = ordered[0]
    for value in ordered[1:]:
        ewma = smoothing_alpha * value + (1 - smoothing_alpha) * ewma

    std = statistics.stdev(history) if len(history) >= 2 else 0.0
    median = statistics.median(history)
    mad = statistics.median([abs(float(x) - median) for x in history])
    mad_std = mad * 1.4826
    effective_std = min(std, mad_std) if mad_std > 0 else std

    warning_band = sigma_multiplier * effective_std
    danger_band = (sigma_multiplier + 1) * effective_std

    if direction == "higher_better":
        return DynamicThreshold(
            metric=metric,
            recipe_id=recipe_id,
            normal_min=ewma - warning_band,
            normal_max=None,
            warning_min=ewma - danger_band,
            warning_max=ewma - warning_band,
            lot_basis=len(history),
            ewma_mean=ewma,
            ewma_std=effective_std,
            mad=mad,
        )
    if direction == "lower_better":
        return DynamicThreshold(
            metric=metric,
            recipe_id=recipe_id,
            normal_min=None,
            normal_max=ewma + warning_band,
            warning_min=ewma + warning_band,
            warning_max=ewma + danger_band,
            lot_basis=len(history),
            ewma_mean=ewma,
            ewma_std=effective_std,
            mad=mad,
        )
    if direction != "two_sided":
        raise ValueError(f"Unknown direction: {direction}")
    return DynamicThreshold(
        metric=metric,
        recipe_id=recipe_id,
        normal_min=ewma - warning_band,
        normal_max=ewma + warning_band,
        warning_min=ewma - danger_band,
        warning_max=ewma + danger_band,
        lot_basis=len(history),
        ewma_mean=ewma,
        ewma_std=effective_std,
        mad=mad,
    )
