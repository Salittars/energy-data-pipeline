import pandas as pd

from energy_pipeline.clean import check_timezone_consistency, clean_power, parse_utc
from conftest import END, START


def test_mixed_offsets_become_consecutive_utc_hours():
    # Around the switch to summer time, local clocks jump from 02:00 to 03:00.
    local = pd.Series(["2019-03-31T01:00:00+0100", "2019-03-31T03:00:00+0200"])
    utc = parse_utc(local)
    assert str(utc.dt.tz) == "UTC"
    assert utc.iloc[1] - utc.iloc[0] == pd.Timedelta(hours=1)


def test_opsd_utc_and_local_columns_agree(opsd_raw):
    assert check_timezone_consistency(opsd_raw) == 0


def test_clean_index_is_continuous_utc_across_dst(opsd_raw):
    df, _ = clean_power(opsd_raw, START, END)
    assert str(df.timestamp_utc.dt.tz) == "UTC"
    assert (df.timestamp_utc.diff().dropna() == pd.Timedelta(hours=1)).all()
    # The local day of 31 March 2019 only had 23 hours; in UTC every day has 24.
    local_day = df.timestamp_utc.dt.tz_convert("Europe/Berlin").dt.date
    assert (local_day == pd.Timestamp("2019-03-31").date()).sum() == 23
