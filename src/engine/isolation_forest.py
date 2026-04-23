"""Isolation Forest 이상도 점수 (2차 검증 스텁).

Oracle 작업명세서 §2.1 / 오라클 2차 검증 기획안 §3 참조.

v1.0에서는 인터페이스만 제공한다. 실제 모델 학습/추론은 2차 검증 활성화 시 구현한다.

설계 의도:
  - 레시피별 독립 모델 (sklearn.ensemble.IsolationForest 등)
  - 입력 feature_vector: [yield_pct, side_et52_rate, takt_p95, blade_wear_index, ...]
  - 출력: 0.0 ~ 1.0 이상 점수 (1.0에 가까울수록 이상)
  - 임계값 0.85 초과 시 DANGER 후보 (Mock 25 기준)
"""

from __future__ import annotations

from collections.abc import Mapping


def compute_anomaly_score(
    features: Mapping[str, float],
    *,
    recipe_id: str,
    contamination: float = 0.05,
) -> float:
    """LOT 1건의 feature vector로부터 0~1 사이 이상도 점수를 산출한다.

    Parameters
    ----------
    features      : metric_name → value 매핑.
    recipe_id     : 대상 레시피 ID. 레시피별 독립 모델 로드 키.
    contamination : 학습 시 가정한 이상치 비율 (sklearn IsolationForest 파라미터).

    Returns
    -------
    float
        ``0.0`` ~ ``1.0`` (1.0 에 가까울수록 이상).

    Raises
    ------
    NotImplementedError
        2차 검증 모듈 활성화 전까지 항상 발생.
    """
    raise NotImplementedError(
        "Isolation Forest 2차 검증 모듈은 v1.0 범위 밖 — Oracle 2차 검증 기획안 §3 구현 필요"
    )
