# LEARN.md - how this project works, in plain language

This file is for you, Salma, so you can explain and defend every part of the project in an interview.

---

## 1. The story in one minute

Energy traders bet on tomorrow's power price. The price depends on **fundamentals**: how much electricity people need (load), how much wind and sun there will be, gas prices, and so on. Before anyone can model any of this, someone has to **collect** the data from different sources, **clean** it (wrong times, missing hours, duplicates, wrong units) and **structure** it into one table that everyone can trust. That is what this project does, for Germany, for two years (Oct 2018 - Sep 2020), hour by hour.

**Sources:**
- **Market data**: day-ahead price for the DE-LU (Germany-Luxembourg) bidding zone, in EUR/MWh.
- **Operational / fundamental data**: actual German wind generation (MW) and actual load (MW), published by the grid operators via ENTSO-E and repackaged by Open Power System Data (OPSD).
- **Weather (fundamental)**: wind speed and temperature for 4 cities. Planned source: Open-Meteo. In the real run, Open-Meteo refused requests (daily limit reached), so the pipeline switched to the German Weather Service (DWD) station data on its own.

**Result:** 17,544 rows (= 731 days x 24 hours), one per hour, in a DuckDB database with SQL views on top.

---

## 2. Every file, explained

| File | What it is for |
|---|---|
| `energy_pipeline/__init__.py` | Makes the folder a Python *package* (something you can `import`). Holds the version number. |
| `energy_pipeline/__main__.py` | The command line. `python -m energy_pipeline build` runs this file. It reads options (`--start`, `--end`, `--weather-source`, `--data-dir`) with `argparse` and calls the pipeline. `summary` prints the results from the database. |
| `energy_pipeline/config.py` | All settings in one place: dates, URLs, the 4 weather stations, physical limits for each column, gap-filling and outlier settings. Changing behaviour means editing one file. Also a tiny `.env` reader. |
| `energy_pipeline/download.py` | **Extract**. Downloads files and caches them in `data/raw/` so a re-run does not download again. Reads OPSD (only the 3 German columns we need, via `usecols`), Open-Meteo JSON, and DWD zip files. `fetch_weather` tries Open-Meteo and falls back to DWD. |
| `energy_pipeline/clean.py` | **Transform / clean**. Small functions, each doing one job: parse to UTC, check UTC vs local time, drop duplicates, rebuild the full hourly grid, report gaps, fill short gaps, check units and limits, flag outliers. Then `clean_power` and `clean_weather` call them in order. |
| `energy_pipeline/transform.py` | **Join**. Merges power and weather on `timestamp_utc`, adds the 4-city averages, wind share of load, and two summary flags: `had_gap` and `quality_ok`. |
| `energy_pipeline/load.py` | **Load**. Writes the table into DuckDB (`data/energy.duckdb`) and runs `views.sql`. |
| `energy_pipeline/sql/views.sql` | Three SQL views: `daily_summary`, `monthly_summary`, `price_by_wind_decile`. A *view* is a saved query: it does not copy data, it recalculates when you query it. |
| `energy_pipeline/pipeline.py` | Runs the 4 steps in order (extract, clean, join, load), times them, and writes `data/run_summary.json` with all the numbers in the README. |
| `tests/conftest.py` | Shared test setup: loads the fixture files so every test can use them. |
| `tests/test_*.py` | 14 tests (see section 4). |
| `tests/fixtures/` | Tiny data samples (72 hours) so tests run **offline** in under a second. Real data, with defects injected on purpose (a duplicate row, a 2-hour gap, a 5-hour gap, a `-999` value). Its README says exactly what was changed. |
| `pytest.ini` | Tells pytest where tests are and lets tests import the package. |
| `requirements.txt` | The libraries to install: pandas, numpy, duckdb, requests, pytest. |
| `Makefile` | Shortcuts: `make build`, `make summary`, `make test`. |
| `.gitignore` | Files git must not save: `data/` (big downloads) and `*.duckdb` (generated). Rule: commit code, not data. |
| `.env.example` | Example optional settings. You copy it to `.env`; `.env` itself is never committed (it could hold secrets later). |
| `LICENSE` | MIT: anyone may use the code if they keep the copyright notice. |
| `README.md` | The project's shop window for recruiters. |

---

## 3. The concepts, one by one

**ETL (Extract, Transform, Load).** The classic shape of a data pipeline. Extract = download. Transform = clean and join. Load = put into a database. This repo follows it exactly, one file per step.

