"""Casos de frontera del cierre meteorológico, sin acceso a servicios externos."""

import contextlib
import importlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from campaign import CAMPANIA_END
from predweem_twin import weather

ROOT = Path(__file__).resolve().parents[1]
updater = importlib.import_module(next(ROOT.glob("actualizar_meteo_*.py")).stem)


def series(first, last, kind):
    frame = pd.DataFrame({
        "Fecha": pd.date_range(first, last).strftime("%Y-%m-%d"),
        "TMAX": 20.0, "TMIN": 10.0, "TMEDIA": 15.0, "Prec": 1.0,
        "TipoDato": kind,
    })
    if kind == "Pronostico":
        for column in ("TMAX", "TMIN", "TMEDIA", "Prec"):
            frame[column + "_P50"] = frame[column]
        frame["N_miembros"] = 50
    return updater.asegurar_columnas(frame)


class CampaignCutoffTests(unittest.TestCase):
    def test_update_before_on_and_after_closure(self):
        for today in (date(2026, 9, 19), date(2026, 9, 29), CAMPANIA_END,
                      date(2026, 10, 2), date(2026, 10, 10), date(2027, 1, 1)):
            with self.subTest(today=today), tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
                base = Path(tmp)
                last_observed = min(today - timedelta(days=1), CAMPANIA_END)
                # A missing historical day must still be filled after closure.
                observed = series(updater.CAMPANIA_START, last_observed, "Observado")
                observed = observed[observed.Fecha != "2026-09-15"]
                with patch.object(updater, "hoy_argentina", return_value=today), \
                     patch.object(updater, "obtener_siga_dataframe", return_value=(observed, "test")) as siga, \
                     patch.object(updater, "cargar_provisionales_ecmwf", return_value=series("2026-09-15", "2026-09-15", "Provisional")) as bridge, \
                     patch.object(updater, "consultar_ecmwf_ens", return_value={}) as api, \
                     patch.object(updater, "procesar_ecmwf_ens", return_value=series(today, today + timedelta(days=6), "Pronostico")), \
                     patch.object(updater, "DIRECTORIO_PRONOSTICOS", base / "forecasts"), \
                     patch.object(updater, "ARCHIVO_ESTADO", base / "state.json"):
                    result = updater.construir_meteo_daily(base / "meteo.csv")
                end = min(today + timedelta(days=6), CAMPANIA_END)
                self.assertEqual(result.Fecha.max(), end.isoformat())
                self.assertEqual(len(result), (end - updater.CAMPANIA_START).days + 1)
                self.assertEqual(siga.call_args.args[1], last_observed)
                self.assertEqual(bridge.call_args.args[0], [date(2026, 9, 15)])
                self.assertEqual(api.call_count, int(today <= CAMPANIA_END))
                state = json.loads((base / "state.json").read_text())
                self.assertEqual(state["fin_campania"], "2026-10-01")
                self.assertEqual(state["huecos_finales"], [])
                if today > CAMPANIA_END:
                    self.assertIsNone(state["inicio_pronostico"])
                    self.assertIsNone(state["fin_pronostico"])
                    self.assertIsNone(state["miembros_validos_min"])
                for archived in (base / "forecasts").glob("*.csv"):
                    self.assertLessEqual(pd.read_csv(archived).Fecha.max(), "2026-10-01")

    def test_forecast_request_is_shortened(self):
        for today, days in [(date(2026, 9, 19), 7), (date(2026, 9, 29), 3), (CAMPANIA_END, 1)]:
            with self.subTest(today=today), patch.object(updater, "hoy_argentina", return_value=today), \
                 patch.object(updater, "solicitar_con_reintentos", return_value=Mock(json=lambda: {})) as api:
                updater.consultar_ecmwf_ens()
                self.assertEqual(api.call_args.kwargs["params"]["forecast_days"], days)

    def test_late_siga_observations_are_clipped_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            source = Path(tmp) / "siga.csv"
            cache = Path(tmp) / "cache.csv"
            series("2026-09-29", "2026-10-10", "Observado").to_csv(source, index=False)
            with patch.object(updater, "ARCHIVO_SIGA_CACHE", cache):
                result, _ = updater.obtener_siga_dataframe(date(2026, 1, 1), date(2026, 10, 10), archivo_forzado=source)
            self.assertEqual(result.Fecha.max(), "2026-10-01")
            self.assertEqual(pd.read_csv(cache).Fecha.max(), "2026-10-01")

    def test_final_validator_rejects_dates_after_closure(self):
        frame = series(updater.CAMPANIA_START, date(2026, 10, 2), "Observado")
        with self.assertRaisesRegex(ValueError, "cierre"):
            updater.validar_serie_final(frame, date(2026, 10, 2))

    def test_window_shortens_horizon_and_closes_without_warning(self):
        frame = series("2026-09-25", "2026-10-10", "Observado")
        for cutoff, expected in [("2026-09-28", 3), ("2026-10-01", 0), ("2026-10-10", 0)]:
            with self.subTest(cutoff=cutoff):
                result, meta = weather.operational_weather_window(frame, as_of=cutoff)
                self.assertEqual(result.Fecha.max(), pd.Timestamp("2026-10-01"))
                self.assertEqual(meta["forecast_days_expected"], expected)
                self.assertEqual(meta["forecast_days_available"], expected)
                self.assertTrue(meta["complete"])
                self.assertEqual(meta["campaign_closed"], expected == 0)
        _, meta = weather.operational_weather_window(frame[frame.Fecha != "2026-09-30"], as_of="2026-09-28")
        self.assertFalse(meta["complete"])

    def test_uploaded_csv_excludes_later_days(self):
        buffer = io.StringIO("Fecha,TMAX,TMIN,Prec\n2026-10-01,20,10,1\n2026-10-02,20,10,1\n")
        buffer.name = "weather.csv"
        self.assertEqual(weather.read_weather_file(buffer).Fecha.tolist(), ["2026-10-01"])

    def test_open_meteo_requests_respect_closure(self):
        for today in (date(2026, 9, 29), CAMPANIA_END, date(2026, 10, 2), date(2026, 10, 8)):
            calls = []
            def get(url, params, timeout):
                calls.append((url, params))
                days = pd.date_range(params["start_date"], params["end_date"]).strftime("%Y-%m-%d").tolist()
                return Mock(json=lambda: {"daily": {
                    "time": days, "temperature_2m_max": [20.] * len(days),
                    "temperature_2m_min": [10.] * len(days), "precipitation_sum": [1.] * len(days),
                }})
            with self.subTest(today=today), patch.object(weather, "_today_argentina", return_value=today), \
                 patch.object(weather.requests, "get", side_effect=get):
                result = weather.fetch_open_meteo(-37.0, -58.0, "2026-01-01")
                self.assertEqual(result.Fecha.max(), pd.Timestamp("2026-10-01"))
                self.assertEqual(len(result), 274)
                self.assertTrue(all(params["end_date"] <= "2026-10-01" for _, params in calls))
                if today > CAMPANIA_END:
                    self.assertFalse(result.TipoDato.eq("Pronostico").any())
                if today == date(2026, 10, 8):
                    self.assertEqual(len(calls), 1)
                    self.assertIn("archive-api", calls[0][0])


if __name__ == "__main__":
    unittest.main()
