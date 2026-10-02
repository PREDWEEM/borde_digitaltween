from pathlib import Path

import numpy as np
import pandas as pd

from predweem_twin.core import (
    ModelParameters,
    PracticalANNModel,
    apply_cohort_decay,
    run_predweem,
)
from predweem_twin.state import thermal_window_dates


ROOT = Path(__file__).parents[1]


def test_real_bordenave_run_has_expected_invariants():
    weather = pd.read_csv(ROOT / "data" / "meteo_daily.csv")
    model = PracticalANNModel.from_directory(ROOT / "models")
    result = run_predweem(weather, model, ModelParameters())
    assert not result.empty
    assert result["Fecha"].is_monotonic_increasing
    assert result["EMERREL"].between(0, 1).all()
    assert result["EMERAC_NORMALIZADA"].between(0, 1).all()
    assert (result["W_superficial"] >= 0).all()
    assert (result["W_superficial"] <= 18.81 + 1e-9).all()
    assert (result.loc[result["Julian_days"] <= 15, "EMERREL"] == 0).all()


def test_weather_validation_rejects_inverted_temperatures():
    weather = pd.DataFrame(
        {"Fecha": ["2026-01-01"], "TMAX": [10], "TMIN": [15], "Prec": [0]}
    )
    model = PracticalANNModel.from_directory(ROOT / "models")
    try:
        run_predweem(weather, model, ModelParameters())
    except ValueError as error:
        assert "TMAX" in str(error)
    else:
        raise AssertionError("Se esperaba ValueError")


def test_run_uses_observed_daily_coverage_series():
    weather = pd.read_csv(ROOT / "data" / "meteo_daily.csv").head(5)
    weather_dates = pd.to_datetime(weather["Fecha"])
    coverage = pd.DataFrame(
        {
            "Fecha": [weather_dates.iloc[0], weather_dates.iloc[2]],
            "Cobertura_PCT": [20.0, 80.0],
        }
    )
    model = PracticalANNModel.from_directory(ROOT / "models")

    result = run_predweem(
        weather,
        model,
        ModelParameters(cobertura_pct=40.0),
        coverage_series=coverage,
    )

    assert np.allclose(
        result["Cobertura_Rastrojo"], [20.0, 50.0, 80.0, 80.0, 80.0]
    )
    assert result["Cobertura_Modo"].eq("serie observada interpolada").all()
    assert result["Cobertura_Observada"].tolist() == [True, False, True, False, False]


def test_thermal_window_dates_detects_600_and_800_degree_days():
    trajectory = pd.DataFrame(
        {
            "Fecha": pd.date_range("2026-04-01", periods=5, freq="D"),
            "TT_DESDE_PICO": [550.0, 600.0, 710.0, 800.0, 850.0],
        }
    )

    start, end = thermal_window_dates(trajectory)

    assert start == pd.Timestamp("2026-04-02")
    assert end == pd.Timestamp("2026-04-04")


def test_v2_cap_requires_strong_pre_april_signal():
    """Reglas v2: sin señal previa fuerte (>=0,5 al menos un día) no hay techo."""
    dates = pd.date_range("2026-04-01", "2026-08-01")
    strong = pd.DataFrame({"Fecha": dates, "EMERREL": 0.8})
    result = apply_cohort_decay(strong, 0, ModelParameters())
    after = result.Fecha.ge("2026-04-15")
    assert result.Techo_Aplicado_15Abr.loc[after].all()
    expected = ModelParameters().decay_cap_fraction * 0.8
    assert np.isclose(result.loc[result.Fecha.eq("2026-04-15"), "EMERREL"].iloc[0], expected)
    assert result.loc[result.Fecha.lt("2026-04-15"), "EMERREL"].eq(0.8).all()
    weak = pd.DataFrame({"Fecha": dates, "EMERREL": np.where(dates < "2026-04-15", 0.3, 0.8)})
    result = apply_cohort_decay(weak, 0, ModelParameters())
    assert result.EMERREL.equals(weak.EMERREL)
    assert not result.Techo_Aplicado_15Abr.any()
    forced = apply_cohort_decay(weak, 0, ModelParameters(decay_requiere_senal_previa=False))
    assert forced.loc[forced.Fecha.eq("2026-04-15"), "EMERREL"].iloc[0] < 0.8


def test_decay_disabled_and_no_cap_without_pre_april_emergence():
    frame = pd.DataFrame({"Fecha": pd.date_range("2026-04-16", periods=10), "EMERREL": 0.8})
    assert apply_cohort_decay(frame, 0, ModelParameters()).EMERREL.equals(frame.EMERREL)
    frame = pd.DataFrame({"Fecha": pd.date_range("2026-04-01", "2026-06-01"), "EMERREL": 0.8})
    disabled = apply_cohort_decay(frame, 0, ModelParameters(decay_enabled=False))
    assert disabled.EMERREL.equals(frame.EMERREL)


def test_legacy_parameters_restore_previous_bordenave_behavior():
    legacy = ModelParameters.legacy()
    assert legacy.umbral_termoinhibicion == 24.0 and legacy.umbral_choque_hidrico == 45.0
    assert legacy.techo_choque == 1.0 and not legacy.decay_enabled
    current = ModelParameters()
    assert current.umbral_termoinhibicion == 26.0 and current.umbral_choque_hidrico == 60.0
    assert current.techo_choque == 0.5 and current.decay_cap_fraction == 0.25
    weather = pd.read_csv(ROOT / "data" / "meteo_daily.csv")
    model = PracticalANNModel.from_directory(ROOT / "models")
    result = run_predweem(weather, model, legacy)
    assert not result.Techo_Aplicado_15Abr.any()
