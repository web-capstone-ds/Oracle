"""Isolation Forest anomaly scoring for Phase 2.

Oracle 작업명세서 §2.1 / 오라클 2차 검증 기획안 §3 참조.

The primary path uses scikit-learn when available. A deterministic distance
fallback keeps tests and constrained environments usable.
"""

from __future__ import annotations

import math
import pickle
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from config import settings

try:  # pragma: no cover - exercised in environments with sklearn installed.
    from sklearn.ensemble import IsolationForest
except Exception:  # pragma: no cover
    IsolationForest = None  # type: ignore[assignment]


_MODEL_CACHE: dict[str, Any] = {}
_MODEL_DIR = Path(getattr(settings, "oracle_model_dir", "model_cache"))


def compute_anomaly_score(
    features: Mapping[str, float] | Sequence[float],
    *,
    recipe_id: str,
    history_features: list[list[float]] | None = None,
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
    ValueError
        If fewer than 10 historical LOT feature vectors are available.
    """
    history_features = history_features or []
    if len(history_features) < 10:
        raise ValueError(f"Isolation Forest 활성 조건 미달: {len(history_features)} < 10 LOT")

    vector = _to_vector(features)
    if IsolationForest is None:
        return round(_distance_score(vector, history_features), 3)

    model = _get_or_train_model(recipe_id, history_features, contamination)
    raw_score = float(model.score_samples([vector])[0])
    return round(_normalize_score(raw_score), 3)


def invalidate_model_cache(recipe_id: str) -> None:
    for key in [k for k in _MODEL_CACHE if k.startswith(f"{recipe_id}:")]:
        del _MODEL_CACHE[key]
    model_file = _MODEL_DIR / f"if_{_safe_recipe_id(recipe_id)}.pkl"
    if model_file.exists():
        model_file.unlink()


def _get_or_train_model(
    recipe_id: str,
    history_features: list[list[float]],
    contamination: float,
):
    cache_key = f"{recipe_id}:{len(history_features)}:{contamination}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_file = _MODEL_DIR / f"if_{_safe_recipe_id(recipe_id)}.pkl"
    if model_file.exists():
        with model_file.open("rb") as f:
            model = pickle.load(f)
    else:
        model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100,
        )
        model.fit(history_features)
        with model_file.open("wb") as f:
            pickle.dump(model, f)
    _MODEL_CACHE[cache_key] = model
    return model


def _normalize_score(raw: float) -> float:
    return 1.0 / (1.0 + math.exp(raw * 5))


def _distance_score(vector: list[float], history: list[list[float]]) -> float:
    columns = list(zip(*history))
    means = [sum(col) / len(col) for col in columns]
    stds = [
        max((sum((x - means[i]) ** 2 for x in col) / len(col)) ** 0.5, 1e-9)
        for i, col in enumerate(columns)
    ]
    z = sum(abs((value - means[i]) / stds[i]) for i, value in enumerate(vector))
    return 1.0 / (1.0 + math.exp(-(z / max(len(vector), 1) - 2.0)))


def _to_vector(features: Mapping[str, float] | Sequence[float]) -> list[float]:
    if isinstance(features, Mapping):
        return [float(features[key]) for key in sorted(features)]
    return [float(value) for value in features]


def _safe_recipe_id(recipe_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in recipe_id)
