"""Synthetic fault signatures and injection ground truth."""
from dataclasses import dataclass
from math import isfinite

from .config import EquipmentConfig, FaultConfig, load_equipment, load_faults
from .models import FaultType


@dataclass(frozen=True)
class FaultInjection:
    fault_type: FaultType
    start_sample_idx: int
    duration_s: int = 30

    def __post_init__(self) -> None:
        try:
            # Normalize StrEnum values across Streamlit module reloads too.
            object.__setattr__(self, "fault_type", FaultType(self.fault_type))
        except ValueError as error:
            raise ValueError(f"Unsupported fault_type: {self.fault_type}") from error
        if not isinstance(self.start_sample_idx, int) or self.start_sample_idx < 0:
            raise ValueError("start_sample_idx must be a nonnegative integer")
        if not isinstance(self.duration_s, int) or self.duration_s < 1:
            raise ValueError("duration_s must be a positive integer at 1 Hz")

    def active_at(self, sample_idx: int) -> bool:
        return self.start_sample_idx <= sample_idx < self.start_sample_idx + self.duration_s

    def elapsed_at(self, sample_idx: int) -> int:
        """The first active sample uses t=1; the last uses t=duration."""
        if not self.active_at(sample_idx):
            raise ValueError("Sample is outside the active injection interval")
        return sample_idx - self.start_sample_idx + 1


def fault_targets(fault: FaultType, elapsed_s: float,
                  equipment: EquipmentConfig | None = None,
                  faults: FaultConfig | None = None) -> dict[str, float]:
    """Return noise-free synthetic targets, never physical equipment limits."""
    if not isfinite(elapsed_s) or elapsed_s < 0:
        raise ValueError("elapsed_s must be finite and nonnegative")
    equipment, faults = equipment or load_equipment(), faults or load_faults()
    if fault not in faults.signatures:
        raise ValueError(f"Unsupported fault: {fault}")
    targets = {name: sensor.mean for name, sensor in equipment.sensors.items()}
    for signal, slope in faults.signatures[fault].items():
        targets[signal] += slope * elapsed_s
    return targets