**UTC.** Universal time, with no daylight saving. Germany uses CET in winter (UTC+1) and CEST in summer (UTC+2). On the last Sunday of March, the local clock jumps from 02:00 to 03:00, so that local day has **23 hours**; in October it has **25**. If you store local time, you get a missing hour in spring and a duplicate hour in autumn. In UTC, every day has 24 hours. That is why everything is stored in UTC, and why the column is called `timestamp_utc` (the name tells the reader the timezone). One test checks exactly this: the local day of 31 March 2019 has 23 hours, but the UTC index has no hole.

**Timezone cross-check.** OPSD gives two columns: `utc_timestamp` and `cet_cest_timestamp`. Parsed correctly they are the same moment. The pipeline counts disagreements (result: 0). Cheap check, catches a broken source.

**Duplicates.** The same hour appearing twice (it happens with re-published data or DST mistakes). We keep the first and count how many were dropped. Real data: 0. Fixture: 1 (injected), and the test checks it is removed.

**Gap detection by reindexing.** If a row is simply absent, `isna()` cannot see it. So we build the complete list of hours from start to end (`pd.date_range`) and `reindex` the data onto it. Missing hours appear as empty rows, which we can count. `gap_report` gives, per column: missing hours, % missing, number of gaps, longest gap.

**Short-gap filling.** Gaps of 1-2 hours are filled by **linear interpolation** (a straight line between the hour before and after). Longer gaps are left empty, because inventing 37 hours of wind is worse than admitting we do not know. Every filled value is flagged in a `_filled` column, and every originally missing value in an `_is_gap` column. Rule: never change data silently.

