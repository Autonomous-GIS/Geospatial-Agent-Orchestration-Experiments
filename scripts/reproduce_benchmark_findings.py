"""Rebuild the benchmark figures, Table 5, and reported performance metrics.

This script reads only the frozen trajectory logs supplied with the repository.
It does not call an LLM or an external service. Run it from the repository root:

    python scripts/reproduce_benchmark_findings.py \
      --results-dir benchmark/results/experiment_luna_20260821_131749 \
      --output-dir reproduction_output/benchmark
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ("C0", "C1", "C2", "C3", "C4", "C5")


def load_trajectories(results_dir: Path) -> list[dict]:
    """Read the 540 frozen isolated-suite trajectory records."""
    records = []
    for path in sorted(results_dir.glob("traj_ISS_*.json")):
        with path.open(encoding="utf-8") as handle:
            record = json.load(handle)
        # The frozen C0/Q24/run1 record is ``evaluation_invalid`` and has no
        # explicit Boolean. It did not satisfy the benchmark oracle and is
        # therefore a non-passing trajectory in the published 540-run totals.
        record["bafo_success"] = record.get("bafo_success") is True
        records.append(record)
    if len(records) != 540:
        raise ValueError(f"Expected 540 evaluable isolated trajectories; found {len(records)}.")
    return records


def task_summaries(records: list[dict]) -> tuple[dict, dict]:
    """Return per-condition task repeat distributions and task-success scores."""
    runs = defaultdict(list)
    for record in records:
        runs[(record["condition"], record["task_id"])].append(bool(record["bafo_success"]))

    distribution = {condition: [0, 0, 0, 0] for condition in CONDITIONS}
    scores = {condition: {} for condition in CONDITIONS}
    for (condition, task_id), outcomes in runs.items():
        if len(outcomes) != 3:
            raise ValueError(f"{condition}/{task_id} has {len(outcomes)} repetitions, not three.")
        passes = sum(outcomes)
        distribution[condition][passes] += 1
        scores[condition][task_id] = float(passes >= 2)
    return distribution, scores


def bootstrap_difference(reference: dict, ablated: dict, seed: int = 2) -> tuple[float, float, float]:
    """Compute the manuscript's paired 10,000-resample TSR difference and CI."""
    task_ids = sorted(set(reference) & set(ablated))
    differences = np.array([reference[task] - ablated[task] for task in task_ids])
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(task_ids), size=(10_000, len(task_ids)))
    bootstrap = differences[samples].mean(axis=1)
    return float(differences.mean()), float(np.percentile(bootstrap, 2.5)), float(np.percentile(bootstrap, 97.5))


def write_table_5(scores: dict, output: Path) -> None:
    """Write Table 5 from majority-success scores, not precomputed values."""
    rows = []
    for ablated, label in (("C2", "No GIS-aware planning"), ("C3", "No structural replanning"), ("C4", "No GIS-aware semantic validation")):
        difference, lower, upper = bootstrap_difference(scores["C5"], scores[ablated])
        rows.append((label, scores["C5"].values(), scores[ablated].values(), difference, lower, upper))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["comparison", "c5_tsr_percent", "ablated_tsr_percent", "difference_percentage_points", "ci_95_lower", "ci_95_upper"])
        for label, c5, ablated, difference, lower, upper in rows:
            writer.writerow([label, f"{100 * np.mean(list(c5)):.1f}", f"{100 * np.mean(list(ablated)):.1f}", f"{100 * difference:.1f}", f"{100 * lower:.1f}", f"{100 * upper:.1f}"])


def draw_figure_2(distribution: dict, records: list[dict], output: Path) -> None:
    """Draw Figure 2: task repeat distribution, TSR, and trajectory pass rate."""
    colors = ("#d9d9d9", "#fdae61", "#abd9e9", "#2c7bb6")
    labels = ("0/3", "1/3", "2/3", "3/3")
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bottom = np.zeros(len(CONDITIONS))
    for index, label in enumerate(labels):
        values = np.array([distribution[condition][index] for condition in CONDITIONS])
        ax.bar(CONDITIONS, values, bottom=bottom, label=label, color=colors[index], edgecolor="white")
        bottom += values
    for index, condition in enumerate(CONDITIONS):
        condition_records = [record for record in records if record["condition"] == condition]
        tsr = (distribution[condition][2] + distribution[condition][3]) / 30
        tpr = np.mean([record["bafo_success"] for record in condition_records])
        ax.text(index, 30.7, f"TSR {tsr:.1%}\nTPR {tpr:.1%}", ha="center", va="bottom", fontsize=8)
    ax.set(ylabel="Benchmark tasks", ylim=(0, 35), title="Benchmark-task success and repeat distributions")
    ax.legend(title="Passing trajectories")
    fig.tight_layout()
    fig.savefig(output, dpi=300)
    plt.close(fig)


