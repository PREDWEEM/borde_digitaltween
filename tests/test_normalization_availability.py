"""Regresiones del inicio de Bordenave y propagación de un estado no estimable."""
import json
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from predweem_twin.assimilation import assimilate_observations
from predweem_twin.calibration import apply_site_calibration
from predweem_twin.charts import trajectory_charts
from predweem_twin.core import ModelParameters, PracticalANNModel, run_predweem
from predweem_twin.observations import prepare_observations
from predweem_twin.onset import onset_alert
from predweem_twin.seasonal import load_seasonal_reference, partial_season_normalization
from predweem_twin.state import build_twin_snapshot, milestone_dates
from predweem_twin.storage import SCHEMA, TwinStore

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def inputs():
    return (
        pd.read_csv(ROOT / "data/calibration/bordenave_2026_weather.csv", parse_dates=["Fecha"]),
        PracticalANNModel.from_directory(ROOT / "models"),
        load_seasonal_reference(ROOT / "models/modelo_clusters_k3.pkl"),
    )


def run(inputs, cutoff, days=7, operational=True):
    weather, model, reference = inputs
    cutoff = pd.Timestamp(cutoff)
    return run_predweem(
        weather.loc[weather.Fecha.le(cutoff + pd.Timedelta(days=days))],
        model, ModelParameters(w_max=18.8, cobertura_pct=50),
        normalization_as_of=cutoff if operational else None,
        seasonal_reference=reference if operational else None,
    )


@pytest.mark.parametrize("cutoff,available", [
    ("2026-01-09", False), ("2026-01-22", False), ("2026-02-09", False),
    ("2026-02-15", True), ("2026-02-16", True), ("2026-03-09", True),
])
def test_future_days_do_not_set_the_past_percentage_or_change_onset(inputs, cutoff, available):
    past = run(inputs, cutoff, days=0)
    future = run(inputs, cutoff)
    assert future.Normalizacion_Disponible.eq(available).all()
    np.testing.assert_allclose(
        past.EMERAC_NORMALIZADA, future.loc[future.Fecha.le(cutoff), "EMERAC_NORMALIZADA"],
        rtol=0, atol=0, equal_nan=True,
    )
    assert pd.to_datetime(future.Fecha_Ancla_Normalizacion).dropna().le(cutoff).all()
    if not available:
        assert future.EMERAC_NORMALIZADA.isna().all()
        assert future.Total_EMERREL_Referencia.isna().all()
    retrospective = run(inputs, cutoff, operational=False)
    for column in ["EMERREL", "EMERAC", "Primer_Pico_Habilitado", "TT_DESDE_PICO"]:
        pd.testing.assert_series_equal(future[column], retrospective[column])
    assert onset_alert(future, cutoff) == onset_alert(retrospective, cutoff)


def test_no_past_anchor_and_nonstandard_index(inputs):
    trajectory = run(inputs, "2026-02-16")
    reference = inputs[2]
    trajectory.index = np.arange(len(trajectory)) * 3 + 100
    denominator, metadata = partial_season_normalization(trajectory, "2025-12-31", reference)
    assert denominator is None and "anchor_date" not in metadata
    denominator, metadata = partial_season_normalization(trajectory, "2026-02-09", reference)
    assert denominator is None and metadata["anchor_date"] == pd.Timestamp("2026-02-09")
    denominator, metadata = partial_season_normalization(trajectory, "2026-02-16", reference)
    assert denominator > 0 and metadata["anchor_date"] == pd.Timestamp("2026-02-16")


def test_operational_run_without_reference_is_unknown(inputs):
    weather, model, _ = inputs
    result = run_predweem(weather.iloc[:40], model, ModelParameters(), normalization_as_of="2026-02-09")
    assert not result.Normalizacion_Disponible.any()
    assert result.EMERAC_NORMALIZADA.isna().all()


def test_pending_counts_survive_storage_and_assimilate_when_available(inputs, tmp_path):
    early = run(inputs, "2026-02-09")
    raw = pd.read_csv(ROOT / "data/calibration/bordenave_2026_counts.csv", parse_dates=["Fecha"])
    raw = raw.loc[raw.Fecha.le("2026-02-09")]
    prepared, metadata = prepare_observations(raw, early)
    assert prepared.Observado.isna().all()
    assert metadata["potencial_estacional_plm2"] is None
    assert metadata["progreso_modelo_ultima_fecha"] is None
    assert prepared.Incertidumbre.notna().all()
    assert prepared.Flujo_observado_PLM2.sum() == pytest.approx(raw["media(SR).m2"].sum())
    assert prepared.Flujo_observado_PLM2.iloc[1] == pytest.approx(713.3333333)
    store = TwinStore(tmp_path / "state.db")
    store.upsert_observations("lote", prepared)
    stored = store.observations("lote")
    assert stored.Observado.isna().all()
    np.testing.assert_allclose(stored.Flujo_observado_PLM2, prepared.Flujo_observado_PLM2)
    np.testing.assert_allclose(stored.EE_repeticiones_PLM2, prepared.EE_repeticiones_PLM2)
    calibrated, calibration_audit = apply_site_calibration(early, None, site="Bordenave", as_of="2026-02-09")
    assert not calibration_audit["applied"]
    twin, audit = assimilate_observations(calibrated, stored)
    assert audit.empty
    assert twin.EMERAC_TWIN.isna().all() and twin.EMERREL_TWIN.isna().all()
    assert twin.POTENCIAL_ESTACIONAL_PLM2.isna().all()
    assert onset_alert(twin, "2026-02-09", stored)["status"] == "observed"

    snapshot = build_twin_snapshot(twin, "lote", "2026-02-09", "test", seasonal_reference=inputs[2])
    assert snapshot["emergence"] is None and snapshot["remaining"] is None
    assert snapshot["intensity_7d"] == "Aún no estimable"
    assert snapshot["increment_7d"] is None and snapshot["seasonal_potential_plm2"] is None
    assert snapshot["thermal_time"] > 0
    json.dumps(snapshot, allow_nan=False)
    assert all(value is None for value in milestone_dates(twin).values())
    for frequency in ("Diario", "Semanal"):
        flow, cumulative = trajectory_charts(twin, stored, "2026-02-09", audit, seasonal_reference=inputs[2], flow_frequency=frequency)
        assert "Intensidad nula del gemelo" not in [t.name for t in flow.data]
        assert "Conteo de campo" not in [t.name for t in cumulative.data]
        assert "Pool histórico · orientativo" in [t.name for t in cumulative.data]
        gemelo = next(t for t in flow.data if t.name == f"Flujo {frequency.lower()} del gemelo")
        assert not np.isfinite(np.asarray(gemelo.y, dtype=float)).any()
        assert any(a.name == "normalization_unavailable" for a in flow.layout.annotations)

    later = run(inputs, "2026-02-16")
    twin, audit = assimilate_observations(later, stored)
    assert len(audit) == len(stored)
    assert twin.EMERAC_TWIN.notna().all() and twin.POTENCIAL_ESTACIONAL_PLM2.gt(0).all()
    assert audit.Flujo_observado_PLM2.sum() == pytest.approx(prepared.Flujo_observado_PLM2.sum())


