"""Cleaning steps. Each function does one job and can be tested on its own."""

import numpy as np
import pandas as pd

from . import config


# ---------- Timestamps ----------

def parse_utc(values: pd.Series) -> pd.Series:
    """Parse timestamps with any UTC offset ('Z', '+0100', '+0200') into UTC."""
    return pd.to_datetime(values, utc=True)


def check_timezone_consistency(df: pd.DataFrame) -> int:
    """OPSD ships a UTC and a local (CET/CEST) column. Count rows where they disagree."""
    utc = parse_utc(df["utc_timestamp"])
    local = parse_utc(df["cet_cest_timestamp"])
    return int((utc != local).sum())


# ---------- Duplicates and gaps ----------

def drop_duplicate_timestamps(df: pd.DataFrame, ts_col: str = "timestamp_utc"):
    """Keep the first row for each timestamp. Returns (clean_df, number_dropped)."""
    dupes = df.duplicated(subset=ts_col, keep="first")
    return df[~dupes].sort_values(ts_col).reset_index(drop=True), int(dupes.sum())


def reindex_hourly(df: pd.DataFrame, start, end, ts_col: str = "timestamp_utc") -> pd.DataFrame:
    """Put the data on a complete hourly UTC grid. Missing hours become NaN rows."""
    full = pd.date_range(start, end, freq="h", tz="UTC", name=ts_col)
    return df.set_index(ts_col).reindex(full).reset_index()


def _run_lengths(is_missing: pd.Series) -> pd.Series:
    """For each missing value, the length of the missing run it belongs to (0 if present)."""
    run_id = (is_missing != is_missing.shift()).cumsum()
    lengths = is_missing.groupby(run_id).transform("sum")
    return lengths.where(is_missing, 0)


def gap_report(df: pd.DataFrame, cols) -> pd.DataFrame:
    """One row per column: missing hours, % missing, number of gaps, longest gap."""
    rows = []
    for col in cols:
        missing = df[col].isna()
        run_id = (missing != missing.shift()).cumsum()
        runs = missing.groupby(run_id).sum()
        runs = runs[runs > 0]
        rows.append({
            "column": col,
            "total_hours": len(df),
            "missing_hours": int(missing.sum()),
            "pct_missing": round(100 * missing.mean(), 3),
            "n_gaps": int(len(runs)),
            "longest_gap_hours": int(runs.max()) if len(runs) else 0,
        })
    return pd.DataFrame(rows)


def fill_short_gaps(df: pd.DataFrame, cols, max_hours: int = config.MAX_FILL_HOURS) -> pd.DataFrame:
    """Linearly interpolate gaps of up to max_hours. Longer gaps stay NaN.
    Adds <col>_is_gap (originally missing) and <col>_filled (we filled it)."""
    df = df.copy()
    for col in cols:
        missing = df[col].isna()
        short = missing & (_run_lengths(missing) <= max_hours)
        interpolated = df[col].interpolate(method="linear", limit_area="inside")
        df[f"{col}_is_gap"] = missing
        df[f"{col}_filled"] = short & interpolated.notna()
        df.loc[df[f"{col}_filled"], col] = interpolated[df[f"{col}_filled"]]
    return df


# ---------- Units and outliers ----------

def assert_plausible_scale(df: pd.DataFrame) -> None:
    """Catch unit mix-ups early, e.g. a source switching from MW to GW."""
    median_load = df["load_mw"].median()
    if median_load < 1_000:
        raise ValueError(f"load_mw median is {median_load:.1f}: looks like GW, expected MW")
    if df["price_eur_mwh"].abs().median() > 1_000:
        raise ValueError("price_eur_mwh looks like EUR/GWh or cents, expected EUR/MWh")


def apply_bounds(df: pd.DataFrame, bounds=None):
    """Values outside physical limits are set to NaN and flagged.
    Returns (df, {column: number_of_bad_values})."""
    bounds = bounds or config.BOUNDS
    df = df.copy()
    counts = {}
    for col, (lo, hi) in bounds.items():
        if col not in df:
            continue
        bad = df[col].notna() & ~df[col].between(lo, hi)
        df[f"{col}_unit_error"] = bad
        df.loc[bad, col] = np.nan
        counts[col] = int(bad.sum())
    return df, counts


def flag_outliers(df: pd.DataFrame, cols, window: int = config.OUTLIER_WINDOW_HOURS,
                  z: float = config.OUTLIER_Z) -> pd.DataFrame:
    """Flag values far from the rolling median, measured in robust (MAD) units.
    We only flag: a price spike can be real and is exactly what traders care about."""
    df = df.copy()
    for col in cols:
        series = df[col]
        median = series.rolling(window, center=True, min_periods=window // 4).median()
        mad = (series - median).abs().rolling(window, center=True, min_periods=window // 4).median()
        robust_z = (series - median) / (1.4826 * mad.replace(0, np.nan))
        df[f"{col}_outlier"] = robust_z.abs() > z
    return df


# ---------- Source-level cleaning ----------

POWER_COLS = list(config.OPSD_COLUMNS.values())
WEATHER_COLS = ["wind_speed_100m_ms", "temperature_c"]


def clean_power(raw: pd.DataFrame, start: str, end: str):
    """OPSD raw -> clean hourly power table. Returns (df, stats)."""
    stats = {"tz_mismatches": check_timezone_consistency(raw)}
    df = raw.drop(columns=["cet_cest_timestamp"]).rename(columns={"utc_timestamp": "timestamp_utc"})
    df["timestamp_utc"] = parse_utc(df["timestamp_utc"])
    lo, hi = _utc_bounds(start, end)
    df = df[df.timestamp_utc.between(lo, hi)]
    df, stats["duplicates_dropped"] = drop_duplicate_timestamps(df)
    df = reindex_hourly(df, lo, hi)
    assert_plausible_scale(df)
    df, stats["unit_errors"] = apply_bounds(df)
    stats["gaps"] = gap_report(df, POWER_COLS)
    df = fill_short_gaps(df, POWER_COLS)
    df = flag_outliers(df, POWER_COLS)
    return df, stats


def clean_weather(raw_long: pd.DataFrame, start: str, end: str):
    """Long weather table (one row per station-hour) -> wide hourly table."""
    lo, hi = _utc_bounds(start, end)
    stats = {"duplicates_dropped": 0, "unit_errors": {}, "gaps": []}
    wide = None
    for station, part in raw_long.groupby("station", sort=False):
        part = part.drop(columns=["station"])
        part, n_dupes = drop_duplicate_timestamps(part)
        stats["duplicates_dropped"] += n_dupes
        part = reindex_hourly(part, lo, hi)
        part, errors = apply_bounds(part)
        for col, n in errors.items():
            stats["unit_errors"][f"{col}_{station}"] = n
        gaps = gap_report(part, WEATHER_COLS)
        gaps["column"] = gaps["column"] + "_" + station
        stats["gaps"].append(gaps)
        part = fill_short_gaps(part, WEATHER_COLS)
        part["source"] = part["source"].ffill().bfill()
        part = part.set_index("timestamp_utc").add_suffix(f"_{station}")
        wide = part if wide is None else wide.join(part)
    stats["gaps"] = pd.concat(stats["gaps"], ignore_index=True)
    return wide.reset_index(), stats


def _utc_bounds(start: str, end: str):
    return pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=23)
