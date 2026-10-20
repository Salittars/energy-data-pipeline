"""All settings in one place: dates, sources, weather points and sanity limits."""

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Read KEY=VALUE lines from a .env file into os.environ (existing values win)."""
    env_file = Path(path)
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


# Two full years. The DE-LU bidding zone (and its day-ahead price) starts on
# 1 Oct 2018, and the latest OPSD release ends on 30 Sep 2020.
START_DATE = "2018-10-01"
END_DATE = "2020-09-30"

OPSD_URL = (
    "https://data.open-power-system-data.org/time_series/2020-10-06/"
    "time_series_60min_singleindex.csv"
)

# OPSD column name -> our column name (units in the name, always).
OPSD_COLUMNS = {
    "DE_wind_generation_actual": "wind_generation_mw",
    "DE_load_actual_entsoe_transparency": "load_mw",
    "DE_LU_price_day_ahead": "price_eur_mwh",
}

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
DWD_BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly"
)


@dataclass(frozen=True)
class Station:
    key: str        # short name used in column names
    name: str       # human-readable name
    lat: float
    lon: float
    dwd_id: str     # German Weather Service (DWD) station id, used by the fallback


# Four points spread across Germany: windy north, east, west, south.
STATIONS = [
    Station("hamburg", "Hamburg-Fuhlsbuettel", 53.6332, 9.9881, "01975"),
    Station("berlin", "Berlin-Tempelhof", 52.4676, 13.4020, "00433"),
    Station("frankfurt", "Frankfurt/Main", 50.0259, 8.5213, "01420"),
    Station("munich", "Muenchen-Stadt", 48.1632, 11.5429, "03379"),
]

# Physically plausible ranges. Values outside are treated as data errors.
# Wind: German installed wind capacity was ~62 GW in 2020.
# Price: EPEX day-ahead technical limits in 2018-2020 were -500 / +3000 EUR/MWh.
BOUNDS = {
    "wind_generation_mw": (0, 65_000),
    "load_mw": (20_000, 100_000),
    "price_eur_mwh": (-500, 3_000),
    "wind_speed_100m_ms": (0, 60),
    "temperature_c": (-35, 45),
}

# Gaps this short (in hours) are filled by linear interpolation and flagged.
MAX_FILL_HOURS = 2

# Rolling robust z-score settings for outlier flags (flag only, never delete).
OUTLIER_WINDOW_HOURS = 24 * 7
OUTLIER_Z = 6.0

# Wind extrapolation from 10 m (DWD stations) to 100 m hub height, power law.
WIND_SHEAR_ALPHA = 1 / 7
DWD_SENSOR_HEIGHT_M = 10
