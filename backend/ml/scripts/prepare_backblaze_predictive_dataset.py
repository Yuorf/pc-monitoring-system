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


def prepare_chunk(dataframe: pd.DataFrame) -> pd.DataFrame:
    prepared = dataframe.copy()

    for column in REQUIRED_COLUMNS:
        if column not in prepared.columns:
            prepared[column] = np.nan

    prepared["serial_number"] = prepared["serial_number"].astype("string").str.strip()
    prepared["model"] = prepared["model"].astype("string")
    prepared["date"] = pd.to_datetime(prepared["date"], errors="coerce")

    for column in NUMERIC_COLUMNS:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    prepared = prepared.dropna(subset=["serial_number", "date", "failure"]).copy()
    prepared = prepared[prepared["serial_number"].ne("")].copy()
    prepared["failure"] = prepared["failure"].astype(int)
    prepared = prepared[prepared["failure"].isin([0, 1])].copy()

    return prepared[REQUIRED_COLUMNS]


def build_predictive_target(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    prepared = dataframe.copy()
    prepared = prepared.sort_values(["serial_number", "date"]).reset_index(drop=True)

    failure_dates = (
        prepared.loc[prepared["failure"] == 1, ["serial_number", "date"]]
        .groupby("serial_number", as_index=False)["date"]
        .min()
        .rename(columns={"date": "failure_date"})
    )

    prepared = prepared.merge(failure_dates, on="serial_number", how="left")
    prepared["days_to_failure"] = (
        prepared["failure_date"] - prepared["date"]
    ).dt.days
    prepared["failure_within_30_days"] = (
        prepared["days_to_failure"].between(1, 30, inclusive="both")
    ).astype(int)
    prepared = prepared[prepared["days_to_failure"].ne(0) | prepared["days_to_failure"].isna()].copy()
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
    temp_path = ml_dir / "data" / "processed" / "backblaze_smart_predictive_30d_tmp.csv"

    csv_files = find_csv_files(raw_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        output_path.unlink()
    if temp_path.exists():
        temp_path.unlink()

    if not csv_files:
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)
        print("Found CSV files: 0")
        print("No Backblaze CSV files found. Created empty predictive dataset.")
        print(f"Saved dataset path: {output_path}")
        return

    processed_rows = 0
    wrote_temp = False

    try:
        for csv_file in csv_files:
            try:
                chunk_iterator, _found_columns = read_required_columns(
                    csv_file,
                    REQUIRED_COLUMNS,
                )
            except Exception as error:
                print(f"Skipping {csv_file}: {error}")
                continue

            for chunk in chunk_iterator:
                prepared_chunk = prepare_chunk(chunk)
                if prepared_chunk.empty:
                    continue

                processed_rows += len(prepared_chunk)
                prepared_chunk.to_csv(
                    temp_path,
                    mode="a",
                    index=False,
                    header=not wrote_temp,
                )
                wrote_temp = True

        if not wrote_temp:
            pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)
            print(f"Found CSV files: {len(csv_files)}")
            print("Processed rows: 0")
            print("Output rows: 0")
            print("Original failure rows: 0")
            print("Predictive positive rows failure_within_30_days=1: 0")
            print("Predictive negative rows: 0")
            print("Number of failed drives: 0")
            print(f"Saved dataset path: {output_path}")
            return

        dataset = pd.read_csv(temp_path, low_memory=False)
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")
        for column in NUMERIC_COLUMNS:
            dataset[column] = pd.to_numeric(dataset[column], errors="coerce")

        predictive_dataset = build_predictive_target(dataset)
        predictive_dataset = add_features(predictive_dataset)
        predictive_dataset.to_csv(output_path, index=False)

        original_failure_rows = int(pd.to_numeric(dataset["failure"], errors="coerce").fillna(0).sum())
        predictive_positive_rows = int(predictive_dataset["failure_within_30_days"].sum())
        predictive_negative_rows = int(
            len(predictive_dataset) - predictive_positive_rows
        )
        failed_drive_count = int(
            predictive_dataset["days_to_failure"].notna().groupby(predictive_dataset["serial_number"]).any().sum()
        )

        print(f"Found CSV files: {len(csv_files)}")
        print(f"Processed rows: {processed_rows}")
        print(f"Output rows: {len(predictive_dataset)}")
        print(f"Original failure rows: {original_failure_rows}")
        print(
            "Predictive positive rows failure_within_30_days=1: "
            f"{predictive_positive_rows}"
        )
        print(f"Predictive negative rows: {predictive_negative_rows}")
        print(f"Number of failed drives: {failed_drive_count}")
        print(f"Saved dataset path: {output_path}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


if __name__ == "__main__":
    main()
