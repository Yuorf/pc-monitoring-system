from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight


FEATURE_COLUMNS = [
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

TARGET_COLUMN = "failure"
CHUNK_SIZE = 100_000


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    ml_dir = script_dir.parent
    default_input = ml_dir / "data" / "processed" / "backblaze_smart_dataset.csv"

    parser = argparse.ArgumentParser(
        description="Train a SMART failure prediction model from the prepared Backblaze dataset."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=default_input,
        help="Path to the processed Backblaze CSV dataset.",
    )
    parser.add_argument(
        "--max-normal-rows",
        type=int,
        default=1_000_000,
        help="Maximum number of failure=0 rows to keep for training.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed used for sampling, shuffling and train/test split.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.2,
        help="Fraction of the balanced dataset reserved for the test split.",
    )
    return parser.parse_args()


def load_dataset(
    input_path: Path,
    feature_columns: list[str],
    *,
    max_normal_rows: int,
    random_state: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if not input_path.exists():
        raise FileNotFoundError(
            "Processed dataset not found. Run "
            "'python ml/scripts/prepare_backblaze_dataset.py' from the backend directory first."
        )

    required_columns = feature_columns + [TARGET_COLUMN]
    header = pd.read_csv(input_path, nrows=0)
    missing_columns = [column for column in required_columns if column not in header.columns]
    if missing_columns:
        raise ValueError(
            f"Dataset is missing required columns: {missing_columns}. "
            "Rebuild it with 'python ml/scripts/prepare_backblaze_dataset.py'."
        )

    rng = np.random.default_rng(random_state)
    failure_chunks: list[pd.DataFrame] = []
    normal_sample = pd.DataFrame(columns=required_columns)

    total_rows_read = 0
    failure_rows = 0
    normal_rows_total = 0

    for chunk in pd.read_csv(
        input_path,
        usecols=required_columns,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        total_rows_read += len(chunk)

        for column in required_columns:
            chunk[column] = pd.to_numeric(chunk[column], errors="coerce")

        chunk = chunk.dropna(subset=[TARGET_COLUMN]).copy()
        if chunk.empty:
            continue

        chunk[TARGET_COLUMN] = chunk[TARGET_COLUMN].astype(int)
        chunk = chunk[chunk[TARGET_COLUMN].isin([0, 1])].copy()
        if chunk.empty:
            continue

        failure_chunk = chunk[chunk[TARGET_COLUMN] == 1].copy()
        normal_chunk = chunk[chunk[TARGET_COLUMN] == 0].copy()

        if not failure_chunk.empty:
            failure_rows += len(failure_chunk)
            failure_chunks.append(failure_chunk)

        if normal_chunk.empty:
            continue

        normal_rows_total += len(normal_chunk)
        if max_normal_rows <= 0:
            continue

        combined_normal = pd.concat([normal_sample, normal_chunk], ignore_index=True)
        if len(combined_normal) <= max_normal_rows:
            normal_sample = combined_normal
            continue

        selected_indices = rng.choice(
            len(combined_normal),
            size=max_normal_rows,
            replace=False,
        )
        normal_sample = combined_normal.iloc[selected_indices].reset_index(drop=True)

    failure_df = (
        pd.concat(failure_chunks, ignore_index=True)
        if failure_chunks
        else pd.DataFrame(columns=required_columns)
    )
    normal_sample = normal_sample.reset_index(drop=True)

    stats = {
        "total_rows_read": int(total_rows_read),
        "failure_rows": int(failure_rows),
        "normal_rows_total": int(normal_rows_total),
        "normal_rows_used": int(len(normal_sample)),
    }
    return failure_df, normal_sample, stats


def balance_dataset(
    failure_df: pd.DataFrame,
    normal_df: pd.DataFrame,
    *,
    random_state: int,
) -> pd.DataFrame:
    combined = pd.concat([failure_df, normal_df], ignore_index=True)
    if combined.empty:
        return combined
    return combined.sample(frac=1.0, random_state=random_state).reset_index(drop=True)


def build_models(random_state: int) -> dict[str, Pipeline]:
    return {
        "LogisticRegression": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=1000,
                        random_state=random_state,
                        solver="liblinear",
                    ),
                ),
            ]
        ),
        "RandomForestClassifier": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestClassifier(
                        class_weight="balanced",
                        n_estimators=200,
                        n_jobs=-1,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "HistGradientBoostingClassifier": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingClassifier(
                        max_iter=200,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
    }


def evaluate_thresholds(
    y_test: pd.Series,
    scores: np.ndarray,
) -> list[dict[str, Any]]:
    threshold_metrics: list[dict[str, Any]] = []
    y_true = y_test.to_numpy()

    for threshold in np.arange(0.05, 1.0, 0.05):
        predictions = (scores >= threshold).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()
        threshold_metrics.append(
            {
                "threshold": round(float(threshold), 2),
                "accuracy": float(accuracy_score(y_true, predictions)),
                "precision": float(precision_score(y_true, predictions, zero_division=0)),
                "recall": float(recall_score(y_true, predictions, zero_division=0)),
                "f1": float(f1_score(y_true, predictions, zero_division=0)),
                "false_positive": int(fp),
                "false_negative": int(fn),
                "true_positive": int(tp),
                "true_negative": int(tn),
                "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
            }
        )

    return threshold_metrics


def evaluate_model(
    model: Pipeline,
    x_test: pd.DataFrame,
    y_test: pd.Series,
) -> dict[str, Any]:
    predictions = model.predict(x_test)

    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(x_test)[:, 1]
    elif hasattr(model, "decision_function"):
        scores = model.decision_function(x_test)
    else:
        scores = predictions

    average_precision = float(average_precision_score(y_test, scores))
    default_confusion_matrix = confusion_matrix(y_test, predictions, labels=[0, 1]).tolist()
    threshold_metrics = evaluate_thresholds(y_test, np.asarray(scores))

    recall_eligible_thresholds = [
        metrics for metrics in threshold_metrics if metrics["recall"] >= 0.80
    ]
    threshold_pool = recall_eligible_thresholds or threshold_metrics
    best_threshold_metrics = max(
        threshold_pool,
        key=lambda metrics: (
            metrics["f1"],
            metrics["precision"],
            -metrics["false_positive"],
            metrics["threshold"],
        ),
    )

    return {
        "default_metrics": {
            "accuracy": float(accuracy_score(y_test, predictions)),
            "precision": float(precision_score(y_test, predictions, zero_division=0)),
            "recall": float(recall_score(y_test, predictions, zero_division=0)),
            "f1": float(f1_score(y_test, predictions, zero_division=0)),
            "roc_auc": float(roc_auc_score(y_test, scores)),
            "average_precision": average_precision,
            "confusion_matrix": default_confusion_matrix,
        },
        "threshold_metrics": threshold_metrics,
        "best_threshold": best_threshold_metrics["threshold"],
        "best_threshold_metrics": {
            **best_threshold_metrics,
            "average_precision": average_precision,
            "roc_auc": float(roc_auc_score(y_test, scores)),
        },
    }


def train_and_select_model(
    dataset: pd.DataFrame,
    feature_columns: list[str],
    *,
    random_state: int,
    test_size: float,
) -> tuple[Pipeline, str, dict[str, dict[str, Any]], dict[str, int], str, float]:
    if dataset.empty:
        raise ValueError("Training dataset is empty after balancing.")

    y = dataset[TARGET_COLUMN].astype(int)
    class_counts = y.value_counts().to_dict()
    if len(class_counts) < 2 or min(class_counts.values()) < 2:
        raise ValueError(
            "Not enough rows in both classes for a stratified split. "
            "Make sure the prepared dataset contains enough failure=1 examples."
        )

    x = dataset[feature_columns].copy()

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,
    )

    metrics_by_model: dict[str, dict[str, Any]] = {}
    trained_models: dict[str, Pipeline] = {}
    sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)

    for model_name, model in build_models(random_state).items():
        if model_name == "HistGradientBoostingClassifier":
            model.fit(x_train, y_train, model__sample_weight=sample_weights)
        else:
            model.fit(x_train, y_train)

        metrics_by_model[model_name] = evaluate_model(model, x_test, y_test)
        trained_models[model_name] = model

    eligible_models = [
        name
        for name, metrics in metrics_by_model.items()
        if metrics["best_threshold_metrics"]["recall"] >= 0.80
    ]
    if eligible_models:
        selection_rule = (
            "Selected by best_threshold_metrics among models with recall >= 0.80, "
            "maximizing f1 and then precision."
        )
        best_model_name = max(
            eligible_models,
            key=lambda name: (
                metrics_by_model[name]["best_threshold_metrics"]["f1"],
                metrics_by_model[name]["best_threshold_metrics"]["precision"],
                metrics_by_model[name]["best_threshold_metrics"]["recall"],
            ),
        )
    else:
        selection_rule = (
            "No model reached recall >= 0.80; selected by maximum recall and then f1 "
            "using best_threshold_metrics."
        )
        best_model_name = max(
            metrics_by_model,
            key=lambda name: (
                metrics_by_model[name]["best_threshold_metrics"]["recall"],
                metrics_by_model[name]["best_threshold_metrics"]["f1"],
                metrics_by_model[name]["best_threshold_metrics"]["precision"],
            ),
        )

    best_threshold = float(metrics_by_model[best_model_name]["best_threshold"])

    split_stats = {
        "train_rows": int(len(x_train)),
        "test_rows": int(len(x_test)),
    }
    return (
        trained_models[best_model_name],
        best_model_name,
        metrics_by_model,
        split_stats,
        selection_rule,
        best_threshold,
    )


