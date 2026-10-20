"""The whole pipeline: download -> clean -> join -> load. Returns a run summary."""

import json
import time
from pathlib import Path

import pandas as pd

from . import config, download
from .clean import POWER_COLS, clean_power, clean_weather
from .load import load_to_duckdb
from .transform import build_hourly_table, ordered_columns


def run(data_dir: Path, start: str = config.START_DATE, end: str = config.END_DATE,
        weather_source: str = "auto", opsd_path: Path = None, weather_raw: pd.DataFrame = None) -> dict:
    """opsd_path / weather_raw let tests run the full pipeline offline on fixtures."""
    t0 = time.perf_counter()
    data_dir = Path(data_dir)
    raw_dir = data_dir / "raw"
    notes = []

    # 1. Extract
    opsd_path = opsd_path or download.fetch_opsd(raw_dir)
    power_raw = download.read_opsd(opsd_path)
    if weather_raw is None:
        weather_raw, notes = download.fetch_weather(start, end, raw_dir, weather_source)
    t_download = time.perf_counter() - t0

    # 2. Clean
    power, power_stats = clean_power(power_raw, start, end)
    weather, weather_stats = clean_weather(weather_raw, start, end)

    # 3. Join
    hourly = build_hourly_table(power, weather)
    hourly = hourly[ordered_columns(hourly)]
    quality = pd.concat([power_stats["gaps"], weather_stats["gaps"]], ignore_index=True)

    # 4. Load
    db_path = data_dir / "energy.duckdb"
    load_to_duckdb(hourly, quality, db_path)

    summary = {
        "rows": len(hourly),
        "columns": hourly.shape[1],
        "start_utc": str(hourly.timestamp_utc.min()),
        "end_utc": str(hourly.timestamp_utc.max()),
        "weather_sources": sorted(weather_raw["source"].unique().tolist()),
        "notes": notes,
        "power_raw_rows_in_range": int(power_stats["gaps"]["total_hours"].iloc[0]),
        "tz_mismatches_utc_vs_local": power_stats["tz_mismatches"],
        "duplicates_dropped": power_stats["duplicates_dropped"] + weather_stats["duplicates_dropped"],
        "unit_errors": {**power_stats["unit_errors"], **weather_stats["unit_errors"]},
        "pct_hours_with_any_gap": round(100 * hourly["had_gap"].mean(), 2),
        "pct_hours_quality_ok": round(100 * hourly["quality_ok"].mean(), 2),
        "values_filled": int(hourly[[c for c in hourly if "_filled" in c]].sum().sum()),
        "outlier_flags": {c: int(hourly[f"{c}_outlier"].sum()) for c in POWER_COLS},
        "gap_report": quality.to_dict(orient="records"),
        "db_path": str(db_path),
        "download_seconds": round(t_download, 1),
        "total_seconds": round(time.perf_counter() - t0, 1),
    }
    (data_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
