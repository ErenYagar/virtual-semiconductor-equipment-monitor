"""Persist paired-seed fault/control runs and export telemetry without sleeping."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from virtual_equipment.config import project_root
from virtual_equipment.models import FaultType
from virtual_equipment.monitor import run_batch
from virtual_equipment.storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.repeats < 1 or args.seed < 0:
        parser.error("repeats must be positive and seed nonnegative")
    root = project_root()
    storage = Storage(root / "data" / "equipment.db")
    output = root / "artifacts" / "dataset.csv"
    output.parent.mkdir(exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        first = True
        for fault in (None, *FaultType):
            for repetition in range(args.repeats):
                monitor = run_batch(args.seed + repetition, fault, storage)
                storage.telemetry(monitor.run_id).to_csv(stream, index=False, header=first)
                first = False
    print(f"Saved {args.repeats * 5} runs / {args.repeats * 600} samples to {storage.path}")
    print(f"Telemetry CSV: {output}; injection ground truth remains in the separate SQLite table.")


if __name__ == "__main__":
    main()
