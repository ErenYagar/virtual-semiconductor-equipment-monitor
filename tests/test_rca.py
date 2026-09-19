import inspect

import pytest

from virtual_equipment import detectors, features, rca
from virtual_equipment.features import Baseline, FeatureSet, extract_features
from virtual_equipment.faults import fault_targets
from virtual_equipment.models import FaultType, SIGNALS, Telemetry


@pytest.mark.parametrize("fault", list(FaultType))
def test_ranks_each_synthetic_signature_first(fault):
    baseline = Baseline(dict(zip(SIGNALS, (60, 10, 100, 500, 3))),
                        dict(zip(SIGNALS, (0.25, 0.15, 0.5, 2, 0.04))))
    samples = [Telemetry(t, "2026-01-01T00:00:00+00:00", **fault_targets(fault, t)) for t in range(11, 21)]
    diagnosis = rca.diagnose(extract_features(samples, baseline))
    assert diagnosis.candidates[0].cause == fault.value
    assert diagnosis.candidates[0].score >= 0.65


def test_rca_api_rejects_ground_truth_and_modules_cannot_read_it(baseline, sample_factory):
    observed = extract_features([sample_factory()], baseline)
    assert list(inspect.signature(rca.diagnose).parameters) == ["features"]
    with pytest.raises(TypeError):
        rca.diagnose(observed, fault_type="VACUUM_LEAK")
    for module in (features, detectors, rca):
        source = inspect.getsource(module)
        assert "fault_type" not in source
        assert "fault_injections" not in source
        assert "from .faults" not in source
        assert "sqlite" not in source


def test_unknown_and_ambiguous_decisions(baseline, sample_factory):
    observed = extract_features([sample_factory()], baseline)
    assert rca.diagnose(observed).decision == "UNKNOWN"
    data = {key: dict(value) for key, value in observed.signals.items()}
    data["temperature_c"].update(z=10, slope=0.6)
    data["gas_flow_sccm"].update(z=-10, slope=-0.5)
    diagnosis = rca.diagnose(FeatureSet(data, None))
    assert diagnosis.ambiguous
    assert diagnosis.decision == "AMBIGUOUS"
    assert len(diagnosis.candidates) == 4
