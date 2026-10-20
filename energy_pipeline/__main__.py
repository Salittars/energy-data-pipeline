"""Command line: python -m energy_pipeline build | summary"""

import argparse
import json
import os
from pathlib import Path

import duckdb

from . import config, pipeline


def main(argv=None) -> None:
    config.load_dotenv()
    parser = argparse.ArgumentParser(prog="energy_pipeline")
    parser.add_argument("command", choices=["build", "summary"])
    parser.add_argument("--start", default=config.START_DATE)
    parser.add_argument("--end", default=config.END_DATE)
    parser.add_argument("--data-dir", default=os.environ.get("ENERGY_DATA_DIR", "data"))
    parser.add_argument("--weather-source", choices=["auto", "open-meteo", "dwd"],
                        default=os.environ.get("ENERGY_WEATHER_SOURCE", "auto"))
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.command == "build":
        s = pipeline.run(data_dir, args.start, args.end, args.weather_source)
        print(f"Built {s['rows']:,} hourly rows ({s['start_utc']} -> {s['end_utc']}) "
              f"in {s['total_seconds']}s")
        print(f"Weather source: {', '.join(s['weather_sources'])}")
        for note in s["notes"]:
            print(f"  note: {note}")
        print(f"Hours with any gap: {s['pct_hours_with_any_gap']}% | "
              f"quality_ok: {s['pct_hours_quality_ok']}% | duplicates dropped: {s['duplicates_dropped']}")
        print(f"DuckDB: {s['db_path']}  (summary in {data_dir / 'run_summary.json'})")

    elif args.command == "summary":
        with duckdb.connect(str(data_dir / "energy.duckdb"), read_only=True) as con:
            print(con.sql("SELECT * FROM data_quality"))
            print(con.sql("SELECT * FROM price_by_wind_decile"))
            print(con.sql("SELECT * FROM monthly_summary"))
        print(json.dumps({k: v for k, v in json.loads(
            (data_dir / "run_summary.json").read_text()).items() if k != "gap_report"}, indent=2))


if __name__ == "__main__":
    main()
