"""Read and validate the synthetic demonstration parameters."""
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from .models import FaultType, SIGNALS


@dataclass(frozen=True)
class SensorConfig:
    mean: float
    sigma: float
    warning_low: float
    warning_high: float


@dataclass(frozen=True)
class EquipmentConfig:
    sample_period_s: float
    recovery_alpha: float
    baseline_samples: int
    sensors: dict[str, SensorConfig]
    hard_trip: dict[str, float]
    safe_recovery: dict[str, float]
    safe_samples_required: int
    rf_ramp_w_per_s: float
    gas_ramp_sccm_per_s: float


@dataclass(frozen=True)
class FaultConfig:
    default_duration_s: int
    signatures: dict[str, dict[str, float]]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_equipment(path: Path | None = None) -> EquipmentConfig:
    raw = json.loads((path or project_root() / "config" / "equipment.json").read_text(encoding="utf-8"))
    raw["sensors"] = {key: SensorConfig(**value) for key, value in raw["sensors"].items()}
    config = EquipmentConfig(**raw)
    if set(config.sensors) != set(SIGNALS):
        raise ValueError("Configuration must define exactly the five telemetry signals")
    for name, sensor in config.sensors.items():
        if not all(isfinite(v) for v in vars(sensor).values()):
            raise ValueError(f"Non-finite sensor configuration: {name}")
        if sensor.sigma <= 0 or not sensor.warning_low < sensor.mean < sensor.warning_high:
            raise ValueError(f"Invalid sigma or warning range: {name}")
    if config.sample_period_s != 1.0 or config.baseline_samples < 3:
        raise ValueError("This demo requires 1 Hz sampling and at least three baseline samples")
    if not 0 < config.recovery_alpha <= 1 or config.safe_samples_required < 1:
        raise ValueError("Invalid recovery alpha or safe-sample count")
    if config.rf_ramp_w_per_s <= 0 or config.gas_ramp_sccm_per_s <= 0:
        raise ValueError("Recovery ramp increments must be positive")
    return config


def load_faults(path: Path | None = None) -> FaultConfig:
    config = FaultConfig(**json.loads((path or project_root() / "config" / "faults.json").read_text(encoding="utf-8")))
    if config.default_duration_s < 1 or set(config.signatures) != {f.value for f in FaultType}:
        raise ValueError("Fault configuration must define all four signatures and a positive duration")
    for signature in config.signatures.values():
        if not set(signature) <= set(SIGNALS) or not all(isfinite(v) for v in signature.values()):
            raise ValueError("Invalid fault signature")
    return config
