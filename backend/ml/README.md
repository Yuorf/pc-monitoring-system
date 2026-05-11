# ML Workspace

Backblaze ZIP and extracted CSV files should be placed under `backend/ml/data/raw/backblaze/`.
You can keep quarterly folders there, for example `2024_Q1/`, `2024_Q2/`, `2024_Q3/`, `2024_Q4/`.

Recommended flow:

1. Download Backblaze datasets as ZIP archives.
2. Extract the CSV files into `backend/ml/data/raw/backblaze/` or its subfolders.
3. From the `backend/` directory run:

```bash
python ml/scripts/prepare_backblaze_dataset.py
```

The prepared dataset will be saved to `backend/ml/data/processed/backblaze_smart_dataset.csv`.

Raw Backblaze data should not be committed to git. The repository `.gitignore` already excludes the raw and processed ML data folders.
