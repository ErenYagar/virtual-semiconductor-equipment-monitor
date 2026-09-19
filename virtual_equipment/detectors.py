"""Telemetry-only anomaly detectors; safety trips live in interlock.py."""
from collections import deque
from math import sqrt

from .config import EquipmentConfig, load_equipment
from .features import Baseline
from .models import DetectionResult, Severity, SIGNALS, Telemetry


def result(method: str, signal: str, alarm: bool, score: float, message: str) -> DetectionResult:
    return DetectionResult(method, signal, bool(alarm), Severity.WARNING if alarm else Severity.INFO,
                           float(score), message)


class ThresholdDetector:
    def __init__(self, config: EquipmentConfig | None = None):
        self.config = config or load_equipment()

    def detect(self, sample: Telemetry) -> list[DetectionResult]:
        results = []
        for name, sensor in self.config.sensors.items():
            value = getattr(sample, name)
            alarm = value < sensor.warning_low or value > sensor.warning_high
            score = abs(value - sensor.mean) / sensor.sigma
            results.append(result("threshold", name, alarm, score,
                                  f"{value:.3f}; warning band [{sensor.warning_low}, {sensor.warning_high}]"))
        return results


class SPCDetector:
    def __init__(self, baseline: Baseline):
        self.baseline = baseline
        self.history = {name: deque(maxlen=3) for name in SIGNALS}

    def detect(self, sample: Telemetry) -> list[DetectionResult]:
        results = []
        for name in SIGNALS:
            z = (getattr(sample, name) - self.baseline.means[name]) / self.baseline.stds[name]
            self.history[name].append(abs(z) > 3)
            alarm = sum(self.history[name]) >= 2
            results.append(result("SPC", name, alarm, abs(z),
                                  f"z={z:.2f}; {sum(self.history[name])}/3 raw violations (requires 2)"))
        return results

    def limits(self, signal: str) -> tuple[float, float]:
        mean, std = self.baseline.means[signal], self.baseline.stds[signal]
        return mean - 3 * std, mean + 3 * std


class EWMADetector:
    def __init__(self, baseline: Baseline, smoothing: float = 0.20, k: float = 3.0):
        if not 0 < smoothing <= 1 or k <= 0:
            raise ValueError("EWMA requires 0 < smoothing <= 1 and k > 0")
        self.baseline, self.smoothing, self.k = baseline, smoothing, k
        self.values = dict(baseline.means)

    def detect(self, sample: Telemetry) -> list[DetectionResult]:
        results = []
        for name in SIGNALS:
            self.values[name] = self.smoothing * getattr(sample, name) + (1 - self.smoothing) * self.values[name]
            std = self.baseline.stds[name] * sqrt(self.smoothing / (2 - self.smoothing))
            score = abs(self.values[name] - self.baseline.means[name]) / std
            results.append(result("EWMA", name, score > self.k, score,
                                  f"EWMA={self.values[name]:.3f}; standardized deviation={score:.2f}"))
        return results

    def limits(self, signal: str) -> tuple[float, float]:
        half_width = self.k * self.baseline.stds[signal] * sqrt(self.smoothing / (2 - self.smoothing))
        mean = self.baseline.means[signal]
        return mean - half_width, mean + half_width
