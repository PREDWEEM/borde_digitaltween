from pathlib import Path

import numpy as np
import pandas as pd

from predweem_twin.core import ModelParameters, PracticalANNModel, run_predweem


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
