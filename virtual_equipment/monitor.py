"""Shared application/batch orchestration; injection labels stop at the simulator."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

from .detectors import EWMADetector, SPCDetector, ThresholdDetector
from .features import Baseline, extract_features
from .interlock import Interlock
from .models import Commands, DetectionResult, Diagnosis, Event, FaultType, Severity, Telemetry
from .rca import diagnose
from .simulator import Simulator
from .storage import Storage


@dataclass(frozen=True)
class Tick:
    sample: Telemetry
    detections: list[DetectionResult]
    diagnosis: Diagnosis | None
    events: list[Event]
    episode_id: str
    monitoring_eligible: bool
    ewma: dict[str, float]

    @property
    def alarm(self) -> bool:
        return any(d.alarm for d in self.detections)


class EquipmentMonitor:
    def __init__(self, seed: int = 42, storage: Storage | None = None,
                 mode: str = "live", auto_recovery: bool = True):
        self.run_id = str(uuid4())
        self.storage, self.mode = storage, mode
        self.simulator = Simulator(seed, started_at=datetime.now(timezone.utc))
        self.interlock = Interlock(auto_recovery, self.simulator.config)
        self.threshold = ThresholdDetector(self.simulator.config)
        self.samples: list[Telemetry] = []
        self.ticks: list[Tick] = []
        self.baseline: Baseline | None = None
        self.spc: SPCDetector | None = None
        self.ewma: EWMADetector | None = None
        self.last_diagnosis: Diagnosis | None = None
        self.last_diagnosis_sample: int | None = None
        self.episode_number = 0
        self._episode_active = False
        self._clear_samples = 0
        self._previous_alarms: set[tuple[str, str]] = set()
        self._last_eligible = True
        self.finished = False
        if storage:
            storage.create_run(self.run_id, self.simulator.started_at.isoformat(), seed, mode)

    @property
    def ready(self) -> bool:
        return self.baseline is not None

    def inject(self, fault: FaultType, duration_s: int = 30) -> None:
        if self.finished or not self.ready:
            raise ValueError("Complete the 60-sample normal baseline before injecting a fault")
        if self.interlock.latched:
            raise ValueError("Wait for the interlock recovery before injecting another fault")
        injection = self.simulator.inject(fault, duration_s)
        if self.storage:
            self.storage.save_injection(self.run_id, injection, self.simulator.seed,
                                        self.simulator.faults.signatures[fault])

    def _alarm_events(self, sample: Telemetry, detections: list[DetectionResult]) -> list[Event]:
        current = {(d.method, d.signal) for d in detections if d.alarm}
        events = [Event(sample.sample_idx, sample.ts_utc, "ALARM", d.severity, d.method,
                        d.signal, d.message, {"score": d.score}) for d in detections
                  if d.alarm and (d.method, d.signal) not in self._previous_alarms]
        if self._previous_alarms and not current:
            events.append(Event(sample.sample_idx, sample.ts_utc, "ALARM_CLEAR", Severity.INFO,
                                "monitor", "ALARM_CLEAR", "Anomaly alarms cleared or monitoring inhibited", {}))
        self._previous_alarms = current
        if current:
            if not self._episode_active:
                self.episode_number += 1
            self._episode_active, self._clear_samples = True, 0
        else:
            self._clear_samples += 1
            if self._clear_samples >= 3:
                self._episode_active = False
        return events

    def step(self) -> Tick:
        if self.finished:
            raise ValueError("Run is completed; create a new simulation")
        fault_active = self.simulator.fault_active
        eligible = self.ready and not self.interlock.latched and self.interlock.commands == Commands()
        raw = self.simulator.step(self.interlock.commands)
        self.samples.append(raw)
        detections, diagnosis = [], None
        if eligible:
            if not self._last_eligible:
                self.spc, self.ewma = SPCDetector(self.baseline), EWMADetector(self.baseline)
            detections = self.threshold.detect(raw) + self.spc.detect(raw) + self.ewma.detect(raw)
        events = self._alarm_events(raw, detections)
        if eligible and any(d.alarm for d in detections):
            # Do not include previously commanded shutdown samples in the feature window.
            clean_window = [s for s in self.samples[-20:] if not s.interlock_active]
            diagnosis = diagnose(extract_features(clean_window, self.baseline))
            self.last_diagnosis, self.last_diagnosis_sample = diagnosis, raw.sample_idx
        events.extend(self.interlock.update(raw, fault_active, any(d.alarm for d in detections)))
        sample = replace(raw, equipment_state=self.interlock.state, interlock_active=self.interlock.latched)
        self.samples[-1] = sample
        if not self.ready and len(self.samples) == self.simulator.config.baseline_samples:
            self.baseline = Baseline.fit(self.samples)
            self.spc, self.ewma = SPCDetector(self.baseline), EWMADetector(self.baseline)
            events.append(Event(sample.sample_idx, sample.ts_utc, "BASELINE_READY", Severity.INFO,
                                "monitor", "BASELINE_READY", "Normal baseline fitted using sample std (ddof=1)", {}))
        tick = Tick(sample, detections, diagnosis, events, f"{self.run_id}:{self.episode_number}",
                    eligible, dict(self.ewma.values) if self.ewma else {})
        self.ticks.append(tick)
        self._last_eligible = eligible
        if self.storage and self.mode == "live":
            self.storage.save_tick(self.run_id, sample, events, diagnosis, tick.episode_id)
        if self.mode == "live":
            # Durable history is in SQLite; keep live memory bounded.
            self.samples = self.samples[-120:]
            self.ticks = self.ticks[-120:]
        return tick

    def acknowledge(self) -> Event:
        if not self.samples:
            raise ValueError("Wait for the first telemetry sample")
        event = self.interlock.acknowledge(self.samples[-1])
        if self.storage:
            self.storage.save_event(self.run_id, event)
        return event

    def manual_reset(self) -> Event:
        event = self.interlock.manual_reset()
        if self.storage:
            self.storage.save_event(self.run_id, event)
        return event

    def finish(self) -> None:
        if self.finished:
            return
        if self.storage:
            if self.mode != "live":
                self.storage.save_batch(self.run_id, self.ticks)
            ended = self.samples[-1].ts_utc if self.samples else self.simulator.started_at.isoformat()
            self.storage.finish_run(self.run_id, ended)
        self.finished = True


def run_batch(seed: int, fault: FaultType | None = None, storage: Storage | None = None) -> EquipmentMonitor:
    """Run 60 baseline + 30 fault/control + 30 post-fault samples without sleep."""
    monitor = EquipmentMonitor(seed, storage, mode="batch")
    for sample_idx in range(120):
        if sample_idx == 60 and fault is not None:
            monitor.inject(fault, 30)
        monitor.step()
    monitor.finish()
    return monitor
