"""Latched demonstration interlock with safe dwell and actuator recovery."""
from .config import EquipmentConfig, load_equipment
from .models import Commands, EquipmentState, Event, Severity, Telemetry


class Interlock:
    def __init__(self, auto_recovery: bool = True, config: EquipmentConfig | None = None):
        self.config = config or load_equipment()
        self.auto_recovery = auto_recovery
        self.state = EquipmentState.NORMAL
        self.latched = False
        self.trip_reason: str | None = None
        self.safe_count = 0
        self.commands = Commands()
        self._latest: Telemetry | None = None
        self._fault_active = False

    def _event(self, sample: Telemetry, code: str, message: str,
               severity: Severity = Severity.INFO) -> Event:
        return Event(sample.sample_idx, sample.ts_utc, code, severity, "interlock", code,
                     message, {"state": self.state.value, "safe_count": self.safe_count,
                               "trip_reason": self.trip_reason})

    def hard_reasons(self, sample: Telemetry) -> list[str]:
        limits = self.config.hard_trip
        reasons = [f"{name} >= {limits[name]}" for name in
                   ("temperature_c", "pressure_mtorr", "pump_current_a")
                   if getattr(sample, name) >= limits[name]]
        # The low-flow permissive is enabled only at full gas demand. A shutdown
        # or partial ramp intentionally commands less than the low-flow limit.
        if self.commands.gas_flow_sccm >= 100 and sample.gas_flow_sccm <= limits["gas_flow_sccm"]:
            reasons.append(f"gas_flow_sccm <= {limits['gas_flow_sccm']} at full demand")
        return reasons

    def update(self, sample: Telemetry, fault_active: bool, anomaly: bool = False) -> list[Event]:
        self._latest, self._fault_active = sample, fault_active
        events = []
        reasons = self.hard_reasons(sample)
        if reasons and (not self.latched or self.state == EquipmentState.RECOVERING):
            self.state, self.latched = EquipmentState.TRIPPED, True
            self.trip_reason = "; ".join(reasons)
            self.commands, self.safe_count = Commands(0, 0), 0
            return [self._event(sample, "TRIP", self.trip_reason, Severity.CRITICAL)]
        if self.state == EquipmentState.TRIPPED:
            self.state = EquipmentState.SAFE_HOLD
            events.append(self._event(sample, "SAFE_HOLD", "Actuators held at zero; interlock remains latched"))
        if self.state == EquipmentState.SAFE_HOLD:
            safe = not fault_active and all(getattr(sample, name) < limit
                                            for name, limit in self.config.safe_recovery.items())
            self.safe_count = self.safe_count + 1 if safe else 0
            if self.auto_recovery and self.safe_count >= self.config.safe_samples_required:
                events.append(self._begin_recovery(sample))
        elif self.state == EquipmentState.RECOVERING:
            # Remain latched until one sample has been checked at full commands.
            if self.commands == Commands():
                self.state, self.latched, self.safe_count = EquipmentState.NORMAL, False, 0
                events.append(self._event(sample, "RECOVERY_COMPLETE", "Full actuator demand verified; latch cleared"))
            else:
                self.commands = Commands(min(500, self.commands.rf_power_w + self.config.rf_ramp_w_per_s),
                                         min(100, self.commands.gas_flow_sccm + self.config.gas_ramp_sccm_per_s))
        elif not self.latched:
            self.state = EquipmentState.WARNING if anomaly else EquipmentState.NORMAL
        return events

    def _begin_recovery(self, sample: Telemetry) -> Event:
        self.state = EquipmentState.RECOVERING
        return self._event(sample, "RECOVERY_STARTED", "Safe dwell satisfied; starting actuator ramp")

    def acknowledge(self, sample: Telemetry) -> Event:
        """Record operator acknowledgement without modifying the latch."""
        return self._event(sample, "ACK", "Operator acknowledged; acknowledgement does not reset the interlock")

    def manual_reset(self) -> Event:
        if self.state != EquipmentState.SAFE_HOLD or self.safe_count < self.config.safe_samples_required:
            raise ValueError("Manual reset requires SAFE_HOLD and ten consecutive fault-inactive safe samples")
        if self._fault_active or self._latest is None:
            raise ValueError("Cannot reset while a fault is active or before sampling")
        return self._begin_recovery(self._latest)
