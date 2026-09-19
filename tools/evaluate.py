"""Reproducible Monte Carlo evaluation; no wall-clock sleeping or optional ML."""
import argparse
from pathlib import Path
import sys

# Support `python tools\evaluate.py` from any working directory on Windows.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from virtual_equipment.config import project_root
from virtual_equipment.metrics import detection_latency, false_alarm_episodes, false_positive_rate, root_cause_accuracy
from virtual_equipment.models import FaultType
from virtual_equipment.monitor import run_batch


def evaluate_run(seed: int, fault: FaultType | None) -> dict:
    monitor = run_batch(seed, fault)
    ticks = monitor.ticks
    alarms = [tick.alarm for tick in ticks]
    indices = [tick.sample.sample_idx for tick in ticks if tick.alarm]
    latency = detection_latency(indices, 60, 90) if fault else None
    # Report FPR only on independent normal-only runs, excluding fitted samples.
    # Post-fault dynamics and deliberate safety commands are not normal negatives.
    normal_mask = [fault is None and tick.monitoring_eligible for tick in ticks]
    diagnoses = [tick.diagnosis for tick in ticks[60:90]
                 if tick.diagnosis is not None and tick.diagnosis.decision != "UNKNOWN"]
    # First qualifying diagnosis, not the best diagnosis chosen with hindsight.
    first = diagnoses[0] if diagnoses else None
    predictions = [candidate.cause for candidate in first.candidates[:2]] if first else []
    truth = fault.value if fault else "NORMAL"
    return {
        "run_id": monitor.run_id, "seed": seed, "fault": truth, "samples": len(ticks),
        "detected": int(latency is not None) if fault else None, "latency_s": latency,
        "normal_samples": sum(normal_mask),
        "false_positive_samples": sum(a and n for a, n in zip(alarms, normal_mask)),
        "sample_fpr": false_positive_rate(alarms, normal_mask),
        "false_alarm_episodes": false_alarm_episodes(alarms, normal_mask) if fault is None else None,
        "top1": predictions[0] if predictions else "UNKNOWN",
        "top2": predictions[1] if len(predictions) > 1 else "",
        "ambiguous": first.ambiguous if first else False,
        "rca_top1_correct": root_cause_accuracy([truth], [predictions], 1) if fault else None,
        "rca_top2_correct": root_cause_accuracy([truth], [predictions], 2) if fault else None,
        "trip_count": sum(event.code == "TRIP" for tick in ticks for event in tick.events),
        "recovery_complete": any(event.code == "RECOVERY_COMPLETE" for tick in ticks for event in tick.events),
    }


def evaluate(repeats: int = 100, normal_runs: int = 100, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    if repeats < 1 or normal_runs < 1 or seed < 0:
        raise ValueError("repeats/normal_runs must be positive and seed nonnegative")
    rows = [evaluate_run(seed + repetition, fault) for fault in FaultType for repetition in range(repeats)]
    rows.extend(evaluate_run(seed + repetition, None) for repetition in range(normal_runs))
    by_run = pd.DataFrame(rows)
    summary = []
    for fault, group in by_run.groupby("fault", sort=False):
        negatives = int(group.normal_samples.sum())
        summary.append({
            "fault": fault, "runs": len(group), "detection_rate": group.detected.mean(),
            "mean_latency_s": group.latency_s.mean(), "median_latency_s": group.latency_s.median(),
            "p95_latency_s": group.latency_s.quantile(0.95),
            "sample_fpr": group.false_positive_samples.sum() / negatives if negatives else float("nan"),
            "normal_samples": negatives,
            "false_alarm_episodes": group.false_alarm_episodes.sum() if negatives else float("nan"),
            "rca_top1_accuracy": group.rca_top1_correct.mean(), "rca_top2_accuracy": group.rca_top2_correct.mean(),
        })
    return pd.DataFrame(summary), by_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--normal-runs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        summary, by_run = evaluate(args.repeats, args.normal_runs, args.seed)
    except ValueError as error:
        parser.error(str(error))
    output = project_root() / "artifacts"
    output.mkdir(exist_ok=True)
    summary.to_csv(output / "evaluation_summary.csv", index=False)
    by_run.to_csv(output / "evaluation_by_run.csv", index=False)
    print("Synthetic simulator evaluation. NaN = not applicable; latency is conditional on detection.")
    print(summary.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print(f"\nSaved numerical results to {output}")


if __name__ == "__main__":
    main()
