"""Download raw data. Files are cached in data/raw so re-runs are fast."""

import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests

from . import config


class SourceError(RuntimeError):
    """A data source could not deliver what we asked for."""


def download_file(url: str, dest: Path, timeout: int = 120) -> Path:
    """Download url to dest unless it is already there."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


# ---------- Power market data (Open Power System Data) ----------

def fetch_opsd(raw_dir: Path) -> Path:
    return download_file(config.OPSD_URL, raw_dir / "opsd_time_series_60min.csv")


def read_opsd(path: Path) -> pd.DataFrame:
    """Read only the German columns we need, with our own column names."""
    wanted = ["utc_timestamp", "cet_cest_timestamp", *config.OPSD_COLUMNS]
    df = pd.read_csv(path, usecols=wanted)
    return df.rename(columns=config.OPSD_COLUMNS)


# ---------- Weather, option 1: Open-Meteo archive API ----------

def fetch_open_meteo(station: config.Station, start: str, end: str, raw_dir: Path) -> pd.DataFrame:
    cache = raw_dir / f"open_meteo_{station.key}_{start}_{end}.json"
    if not cache.exists():
        params = {
            "latitude": station.lat,
            "longitude": station.lon,
            "start_date": start,
            "end_date": end,
            "hourly": "wind_speed_100m,temperature_2m",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
        }
        resp = requests.get(config.OPEN_METEO_URL, params=params, timeout=120)
        payload = resp.json()
        if resp.status_code != 200 or payload.get("error"):
            raise SourceError(f"Open-Meteo: {payload.get('reason', resp.status_code)}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload))
    return parse_open_meteo(json.loads(cache.read_text()), station.key)


def parse_open_meteo(payload: dict, station_key: str) -> pd.DataFrame:
    hourly = payload["hourly"]
    return pd.DataFrame({
        "timestamp_utc": pd.to_datetime(hourly["time"], utc=True),
        "station": station_key,
        "wind_speed_100m_ms": hourly["wind_speed_100m"],
        "temperature_c": hourly["temperature_2m"],
        "source": "open-meteo",
    })


# ---------- Weather, option 2 (fallback): DWD station observations ----------

def _dwd_zip_url(product: str, code: str, station_id: str) -> str:
    """Find the station's zip in the DWD directory listing (file names contain dates)."""
    folder = f"{config.DWD_BASE_URL}/{product}/historical/"
    listing = requests.get(folder, timeout=60).text
    match = re.search(rf"stundenwerte_{code}_{station_id}_\d+_\d+_hist\.zip", listing)
    if not match:
        raise SourceError(f"DWD: no {product} file for station {station_id}")
    return folder + match.group(0)


def _cached_dwd_zip(product: str, code: str, station_id: str, dest: Path) -> Path:
    """Only look up the DWD file name (a network call) if we do not have the file yet."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    return download_file(_dwd_zip_url(product, code, station_id), dest)


def read_dwd_product(path: Path, value_col: str, new_name: str) -> pd.DataFrame:
    """Read a DWD 'produkt_*.txt' file (inside a zip or plain). -999 means missing."""
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            inner = next(n for n in zf.namelist() if n.startswith("produkt"))
            text = zf.read(inner).decode("latin-1")
    else:
        text = path.read_text(encoding="latin-1")
    df = pd.read_csv(io.StringIO(text), sep=";", skipinitialspace=True, na_values=[-999, "-999"])
    df.columns = [c.strip() for c in df.columns]
    # MESS_DATUM is yyyymmddhh; DWD hourly data is in UTC since 2000.
    ts = pd.to_datetime(df["MESS_DATUM"].astype(str), format="%Y%m%d%H", utc=True)
    return pd.DataFrame({"timestamp_utc": ts, new_name: df[value_col].astype(float)})


def fetch_dwd(station: config.Station, start: str, end: str, raw_dir: Path) -> pd.DataFrame:
    wind_zip = _cached_dwd_zip("wind", "FF", station.dwd_id, raw_dir / f"dwd_wind_{station.dwd_id}.zip")
    temp_zip = _cached_dwd_zip("air_temperature", "TU", station.dwd_id,
                               raw_dir / f"dwd_temp_{station.dwd_id}.zip")
    wind = read_dwd_product(wind_zip, "F", "wind_speed_10m_ms")
    temp = read_dwd_product(temp_zip, "TT_TU", "temperature_c")
    return combine_dwd(wind, temp, station.key, start, end)


def combine_dwd(wind: pd.DataFrame, temp: pd.DataFrame, station_key: str,
                start: str, end: str) -> pd.DataFrame:
    """Merge DWD wind + temperature and estimate 100 m wind with the power law."""
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=23)
    wind = wind[wind.timestamp_utc.between(lo, hi)]
    temp = temp[temp.timestamp_utc.between(lo, hi)]
    df = wind.merge(temp, on="timestamp_utc", how="outer")
    factor = (100 / config.DWD_SENSOR_HEIGHT_M) ** config.WIND_SHEAR_ALPHA
    df["wind_speed_100m_ms"] = df.pop("wind_speed_10m_ms") * factor
    df["station"] = station_key
    df["source"] = "dwd-10m-extrapolated"
    return df[["timestamp_utc", "station", "wind_speed_100m_ms", "temperature_c", "source"]]


def fetch_weather(start: str, end: str, raw_dir: Path, source: str = "auto"):
    """Return (long weather table, list of notes). 'auto' tries Open-Meteo, then DWD."""
    frames, notes = [], []
    for station in config.STATIONS:
        if source in ("auto", "open-meteo"):
            try:
                frames.append(fetch_open_meteo(station, start, end, raw_dir))
                continue
            except (SourceError, requests.RequestException, ValueError) as err:
                if source == "open-meteo":
                    raise
                notes.append(f"{station.key}: Open-Meteo failed ({err}); used DWD instead")
        frames.append(fetch_dwd(station, start, end, raw_dir))
    return pd.concat(frames, ignore_index=True), notes
