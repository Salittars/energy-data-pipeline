# energy-data-pipeline

**Proves:** "Collect, clean, and structure large datasets from market, fundamental, and operational sources" using "Pandas, NumPy, and SQL"

A one-command pipeline that turns two years of public German power-market data (wind output, load, day-ahead price) and weather observations into one clean, quality-flagged hourly table in DuckDB, for an energy analyst or trader who needs data they can trust before modelling.

## Demo

Run `make build` then `make summary` to reproduce the table below (a screen recording will be added here).

## How it works

- **Input:** Open Power System Data hourly file (Germany wind generation, load, DE-LU day-ahead price) + hourly weather (wind speed at 100 m, temperature) for Hamburg, Berlin, Frankfurt and Munich. Weather comes from the Open-Meteo archive API, with an automatic fallback to German Weather Service (DWD) station data.
- **Timestamps:** every timestamp is parsed to UTC, the UTC and local (CET/CEST) columns are cross-checked, and the data is put on a complete hourly grid so missing hours become visible instead of silently skipped.
- **Cleaning:** duplicate hours are dropped, values outside physical limits are nulled and flagged (e.g. price outside the -500/+3000 EUR/MWh exchange limits), a MW-vs-GW scale check runs, gaps of up to 2 hours are interpolated and flagged, and price/load/wind spikes get a robust rolling z-score flag (flagged, never deleted).
- **Join:** power and weather are joined one-to-one on `timestamp_utc`, with station averages, wind share of load and two summary flags (`had_gap`, `quality_ok`).
- **Output:** `data/energy.duckdb` with tables `hourly` and `data_quality`, plus SQL views `daily_summary`, `monthly_summary` and `price_by_wind_decile`; a `data/run_summary.json` with the numbers below.

## Results

From the real run in this repo (Oct 2026, period 2018-10-01 00:00 to 2020-09-30 23:00 UTC):

| Metric | Value |
|---|---|
| Hourly rows in final table | 17,544 (2 full years, no missing timestamps) |
| Columns | 57 (values + per-column quality flags) |
| Hours with any gap in any source | 108 (0.62%) |
| Price gaps | 5 hours (0.03%) in 3 gaps, longest 2 h; 4 filled by interpolation |
| Worst weather gap | Berlin wind: 69 h missing (0.39%), longest run 37 h |
| Duplicates / UTC-vs-local mismatches / unit errors | 0 / 0 / 0 |
| Hours fully usable (`quality_ok`) | 99.99% (17,543 of 17,544) |
| Price hours flagged as spikes | 96 (88 of them negative-price hours); 484 negative-price hours in total |
| Run time | 49 s first run including downloads (~145 MB), 13 s re-run from cache |

What the data shows (from the `price_by_wind_decile` view): in the 10% windiest hours (30.7-46.1 GW of wind) the average day-ahead price was **19.41 EUR/MWh**, against **42.30 EUR/MWh** in the 10% calmest hours. That is the merit-order effect, visible straight from the cleaned table. Station wind speed correlates 0.73 with national wind output.

A finding from the gap report: the only mid-series price gaps sit on the two spring daylight-saving days (2019-03-31 and 2020-03-29, 02:00-03:00 UTC). The source lost those hours while converting local exchange time, which is exactly why this pipeline works in UTC and checks the grid.

**What failed at first:** the Open-Meteo archive API returned `Daily API request limit exceeded` for every weather point, so the first build had no weather. I added a fallback: `--weather-source auto` now tries Open-Meteo and, on failure, downloads DWD hourly station observations for the same four cities, converts their 10 m wind to an estimated 100 m wind with the wind power law (alpha = 1/7), and records which source each column came from (`source_<city>` column and a note in `run_summary.json`). The numbers above use the DWD fallback.

## Run it

```bash
git clone <this repo> && cd energy-data-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m energy_pipeline build          # or: make build
python -m energy_pipeline summary        # prints the quality report and SQL views
python -m pytest -q                      # 14 offline tests on small fixtures, or: make test
```

Options: `--start 2019-01-01 --end 2019-12-31`, `--weather-source auto|open-meteo|dwd`, `--data-dir data`. The same settings can go in a `.env` file (see `.env.example`). Query the result with DuckDB:

```sql
SELECT * FROM daily_summary WHERE negative_price_hours > 0 ORDER BY avg_price_eur_mwh LIMIT 10;
```

## What I'd do next

- Switch the power data to the ENTSO-E Transparency API so it runs up to yesterday (OPSD stops at September 2020) and add gas prices (TTF) and cross-border flows, which matter just as much for European power prices.
- Replace the 4-city weather average with capacity-weighted wind at the locations of German wind farms, and use it to build a first day-ahead wind-output forecast on top of this table.