def save_artifacts(
    model: Pipeline,
    model_name: str,
    feature_columns: list[str],
    best_threshold: float,
    selection_rule: str,
    report: dict[str, Any],
    *,
    model_path: Path,
    report_path: Path,
) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(
        {
            "model_name": model_name,
            "feature_columns": feature_columns,
            "best_threshold": best_threshold,
            "selection_rule": selection_rule,
            "pipeline": model,
        },
        model_path,
    )

    with report_path.open("w", encoding="utf-8") as report_file:
        json.dump(report, report_file, ensure_ascii=False, indent=2)


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()

    try:
        failure_df, normal_df, stats = load_dataset(
            input_path,
            FEATURE_COLUMNS,
            max_normal_rows=args.max_normal_rows,
            random_state=args.random_state,
        )
    except FileNotFoundError as error:
        print(error)
        raise SystemExit(1) from error
    except ValueError as error:
        print(error)
        raise SystemExit(1) from error

    dataset = balance_dataset(
        failure_df,
        normal_df,
        random_state=args.random_state,
    )

    model_path = input_path.parent.parent.parent / "models" / "smart_failure_model.joblib"
    report_path = input_path.parent.parent.parent / "reports" / "smart_training_report.json"

    try:
        (
            best_model,
            best_model_name,
            metrics_by_model,
            split_stats,
            selection_rule,
            best_threshold,
        ) = train_and_select_model(
            dataset,
            FEATURE_COLUMNS,
            random_state=args.random_state,
            test_size=args.test_size,
        )
    except ValueError as error:
        print(error)
        raise SystemExit(1) from error

    report = {
        "total_rows_read": stats["total_rows_read"],
        "failure_rows": stats["failure_rows"],
        "normal_rows_total": stats["normal_rows_total"],
        "normal_rows_used": stats["normal_rows_used"],
        "train_rows": split_stats["train_rows"],
        "test_rows": split_stats["test_rows"],
        "feature_columns": FEATURE_COLUMNS,
        "metrics_by_model": metrics_by_model,
        "best_model_name": best_model_name,
        "best_threshold": best_threshold,
        "best_threshold_metrics": metrics_by_model[best_model_name]["best_threshold_metrics"],
        "selection_rule": selection_rule,
    }

    save_artifacts(
        best_model,
        best_model_name,
        FEATURE_COLUMNS,
        best_threshold,
        selection_rule,
        report,
        model_path=model_path,
        report_path=report_path,
    )

    print(f"Total rows read: {stats['total_rows_read']}")
    print(f"Failure rows (failure=1): {stats['failure_rows']}")
    print(f"Normal rows total (failure=0): {stats['normal_rows_total']}")
    print(f"Normal rows used: {stats['normal_rows_used']}")
    print(f"Feature columns: {FEATURE_COLUMNS}")

    for model_name, metrics in metrics_by_model.items():
        print(f"{model_name} metrics:")
        print(
            "  default_metrics: "
            f"accuracy={metrics['default_metrics']['accuracy']:.6f}, "
            f"precision={metrics['default_metrics']['precision']:.6f}, "
            f"recall={metrics['default_metrics']['recall']:.6f}, "
            f"f1={metrics['default_metrics']['f1']:.6f}, "
            f"roc_auc={metrics['default_metrics']['roc_auc']:.6f}, "
            f"average_precision={metrics['default_metrics']['average_precision']:.6f}, "
            f"confusion_matrix={metrics['default_metrics']['confusion_matrix']}"
        )
        print(f"  best_threshold={metrics['best_threshold']:.2f}")
        print(
            "  best_threshold_metrics: "
            f"accuracy={metrics['best_threshold_metrics']['accuracy']:.6f}, "
            f"precision={metrics['best_threshold_metrics']['precision']:.6f}, "
            f"recall={metrics['best_threshold_metrics']['recall']:.6f}, "
            f"f1={metrics['best_threshold_metrics']['f1']:.6f}, "
            f"roc_auc={metrics['best_threshold_metrics']['roc_auc']:.6f}, "
            f"average_precision={metrics['best_threshold_metrics']['average_precision']:.6f}, "
            f"confusion_matrix={metrics['best_threshold_metrics']['confusion_matrix']}"
        )

    print(f"Best model: {best_model_name}")
    print(f"Best threshold: {best_threshold:.2f}")
    print(f"Selection rule: {selection_rule}")
    print(f"Saved model: {model_path}")
    print(f"Saved report: {report_path}")


if __name__ == "__main__":
    main()
