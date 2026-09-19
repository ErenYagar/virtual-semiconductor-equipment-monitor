"""Seeded 1 Hz virtual machine with explicit actuator commands."""
from datetime import datetime, timedelta, timezone

import numpy as np

from .config import EquipmentConfig, FaultConfig, load_equipment, load_faults
from .faults import FaultInjection, fault_targets
from .models import Commands, FaultType, Telemetry


class Simulator:
    def __init__(self, seed: int = 42, config: EquipmentConfig | None = None,
                 faults: FaultConfig | None = None, started_at: datetime | None = None):
        if not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        self.seed = seed
        self.config = config or load_equipment()
        self.faults = faults or load_faults()
        self.rng = np.random.default_rng(seed)
        self.started_at = started_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
        if self.started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        self.sample_idx = 0
        self.injection: FaultInjection | None = None
        self._values = {name: sensor.mean for name, sensor in self.config.sensors.items()}
        self._recovering = False
        self._was_active = False

    @property
    def fault_active(self) -> bool:
        return self.injection is not None and self.injection.active_at(self.sample_idx)

    def inject(self, fault: FaultType, duration_s: int | None = None) -> FaultInjection:
        if self.fault_active:
            raise ValueError("A fault is already active")
        self.injection = FaultInjection(fault, self.sample_idx,
                                        self.faults.default_duration_s if duration_s is None else duration_s)
        return self.injection

    def step(self, commands: Commands = Commands()) -> Telemetry:
        """Advance exactly one simulated second without wall-clock sleeping."""
        if not 0 <= commands.rf_power_w <= 500 or not 0 <= commands.gas_flow_sccm <= 100:
            raise ValueError("Commands must be in the demo actuator ranges")
        active = self.fault_active
        targets = {name: sensor.mean for name, sensor in self.config.sensors.items()}
        if active:
            targets = fault_targets(self.injection.fault_type,
                                    self.injection.elapsed_at(self.sample_idx), self.config, self.faults)
        if self._was_active and not active:
            self._recovering = True
        # Gas drift scales with the demanded gas; shutdown commands take precedence.
        targets["gas_flow_sccm"] *= commands.gas_flow_sccm / 100.0
        targets["rf_power_w"] = commands.rf_power_w
        for name, sensor in self.config.sensors.items():
            target = targets[name]
            if self._recovering and not active and name not in ("gas_flow_sccm", "rf_power_w"):
                target = self._values[name] + self.config.recovery_alpha * (target - self._values[name])
            elif self._recovering and not active and name == "gas_flow_sccm" and commands.gas_flow_sccm == 100:
                target = self._values[name] + self.config.recovery_alpha * (target - self._values[name])
            value = target + float(self.rng.normal(0.0, sensor.sigma))
            self._values[name] = max(0.0, value) if name in ("gas_flow_sccm", "rf_power_w") else value
        # End the recovery transient once all process signals are close to normal.
        if self._recovering and not active and commands == Commands():
            self._recovering = not all(abs(self._values[n] - s.mean) <= 2 * s.sigma
                                       for n, s in self.config.sensors.items())
        sample = Telemetry(self.sample_idx,
                           (self.started_at + timedelta(seconds=self.sample_idx)).astimezone(timezone.utc).isoformat(),
                           **self._values)
        self.sample_idx += 1
        self._was_active = active
        return sample
