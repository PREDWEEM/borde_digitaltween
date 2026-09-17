"""Persistencia SQLite por lote para observaciones, estados y auditoría."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    cumulative REAL NOT NULL CHECK(cumulative BETWEEN 0 AND 1),
    uncertainty REAL NOT NULL CHECK(uncertainty > 0),
    note TEXT NOT NULL DEFAULT '',
    raw_value REAL,
    raw_unit TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT 'Manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(site_id, observed_at)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class TwinStore:
    def __init__(self, path: str | Path = "data/twin_state.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            existing = {
                row[1] for row in connection.execute("PRAGMA table_info(observations)")
            }
            migrations = {
                "raw_value": "ALTER TABLE observations ADD COLUMN raw_value REAL",
                "raw_unit": "ALTER TABLE observations ADD COLUMN raw_unit TEXT NOT NULL DEFAULT ''",
                "source_name": "ALTER TABLE observations ADD COLUMN source_name TEXT NOT NULL DEFAULT 'Manual'",
            }
            for column, statement in migrations.items():
                if column not in existing:
                    connection.execute(statement)

    def connect(self):
        return sqlite3.connect(self.path)

    def upsert_observation(
        self,
        site_id: str,
        observed_at,
        cumulative: float,
        uncertainty: float,
        note="",
        raw_value=None,
        raw_unit="",
        source_name="Manual",
    ):
        date = pd.Timestamp(observed_at).date().isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO observations(
                    site_id, observed_at, cumulative, uncertainty, note,
                    raw_value, raw_unit, source_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, observed_at) DO UPDATE SET
                    cumulative=excluded.cumulative,
                    uncertainty=excluded.uncertainty,
                    note=excluded.note,
                    raw_value=excluded.raw_value,
                    raw_unit=excluded.raw_unit,
                    source_name=excluded.source_name,
                    created_at=CURRENT_TIMESTAMP
                """,
                (
                    site_id,
                    date,
                    float(cumulative),
                    float(uncertainty),
                    note,
                    None if raw_value is None else float(raw_value),
                    raw_unit,
                    source_name,
                ),
            )

    def upsert_observations(self, site_id: str, observations: pd.DataFrame):
        """Guarda una carga validada dentro de una única transacción."""
        rows = []
        for row in observations.itertuples(index=False):
            rows.append(
                (
                    site_id,
                    pd.Timestamp(row.Fecha).date().isoformat(),
                    float(row.Observado),
                    float(row.Incertidumbre),
                    str(getattr(row, "Nota", "")),
                    float(row.Valor_original),
                    str(getattr(row, "Unidad_original", "")),
                    str(getattr(row, "Fuente", "Archivo cargado")),
                )
            )
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO observations(
                    site_id, observed_at, cumulative, uncertainty, note,
                    raw_value, raw_unit, source_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, observed_at) DO UPDATE SET
                    cumulative=excluded.cumulative,
                    uncertainty=excluded.uncertainty,
                    note=excluded.note,
                    raw_value=excluded.raw_value,
                    raw_unit=excluded.raw_unit,
                    source_name=excluded.source_name,
                    created_at=CURRENT_TIMESTAMP
                """,
                rows,
            )

    def observations(self, site_id: str) -> pd.DataFrame:
        with self.connect() as connection:
            return pd.read_sql_query(
                """
                SELECT observed_at AS Fecha, cumulative AS Observado,
                       uncertainty AS Incertidumbre, raw_value AS Valor_original,
                       raw_unit AS Unidad_original, source_name AS Fuente,
                       note AS Nota, created_at AS Registrado
                FROM observations WHERE site_id=? ORDER BY observed_at
                """,
                connection,
                params=(site_id,),
                parse_dates=["Fecha", "Registrado"],
            )

    def save_snapshot(self, snapshot: dict):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO snapshots(site_id, as_of, payload) VALUES (?, ?, ?)",
                (snapshot["site_id"], snapshot["as_of"], json.dumps(snapshot, ensure_ascii=False)),
            )
