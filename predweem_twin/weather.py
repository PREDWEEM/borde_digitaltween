"""Fuentes meteorológicas: archivo operativo y Open-Meteo."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import requests


def read_weather_file(source) -> pd.DataFrame:
    if hasattr(source, "name"):
        suffix = Path(source.name).suffix.lower()
    else:
        suffix = Path(source).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(source)
    return pd.read_csv(source)


def fetch_open_meteo(latitude: float, longitude: float, start_date, forecast_days: int = 16) -> pd.DataFrame:
    """Combina ERA5/archivo histórico y pronóstico para una coordenada."""
    start = pd.Timestamp(start_date).date().isoformat()
    today = pd.Timestamp.now(tz="America/Argentina/Buenos_Aires").date()
    history_end = today - pd.Timedelta(days=6)
    archive_url = "https://archive-api.open-meteo.com/v1/archive"
    daily = "temperature_2m_max,temperature_2m_min,precipitation_sum"
    archive = requests.get(
        archive_url,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start,
            "end_date": history_end.isoformat(),
            "daily": daily,
            "timezone": "America/Argentina/Buenos_Aires",
        },
        timeout=45,
    )
    archive.raise_for_status()
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "past_days": 5,
            "forecast_days": forecast_days,
            "daily": daily,
            "timezone": "America/Argentina/Buenos_Aires",
        },
        timeout=45,
    )
    forecast.raise_for_status()

    frames = []
    for payload, source, data_type in (
        (archive.json(), "OPEN_METEO_ERA5", "Historico"),
        (forecast.json(), "OPEN_METEO_FORECAST", "Pronostico"),
    ):
        block = payload["daily"]
        frame = pd.DataFrame(
            {
                "Fecha": block["time"],
                "TMAX": block["temperature_2m_max"],
                "TMIN": block["temperature_2m_min"],
                "Prec": block["precipitation_sum"],
                "Fuente": source,
                "TipoDato": data_type,
            }
        )
        frames.append(frame)
    return (
        pd.concat(frames, ignore_index=True)
        .assign(Fecha=lambda frame: pd.to_datetime(frame["Fecha"]))
        .sort_values("Fecha")
        .drop_duplicates("Fecha", keep="last")
        .reset_index(drop=True)
    )


def weather_source_label(df: pd.DataFrame) -> str:
    if "Fuente" not in df.columns:
        return "Archivo aportado"
    sources = [str(value) for value in df["Fuente"].dropna().unique()]
    return " + ".join(sources[:3]) if sources else "Archivo aportado"

