from __future__ import annotations

from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = [
    "date",
    "serial_number",
    "model",
    "capacity_bytes",
    "failure",
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
]

NUMERIC_COLUMNS = [
    "capacity_bytes",
    "failure",
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
]

FEATURE_COLUMNS = [
    "power_on_years",
    "has_reallocated",
    "has_pending",
    "has_uncorrectable",
    "has_reported_uncorrectable",
    "has_crc_errors",
]

OUTPUT_COLUMNS = REQUIRED_COLUMNS + [
    "days_to_failure",
    "failure_within_30_days",
] + FEATURE_COLUMNS

CHUNK_SIZE = 50_000


def find_csv_files(base_dir: Path) -> list[Path]:
    csv_files: list[Path] = []
    for path in base_dir.rglob("*.csv"):
        if not path.is_file():
            continue
        if path.name == ".DS_Store":
            continue
        if path.name.startswith("._"):
            continue
        if "__MACOSX" in path.parts:
            continue
        if any(part.startswith("._") for part in path.parts):
            continue
        csv_files.append(path)
    return sorted(csv_files)


def read_required_columns(
    csv_path: Path,
    required_columns: list[str],
    chunk_size: int = CHUNK_SIZE,
) -> tuple[Iterator[pd.DataFrame], list[str]]:
    header = pd.read_csv(csv_path, nrows=0)
    found_columns = [column for column in required_columns if column in header.columns]
    missing_columns = [column for column in required_columns if column not in header.columns]

    if not found_columns:
        return iter(()), []

    reader = pd.read_csv(
        csv_path,
        usecols=found_columns,
        chunksize=chunk_size,
        low_memory=False,
    )

    def _generator() -> Iterator[pd.DataFrame]:
        for chunk in reader:
            for column in missing_columns:
                chunk[column] = np.nan
            yield chunk[required_columns]

    return _generator(), found_columns


def prepare_chunk(
    dataframe: pd.DataFrame,
    required_columns: list[str],
) -> pd.DataFrame:
    prepared = dataframe.copy()

    for column in required_columns:
        if column not in prepared.columns:
            prepared[column] = np.nan

    prepared["serial_number"] = prepared["serial_number"].astype("string").str.strip()
    if "model" in prepared.columns:
        prepared["model"] = prepared["model"].astype("string")
    prepared["date"] = pd.to_datetime(prepared["date"], errors="coerce")

    for column in NUMERIC_COLUMNS:
        if column not in prepared.columns:
            continue
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    prepared = prepared.dropna(subset=["serial_number", "date", "failure"]).copy()
    prepared = prepared[prepared["serial_number"].ne("")].copy()
    prepared["failure"] = prepared["failure"].astype(int)
    prepared = prepared[prepared["failure"].isin([0, 1])].copy()

    return prepared[required_columns]


def collect_failure_dates(csv_files: list[Path]) -> tuple[dict[str, pd.Timestamp], dict[str, int]]:
    minimal_columns = ["date", "serial_number", "failure"]
    failure_dates: dict[str, pd.Timestamp] = {}
    processed_rows = 0
    original_failure_rows = 0

    for index, csv_file in enumerate(csv_files, start=1):
        try:
            chunk_iterator, _found_columns = read_required_columns(
                csv_file,
                minimal_columns,
            )
        except Exception as error:
            print(f"Skipping {csv_file}: {error}")
            print(f"First pass: processed {index} files")
            continue

        for chunk in chunk_iterator:
            prepared_chunk = prepare_chunk(chunk, minimal_columns)
            if prepared_chunk.empty:
                continue

            processed_rows += len(prepared_chunk)
            failed_rows = prepared_chunk.loc[
                prepared_chunk["failure"] == 1,
                ["serial_number", "date"],
            ]
            if failed_rows.empty:
                continue

            original_failure_rows += len(failed_rows)
            chunk_failure_dates = failed_rows.groupby("serial_number")["date"].min()
            for serial_number, failure_date in chunk_failure_dates.items():
                existing_date = failure_dates.get(serial_number)
                if existing_date is None or failure_date < existing_date:
                    failure_dates[serial_number] = failure_date

        print(f"First pass: processed {index} files")

    stats = {
        "processed_rows": int(processed_rows),
        "original_failure_rows": int(original_failure_rows),
        "failed_drive_count": int(len(failure_dates)),
    }
    return failure_dates, stats