def test_existing_database_migrates_without_losing_rows_or_indexes(tmp_path, inputs):
    path = tmp_path / "legacy.db"
    old_schema = SCHEMA.replace("cumulative REAL CHECK", "cumulative REAL NOT NULL CHECK")
    with sqlite3.connect(path) as connection:
        connection.executescript(old_schema)
        connection.execute("CREATE INDEX observations_note ON observations(note)")
        connection.execute("CREATE TABLE insert_audit (observed_at TEXT)")
        connection.execute("CREATE TRIGGER observe_insert AFTER INSERT ON observations BEGIN INSERT INTO insert_audit VALUES (NEW.observed_at); END")
        connection.execute("INSERT INTO observations(site_id, observed_at, cumulative, uncertainty, note) VALUES ('lote', '2026-01-20', .1, .05, 'original')")
        connection.execute("INSERT INTO snapshots(site_id, as_of, payload) VALUES ('lote', '2026-01-20', '{}')")
        connection.execute("UPDATE sqlite_sequence SET seq=10 WHERE name='observations'")
    store = TwinStore(path)
    with store.connect() as connection:
        assert connection.execute("SELECT id, cumulative, note FROM observations").fetchall() == [(1, .1, "original")]
        assert connection.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='observations_note'").fetchone()
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='observe_insert'").fetchone()
        assert connection.execute("SELECT count(*) FROM insert_audit").fetchone()[0] == 1
        assert next(r for r in connection.execute("PRAGMA table_info(observations)") if r[1] == "cumulative")[3] == 0
    prepared, _ = prepare_observations(pd.DataFrame({"Fecha": ["2026-02-02"], "PLM2": [12.]}), run(inputs, "2026-02-09"))
    store.upsert_observations("lote", prepared)
    stored = TwinStore(path).observations("lote")
    assert len(stored) == 2 and stored.iloc[0].Observado == .1
    assert pd.isna(stored.iloc[1].Observado) and stored.iloc[1].Flujo_observado_PLM2 == 12.
    with store.connect() as connection:
        assert connection.execute("SELECT max(id) FROM observations").fetchone()[0] == 11
        assert connection.execute("SELECT count(*) FROM insert_audit").fetchone()[0] == 2
    store.upsert_observations("lote", prepared)
    assert len(store.observations("lote")) == 2


def test_app_handles_pending_and_available_percentages_with_saved_counts(tmp_path, inputs):
    from streamlit.testing.v1 import AppTest

    shutil.copy2(ROOT / "app.py", tmp_path / "app.py")
    for directory in ("models", "predweem_twin", "data/calibration"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    shutil.copy2(ROOT / "data/meteo_daily.csv", tmp_path / "data/meteo_daily.csv")
    raw = pd.read_csv(ROOT / "data/calibration/bordenave_2026_counts.csv", parse_dates=["Fecha"])
    prepared, _ = prepare_observations(raw.loc[raw.Fecha.le("2026-02-09")], run(inputs, "2026-02-09"))
    TwinStore(tmp_path / "data/twin_state.db").upsert_observations("Bordenave-01", prepared)
    at = AppTest.from_file(str(tmp_path / "app.py"), default_timeout=30).run()
    assert not at.exception
    for cutoff, available in [("2026-01-22", False), ("2026-02-09", False), ("2026-02-16", True)]:
        at.date_input[0].set_value(pd.Timestamp(cutoff).date()).run()
        assert not at.exception
        metrics = {metric.label: metric.value for metric in at.metric}
        assert (metrics["Emergencia estimada"] != "Aún no estimable") == available
        assert (metrics["Emergencia remanente"] != "Aún no estimable") == available
        assert "nan" not in str(metrics).lower()
        if not available:
            assert "Aún no estimable" in metrics["Intensidad de emergencia · 7 días"]
            assert "Conteos acumulados registrados" in metrics
