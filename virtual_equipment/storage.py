"""SQLite history with parameterized writes and explicitly closed connections."""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

import pandas as pd

from .faults import FaultInjection
from .models import Diagnosis, Event, Telemetry


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, started_at_utc TEXT NOT NULL, ended_at_utc TEXT,
 seed INTEGER NOT NULL, sample_period_s REAL NOT NULL, mode TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS telemetry (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(run_id),
 sample_idx INTEGER NOT NULL, ts_utc TEXT NOT NULL, temperature_c REAL NOT NULL,
 pressure_mtorr REAL NOT NULL, gas_flow_sccm REAL NOT NULL, rf_power_w REAL NOT NULL,
 pump_current_a REAL NOT NULL, equipment_state TEXT NOT NULL, interlock_active INTEGER NOT NULL,
 UNIQUE(run_id, sample_idx)
);
CREATE TABLE IF NOT EXISTS fault_injections (
 injection_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
 fault_type TEXT NOT NULL, start_sample_idx INTEGER NOT NULL, duration_s REAL NOT NULL,
 seed INTEGER NOT NULL, params_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(run_id),
 sample_idx INTEGER NOT NULL, ts_utc TEXT NOT NULL, event_type TEXT NOT NULL,
 severity TEXT NOT NULL, source TEXT NOT NULL, code TEXT NOT NULL,
 message TEXT NOT NULL, details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnoses (
 diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(run_id),
 sample_idx INTEGER NOT NULL, episode_id TEXT NOT NULL, top1_cause TEXT NOT NULL,
 top1_score REAL NOT NULL, top2_cause TEXT, top2_score REAL, evidence_json TEXT NOT NULL,
 method TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_run_sample ON telemetry(run_id, sample_idx);
CREATE INDEX IF NOT EXISTS idx_events_run_sample ON events(run_id, sample_idx);
CREATE INDEX IF NOT EXISTS idx_diagnoses_run_sample ON diagnoses(run_id, sample_idx);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_run(self, run_id: str, started_at_utc: str, seed: int, mode: str,
                   sample_period_s: float = 1.0, notes: str = "") -> None:
        with self.connection() as connection:
            connection.execute("INSERT INTO runs VALUES (?, ?, NULL, ?, ?, ?, ?)",
                               (run_id, started_at_utc, seed, sample_period_s, mode, notes))

    def finish_run(self, run_id: str, ended_at_utc: str) -> None:
        with self.connection() as connection:
            connection.execute("UPDATE runs SET ended_at_utc = ? WHERE run_id = ?", (ended_at_utc, run_id))

    def save_injection(self, run_id: str, injection: FaultInjection, seed: int, params: dict) -> None:
        with self.connection() as connection:
            connection.execute("INSERT INTO fault_injections VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (str(uuid4()), run_id, injection.fault_type.value, injection.start_sample_idx,
                                injection.duration_s, seed, json.dumps(params)))

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, run_id: str, event: Event) -> None:
        connection.execute("""INSERT INTO events
            (run_id, sample_idx, ts_utc, event_type, severity, source, code, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (run_id, event.sample_idx, event.ts_utc, event.event_type, event.severity.value,
                            event.source, event.code, event.message, json.dumps(event.details)))

    def save_event(self, run_id: str, event: Event) -> None:
        with self.connection() as connection:
            self._insert_event(connection, run_id, event)

    def save_tick(self, run_id: str, sample: Telemetry, events: list[Event],
                  diagnosis: Diagnosis | None = None, episode_id: str = "") -> None:
        """Commit sample, associated events and diagnosis atomically."""
        with self.connection() as connection:
            self._insert_tick(connection, run_id, sample, events, diagnosis, episode_id)

    def _insert_tick(self, connection: sqlite3.Connection, run_id: str, sample: Telemetry,
                     events: list[Event], diagnosis: Diagnosis | None, episode_id: str) -> None:
        connection.execute("""INSERT INTO telemetry
            (run_id, sample_idx, ts_utc, temperature_c, pressure_mtorr, gas_flow_sccm,
             rf_power_w, pump_current_a, equipment_state, interlock_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (run_id, sample.sample_idx, sample.ts_utc, sample.temperature_c,
                            sample.pressure_mtorr, sample.gas_flow_sccm, sample.rf_power_w,
                            sample.pump_current_a, sample.equipment_state.value, int(sample.interlock_active)))
        for event in events:
            self._insert_event(connection, run_id, event)
        if diagnosis is not None:
            first, second = diagnosis.candidates[:2]
            evidence = {"decision": diagnosis.decision, "ambiguous": diagnosis.ambiguous,
                        "candidates": [asdict(c) for c in diagnosis.candidates],
                        "features": diagnosis.feature_values}
            connection.execute("""INSERT INTO diagnoses
                (run_id, sample_idx, episode_id, top1_cause, top1_score, top2_cause,
                 top2_score, evidence_json, method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                               (run_id, sample.sample_idx, episode_id, first.cause, first.score,
                                second.cause, second.score, json.dumps(evidence), diagnosis.method))

    def save_batch(self, run_id: str, ticks: list) -> None:
        """One transaction for a completed batch run; no per-sample connection cost."""
        with self.connection() as connection:
            for tick in ticks:
                self._insert_tick(connection, run_id, tick.sample, tick.events, tick.diagnosis, tick.episode_id)

    def telemetry(self, run_id: str, limit: int | None = None) -> pd.DataFrame:
        with self.connection() as connection:
            if limit is None:
                return pd.read_sql_query("SELECT * FROM telemetry WHERE run_id = ? ORDER BY sample_idx",
                                         connection, params=(run_id,))
            if limit < 1:
                raise ValueError("limit must be positive")
            return pd.read_sql_query("""SELECT * FROM
                (SELECT * FROM telemetry WHERE run_id = ? ORDER BY sample_idx DESC LIMIT ?)
                ORDER BY sample_idx""", connection, params=(run_id, limit))

    def runs(self) -> pd.DataFrame:
        with self.connection() as connection:
            return pd.read_sql_query("SELECT * FROM runs ORDER BY started_at_utc DESC, rowid DESC", connection)

    def events(self, run_id: str, limit: int = 50) -> pd.DataFrame:
        with self.connection() as connection:
            return pd.read_sql_query("SELECT * FROM events WHERE run_id = ? ORDER BY event_id DESC LIMIT ?",
                                     connection, params=(run_id, limit))

    def diagnoses(self, run_id: str) -> pd.DataFrame:
        with self.connection() as connection:
            return pd.read_sql_query("SELECT * FROM diagnoses WHERE run_id = ? ORDER BY sample_idx",
                                     connection, params=(run_id,))

    def export_csv(self, run_id: str) -> bytes:
        return self.telemetry(run_id).to_csv(index=False).encode("utf-8-sig")