def build_predictive_chunk(
    dataframe: pd.DataFrame,
    failure_dates: dict[str, pd.Timestamp],
) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    prepared = dataframe.copy()
    prepared["failure_date"] = prepared["serial_number"].map(failure_dates)
    prepared["days_to_failure"] = (prepared["failure_date"] - prepared["date"]).dt.days
    prepared["failure_within_30_days"] = (
        prepared["days_to_failure"].between(1, 30, inclusive="both")
    ).astype(int)
    prepared = prepared[
        prepared["days_to_failure"].ne(0) | prepared["days_to_failure"].isna()
    ].copy()
    prepared = prepared.drop(columns=["failure_date"])

    return prepared


def add_features(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    prepared = dataframe.copy()
    prepared["power_on_years"] = prepared["smart_9_raw"] / 8760
    prepared["has_reallocated"] = (prepared["smart_5_raw"] > 0).astype(int)
    prepared["has_pending"] = (prepared["smart_197_raw"] > 0).astype(int)
    prepared["has_uncorrectable"] = (prepared["smart_198_raw"] > 0).astype(int)
    prepared["has_reported_uncorrectable"] = (prepared["smart_187_raw"] > 0).astype(int)
    prepared["has_crc_errors"] = (prepared["smart_199_raw"] > 0).astype(int)

    return prepared[OUTPUT_COLUMNS]


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    ml_dir = script_dir.parent
    raw_dir = ml_dir / "data" / "raw" / "backblaze"
    output_path = ml_dir / "data" / "processed" / "backblaze_smart_predictive_30d.csv"

    csv_files = find_csv_files(raw_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        output_path.unlink()

    if not csv_files:
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)
        print("Found CSV files: 0")
        print("No Backblaze CSV files found. Created empty predictive dataset.")
        print(f"Saved dataset path: {output_path}")
        return

    failure_dates, first_pass_stats = collect_failure_dates(csv_files)

    output_rows = 0
    predictive_positive_rows = 0
    predictive_negative_rows = 0
    wrote_output = False

    for index, csv_file in enumerate(csv_files, start=1):
        try:
            chunk_iterator, _found_columns = read_required_columns(
                csv_file,
                REQUIRED_COLUMNS,
            )
        except Exception as error:
            print(f"Skipping {csv_file}: {error}")
            print(f"Second pass: processed {index} files")
            continue

        for chunk in chunk_iterator:
            prepared_chunk = prepare_chunk(chunk, REQUIRED_COLUMNS)
            if prepared_chunk.empty:
                continue

            predictive_chunk = build_predictive_chunk(prepared_chunk, failure_dates)
            if predictive_chunk.empty:
                continue

            predictive_chunk = add_features(predictive_chunk)
            if predictive_chunk.empty:
                continue

            chunk_positive_rows = int(predictive_chunk["failure_within_30_days"].sum())
            chunk_output_rows = len(predictive_chunk)

            predictive_chunk.to_csv(
                output_path,
                mode="a",
                index=False,
                header=not wrote_output,
            )
            wrote_output = True

            output_rows += chunk_output_rows
            predictive_positive_rows += chunk_positive_rows
            predictive_negative_rows += chunk_output_rows - chunk_positive_rows

        print(f"Second pass: processed {index} files")

    if not wrote_output:
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)

    print(f"Found CSV files: {len(csv_files)}")
    print(f"Processed rows: {first_pass_stats['processed_rows']}")
    print(f"Output rows: {output_rows}")
    print(f"Original failure rows: {first_pass_stats['original_failure_rows']}")
    print(
        "Predictive positive rows failure_within_30_days=1: "
        f"{predictive_positive_rows}"
    )
    print(f"Predictive negative rows: {predictive_negative_rows}")
    print(f"Number of failed drives: {first_pass_stats['failed_drive_count']}")
    print(f"Saved dataset path: {output_path}")


if __name__ == "__main__":
    main()
