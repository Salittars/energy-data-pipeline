# Test fixtures

Small samples so the tests run offline in a second.

- `opsd_sample.csv` - real rows from the OPSD 60-min file (2019-03-30 to 2019-04-01 UTC,
  German wind, load and DE-LU price). Includes the switch to summer time on 31 March 2019.
  **Defects injected on purpose:** the 2019-03-30 12:00 UTC row appears twice, 2 hours are
  removed on 2019-03-31 (05:00, 06:00 UTC), and 5 hours are removed on 2019-04-01 (10:00-14:00 UTC).
- `dwd_wind_hamburg_sample.txt`, `dwd_temp_hamburg_sample.txt` - real DWD hourly rows for
  Hamburg-Fuhlsbuettel over the same days. One wind value was replaced by -999 (DWD's "missing").
- `open_meteo_sample.json` - hand-written in the Open-Meteo archive API response shape
  (3 hours), used only to test the parser. Values are made up.
