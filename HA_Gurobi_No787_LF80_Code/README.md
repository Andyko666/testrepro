# Hawaiian Airlines: Unified LF80 Code Package

The primary rule is historical directional-route LF strictly greater than 0.80: phi=1.20; otherwise phi=1.00. The sole default source is `primary_assumptions.json`. Candidate aircraft exclude the B787.

This archive contains the complete program, configuration, Windows launcher, and tests. It does not contain Excel source data, PDFs, solver results, or virtual environments.

## Run on Windows

Extract this archive to a new folder. Copy the unchanged `data` folder from your existing working project next to `run_model.py`. It must contain `on_time.xlsx`, `t100.xlsx`, and `costs.xlsx`. Do not copy old validation folders or old result documents into this new version.

Double-click `run_windows.cmd`. It locates its own project folder, creates a local Python 3.12 environment when needed, installs requirements, and runs the model. Python 3.12 with its Windows launcher and a working Gurobi license are required.

Manual PowerShell commands from the folder containing `run_model.py` and `requirements.txt`:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
.\.venv312\Scripts\python.exe run_model.py
```

## Definition and configuration

```text
historical LF = sum directional-route PASSENGERS / sum directional-route SEATS
base demand = sum directional-route PASSENGERS / sum DEPARTURES_PERFORMED
phi = 1.20 if historical LF > 0.80, otherwise 1.00
estimated demand = base demand * phi
```

Use the historical observations before assignment, aggregate before dividing, and compare without rounding. Exactly 0.80 does not trigger uplift. Historical B787 observations on retained routes remain historical demand evidence although B787 is excluded from assignment. The threshold and uplift are assumptions; monthly carried passengers do not identify true unmet demand or flight-level peaks.

Change `demand_adjustment.load_factor_threshold` in `primary_assumptions.json` to change the persistent default. No hardcoded Python override remains. Generated input estimates are followed by the primary JSON, optional `--parameters`, and the explicit CLI demand rule.

## Compare scenarios

```powershell
.\.venv312\Scripts\python.exe run_load_factor_comparison.py
.\.venv312\Scripts\python.exe run_model.py --load-factor-threshold 0.90
.\.venv312\Scripts\python.exe run_model.py --demand-multiplier 1.00
```

The comparison includes the configured primary cutoff, the historical-mean benchmark, and separate 90%/95% sensitivity cutoffs. Uniform stress scenarios remain optional through `run_sensitivity.py`. `--demand-multiplier 1.20` bypasses the LF condition and uplifts every route; it is a different experiment.

## Read the result

Each run prints a new `results/<UTC timestamp>/` path. Open `gurobi_results.xlsx`: `Run_Summary` records the actual scenario ID, effective rule, solver status, objective and gap. `Assignments` records historical LF, actual phi, estimated demand/spill and costs. `Demand_Rule_Audit` records the route adjustments. Reports describe the effective settings after overrides. Nonempty output directories are not overwritten.

DB1B fares remain unavailable unless real directional fares are supplied with `--fares`. The default spill penalty is an explicitly labeled operating-cost-per-carried-passenger proxy, not an observed fare or actual lost revenue. The model retains the supplied PDF's airborne-cost, spill, cyclic flow, readiness and fleet-cap structure within the documented no-B787 scope. Turnarounds, inferred fleet availability and historical type compatibility remain assumptions.

The program preserves source files, converts full local dates/times to UTC, audits scope exclusions and missing data, and checks the solved assignment at all common events. Compact and full formulations implement the same model; the full version may require a larger Gurobi license.

With the source workbooks in place, run checks using:

```powershell
.\.venv312\Scripts\python.exe -m unittest discover -v
```

All code and output labels are English. Result spreadsheets use a plain black-and-white style. See `CODE_PACKAGE.json` for this archive's configuration and code hashes; operational results are generated locally.
