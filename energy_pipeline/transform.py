"""Join the clean power and weather tables into one hourly table."""

import pandas as pd

from . import config
from .clean import POWER_COLS


def build_hourly_table(power: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    df = power.merge(weather, on="timestamp_utc", how="left", validate="one_to_one")

    keys = [s.key for s in config.STATIONS if f"wind_speed_100m_ms_{s.key}" in df]
    df["wind_speed_100m_ms_mean"] = df[[f"wind_speed_100m_ms_{k}" for k in keys]].mean(axis=1)
    df["temperature_c_mean"] = df[[f"temperature_c_{k}" for k in keys]].mean(axis=1)
    df["wind_share_of_load"] = df["wind_generation_mw"] / df["load_mw"]

    gap_cols = [c for c in df if c.endswith("_is_gap") or "_is_gap_" in c]
    error_cols = [c for c in df if "_unit_error" in c]
    core = POWER_COLS + ["wind_speed_100m_ms_mean", "temperature_c_mean"]
    # had_gap: something was missing in the raw data this hour (maybe filled since).
    df["had_gap"] = df[gap_cols].any(axis=1)
    # quality_ok: every core value is present and none failed a unit check.
    df["quality_ok"] = df[core].notna().all(axis=1) & ~df[error_cols].any(axis=1)
    return df


# Column order for the final table: the values first, then quality flags.
def ordered_columns(df: pd.DataFrame) -> list:
    first = ["timestamp_utc", *POWER_COLS, "wind_share_of_load",
             "wind_speed_100m_ms_mean", "temperature_c_mean"]
    weather = sorted(c for c in df if c.startswith(("wind_speed_100m_ms_", "temperature_c_"))
                     and c not in first and not any(f in c for f in ("_is_gap", "_filled", "_unit_error")))
    flags = ["had_gap", "quality_ok"]
    rest = [c for c in df if c not in first + weather + flags]
    return first + weather + flags + rest