def draw_figure_3(records: list[dict], output: Path) -> None:
    """Draw Figure 3 from per-trajectory wall time and provider token records."""
    means = []
    for condition in CONDITIONS:
        group = [record for record in records if record["condition"] == condition]
        means.append((np.mean([record.get("total_wall_time", 0.0) for record in group]), np.mean([record.get("total_tokens", 0) for record in group])))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    axes[0].bar(CONDITIONS, [item[0] for item in means], color="#4c78a8")
    axes[0].set(title="Mean runtime", ylabel="Seconds per trajectory")
    axes[1].bar(CONDITIONS, [item[1] for item in means], color="#f58518")
    axes[1].set(title="Mean token use", ylabel="Tokens per trajectory")
    fig.suptitle("Runtime and token-use characteristics")
    fig.tight_layout()
    fig.savefig(output, dpi=300)
    plt.close(fig)


def write_table_6(results_dir: Path, records: list[dict], output: Path) -> None:
    """Count the published, trajectory-level Table 6 coding ledger."""
    ledger = results_dir / "table_6_failure_classification.csv"
    by_id = {record["trajectory_id"]: record for record in records}
    counts = defaultdict(int)
    families = defaultdict(list)
    with ledger.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = by_id.get(row["trajectory_id"])
            if record is None or record["condition"] != "C5" or record["bafo_success"]:
                raise ValueError(f"Invalid Table 6 ledger row: {row['trajectory_id']}")
            counts[row["primary_failure_mode"]] += 1
            families[row["primary_failure_mode"]].append(record["task_id"].replace("ISS_Q", "F"))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["primary_failure_mode", "failed_trajectories"])
        for mode, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            writer.writerow([mode, count])


def write_metrics(records: list[dict], distribution: dict, output: Path) -> None:
    """Write every numeric benchmark measure used by Figures 2--3 and Table 5."""
    summary = {}
    for condition in CONDITIONS:
        group = [record for record in records if record["condition"] == condition]
        summary[condition] = {
            "trajectories": len(group),
            "passing_trajectories": int(sum(record["bafo_success"] for record in group)),
            "trajectory_pass_rate": float(np.mean([record["bafo_success"] for record in group])),
            "task_success_rate": float((distribution[condition][2] + distribution[condition][3]) / 30),
            "mean_wall_time_seconds": float(np.mean([record.get("total_wall_time", 0.0) for record in group])),
            "p95_wall_time_seconds": float(np.percentile([record.get("total_wall_time", 0.0) for record in group], 95)),
            "mean_total_tokens": float(np.mean([record.get("total_tokens", 0) for record in group])),
        }
    summary["all_conditions"] = {
        "trajectories": len(records),
        "total_wall_time_seconds": float(sum(record.get("total_wall_time", 0.0) for record in records)),
        "total_tokens": int(sum(record.get("total_tokens", 0) for record in records)),
        "input_tokens": int(sum(record.get("input_tokens", 0) for record in records)),
        "output_tokens": int(sum(record.get("output_tokens", 0) for record in records)),
    }
    with output.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=ROOT / "benchmark" / "results" / "experiment_luna_20260821_131749")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reproduction_output" / "benchmark")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = load_trajectories(args.results_dir)
    distribution, scores = task_summaries(records)
    write_table_5(scores, args.output_dir / "table_5.csv")
    write_table_6(args.results_dir, records, args.output_dir / "table_6.csv")
    write_metrics(records, distribution, args.output_dir / "metrics.json")
    draw_figure_2(distribution, records, args.output_dir / "figure_2.png")
    draw_figure_3(records, args.output_dir / "figure_3.png")
    print(f"Wrote Figures 2--3, Tables 5--6, and metrics to {args.output_dir}")


if __name__ == "__main__":
    main()
