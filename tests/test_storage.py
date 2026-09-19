import sqlite3

import pandas as pd
import pytest

from virtual_equipment.models import FaultType
from virtual_equipment.monitor import run_batch
from virtual_equipment.storage import Storage


def test_sample_insert_query_roundtrip_and_history(tmp_path, normal_sample):
    path = tmp_path / "nested" / "equipment.db"
    storage = Storage(path)
    run_id = "run'; DROP TABLE telemetry;--"
    storage.create_run(run_id, normal_sample.ts_utc, 42, "test")
    storage.save_tick(run_id, normal_sample, [])
    restored = Storage(path).telemetry(run_id)
    assert len(restored) == 1
    assert restored.iloc[0].temperature_c == normal_sample.temperature_c
    assert restored.iloc[0].run_id == run_id
    assert len(storage.telemetry(run_id, limit=1)) == 1
    storage.finish_run(run_id, normal_sample.ts_utc)
    assert storage.runs().iloc[0].ended_at_utc == normal_sample.ts_utc
    assert b"temperature_c" in storage.export_csv(run_id)


def test_batch_persists_ground_truth_separately_events_and_diagnoses(tmp_path):
    storage = Storage(tmp_path / "equipment.db")
    monitor = run_batch(42, FaultType.COOLING_FAILURE, storage)
    telemetry = storage.telemetry(monitor.run_id)
    assert len(telemetry) == 120
    assert "fault_type" not in telemetry.columns
    assert len(storage.diagnoses(monitor.run_id)) > 0
    assert "TRIP" in storage.events(monitor.run_id, 200).event_type.tolist()
    assert pd.notna(storage.runs().iloc[0].ended_at_utc)
    with storage.connection() as connection:
        row = connection.execute("SELECT * FROM fault_injections WHERE run_id = ?", (monitor.run_id,)).fetchone()
    assert row["fault_type"] == "COOLING_FAILURE"
    assert row["start_sample_idx"] == 60
    assert row["duration_s"] == 30


def test_duplicate_sample_rolls_back_and_connection_closes(tmp_path, normal_sample):
    storage = Storage(tmp_path / "equipment.db")
    storage.create_run("a", normal_sample.ts_utc, 42, "test")
    storage.save_tick("a", normal_sample, [])
    with pytest.raises(sqlite3.IntegrityError):
        storage.save_tick("a", normal_sample, [])
    assert len(storage.telemetry("a")) == 1
    with storage.connection() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
