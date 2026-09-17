"""Lectura y normalización de observaciones de emergencia de campo."""

from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd


DATE_ALIASES = {"fecha", "date", "datetime", "fecha_muestreo"}
FLOW_ALIASES = {
    "plm2",
    "pl_m2",
    "plantas_m2",
    "plantas_por_m2",
    "flujo",
    "flujo_observado",
    "conteo",
    "emergencia_intervalo",
}
CUMULATIVE_ALIASES = {
    "observado",
    "emerac",
    "emerac_normalizada",
    "campo_normalizado",
    "emergencia_acumulada",
    "emergencia_acumulada_pct",
    "porcentaje_acumulado",
    "acumulada",
}


def _normalized_name(value) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _file_bytes(source) -> tuple[bytes, str]:
    if hasattr(source, "getvalue"):
        return source.getvalue(), getattr(source, "name", "observaciones.xlsx")
    path = Path(source)
    return path.read_bytes(), path.name


def read_observation_file(source) -> tuple[pd.DataFrame, dict]:
    """Lee CSV/XLS/XLSX y elige la primera hoja con columnas reconocibles."""
    payload, filename = _file_bytes(source)
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        sheets = pd.read_excel(BytesIO(payload), sheet_name=None)
    elif suffix in {".csv", ".txt", ".tsv"}:
        separator = "\t" if suffix == ".tsv" else None
        try:
            frame = pd.read_csv(BytesIO(payload), sep=separator, engine="python")
        except UnicodeDecodeError:
            frame = pd.read_csv(
                StringIO(payload.decode("latin-1")), sep=separator, engine="python"
            )
        sheets = {"CSV": frame}
    else:
        raise ValueError("Formato no admitido. Use CSV, TSV, XLS o XLSX.")

    available = []
    for sheet_name, frame in sheets.items():
        names = {_normalized_name(column) for column in frame.columns}
        available.append(sheet_name)
        if names.intersection(DATE_ALIASES) and names.intersection(
            FLOW_ALIASES | CUMULATIVE_ALIASES
        ):
            return frame, {"archivo": filename, "hoja": sheet_name}
    raise ValueError(
        "No se encontró una hoja con fecha y emergencia observada. "
        f"Hojas revisadas: {', '.join(available)}."
    )


def _column_map(frame: pd.DataFrame) -> dict[str, str]:
    return {_normalized_name(column): column for column in frame.columns}


def _first_column(mapping: dict[str, str], aliases: set[str]):
    return next((mapping[name] for name in aliases if name in mapping), None)


def _model_cumulative_at(trajectory: pd.DataFrame, dates: pd.Series) -> np.ndarray:
    model = trajectory[["Fecha", "EMERAC_NORMALIZADA"]].copy()
    model["Fecha"] = pd.to_datetime(model["Fecha"], errors="coerce").dt.tz_localize(None)
    query = pd.DataFrame({"Fecha": pd.to_datetime(dates).dt.tz_localize(None)})
    matched = pd.merge_asof(
        query.sort_values("Fecha"),
        model.sort_values("Fecha"),
        on="Fecha",
        direction="backward",
    )
    if matched["EMERAC_NORMALIZADA"].isna().any():
        raise ValueError("Hay observaciones anteriores al inicio de la serie meteorológica.")
    return matched["EMERAC_NORMALIZADA"].to_numpy(float)


