"""Write the hourly table and the data-quality report into DuckDB, then create views."""

from pathlib import Path

import duckdb
import pandas as pd

SQL_DIR = Path(__file__).parent / "sql"


def load_to_duckdb(hourly: pd.DataFrame, quality: pd.DataFrame, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    hourly = hourly.copy()
    # DuckDB stores plain timestamps; we store UTC wall-clock time and say so in the name.
    hourly["timestamp_utc"] = hourly["timestamp_utc"].dt.tz_convert("UTC").dt.tz_localize(None)
    with duckdb.connect(str(db_path)) as con:
        con.register("hourly_df", hourly)
        con.register("quality_df", quality)
        con.execute("CREATE OR REPLACE TABLE hourly AS SELECT * FROM hourly_df ORDER BY timestamp_utc")
        con.execute("CREATE OR REPLACE TABLE data_quality AS SELECT * FROM quality_df")
        con.execute((SQL_DIR / "views.sql").read_text())
