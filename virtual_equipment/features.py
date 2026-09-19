"""Label-free baseline fitting and telemetry feature extraction."""
from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .models import SIGNALS, Telemetry


@dataclass(frozen=True)
class Baseline:
    means: dict[str, float]
    stds: dict[str, float]

    @classmethod
    def fit(cls, samples: Sequence[Telemetry]) -> "Baseline":
        if len(samples) < 3:
            raise ValueError("Baseline requires at least three samples")
        values = np.array([[getattr(s, n) for n in SIGNALS] for s in samples], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Baseline values must be finite")
        stds = values.std(axis=0, ddof=1)
        if (stds <= 0).any():
            raise ValueError("Every baseline signal must have nonzero sample standard deviation")
        return cls(dict(zip(SIGNALS, values.mean(axis=0).tolist())), dict(zip(SIGNALS, stds.tolist())))


@dataclass(frozen=True)
class FeatureSet:
    signals: dict[str, dict[str, float]]
    pressure_current_correlation: float | None


def extract_features(samples: Sequence[Telemetry], baseline: Baseline) -> FeatureSet:
    """Use up to 10 samples for moments/slopes and 20 for correlation."""
    if not samples:
        raise ValueError("Feature extraction requires telemetry")
    recent = samples[-10:]
    times = np.array([s.sample_idx for s in recent], dtype=float)
    centered = times - times.mean()
    denominator = float(centered @ centered)
    if len(times) > 1 and (np.diff(times) <= 0).any():
        raise ValueError("Samples must be ordered with strictly increasing indices at 1 Hz")
    features = {}
    for name in SIGNALS:
        values = np.array([getattr(s, name) for s in recent], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"Non-finite telemetry: {name}")
        features[name] = {
            "last": float(values[-1]),
            "z": float((values[-1] - baseline.means[name]) / baseline.stds[name]),
            "mean": float(values.mean()),
            "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            "slope": float(centered @ values / denominator) if denominator else 0.0,
        }
    window = samples[-20:]
    pressure = np.array([s.pressure_mtorr for s in window])
    current = np.array([s.pump_current_a for s in window])
    correlation = None
    if len(window) > 2 and pressure.std() > 0 and current.std() > 0:
        correlation = float(np.corrcoef(pressure, current)[0, 1])
    return FeatureSet(features, correlation)
