import numpy as np
import pandas as pd

from energy_pipeline.clean import clean_power, fill_short_gaps, gap_report, reindex_hourly
from conftest import END, START


def test_reindex_reveals_missing_hours():
    ts = pd.to_datetime(["2020-01-01 00:00", "2020-01-01 03:00"], utc=True)
    df = pd.DataFrame({"timestamp_utc": ts, "x": [1.0, 4.0]})
    full = reindex_hourly(df, ts[0], ts[1])
    assert len(full) == 4
    assert full.x.isna().sum() == 2


def test_gap_report_on_fixture(opsd_raw):
    _, stats = clean_power(opsd_raw, START, END)
    load = stats["gaps"].set_index("column").loc["load_mw"]
    assert load.total_hours == 72
    assert load.missing_hours == 7      # 2 + 5 hours removed in the fixture
    assert load.n_gaps == 2
    assert load.longest_gap_hours == 5


def test_short_gaps_filled_long_gaps_kept():
    df = pd.DataFrame({"x": [1.0, np.nan, np.nan, 4.0, np.nan, np.nan, np.nan, 8.0]})
    out = fill_short_gaps(df, ["x"], max_hours=2)
    assert out.x.iloc[1:3].tolist() == [2.0, 3.0]          # 2-hour gap: interpolated
    assert out.x.iloc[4:7].isna().all()                     # 3-hour gap: left empty
    assert out.x_filled.sum() == 2
    assert out.x_is_gap.sum() == 5


def test_dwd_missing_marker_becomes_nan(weather_raw):
    # One -999 value was put in the DWD wind fixture.
    assert weather_raw.wind_speed_100m_ms.isna().sum() == 1
