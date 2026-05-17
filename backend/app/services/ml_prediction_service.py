from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd

from app.services.smart_service import collect_smart_data


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
SMART_MODEL_INFO_FIELDS = (
    "model_name",
    "target_column",
    "prediction_mode",
    "best_threshold",
    "balanced_model_name",
    "balanced_threshold",
    "safety_model_name",
    "safety_threshold",
    "split_mode",
    "test_start_date",
    "feature_columns",
    "balanced_threshold_metrics",
    "safety_threshold_metrics",
)
SMART_DRIVE_COLLECTION_KEYS = ("drives", "disks", "devices")
SMART_DRIVE_TO_MODEL_FIELDS = {
    "smart_1_raw": "raw_read_error_rate",
    "smart_5_raw": "reallocated_sectors_count",
    "smart_7_raw": "seek_error_rate",
    "smart_9_raw": "power_on_hours",
    "smart_12_raw": "power_cycle_count",
    "smart_187_raw": "reported_uncorrectable_errors",
    "smart_188_raw": "command_timeout",
    "smart_194_raw": "temperature_celsius",
    "smart_196_raw": "reallocated_event_count",
    "smart_197_raw": "current_pending_sector_count",
    "smart_198_raw": "offline_uncorrectable",
    "smart_199_raw": "udma_crc_error_count",
}
SMART_STATUS_DRIVE_FIELDS = (
    "name",
    "model",
    "serial",
    "interface",
    "media_type",
    "size_gb",
    "health_status",
    "temperature_celsius",
    "power_on_hours",
    "power_cycle_count",
    "life_percent",
    "percentage_used",
    "available_spare",
    "available_spare_threshold",
    "reallocated_sectors_count",
    "current_pending_sector_count",
    "offline_uncorrectable",
    "reported_uncorrectable_errors",
    "unsafe_shutdowns",
    "media_errors",
    "data_read_gb",
    "data_written_gb",
    "udma_crc_error_count",
    "raw_read_error_rate",
    "seek_error_rate",
    "reallocated_event_count",
    "command_timeout",
    "smartctl_exit_status",
)


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


