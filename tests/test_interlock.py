import pytest

from virtual_equipment.interlock import Interlock
from virtual_equipment.models import Commands, EquipmentState


def trip(controller, sample_factory):
    return controller.update(sample_factory(temperature_c=75), fault_active=True)


@pytest.mark.parametrize("values", [{"temperature_c": 75}, {"pressure_mtorr": 20},
                                       {"gas_flow_sccm": 80}, {"pump_current_a": 4}])
def test_each_hard_threshold_trips(values, sample_factory):
    controller = Interlock()
    events = controller.update(sample_factory(**values), fault_active=True)
    assert controller.state == EquipmentState.TRIPPED
    assert controller.latched
    assert controller.commands == Commands(0, 0)
    assert events[0].severity == "CRITICAL"
    assert controller.trip_reason


def test_ack_does_not_reset(sample_factory):
    controller = Interlock()
    trip(controller, sample_factory)
    reason = controller.trip_reason
    assert controller.acknowledge(sample_factory()).code == "ACK"
    assert controller.latched and controller.trip_reason == reason
    assert controller.state == EquipmentState.TRIPPED
    assert controller.commands == Commands(0, 0)


def test_unsafe_or_active_fault_cannot_recover(sample_factory):
    controller = Interlock()
    trip(controller, sample_factory)
    for _ in range(20):
        controller.update(sample_factory(temperature_c=69), fault_active=False)
    assert controller.state == EquipmentState.SAFE_HOLD
    for _ in range(20):
        controller.update(sample_factory(), fault_active=True)
    assert controller.safe_count == 0 and controller.latched


def test_ten_consecutive_safe_samples_allow_recovery(sample_factory):
    controller = Interlock()
    trip(controller, sample_factory)
    for _ in range(9):
        controller.update(sample_factory(gas_flow_sccm=0), fault_active=False)
        assert controller.state == EquipmentState.SAFE_HOLD
    controller.update(sample_factory(temperature_c=68), fault_active=False)
    assert controller.safe_count == 0
    for _ in range(10):
        events = controller.update(sample_factory(gas_flow_sccm=0), fault_active=False)
    assert controller.state == EquipmentState.RECOVERING
    assert controller.latched
    assert events[-1].code == "RECOVERY_STARTED"


def recovering(sample_factory):
    controller = Interlock()
    trip(controller, sample_factory)
    for _ in range(10):
        controller.update(sample_factory(), fault_active=False)
    return controller


def test_ramp_increments_and_full_command_verification(sample_factory):
    controller = recovering(sample_factory)
    for step in range(1, 6):
        controller.update(sample_factory(gas_flow_sccm=controller.commands.gas_flow_sccm), False)
        assert controller.commands == Commands(100 * step, 20 * step)
        assert controller.latched
    controller.update(sample_factory(), False)
    assert controller.state == EquipmentState.NORMAL
    assert not controller.latched


def test_retrip_during_recovery(sample_factory):
    controller = recovering(sample_factory)
    events = controller.update(sample_factory(temperature_c=76), False)
    assert events[0].code == "TRIP"
    assert controller.state == EquipmentState.TRIPPED
    assert controller.commands == Commands(0, 0)


def test_low_flow_retrips_when_full_demand_returns(sample_factory):
    controller = recovering(sample_factory)
    for _ in range(5):
        controller.update(sample_factory(), False)
    controller.update(sample_factory(gas_flow_sccm=70), False)
    assert controller.state == EquipmentState.TRIPPED


def test_manual_reset_requires_safe_dwell(sample_factory):
    controller = Interlock(auto_recovery=False)
    trip(controller, sample_factory)
    with pytest.raises(ValueError):
        controller.manual_reset()
    for _ in range(10):
        controller.update(sample_factory(), False)
    assert controller.state == EquipmentState.SAFE_HOLD
    assert controller.manual_reset().code == "RECOVERY_STARTED"
    assert controller.state == EquipmentState.RECOVERING
