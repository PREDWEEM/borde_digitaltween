"""Asimilación secuencial de observaciones de emergencia acumulada."""

from __future__ import annotations

import numpy as np
import pandas as pd


def kalman_gain(model_uncertainty: float, observation_uncertainty: float) -> float:
    """Ganancia escalar para una observación expresada en escala 0–1."""
    p = max(float(model_uncertainty), 1e-6) ** 2
    r = max(float(observation_uncertainty), 1e-6) ** 2
    return p / (p + r)


def assimilate_observations(
    trajectory: pd.DataFrame,
    observations: pd.DataFrame | None,
    model_uncertainty: float = 0.12,
    default_observation_uncertainty: float = 0.08,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Actualiza la curva preservando monotonía y la fracción futura remanente.

    Cada conteo corrige el estado acumulado con una ganancia de Kalman escalar.
    La trayectoria posterior se reancla sobre la fracción aún no emergida, sin
    modificar los motores ecofisiológicos que generaron la curva base.
    """
    df = trajectory.copy().sort_values("Fecha").reset_index(drop=True)
    df["EMERAC_TWIN"] = pd.to_numeric(df["EMERAC_NORMALIZADA"], errors="coerce").fillna(0.0)
    df["EMERREL_TWIN"] = df["EMERAC_TWIN"].diff().fillna(df["EMERAC_TWIN"]).clip(lower=0.0)
    if observations is None or observations.empty:
        return df, pd.DataFrame()

    obs = observations.copy()
    rename = {
        "fecha": "Fecha",
        "emergencia_acumulada": "Observado",
        "observado": "Observado",
        "incertidumbre": "Incertidumbre",
    }
    obs = obs.rename(columns={column: rename.get(str(column).strip().lower(), column) for column in obs.columns})
    required = {"Fecha", "Observado"}
    if not required.issubset(obs.columns):
        raise ValueError("Las observaciones requieren las columnas Fecha y Observado.")
    obs["Fecha"] = pd.to_datetime(obs["Fecha"], errors="coerce").dt.tz_localize(None)
    obs["Observado"] = pd.to_numeric(obs["Observado"], errors="coerce")
    if "Incertidumbre" not in obs:
        obs["Incertidumbre"] = default_observation_uncertainty
    obs["Incertidumbre"] = pd.to_numeric(obs["Incertidumbre"], errors="coerce").fillna(default_observation_uncertainty)
    obs = obs.dropna(subset=["Fecha", "Observado"]).sort_values("Fecha")
    obs["Observado"] = obs["Observado"].clip(0.0, 1.0)

    audit = []
    for row in obs.itertuples(index=False):
        valid_indices = df.index[df["Fecha"] <= row.Fecha].tolist()
        if not valid_indices:
            continue
        idx = valid_indices[-1]
        prior = float(df.at[idx, "EMERAC_TWIN"])
        gain = kalman_gain(model_uncertainty, row.Incertidumbre)
        posterior = float(np.clip(prior + gain * (row.Observado - prior), 0.0, 1.0))

        before = df.loc[:idx, "EMERAC_TWIN"].to_numpy(copy=True)
        if prior > 1e-9:
            before = before * (posterior / prior)
        else:
            before[-1] = posterior
        df.loc[:idx, "EMERAC_TWIN"] = np.maximum.accumulate(np.clip(before, 0.0, posterior))

        base_anchor = float(df.at[idx, "EMERAC_NORMALIZADA"])
        base_future = df.loc[idx:, "EMERAC_NORMALIZADA"].to_numpy(float)
        if base_anchor < 1.0 - 1e-9:
            progress = np.clip((base_future - base_anchor) / (1.0 - base_anchor), 0.0, 1.0)
            adjusted_future = posterior + (1.0 - posterior) * progress
        else:
            adjusted_future = np.full(len(base_future), posterior)
        df.loc[idx:, "EMERAC_TWIN"] = np.maximum.accumulate(np.clip(adjusted_future, posterior, 1.0))

        audit.append(
            {
                "Fecha_observacion": row.Fecha,
                "Fecha_asimilada": df.at[idx, "Fecha"],
                "Pronostico_previo": prior,
                "Observado": float(row.Observado),
                "Incertidumbre_observacion": float(row.Incertidumbre),
                "Ganancia": gain,
                "Estado_posterior": posterior,
                "Innovacion": float(row.Observado - prior),
            }
        )

    df["EMERAC_TWIN"] = np.maximum.accumulate(df["EMERAC_TWIN"].clip(0.0, 1.0))
    df["EMERREL_TWIN"] = df["EMERAC_TWIN"].diff().fillna(df["EMERAC_TWIN"]).clip(lower=0.0)
    return df, pd.DataFrame(audit)

