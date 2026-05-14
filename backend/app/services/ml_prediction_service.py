from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd


MODEL_FILENAME = "smart_failure_model.joblib"
MODEL_PATH = Path(__file__).resolve().parents[2] / "ml" / "models" / MODEL_FILENAME
MODEL_FEATURE_COLUMNS = [
    "capacity_bytes",
    "smart_1_raw",
    "smart_5_raw",
    "smart_7_raw",
    "smart_9_raw",
    "smart_12_raw",
    "smart_187_raw",
    "smart_188_raw",
    "smart_194_raw",
    "smart_196_raw",
    "smart_197_raw",
    "smart_198_raw",
    "smart_199_raw",
    "power_on_years",
    "has_reallocated",
    "has_pending",
    "has_uncorrectable",
    "has_reported_uncorrectable",
    "has_crc_errors",
]


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp_value = math.exp(-value)
        return 1.0 / (1.0 + exp_value)
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


@lru_cache(maxsize=1)
def load_smart_model_artifact() -> dict[str, object]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"SMART ML model not found at '{MODEL_PATH}'. "
            "Make sure backend/ml/models/smart_failure_model.joblib exists."
        )

    artifact = joblib.load(MODEL_PATH)
    if not isinstance(artifact, dict):
        raise ValueError("SMART ML artifact has unexpected format: expected a joblib dictionary.")
    if artifact.get("pipeline") is None:
        raise ValueError("SMART ML artifact does not contain 'pipeline'.")
    return artifact


def prepare_smart_features(smart_data: dict[str, object]) -> dict[str, float | int | None]:
    smart_5_raw = _to_float(smart_data.get("smart_5_raw"), 0.0)
    smart_9_raw = _to_float(smart_data.get("smart_9_raw"), 0.0)
    smart_187_raw = _to_float(smart_data.get("smart_187_raw"), 0.0)
    smart_197_raw = _to_float(smart_data.get("smart_197_raw"), 0.0)
    smart_198_raw = _to_float(smart_data.get("smart_198_raw"), 0.0)
    smart_199_raw = _to_float(smart_data.get("smart_199_raw"), 0.0)

    capacity_value = smart_data.get("capacity_bytes")
    capacity_bytes = None if capacity_value is None else _to_float(capacity_value, 0.0)

    return {
        "capacity_bytes": capacity_bytes,
        "smart_1_raw": _to_float(smart_data.get("smart_1_raw"), 0.0),
        "smart_5_raw": smart_5_raw,
        "smart_7_raw": _to_float(smart_data.get("smart_7_raw"), 0.0),
        "smart_9_raw": smart_9_raw,
        "smart_12_raw": _to_float(smart_data.get("smart_12_raw"), 0.0),
        "smart_187_raw": smart_187_raw,
        "smart_188_raw": _to_float(smart_data.get("smart_188_raw"), 0.0),
        "smart_194_raw": _to_float(smart_data.get("smart_194_raw"), 0.0),
        "smart_196_raw": _to_float(smart_data.get("smart_196_raw"), 0.0),
        "smart_197_raw": smart_197_raw,
        "smart_198_raw": smart_198_raw,
        "smart_199_raw": smart_199_raw,
        "power_on_years": smart_9_raw / 8760.0,
        "has_reallocated": int(smart_5_raw > 0),
        "has_pending": int(smart_197_raw > 0),
        "has_uncorrectable": int(smart_198_raw > 0),
        "has_reported_uncorrectable": int(smart_187_raw > 0),
        "has_crc_errors": int(smart_199_raw > 0),
    }


def _build_recommendation(prediction: int, risk_percent: float) -> str:
    if prediction == 1:
        return (
            "Обнаружен повышенный риск отказа накопителя. "
            "Рекомендуется срочно проверить резервные копии, провести расширенную диагностику SMART "
            "и запланировать замену диска."
        )
    if risk_percent >= 50:
        return (
            "Сейчас модель не считает накопитель критически рискованным, "
            "но показатель заметный. Рекомендуется усилить мониторинг и проверить SMART-историю."
        )
    return (
        "Критический риск по модели не выявлен. "
        "Продолжайте штатный мониторинг и периодически проверяйте SMART-показатели."
    )


def predict_smart_failure(smart_data: dict[str, object]) -> dict[str, object]:
    artifact = load_smart_model_artifact()
    pipeline = artifact["pipeline"]
    threshold = float(artifact.get("best_threshold", 0.5))
    target_column = str(artifact.get("target_column", "failure"))
    model_name = str(artifact.get("model_name", artifact.get("balanced_model_name", "unknown_model")))
    prediction_mode = str(artifact.get("prediction_mode", "balanced"))

    prepared_features = prepare_smart_features(smart_data)
    feature_columns = artifact.get("feature_columns")
    if not isinstance(feature_columns, list) or not feature_columns:
        feature_columns = MODEL_FEATURE_COLUMNS

    feature_frame = pd.DataFrame(
        [{column: prepared_features.get(column) for column in feature_columns}]
    )

    if hasattr(pipeline, "predict_proba"):
        risk_score = float(pipeline.predict_proba(feature_frame)[0][1])
    elif hasattr(pipeline, "decision_function"):
        decision_score = float(pipeline.decision_function(feature_frame)[0])
        risk_score = _sigmoid(decision_score)
    else:
        risk_score = float(pipeline.predict(feature_frame)[0])

    prediction = int(risk_score >= threshold)
    risk_percent = round(risk_score * 100.0, 2)

    return {
        "target": target_column,
        "model_name": model_name,
        "prediction_mode": prediction_mode,
        "threshold": threshold,
        "risk_score": risk_score,
        "risk_percent": risk_percent,
        "prediction": prediction,
        "status": "high_risk" if prediction == 1 else "normal",
        "recommendation": _build_recommendation(prediction, risk_percent),
        "features": prepared_features,
    }
