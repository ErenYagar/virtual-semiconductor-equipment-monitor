"""Shared typed records; telemetry contains no injection labels."""
from dataclasses import asdict, dataclass
from enum import StrEnum


SIGNALS = ("temperature_c", "pressure_mtorr", "gas_flow_sccm", "rf_power_w", "pump_current_a")


class FaultType(StrEnum):
    VACUUM_LEAK = "VACUUM_LEAK"
    COOLING_FAILURE = "COOLING_FAILURE"
    GAS_FLOW_DRIFT = "GAS_FLOW_DRIFT"
    PUMP_DEGRADATION = "PUMP_DEGRADATION"


class EquipmentState(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    TRIPPED = "TRIPPED"
    SAFE_HOLD = "SAFE_HOLD"
    RECOVERING = "RECOVERING"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Commands:
    rf_power_w: float = 500.0
    gas_flow_sccm: float = 100.0


@dataclass(frozen=True)
class Telemetry:
    sample_idx: int
    ts_utc: str
    temperature_c: float
    pressure_mtorr: float
    gas_flow_sccm: float
    rf_power_w: float
    pump_current_a: float
    equipment_state: EquipmentState = EquipmentState.NORMAL
    interlock_active: bool = False

    def values(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in SIGNALS}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DetectionResult:
    method: str
    signal: str
    alarm: bool
    severity: Severity
    score: float
    message: str


@dataclass(frozen=True)
class Candidate:
    cause: str
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Diagnosis:
    decision: str
    candidates: tuple[Candidate, ...]
    ambiguous: bool
    feature_values: dict[str, dict[str, float]]
    method: str = "telemetry_rules_v1"


@dataclass(frozen=True)
class Event:
    sample_idx: int
    ts_utc: str
    event_type: str
    severity: Severity
    source: str
    code: str
    message: str
    details: dict
