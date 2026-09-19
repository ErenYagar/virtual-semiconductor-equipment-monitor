import pytest

from virtual_equipment.faults import FaultInjection, fault_targets
from virtual_equipment.models import FaultType


@pytest.mark.parametrize("t", [10, 20, 30])
def test_vacuum_leak_formula(t):
    values = fault_targets(FaultType.VACUUM_LEAK, t)
    assert values["pressure_mtorr"] == pytest.approx(10 + 0.40 * t)
    assert values["pump_current_a"] == pytest.approx(3 + 0.005 * t)
    assert values["temperature_c"] == 60


@pytest.mark.parametrize("t", [10, 20, 30])
def test_cooling_formula(t):
    assert fault_targets(FaultType.COOLING_FAILURE, t)["temperature_c"] == pytest.approx(60 + 0.55 * t)


@pytest.mark.parametrize("t", [10, 20, 30])
def test_flow_formula(t):
    values = fault_targets(FaultType.GAS_FLOW_DRIFT, t)
    assert values["gas_flow_sccm"] == pytest.approx(100 - 0.50 * t)
    assert values["pressure_mtorr"] == pytest.approx(10 - 0.02 * t)


@pytest.mark.parametrize("t", [10, 20, 30])
def test_pump_formula(t):
    values = fault_targets(FaultType.PUMP_DEGRADATION, t)
    assert values["pump_current_a"] == pytest.approx(3 + 0.020 * t)
    assert values["pressure_mtorr"] == pytest.approx(10 + 0.12 * t)


def test_fault_timing_and_invalid_inputs():
    injection = FaultInjection(FaultType.VACUUM_LEAK, 60, 30)
    assert not injection.active_at(59)
    assert injection.elapsed_at(60) == 1
    assert injection.elapsed_at(89) == 30
    assert not injection.active_at(90)
    with pytest.raises(ValueError):
        injection.elapsed_at(90)
    with pytest.raises(ValueError):
        FaultInjection(FaultType.VACUUM_LEAK, 0, 0)
    with pytest.raises(ValueError):
        fault_targets(FaultType.VACUUM_LEAK, float("nan"))


def test_injection_normalizes_enum_after_module_reload():
    from enum import StrEnum
    class ReloadedFault(StrEnum):
        VACUUM_LEAK = "VACUUM_LEAK"
    injection = FaultInjection(ReloadedFault.VACUUM_LEAK, 60, 30)
    assert injection.fault_type is FaultType.VACUUM_LEAK