def prepare_observations(
    raw: pd.DataFrame,
    trajectory: pd.DataFrame,
    mode: str = "auto",
    uncertainty: float = 0.08,
    source_name: str = "Archivo cargado",
) -> tuple[pd.DataFrame, dict]:
    """Convierte flujos PLM2 o acumulados porcentuales al estado 0–1.

    Para una serie PLM2 prácticamente completa (>=85 % del acumulado simulado
    en la última fecha), el total del archivo define el potencial observado.
    En campaña incompleta se estima la densidad estacional mediante una escala
    de mínimos cuadrados entre flujos observados y fracciones simuladas.
    """
    if not 0 < float(uncertainty) <= 1:
        raise ValueError("La incertidumbre debe expresarse entre 0 y 1.")
    mapping = _column_map(raw)
    date_column = _first_column(mapping, DATE_ALIASES)
    if date_column is None:
        raise ValueError("Falta una columna de fecha (por ejemplo, FECHA).")

    flow_column = _first_column(mapping, FLOW_ALIASES)
    cumulative_column = _first_column(mapping, CUMULATIVE_ALIASES)
    normalized_mode = _normalized_name(mode)
    if normalized_mode in {"auto", "detectar_automaticamente"}:
        selected_mode = "flujo" if flow_column is not None else "acumulado"
    elif normalized_mode in {"flujo", "flujo_por_intervalo_plm2", "plm2"}:
        selected_mode = "flujo"
    elif normalized_mode in {"acumulado", "acumulada", "acumulada_pct"}:
        selected_mode = "acumulado"
    else:
        raise ValueError(f"Modo de observación desconocido: {mode}")

    value_column = flow_column if selected_mode == "flujo" else cumulative_column
    if value_column is None:
        raise ValueError(
            "No se encontró la columna requerida. Para flujos use PLM2; "
            "para acumulados use EMERGENCIA_ACUMULADA u OBSERVADO."
        )

    prepared = raw[[date_column, value_column]].copy()
    prepared.columns = ["Fecha", "Valor_original"]
    prepared["Fecha"] = pd.to_datetime(prepared["Fecha"], errors="coerce").dt.tz_localize(None)
    prepared["Valor_original"] = pd.to_numeric(
        prepared["Valor_original"], errors="coerce"
    )
    invalid = prepared[["Fecha", "Valor_original"]].isna().any(axis=1)
    if invalid.any():
        raise ValueError(f"El archivo contiene {int(invalid.sum())} filas con fecha o valor inválido.")
    if (prepared["Valor_original"] < 0).any():
        raise ValueError("La emergencia observada no puede contener valores negativos.")

    if selected_mode == "flujo":
        prepared = (
            prepared.groupby("Fecha", as_index=False)["Valor_original"]
            .sum()
            .sort_values("Fecha")
            .reset_index(drop=True)
        )
    else:
        prepared = (
            prepared.drop_duplicates("Fecha", keep="last")
            .sort_values("Fecha")
            .reset_index(drop=True)
        )

    model_min = pd.Timestamp(trajectory["Fecha"].min())
    model_max = pd.Timestamp(trajectory["Fecha"].max())
    if prepared["Fecha"].min() < model_min or prepared["Fecha"].max() > model_max:
        raise ValueError(
            "Las observaciones deben estar dentro del período meteorológico "
            f"{model_min.date().isoformat()} a {model_max.date().isoformat()}."
        )

    metadata = {
        "modo": selected_mode,
        "columna_fecha": str(date_column),
        "columna_valor": str(value_column),
        "filas": len(prepared),
    }
    if selected_mode == "flujo":
        model_cumulative = _model_cumulative_at(trajectory, prepared["Fecha"])
        model_intervals = np.diff(np.r_[0.0, model_cumulative]).clip(min=1e-6)
        observed_flows = prepared["Valor_original"].to_numpy(float)
        observed_total = float(observed_flows.sum())
        if observed_total <= 0:
            raise ValueError("La suma de PLM2 debe ser mayor que cero.")

        if model_cumulative[-1] >= 0.85:
            seasonal_total = observed_total
            method = "total observado de una serie casi completa"
        else:
            denominator = float(np.dot(model_intervals, model_intervals))
            regression_total = (
                float(np.dot(model_intervals, observed_flows) / denominator)
                if denominator > 0
                else observed_total
            )
            seasonal_total = max(observed_total, regression_total)
            method = "potencial estacional estimado por escala modelo–campo"

        prepared["Flujo_observado_PLM2"] = prepared["Valor_original"]
        prepared["Acumulado_PLM2"] = prepared["Valor_original"].cumsum()
        prepared["Observado"] = (prepared["Acumulado_PLM2"] / seasonal_total).clip(0, 1)
        prepared["Unidad_original"] = "plantas/m² por intervalo"
        metadata.update(
            {
                "total_observado_plm2": observed_total,
                "potencial_estacional_plm2": seasonal_total,
                "metodo_normalizacion": method,
                "progreso_modelo_ultima_fecha": float(model_cumulative[-1]),
            }
        )
    else:
        values = prepared["Valor_original"].to_numpy(float)
        if values.max(initial=0.0) > 1.0:
            if values.max() > 100.0:
                raise ValueError("Los acumulados deben expresarse entre 0–1 o 0–100 %.")
            values = values / 100.0
            original_unit = "% acumulado"
        else:
            original_unit = "fracción acumulada"
        if np.any(np.diff(values) < -1e-9):
            raise ValueError("La emergencia acumulada debe ser monótona creciente.")
        prepared["Observado"] = np.clip(values, 0.0, 1.0)
        prepared["Unidad_original"] = original_unit
        metadata["metodo_normalizacion"] = "acumulado aportado por el usuario"

    prepared["Incertidumbre"] = float(uncertainty)
    prepared["Fuente"] = source_name
    prepared["Nota"] = (
        "Carga masiva; " + str(metadata["metodo_normalizacion"])
    )
    return prepared, metadata
