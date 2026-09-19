import numpy as np
import pytest

from virtual_equipment.detectors import EWMADetector, SPCDetector, ThresholdDetector
from virtual_equipment.features import Baseline, extract_features
from virtual_equipment.monitor import run_batch
from virtual_equipment.simulator import Simulator


def test_spc_large_shift_requires_two_of_three(baseline, sample_factory):
    detector = SPCDetector(baseline)
    shift = sample_factory(temperature_c=80)
    assert not any(d.alarm for d in detector.detect(shift))
    assert any(d.alarm and d.signal == "temperature_c" for d in detector.detect(shift))
    assert any(d.alarm for d in detector.detect(sample_factory()))
    assert not any(d.alarm for d in detector.detect(sample_factory()))


def test_baseline_uses_sample_std():
    simulator = Simulator(42)
    samples = [simulator.step() for _ in range(60)]
    baseline = Baseline.fit(samples)
    assert baseline.stds["temperature_c"] == pytest.approx(np.std([s.temperature_c for s in samples], ddof=1))


def test_ewma_detects_sustained_flow_drift(baseline, sample_factory):
    detector = EWMADetector(baseline)
    alerts = [any(d.alarm and d.signal == "gas_flow_sccm" for d in
                  detector.detect(sample_factory(gas_flow_sccm=100 - 0.5 * t))) for t in range(1, 15)]
    assert any(alerts)
    assert alerts[-1]


def test_ewma_formula_and_limits(baseline, sample_factory):
    detector = EWMADetector(baseline)
    detector.detect(sample_factory(temperature_c=70))
    assert detector.values["temperature_c"] == pytest.approx(0.2 * 70 + 0.8 * baseline.means["temperature_c"])
    low, high = detector.limits("temperature_c")
    assert high - low == pytest.approx(6 * baseline.stds["temperature_c"] * np.sqrt(0.2 / 1.8))


def test_fixed_reference_normal_alarm_budget():
    runs = [run_batch(seed) for seed in range(42, 62)]
    eligible = [tick for run in runs for tick in run.ticks if tick.monitoring_eligible]
    assert len(eligible) == 1200
    assert sum(tick.alarm for tick in eligible) / len(eligible) < 0.10
    assert not any(run.interlock.latched for run in runs)


def test_warning_threshold_is_separate_from_trip(sample_factory):
    results = ThresholdDetector().detect(sample_factory(temperature_c=70))
    assert any(d.alarm and d.signal == "temperature_c" and d.severity == "WARNING" for d in results)


def test_features_use_real_sample_indices(baseline, sample_factory):
    samples = [sample_factory(sample_idx=i, pressure_mtorr=10 + 0.4 * i,
                              pump_current_a=3 + 0.005 * i) for i in range(20)]
    features = extract_features(samples, baseline)
    assert features.signals["pressure_mtorr"]["slope"] == pytest.approx(0.4)
    assert features.pressure_current_correlation == pytest.approx(1.0)
