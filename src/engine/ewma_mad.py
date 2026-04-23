"""EWMA + MAD 동적 임계값 산출 (2차 검증 스텁).

Oracle 작업명세서 §2.1 / 오라클 2차 검증 기획안 §2 참조.

v1.0에서는 인터페이스만 제공한다. 실제 모델 학습/추론은 2차 검증 활성화 시 구현한다.

설계 의도:
  - 레시피별 독립 학습 (DEFAULT_RECIPE 폴백 없음)
  - EWMA 평균 + 표준편차로 동적 정상 구간 [μ-2σ, μ+2σ] 계산
  - MAD (Median Absolute Deviation) 로 robust 이상치 감지
  - rule_thresholds.lot_basis ≥ N (예: 8 LOT) 충족 시 활성화
"""

from __future__ import annotations

from dataclasses import dataclass


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
    history: list[float] | None = None,
    smoothing_alpha: float = 0.3,
    sigma_multiplier: float = 2.0,
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
    NotImplementedError
        2차 검증 모듈 활성화 전까지 항상 발생.
    """
    raise NotImplementedError(
        "EWMA+MAD 2차 검증 모듈은 v1.0 범위 밖 — Oracle 2차 검증 기획안 §2 구현 필요"
    )
