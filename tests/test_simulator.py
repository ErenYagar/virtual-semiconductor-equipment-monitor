import pytest

from virtual_equipment.models import Commands, FaultType
from virtual_equipment.monitor import run_batch
from virtual_equipment.simulator import Simulator


def test_same_seed_and_commands_are_reproducible():
    first, second = Simulator(42), Simulator(42)
    first.inject(FaultType.COOLING_FAILURE)
    second.inject(FaultType.COOLING_FAILURE)
    for idx in range(70):
        command = Commands(0, 0) if 25 <= idx < 50 else Commands()
        assert first.step(command) == second.step(command)


def test_different_seed_changes_noise():
    assert Simulator(42).step().values() != Simulator(43).step().values()


def test_fault_expires_after_exact_duration():
    simulator = Simulator(42)
    simulator.inject(FaultType.COOLING_FAILURE, 30)
    for _ in range(30):
        assert simulator.fault_active
        simulator.step()
    assert not simulator.fault_active
    previous = simulator._values["temperature_c"]
    recovered = simulator.step()
    assert 60 < recovered.temperature_c < previous


def test_recovery_equation_matches_noise_sequence():
    import numpy as np
    simulator = Simulator(17)
    simulator.inject(FaultType.COOLING_FAILURE, 1)
    first = simulator.step()
    rng = np.random.default_rng(17)
    for sensor in simulator.config.sensors.values():
        rng.normal(0, sensor.sigma)
    expected = first.temperature_c + 0.25 * (60 - first.temperature_c) + rng.normal(0, 0.25)
    assert simulator.step().temperature_c == pytest.approx(expected)


@pytest.mark.parametrize("fault", list(FaultType))
def test_batch_contract_and_diagnosis(fault):
    run = run_batch(42, fault)
    assert len(run.ticks) == 120
    assert run.ticks[59].sample.sample_idx == 59
    assert any(t.alarm for t in run.ticks[60:90])
    assert any(t.diagnosis and t.diagnosis.candidates[0].cause == fault.value for t in run.ticks[60:90])
    assert not run.simulator.fault_active


@pytest.mark.parametrize("fault", [FaultType.COOLING_FAILURE, FaultType.VACUUM_LEAK])
def test_full_trip_and_recovery_path(fault):
    run = run_batch(42, fault)
    codes = [event.code for tick in run.ticks for event in tick.events]
    assert all(code in codes for code in ("TRIP", "SAFE_HOLD", "RECOVERY_STARTED", "RECOVERY_COMPLETE"))
    assert codes.count("TRIP") == 1
    assert not run.interlock.latched


def test_bad_seed_and_commands():
    with pytest.raises(ValueError, match="seed"):
        Simulator(-1)
    with pytest.raises(ValueError, match="Commands"):
        Simulator().step(Commands(-1, 100))
