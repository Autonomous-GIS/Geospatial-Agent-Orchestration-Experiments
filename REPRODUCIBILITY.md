# Reproducing the reported findings

This is the canonical, command-line reproduction guide for the manuscript.  It
maps each reported result to its source data, analysis code, and output.  All
commands below are run from the repository root and use relative paths.  The
historical `.gas-workflow.json` files preserve agent-run provenance; some retain
their original absolute runtime paths and are **not** the commands to execute.
The two scripts named below are the portable, commented implementations.

## 1. Set up a clean environment

```sh
git clone https://github.com/Autonomous-GIS/Geospatial-Agent-Orchestration-Experiments.git
cd Geospatial-Agent-Orchestration-Experiments
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-reproducibility.txt
```

The reproducibility scripts are ordinary Python programs; no desktop GIS or
other off-the-shelf GUI application is used, so screenshots are not applicable.
`MPLCONFIGDIR=.cache/matplotlib` can be prepended to the commands on a system
where the default Matplotlib cache is not writable.

## 2. Findings, inputs, commands, and checks

| Manuscript finding | Source data and analysis | Run | Expected check |
| --- | --- | --- | --- |
| Figure 2: task-success and repeat distributions | The 540 frozen `traj_ISS_*.json` logs in `benchmark/results/experiment_luna_20260821_131749/`; `scripts/reproduce_benchmark_findings.py` | `python scripts/reproduce_benchmark_findings.py --output-dir reproduction_output/benchmark` | `figure_2.png`; C5 TSR is 83.3%, C2 TSR is 56.7%, C3 is 60.0%, and C4 is 66.7%. |
| Figure 3: runtime and token-use characteristics; all reported runtime/token metrics | Same 540 logs and the same script | Same command | `figure_3.png` and `metrics.json`; 540 trajectories, 17,225.713 s (4.78 h), 6,404,483 total tokens (5,082,957 input; 1,321,526 output); C5 mean 38.9 s and 15,237 tokens; C2 p95 runtime 99.8 s; C4 mean 7,281 tokens. |
| Table 5: ablation contrasts and paired 95% CIs | Same 540 logs; majority success over the three runs per task; paired 10,000-resample bootstrap implemented in the same script | Same command | `table_5.csv`: C5−C2 26.7 pp [10.0, 46.7], C5−C3 23.3 pp [10.0, 40.0], C5−C4 16.7 pp [0.0, 33.3]. |
| Table 6: C5 failure-mode counts | Raw C5 trajectory logs plus the transparent, row-level coding ledger `benchmark/results/experiment_luna_20260821_131749/table_6_failure_classification.csv` | Same command | `table_6.csv`: 10 budget exhaustion, 8 artifact/contract, 5 recovery execution, 4 evidence/escalation, and 1 unresolved structural replanning. |
| Figure 4 (repository files historically call this Figure 3a–d): economic-distress map panels | Case B/C shared ACS CSVs and Census county GeoPackages; Case D shared ACS CSV plus its documented GeoPackage | `python scripts/reproduce_figure_4.py --output-dir reproduction_output/figure_4` | `figure_4.png`, and four GeoJSON/CSV calculated layers.  The script rebuilds indicators, index, join, projection, and plotting—not merely a saved image. |
| Tables 1–4: benchmark/task/condition specifications | `benchmark/manifests/isolated_suite.json`, `benchmark/run_luna_experiment.py`, and the versioned benchmark code | Inspect those versioned inputs; no calculation is involved | They are descriptive specifications rather than derived numerical findings. |

The Figure 4 terminology is made explicit because the manuscript labels the
four-panel map as Figure 4, while the originally archived case-study assets use
the historical `Figure 3` filename.  They refer to the same four panels.

## 3. What the benchmark script does

`scripts/reproduce_benchmark_findings.py` reads every frozen trajectory record,
marks `bafo_success == true` as a passing trajectory, groups the three repeats
for each condition/task, and writes Figures 2–3, Tables 5–6, and `metrics.json`.
The one C0 record marked `evaluation_invalid` without a Boolean pass value is
treated as non-passing; this is required to retain the published 540-run
denominator.  Table 6 is reproducible from the checked-in, trajectory-level
ledger; each ledger row is checked against a failed C5 log before it is counted.

To regenerate the supplementary log extraction before rerunning the analysis:

```sh
python benchmark/evaluation/export_supplementary_artifacts.py \
  --results-dir benchmark/results/experiment_luna_20260821_131749 \
  --manifest benchmark/manifests/isolated_suite.json
```

## 4. Figure 4 data workflow

The Figure 4 script performs these source-to-output steps in code: read ACS
2017–2021 county estimates; calculate six adverse shares (education, poverty,
unemployment, income below $30k, SSI, SNAP/public assistance); calculate the
case-specific index; join to Census county geometry by zero-padded GEOID;
project to EPSG:5070; classify with five Natural Breaks classes; and write both
the calculated spatial layers and the plotted panel figure.

Cases B and C are fully included in Git:

- `Analytical Specification Case Study/Case_B_Fully_Specified/agent_artifacts/data_retrieval/download_the_386195.csv`
  and `download_the_599189.gpkg`
- `Analytical Specification Case Study/Case_C_Indicator_Specified/agent_artifacts/data_retrieval/download_the_622091.csv`
  and `download_the_968200.gpkg`

Case D has two public, size-exempt GeoPackages.  Download them to the relative
paths and verify their SHA-256 values exactly as listed in
[`Case_D_Goal_Oriented/DATA_AVAILABILITY.md`](Analytical%20Specification%20Case%20Study/Case_D_Goal_Oriented/DATA_AVAILABILITY.md).
The Figure 4 script stops with a precise path error if the required Case D
geometry is not present; it does not substitute an archived figure.

The supplied raw Case B/C retrieval files are regenerated Census downloads.
County-boundary vintages can change county-equivalent identifiers, so the script
reports any unmatched rows rather than concealing them.  This can change a
freshly rendered map slightly but does not alter the archived manuscript panel,
which remains included for comparison.

## 5. Optional live benchmark rerun

The commands above reproduce the published outputs without API calls.  A new
live experiment requires the project runtime, credentials, and incurs model/API
costs; stochastic outputs can differ from the frozen published logs:

```sh
python benchmark/run_luna_experiment.py \
  --suite isolated --conditions C0,C1,C2,C3,C4,C5 --runs 3 --seed 42 \
  --output-dir benchmark/results/new_live_run
```

Analyze that new directory only as a new experiment, not as a replacement for
the frozen manuscript record.
