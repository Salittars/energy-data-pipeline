import json

import duckdb

from energy_pipeline import download, pipeline
from conftest import END, FIXTURES, START

EXPECTED_TYPES = {
    "timestamp_utc": "TIMESTAMP",
    "wind_generation_mw": "DOUBLE",
    "load_mw": "DOUBLE",
    "price_eur_mwh": "DOUBLE",
    "wind_speed_100m_ms_mean": "DOUBLE",
    "temperature_c_mean": "DOUBLE",
    "wind_speed_100m_ms_hamburg": "DOUBLE",
    "had_gap": "BOOLEAN",
    "quality_ok": "BOOLEAN",
}


def test_full_pipeline_offline(tmp_path, weather_raw):
    summary = pipeline.run(tmp_path, START, END, opsd_path=FIXTURES / "opsd_sample.csv",
                           weather_raw=weather_raw)
    assert summary["rows"] == 72
    assert summary["duplicates_dropped"] == 1

    with duckdb.connect(str(tmp_path / "energy.duckdb"), read_only=True) as con:
        types = dict(con.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'hourly'"
        ).fetchall())
        for col, dtype in EXPECTED_TYPES.items():
            assert types.get(col) == dtype, col

        n, n_unique, first = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT timestamp_utc), MIN(timestamp_utc) FROM hourly").fetchone()
        assert n == n_unique == 72
        assert str(first) == "2019-03-30 00:00:00"

        assert con.execute("SELECT COUNT(*) FROM daily_summary").fetchone()[0] == 3
        assert con.execute("SELECT SUM(hours) FROM daily_summary").fetchone()[0] == 72
        assert con.execute("SELECT COUNT(*) FROM price_by_wind_decile").fetchone()[0] == 10

    saved = json.loads((tmp_path / "run_summary.json").read_text())
    assert saved["rows"] == 72


def test_open_meteo_parser_schema():
    payload = json.loads((FIXTURES / "open_meteo_sample.json").read_text())
    df = download.parse_open_meteo(payload, "hamburg")
    assert list(df.columns) == ["timestamp_utc", "station", "wind_speed_100m_ms", "temperature_c", "source"]
    assert str(df.timestamp_utc.dt.tz) == "UTC"
    assert len(df) == 3
