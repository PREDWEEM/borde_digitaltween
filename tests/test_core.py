from pathlib import Path

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

