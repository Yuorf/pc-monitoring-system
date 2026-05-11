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

OUTPUT_COLUMNS = REQUIRED_COLUMNS + [
    "power_on_years",
    "has_reallocated",
    "has_pending",
    "has_uncorrectable",
    "has_reported_uncorrectable",
    "has_crc_errors",
]

CHUNK_SIZE = 50_000


def find_csv_files(base_dir: Path) -> list[Path]:
    return sorted(path for path in base_dir.rglob("*.csv") if path.is_file())


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


def prepare_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    prepared = dataframe.copy()

    for column in REQUIRED_COLUMNS:
        if column not in prepared.columns:
            prepared[column] = np.nan

    for column in NUMERIC_COLUMNS:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    prepared = prepared.dropna(subset=["failure"]).copy()
    prepared["failure"] = prepared["failure"].astype(int)

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
    output_path = ml_dir / "data" / "processed" / "backblaze_smart_dataset.csv"

    csv_files = find_csv_files(raw_dir)
    found_columns_global: set[str] = set()
    processed_rows = 0
    output_rows = 0
    failure_rows = 0
    wrote_output = False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    for csv_file in csv_files:
        try:
            chunk_iterator, found_columns = read_required_columns(csv_file, REQUIRED_COLUMNS)
        except Exception as error:
            print(f"Skipping {csv_file}: {error}")
            continue

        found_columns_global.update(found_columns)

        for chunk in chunk_iterator:
            processed_rows += len(chunk)
            prepared_chunk = prepare_dataframe(chunk)
            if prepared_chunk.empty:
                continue

            output_rows += len(prepared_chunk)
            failure_rows += int(prepared_chunk["failure"].sum())
            prepared_chunk.to_csv(
                output_path,
                mode="a",
                index=False,
                header=not wrote_output,
            )
            wrote_output = True

    if not wrote_output:
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)

    print(f"Found CSV files: {len(csv_files)}")
    print(f"Processed rows: {processed_rows}")
    print(f"Rows in final dataset: {output_rows}")
    print(f"Failure rows (failure=1): {failure_rows}")
    print(f"Found columns: {sorted(found_columns_global)}")
    print(f"Saved dataset: {output_path}")


if __name__ == "__main__":
    main()
