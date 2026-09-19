"""Evaluation equations; undefined rates are NaN, never fabricated zeros."""
from collections.abc import Sequence
from math import nan


def detection_latency(alarm_indices: Sequence[int], fault_start: int, fault_end: int,
                      sample_period_s: float = 1.0) -> float | None:
    """First alarm in [start, end), relative to the first fault sample."""
    if fault_start < 0 or fault_end <= fault_start or sample_period_s <= 0:
        raise ValueError("Invalid fault interval or sample period")
    hits = [idx for idx in alarm_indices if fault_start <= idx < fault_end]
    return (min(hits) - fault_start) * sample_period_s if hits else None


def detection_rate(detected: Sequence[bool]) -> float:
    return sum(bool(value) for value in detected) / len(detected) if len(detected) else nan


def false_positive_rate(alarms: Sequence[bool], normal_mask: Sequence[bool]) -> float:
    if len(alarms) != len(normal_mask):
        raise ValueError("Alarm and normal-mask lengths must match")
    denominator = sum(bool(value) for value in normal_mask)
    return sum(bool(a) and bool(n) for a, n in zip(alarms, normal_mask)) / denominator if denominator else nan


def false_alarm_episodes(alarms: Sequence[bool], normal_mask: Sequence[bool]) -> int:
    """Count contiguous alarm runs wholly within the eligible normal mask."""
    if len(alarms) != len(normal_mask):
        raise ValueError("Alarm and normal-mask lengths must match")
    count, previous = 0, False
    for alarm, normal in zip(alarms, normal_mask):
        active = bool(alarm and normal)
        count += int(active and not previous)
        previous = active
    return count


def root_cause_accuracy(truths: Sequence[str], predictions: Sequence[Sequence[str]], k: int = 1) -> float:
    """Missed/UNKNOWN diagnoses must be supplied as empty prediction lists."""
    if k not in (1, 2) or len(truths) != len(predictions):
        raise ValueError("k must be 1 or 2, with one prediction list per truth")
    return sum(truth in predicted[:k] for truth, predicted in zip(truths, predictions)) / len(truths) if truths else nan
