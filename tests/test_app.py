from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from virtual_equipment.models import FaultType
from virtual_equipment.monitor import EquipmentMonitor
from virtual_equipment.storage import Storage


@pytest.mark.parametrize("fault", list(FaultType))
def test_dashboard_reruns_do_not_advance_time_and_controls_work(tmp_path, fault):
    storage = Storage(tmp_path / "equipment.db")
    monitor = EquipmentMonitor(42, storage)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
    app.session_state["storage"] = storage
    app.session_state["monitor"] = monitor
    # Freeze the time gate, independently of test execution speed.
    app.session_state["last_tick_at"] = float("inf")
    app.run()
    assert not app.exception
    assert monitor.simulator.sample_idx == 0
    for _ in range(60):
        monitor.step()
    app.run()
    assert not app.exception
    assert monitor.simulator.sample_idx == 60
    next(select for select in app.selectbox if select.label == "Fault type").select(fault.value).run()
    inject = next(button for button in app.button if button.label == "Inject Fault")
    inject.click().run()
    assert not app.exception
    assert monitor.simulator.fault_active
    assert monitor.simulator.injection.fault_type == fault
    assert monitor.simulator.sample_idx == 60
    for _ in range(30):
        monitor.step()
    app.run()
    expected_trip = fault in (FaultType.VACUUM_LEAK, FaultType.COOLING_FAILURE)
    assert monitor.interlock.latched == expected_trip
    next(button for button in app.button if button.label == "ACK").click().run()
    assert monitor.interlock.latched == expected_trip
    next(button for button in app.button if button.label == "Complete Run").click().run()
    assert monitor.finished
    assert not app.exception
    assert len(storage.telemetry(monitor.run_id)) == 90
    next(button for button in app.button if button.label == "Export Run CSV").click().run()
    export_id, csv_data = app.session_state["export_data"]
    assert export_id == monitor.run_id
    assert len(csv_data.decode("utf-8-sig").splitlines()) == 91
    assert not app.exception
