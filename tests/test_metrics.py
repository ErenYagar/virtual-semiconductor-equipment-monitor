from math import isnan

import pytest

from virtual_equipment.metrics import (detection_latency, detection_rate, false_alarm_episodes,
                                       false_positive_rate, root_cause_accuracy)


def test_metric_equations():
    assert detection_latency([4, 62, 90], 60, 90) == 2
    assert detection_latency([4, 90], 60, 90) is None
    assert detection_latency([63], 60, 90, 0.5) == 1.5
    assert detection_rate([True, False, True, True]) == 0.75
    alarms = [False, True, True, False, True, True]
    normal = [True, True, True, True, True, False]
    assert false_positive_rate(alarms, normal) == 3 / 5
    assert false_alarm_episodes(alarms, normal) == 2
    assert root_cause_accuracy(["a", "b", "c"], [["a", "b"], ["a", "b"], []], 1) == 1 / 3
    assert root_cause_accuracy(["a", "b", "c"], [["a", "b"], ["a", "b"], []], 2) == 2 / 3


def test_undefined_rates_and_invalid_input():
    assert isnan(detection_rate([]))
    assert isnan(false_positive_rate([True], [False]))
    assert isnan(root_cause_accuracy([], []))
    with pytest.raises(ValueError):
        false_positive_rate([True], [])
    with pytest.raises(ValueError):
        detection_latency([], 60, 30)
    with pytest.raises(ValueError):
        root_cause_accuracy(["a"], [], 3)


def test_optional_statistics_use_matched_run_aggregates():
    pytest.importorskip("scipy")
    from virtual_equipment.stat_analysis import matched_seed_effect, pearson_correlation, welch_t_test
    effect = matched_seed_effect({1: 3, 2: 6, 3: 9}, {1: 1, 2: 2, 3: 3})
    assert effect["mean_effect"] == 4
    assert effect["n_pairs"] == 3
    assert effect["ci95_low"] < 4 < effect["ci95_high"]
    assert pearson_correlation([1, 2, 3], [2, 4, 6])["correlation"] == pytest.approx(1)
    assert welch_t_test([1, 2, 3], [4, 7, 10])["statistic"] < 0
    with pytest.raises(ValueError, match="seed sets"):
        matched_seed_effect({1: 3, 2: 4}, {2: 1, 3: 1})
