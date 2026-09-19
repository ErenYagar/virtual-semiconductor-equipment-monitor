from dataclasses import replace

import pytest

from virtual_equipment.features import Baseline
from virtual_equipment.models import Telemetry
from virtual_equipment.simulator import Simulator


@pytest.fixture
def normal_sample():
    return Telemetry(0, "2026-01-01T00:00:00+00:00", 60, 10, 100, 500, 3)


@pytest.fixture
def baseline():
    simulator = Simulator(42)
    return Baseline.fit([simulator.step() for _ in range(60)])


@pytest.fixture
def sample_factory(normal_sample):
    return lambda **values: replace(normal_sample, **values)