**Unit checks.** Two kinds:
1. *Scale check*: if median German load is below 1,000, the data is probably in GW, not MW. The pipeline stops with an error instead of producing nonsense.
2. *Physical limits*: wind output 0-65,000 MW (Germany had ~62 GW installed), load 20,000-100,000 MW, price -500 to +3,000 EUR/MWh (the exchange's limits then), wind speed 0-60 m/s, temperature -35 to 45 C. Values outside become empty and flagged (`_unit_error`). Real data: 0 errors.

**Negative prices are not errors.** When it is very windy and demand is low, producers pay to keep running. Germany had 484 negative-price hours in this period. That is why the limit is -500, not 0.

**Outlier flags with a robust z-score.** For each hour, compare the value with the median of the surrounding week, and divide by the MAD (median absolute deviation, a "typical distance" that is not distorted by spikes like a standard deviation is). Above 6 = flagged. We use the median, not the mean, because one huge spike would pull the mean towards itself and hide. We **flag, never delete**: a price spike is often the most interesting hour for a trader. Real data: 96 price hours flagged, 88 of them negative-price hours.

**Wind at 100 m from 10 m.** Weather stations measure wind at about 10 m; turbines sit around 100 m, where it is windier. The **wind power law** estimates it: `v100 = v10 x (100/10)^(1/7)`, about x1.39. Alpha = 1/7 is the textbook value for open land; the real value changes with terrain and weather, so this is an estimate and the column `source_<city>` says so (`dwd-10m-extrapolated`).

**The join.** Power and weather are merged on `timestamp_utc` with `validate="one_to_one"`: pandas raises an error if any hour appears twice on either side. That turns a silent bug (rows doubling) into a loud one.

**`had_gap` vs `quality_ok`.** `had_gap` = something was missing in the raw data this hour (even if we filled it). `quality_ok` = all key values are present now and none failed a unit check. Analysts filter on `quality_ok`; the price-by-wind view does.

**DuckDB.** A database that lives in one file, with no server to install, very fast for analysis (columnar). Ideal for a portfolio project; the SQL is standard, so it moves easily to Postgres or Snowflake. Timestamps are stored without timezone, as UTC, which the column name states.

**SQL views.**
- `daily_summary`: per day, average/min/max price, negative-price hours, wind and load in GWh, wind share, average wind speed and temperature, hours with gaps.
- `monthly_summary`: the same at month level.
- `price_by_wind_decile`: sorts all good hours by wind output, splits them into 10 equal groups with `NTILE(10)` (a *window function*), and gives the average price of each group. Result: 42.30 EUR/MWh in the calmest 10% vs 19.41 EUR/MWh in the windiest 10%.

**Merit-order effect.** Power plants are called in order of cost: wind and solar first (fuel is free), then coal, then gas. The price is set by the last, most expensive plant needed. More wind pushes expensive plants out, so the price drops. The decile view shows this directly. This is the sentence that makes the project relevant for a trading desk.

**Caching.** Downloads are saved in `data/raw/`; a re-run skips them (49 s first run, 13 s re-run).

**Fallback source.** If Open-Meteo fails, the pipeline uses DWD automatically and writes a note. In real jobs, sources fail all the time; a pipeline must degrade gracefully and say what it did.

**Tests and fixtures.** A *test* is code that checks your code. A *fixture* is small, fixed test data. Tests run offline (no internet needed), so anyone (or a CI server) can run them in a second. They were also run with the internet blocked to prove it.

**Git commits in small steps.** Each commit is one logical change (skeleton, downloaders, cleaning, join/load, CLI, fixtures, tests, README). A reviewer can read the history like a story.

---

## 4. What the 14 tests check

| Test file | Checks |
|---|---|
| `test_timezone.py` | Mixed offsets (`+0100`, `+0200`) become consecutive UTC hours; OPSD UTC and local columns agree; the clean index is continuous across the DST switch, and the local day has 23 hours. |
| `test_duplicates.py` | The first copy is kept; the injected duplicate in the fixture is removed and counted. |
| `test_gaps.py` | Reindexing reveals missing hours; the gap report finds 7 missing hours in 2 gaps, longest 5; 2-hour gaps get filled, 3-hour gaps do not; DWD `-999` becomes empty. |
| `test_units.py` | Out-of-range prices become empty and flagged, negative prices are kept; load in GW is rejected; a spike is flagged but not removed. |
| `test_schema.py` | The whole pipeline runs offline on fixtures; the DuckDB table has the expected columns and types; timestamps are unique and start at the right hour; the views return 3 days / 72 hours / 10 deciles; the Open-Meteo parser outputs the right columns in UTC. |

---

## 5. Honest limits (say them before they ask)

- OPSD stops at 30 September 2020, so the data is not recent. Next step: ENTSO-E Transparency API directly.
- The weather in the real run is DWD 10 m wind extrapolated to 100 m, not Open-Meteo modelled 100 m wind. The code supports both; the source is recorded in the data.
- 4 cities is a rough proxy. Most German wind capacity is in the north; a capacity-weighted average would be better.
- The 4-city average ignores a missing station for that hour (it averages the others), so a long Berlin gap does not break `quality_ok`, but that hour's average is based on 3 cities. The `_is_gap_berlin` flag shows it.
- No gas price (TTF) yet, which drives the price in many hours.

---

## 6. Six likely interview questions, with good answers

**1. "Why did you store everything in UTC?"**
Because local German time has a 23-hour day in March and a 25-hour day in October. In local time you get a missing hour and a duplicate hour every year, and joins between sources break. UTC has 24 hours every day. I convert to local time only for display. I also cross-check OPSD's UTC and local columns (0 mismatches), and I have a test that the index stays continuous across the March 2019 switch. Interestingly, the only mid-series price gaps I found were on the two spring DST days, so the source itself lost those hours while converting.

**2. "How do you deal with missing data? Why not just drop the rows or fill everything?"**
First I make gaps visible by reindexing onto a full hourly grid, because a missing row cannot be detected with `isna()`. Then I measure them: 0.62% of hours had a gap somewhere, price only 0.03%. Gaps of up to 2 hours are interpolated, longer ones are left empty, and every change is flagged. Dropping rows breaks the hourly series; filling long gaps invents data, for example 37 hours of Berlin wind. The analyst decides with the flags.

**3. "You flagged 96 price outliers. Did you remove them?"**
No. 88 of them are negative-price hours, which are real market events: high wind, low demand. For a trading desk those spikes are the most valuable hours, not noise. I only remove values that are physically impossible, outside the exchange limits of -500 to 3,000 EUR/MWh, and there were none. I use a robust z-score (rolling median and MAD over a week) because a normal mean and standard deviation get pulled by the very spikes you are trying to find.

**4. "What did you learn from the data itself?"**
The merit-order effect. Splitting hours into 10 groups by wind output, the average day-ahead price falls from 42.30 EUR/MWh in the calmest 10% to 19.41 EUR/MWh in the windiest 10%. Wind has almost zero marginal cost, so it pushes gas and coal plants out of the merit order. Station wind speed also correlates 0.73 with national wind output, so even 4 stations carry a strong signal for a wind forecast.

**5. "What went wrong while building it?"**
The Open-Meteo archive API hit its daily request limit, so my first build had no weather. Instead of waiting, I added a fallback to DWD station data: same cities, hourly, free. The difference is that stations measure at 10 m, so I estimated 100 m wind with the power law (alpha 1/7) and recorded the source in the data and in the run summary so nobody mistakes an estimate for a measurement. The lesson: real pipelines need a plan B and must say which plan they used.

**6. "How would you put this into production at Cobblestone?"**
Run it on a schedule (cron or Airflow) after the day-ahead auction results are published, using the ENTSO-E API and a commercial weather feed instead of OPSD. Load into the team's warehouse instead of a DuckDB file. Run the same tests in CI on every change, and turn the data-quality table into alerts: for example, if the gap rate jumps or a unit check fails, notify before the traders use the numbers. Then add gas (TTF), solar and cross-border flows, and use the table as the base for a day-ahead wind or price forecast.