def _serialize_metadata_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _serialize_metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_metadata_value(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return item_method()
        except (TypeError, ValueError):
            return value
    return value


def get_smart_model_info() -> dict[str, object]:
    artifact = load_smart_model_artifact()
    model_info: dict[str, object] = {}

    for field_name in SMART_MODEL_INFO_FIELDS:
        if field_name == "model_name":
            value = artifact.get(field_name) or artifact.get("balanced_model_name")
        elif field_name == "prediction_mode":
            value = artifact.get(field_name) or "balanced"
        elif field_name == "feature_columns":
            value = artifact.get(field_name)
            if not isinstance(value, list) or not value:
                value = MODEL_FEATURE_COLUMNS
        else:
            value = artifact.get(field_name)
        model_info[field_name] = _serialize_metadata_value(value)

    return model_info


def sanitize_smart_drive_for_status(drive: object) -> dict[str, object] | None:
    if not isinstance(drive, dict):
        return None

    return {
        field_name: drive.get(field_name)
        for field_name in SMART_STATUS_DRIVE_FIELDS
    }


def _extract_capacity_bytes(drive: dict[str, object]) -> int | None:
    for field_name in ("capacity_bytes", "size_bytes"):
        value = _to_float(drive.get(field_name), default=float("nan"))
        if not math.isnan(value) and value > 0:
            return int(value)

    raw_sources = drive.get("raw")
    if isinstance(raw_sources, dict):
        smartctl_raw = raw_sources.get("smartctl")
        if isinstance(smartctl_raw, dict):
            payload = smartctl_raw.get("payload")
            if isinstance(payload, dict):
                user_capacity = payload.get("user_capacity")
                if isinstance(user_capacity, dict):
                    user_capacity_bytes = _to_float(
                        user_capacity.get("bytes"),
                        default=float("nan"),
                    )
                    if not math.isnan(user_capacity_bytes) and user_capacity_bytes > 0:
                        return int(user_capacity_bytes)

                nvme_total_capacity = _to_float(
                    payload.get("nvme_total_capacity"),
                    default=float("nan"),
                )
                if not math.isnan(nvme_total_capacity) and nvme_total_capacity > 0:
                    return int(nvme_total_capacity)

        windows_physical_disk_raw = raw_sources.get("windows_physical_disk")
        if isinstance(windows_physical_disk_raw, dict):
            physical_disk_size = _to_float(
                windows_physical_disk_raw.get("Size"),
                default=float("nan"),
            )
            if not math.isnan(physical_disk_size) and physical_disk_size > 0:
                return int(physical_disk_size)

    size_gb = _to_float(drive.get("size_gb"), default=float("nan"))
    if not math.isnan(size_gb) and size_gb > 0:
        return int(size_gb * (1024 ** 3))
    return None


def _extract_drive_candidates(
    raw_smart_data: dict[str, object] | list[object] | object,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    if isinstance(raw_smart_data, dict):
        fallback_drives: list[dict[str, object]] = []
        for field_name in SMART_DRIVE_COLLECTION_KEYS:
            candidate_drives = raw_smart_data.get(field_name)
            if isinstance(candidate_drives, list):
                drive_dicts = [item for item in candidate_drives if isinstance(item, dict)]
                if drive_dicts:
                    return (
                        drive_dicts,
                        raw_smart_data.get("sources")
                        if isinstance(raw_smart_data.get("sources"), dict)
                        else None,
                    )
                fallback_drives = drive_dicts
        if fallback_drives == [] and any(key in raw_smart_data for key in SMART_DRIVE_COLLECTION_KEYS):
            return (
                [],
                raw_smart_data.get("sources")
                if isinstance(raw_smart_data.get("sources"), dict)
                else None,
            )
        return [raw_smart_data], None

    if isinstance(raw_smart_data, list):
        return [item for item in raw_smart_data if isinstance(item, dict)], None

    return [], None


def _build_predict_payload_from_drive(drive: dict[str, object]) -> dict[str, int | float | None]:
    predict_payload: dict[str, int | float | None] = {
        "capacity_bytes": _extract_capacity_bytes(drive),
    }

    for model_field, drive_field in SMART_DRIVE_TO_MODEL_FIELDS.items():
        predict_payload[model_field] = _to_float(drive.get(drive_field), 0.0)

    return predict_payload


def _is_predictable_drive(drive: dict[str, object], predict_payload: dict[str, object]) -> bool:
    if predict_payload.get("capacity_bytes") is not None:
        return True
    return any(drive.get(drive_field) is not None for drive_field in SMART_DRIVE_TO_MODEL_FIELDS.values())


def _has_predictive_smart_values(drive: dict[str, object]) -> bool:
    return any(drive.get(drive_field) is not None for drive_field in SMART_DRIVE_TO_MODEL_FIELDS.values())


def extract_predictable_smart_payload(raw_smart_data: dict[str, object] | list[object] | object) -> dict[str, object]:
    drives, sources = _extract_drive_candidates(raw_smart_data)
    if not drives:
        raise ValueError("SMART data does not contain any drives for prediction.")

    ordered_drives = [
        *[drive for drive in drives if _has_predictive_smart_values(drive)],
        *[drive for drive in drives if not _has_predictive_smart_values(drive)],
    ]

    for drive in ordered_drives:
        predict_payload = _build_predict_payload_from_drive(drive)
        if not _is_predictable_drive(drive, predict_payload):
            continue

        normalized_features = prepare_smart_features(predict_payload)
        return {
            "source_drive": drive,
            "predict_payload": predict_payload,
            "normalized_features": normalized_features,
            "sources": sources,
        }

    raise ValueError("SMART data does not contain a suitable drive with predictive SMART attributes.")


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


def predict_current_smart_failure() -> dict[str, object]:
    raw_smart_data = collect_smart_data()
    extracted_payload = extract_predictable_smart_payload(raw_smart_data)
    prediction = predict_smart_failure(extracted_payload["predict_payload"])
    source_drive = extracted_payload.get("source_drive")

    return {
        "prediction": prediction,
        "source_drive": source_drive,
        "source_drive_summary": sanitize_smart_drive_for_status(source_drive),
        "predict_payload": extracted_payload["predict_payload"],
        "normalized_features": extracted_payload["normalized_features"],
        "sources": extracted_payload["sources"],
    }
