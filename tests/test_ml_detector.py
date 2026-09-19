import subprocess
import sys

import pytest


def test_core_imports_work_when_optional_packages_are_blocked():
    source = '''
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('sklearn', 'scipy'):
            raise ImportError('optional module deliberately unavailable')
sys.meta_path.insert(0, BlockOptional())
from virtual_equipment import features, detectors, rca, ml_detector, stat_analysis
from virtual_equipment.monitor import run_batch
import app
assert len(run_batch(42).ticks) == 120
assert 'sklearn' not in sys.modules and 'scipy' not in sys.modules
'''
    subprocess.run([sys.executable, "-c", source], check=True, capture_output=True, text=True)


def test_optional_ml_trains_only_normal_windows():
    pytest.importorskip("sklearn")
    import numpy as np
    from virtual_equipment.ml_detector import MLDetector
    rng = np.random.default_rng(42)
    values = rng.normal(size=(40, 5))
    values[30:] = 1000
    detector = MLDetector().fit(values, ["NORMAL"] * 30 + ["FAULT"] * 10)
    assert detector.training_count == 30
    assert detector.model.n_estimators == 200
    assert detector.model.random_state == 42
    assert detector.detect([1000] * 5).alarm
