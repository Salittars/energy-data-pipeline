import pandas as pd

from energy_pipeline.clean import clean_power, drop_duplicate_timestamps
from conftest import END, START


def test_drop_duplicates_keeps_first():
    ts = pd.to_datetime(["2020-01-01 00:00", "2020-01-01 00:00", "2020-01-01 01:00"], utc=True)
    df = pd.DataFrame({"timestamp_utc": ts, "value": [1.0, 99.0, 2.0]})
    clean, n = drop_duplicate_timestamps(df)
    assert n == 1
    assert clean.value.tolist() == [1.0, 2.0]


def test_fixture_duplicate_is_removed(opsd_raw):
    df, stats = clean_power(opsd_raw, START, END)
    assert stats["duplicates_dropped"] == 1
    assert df.timestamp_utc.is_unique
