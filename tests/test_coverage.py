from io import BytesIO

import numpy as np
import pandas as pd

from predweem_twin.coverage import prepare_coverage_series, read_coverage_file
from predweem_twin.core import daily_coverage, surface_parameters
from predweem_twin.storage import TwinStore


def test_coverage_file_is_read_and_validated():
    payload = BytesIO()
    source = pd.DataFrame(
        {
            "FECHA": ["2026-03-01", "2026-03-15"],
            "COBERTURA_PCT": [82.0, 70.0],
        }
    )
    with pd.ExcelWriter(payload, engine="openpyxl") as writer:
        source.to_excel(writer, sheet_name="Rastrojo", index=False)
    payload.name = "cobertura.xlsx"

    raw, file_metadata = read_coverage_file(payload)
    prepared, metadata = prepare_coverage_series(raw)

    assert file_metadata == {"archivo": "cobertura.xlsx", "hoja": "Rastrojo"}
    assert prepared["Cobertura_PCT"].tolist() == [82.0, 70.0]
    assert metadata["filas"] == 2


def test_daily_coverage_interpolates_and_holds_last_value():
    dates = pd.Series(pd.date_range("2026-03-01", periods=5, freq="D"))
    observed = pd.DataFrame(
        {
            "Fecha": pd.to_datetime(["2026-03-02", "2026-03-04"]),
            "Cobertura_PCT": [20.0, 80.0],
        }
    )

    result = daily_coverage(dates, 40.0, observed)
    ke_soil, thermal_modulator = surface_parameters(result)

    assert np.allclose(result, [40.0, 20.0, 50.0, 80.0, 80.0])
    assert ke_soil[1] > ke_soil[3]
    assert thermal_modulator[1] > thermal_modulator[3]


def test_coverage_storage_is_isolated_by_site_and_deletable(tmp_path):
    coverage = pd.DataFrame(
        {
            "Fecha": pd.to_datetime(["2026-03-01", "2026-03-15"]),
            "Cobertura_PCT": [82.0, 70.0],
            "Fuente": ["campo.xlsx", "campo.xlsx"],
        }
    )
    store = TwinStore(tmp_path / "twin.db")
    store.upsert_coverage_observations("Lote-A", coverage)
    store.upsert_coverage_observations("Lote-B", coverage)

    assert store.coverage_observations("Lote-A")["Cobertura_PCT"].tolist() == [
        82.0,
        70.0,
    ]
    assert store.delete_coverage_observations("Lote-A", ["2026-03-01"]) == 1
    assert store.coverage_observations("Lote-A")["Cobertura_PCT"].tolist() == [70.0]
    assert len(store.coverage_observations("Lote-B")) == 2
