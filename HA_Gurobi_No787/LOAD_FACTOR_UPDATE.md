# Code Update: Conditional Historical Load Factor

This download contains code/configuration only. It does not include uploaded
Excel data or newly derived operational results. Use your existing project,
data files and Python virtual environment.

## Apply the update in your existing project folder

Copy these files next to your current `prepare_data.py` and `compact_model.py`,
replacing the matching code/configuration files:

- `run_model.py`
- `gurobi_model.py`
- `primary_assumptions.json`
- `run_load_factor_comparison.py` (new comparison runner)

Keep your `data` and `.venv312` folders. No new dependencies are required.
Do not run from the ZIP preview or an outer Downloads folder.

In your existing VS Code terminal, run:

```powershell
.\.venv312\Scripts\python.exe run_model.py
```

Or state the rule explicitly:

```powershell
.\.venv312\Scripts\python.exe run_model.py --load-factor-threshold 0.90 --high-load-multiplier 1.20
```

**Do not add `--demand-multiplier 1.20` for the conditional rule.** That option
explicitly applies a uniform uplift to every route and bypasses LF selection.

## Definition and assumption

Before optimization, for each directional route:

LF = sum historical PASSENGERS / sum historical SEATS.

Base demand = sum historical PASSENGERS / sum DEPARTURES_PERFORMED.

If LF > 0.90, phi=1.20. If LF <= 0.90, phi=1.00.

Estimated flight demand = base demand * phi.

Compare at full precision; equality does not trigger uplift. Sum the observations
first rather than averaging aircraft-type LF ratios. Historical observations on
retained routes include all aircraft types, even when 787 is not an assignment
option. Do not use the newly assigned capacity or inflated demand to trigger
uplift; that would make demand depend on the optimization decision.

Threshold and uplift are user-selected assumptions. The PDF permits a documented
team-defined load-factor adjustment, but does not prescribe these numbers.
Monthly averages do not identify time-of-day peaks or true unmet demand. Original
source observations remain unchanged; spill penalties remain proxies unless
observed directional fares are provided.

## Compare thresholds

```powershell
.\.venv312\Scripts\python.exe run_load_factor_comparison.py
```

This reruns the historical-average benchmark, LF>0.90 and LF>0.95 using your local
data and Gurobi. Open the generated `Load_Factor_Comparison.xlsx` in the new
`results/load_factor_comparison_<timestamp>/` folder. Results remain local.

## Read the generated result

`Assignments` now includes `historical_load_factor`, the historical passenger
mean, actual `phi`, `demand_uplift_applied`, adjusted demand, and spill/costs.
`Demand_Rule_Audit` lists the rule for every retained route. `Run_Summary` records
the actual solver status, gap and uplift counts. These fields let you check
whether a rule triggered without inferring it from the final aircraft capacity.

The aircraft scope remains the no-787 model. Existing source-preparation,
capacity, fleet and turnaround assumptions remain in use. Source data and
Gurobi licensing must already be configured as in your working project.
