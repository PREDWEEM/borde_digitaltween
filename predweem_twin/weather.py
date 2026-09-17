"""Fuentes meteorológicas: archivo operativo y Open-Meteo."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import requests


def _weather_date_column(frame: pd.DataFrame) -> str:
    for column in frame.columns:
        if str(column).strip().lower() in {"fecha", "date", "datetime"}:
            return column
    raise ValueError("La meteorología requiere una columna Fecha.")


def forecast_mask(frame: pd.DataFrame) -> pd.Series:
    """Identifica filas explícitamente marcadas como pronóstico."""
    type_column = next(
        (
            column
            for column in frame.columns
            if str(column).strip().lower() in {"tipodato", "tipo_dato", "data_type"}
        ),
        None,
    )
    if type_column is None:
        return pd.Series(False, index=frame.index)
    labels = frame[type_column].astype(str).str.lower()
    return labels.str.contains("pronost|forecast", regex=True, na=False)


def last_observed_weather_date(frame: pd.DataFrame):
    """Devuelve la última fecha que no está marcada como pronóstico."""
    date_column = _weather_date_column(frame)
    dates = pd.to_datetime(frame[date_column], errors="coerce").dt.tz_localize(None)
    observed = dates[~forecast_mask(frame) & dates.notna()]
    if observed.empty:
        valid = dates.dropna()
        if valid.empty:
            raise ValueError("No hay fechas meteorológicas válidas.")
        return valid.max()
    return observed.max()


def operational_weather_window(
    frame: pd.DataFrame,
    as_of=None,
    forecast_days: int = 7,
) -> tuple[pd.DataFrame, dict]:
    """Recorta la meteorología al estado observado más siete días."""
    if int(forecast_days) < 1:
        raise ValueError("El horizonte de pronóstico debe ser al menos un día.")
    date_column = _weather_date_column(frame)
    prepared = frame.copy()
    prepared[date_column] = pd.to_datetime(
        prepared[date_column], errors="coerce"
    ).dt.tz_localize(None)
    prepared = prepared.dropna(subset=[date_column]).sort_values(date_column)
    cutoff = (
        pd.Timestamp(as_of).tz_localize(None).normalize()
        if as_of is not None
        else pd.Timestamp(last_observed_weather_date(prepared)).normalize()
    )
    horizon_end = cutoff + pd.Timedelta(days=int(forecast_days))
    window = prepared[prepared[date_column] <= horizon_end].copy()
    future_dates = window.loc[window[date_column] > cutoff, date_column].drop_duplicates()
    available = int(len(future_dates))
    return window.reset_index(drop=True), {
        "as_of": cutoff,
        "forecast_end": future_dates.max() if available else None,
        "forecast_days_requested": int(forecast_days),
        "forecast_days_available": min(available, int(forecast_days)),
        "complete": available >= int(forecast_days),
    }


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
        if data_type == "Pronostico":
            frame_dates = pd.to_datetime(frame["Fecha"]).dt.date
            frame["TipoDato"] = [
                "Provisional" if value < today else "Pronostico"
                for value in frame_dates
            ]
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
