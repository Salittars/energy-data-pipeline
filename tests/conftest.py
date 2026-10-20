from pathlib import Path

import pandas as pd
import pytest

from energy_pipeline import download

FIXTURES = Path(__file__).parent / "fixtures"
START, END = "2019-03-30", "2019-04-01"  # the fixture covers these 3 days (72 hours)


@pytest.fixture
def opsd_raw() -> pd.DataFrame:
    return download.read_opsd(FIXTURES / "opsd_sample.csv")


@pytest.fixture
def weather_raw() -> pd.DataFrame:
    wind = download.read_dwd_product(FIXTURES / "dwd_wind_hamburg_sample.txt", "F", "wind_speed_10m_ms")
    temp = download.read_dwd_product(FIXTURES / "dwd_temp_hamburg_sample.txt", "TT_TU", "temperature_c")
    return download.combine_dwd(wind, temp, "hamburg", START, END)
