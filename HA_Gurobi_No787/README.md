# Hawaiian Airlines: Gurobi without the 787

This version uses only **608(B717),696(A330),721(A321neo)** as candidate types.
Type 889(B787) is excluded from assignments, fleet counts and operating costs.
No 787 cost proxy is calculated. Code, comments and outputs are English; Excel
outputs are plain black and white.

## Quick start

Unzip and open a terminal in this folder:

```bash
python -m pip install -r requirements.txt
python run_model.py
```

Use Python 3.11 or 3.12. On macOS/Linux use `python3` if needed; on Windows `py`
may be the Python command. A usable Gurobi license applies. Gurobi 12–13 are
supported;13.0.3 was tested. The compact default fits the restricted license
tested here. No cloud paths or earlier files are required.

## Recorded run with this version

Gurobi 13.0.3 actually solved all 204 retained flights using the default
three-type estimates: objective **USD 3,201,237.68**, estimated spill **0.00**,
and MIP gap **0%**. The compact model has **1,171 variables and 1,036 constraints**.
Every original shared-event flow/fleet check passed, as did **31 tests**.
Zero model spill is conditional on the estimated inputs, not proof of zero
real rejected passengers. Evidence is under `validation/no787_gurobi/`.

## User-requested scope

The supplied daily file has206 flights. Two have no eligible type after removing 787:

| Flight | Route | Remaining eligible types | Treatment |
|---|---|---|---|
|HA35|PHX-HNL|None|Outside this run's scope|
|HA36|HNL-PHX|None|Outside this run's scope|

The model therefore retains **204 flights,18 airports,70 directional routes**.
Excluded records and reasons are saved in `prepared/`. Other flights remain,
including LAX-HNL/HNL-LAX flights historically served by 787 that can be assigned
another historically eligible type. No further cancellations or retiming occur.

The supplied PDF, saved as `docs/model.pdf`, has a Milestone 3 filename but its
content is the complete Milestone 4 model. This experiment deliberately restricts
its candidate set and flight scope at the user's request; coverage, spill,
cyclic flow, readiness and fleet-cap structure otherwise follow that PDF.

## Source files are unchanged

| Local file | Latest uploaded source | Rows |
|---|---|---:|
|`data/on_time.xlsx`|October 16 On-Time|206|
|`data/t100.xlsx`|October 2024 T100|104|
|`data/costs.xlsx`|Q4 cost summary|5|

All 104 monthly rows remain source evidence. Monthly-only routes do not create
scheduled flights. Original 787 rows are not assignment choices, but their
passengers/time remain historical demand information on retained routes.

**Demand and airborne time use full historical route totals, including 787.**
Excluding an aircraft option must not artificially erase its carried passengers.
**Spill-penalty calibration uses only candidate-aircraft costs/passengers**, so
it needs no unknown787cost. Type-level capacities are128/278/189seats.

Tail classification uses the original206 flights and full historical eligibility
BEFORE scope exclusions. Two source tails uniquely compatible with 787 are not
reclassified as A330 just because their PHX flights are removed. No FAA evidence
or outside inventory data are invented.

## Estimates and unresolved issues

| Input | Default method | Limitation |
|---|---|---|
|Demand|Route monthly passengers/performed departures;phi=1|No arbitrary uplift; lost demand remains unobserved.|
|Costs|Supplied 608/696/721 hourly costs|Processed summaries, not independently authenticated raw Form 41. No 889 cost used.|
|Turnarounds|Positive planned-dwell P10 rounded up to 5 minutes:30/100/75|Not approved minima. Samples119/9/16; ambiguous tail groups excluded.|
|Fleet|Observed tail/type inference:16/16/17|Active-fleet scenario, not verified available fleet. Spares, maintenance and international assignments remain unknown.|
|Spill penalty|Candidate monthly route air-operating cost / candidate carried passengers|Cost-recovery proxy, **not DB1Bfare or lost revenue**. This explicitly substitutes for the PDF-requested fare source.|

Other findings:

- The206source airport totals balance; removing the two opposite PHX flights
  preserves balance in the204 flight scope. Full timing/type/fleet feasibility
  is still independently checked after optimization.
- Five source tails have ambiguous types. Route-share likelihood scores are
  not calibrated probabilities or registry verification.
- Ten monthly rows have scheduled 0 / performed positive. They are retained and
  flagged; use performed departures. Do not presume errors or ferry flights.
- HNL-LAX/type 696 has two nonidentical source rows. Sum them: 69 departures,
 17,495 passengers, 19,182 seats, 20,245 airborne minutes. Do not deduplicate them.
- N493HA, HA241 to HA296has a planned−15 minute gap versus 44 minutes actual. It is
  flagged and excluded from turnaround samples. Original times are preserved;
  actual tail order need not be the planned assignment.
- Cost types 837 and 889 remain in the source summary and are not candidates.
- All times are converted using IANA zones, retaining full dates before modulo
 1440minutes. Phoenix has no DST. Costs and flight hours use airborne units.

## Options

### Demand sensitivity: start with the baseline, then compare scenarios

Do not change source PASSENGERS or manually fill the spill variable. The demand
formula is `q = monthly route passengers / performed departures * phi`.
The default remains phi=1; true unmet demand is not identified from carried
passengers. Higher multipliers are explicit stress scenarios, not observations.

Run one uniform demand scenario, for example +10%:

```bash
python run_model.py --demand-multiplier 1.10
```

The flag sets absolute phi for every retained route and takes precedence over
JSON load-factor rules and route-specific values. It must be finite and >=1.
The effective phi is recorded in the assignments, calculated inputs, parameters
and run summary. It does not introduce time-of-day differences within a route.

Run the four standard cases and create a comparison workbook:

```bash
python run_sensitivity.py
```

Open `results/sensitivity_<timestamp>/Demand_Sensitivity.xlsx`. Each case also
has its own full Gurobi outputs and audit. For a different set of scenarios:

```bash
python run_sensitivity.py --factors 1 1.05 1.10 1.20
```

Recorded actual Gurobi results with unchanged fleet, costs and turns:

| Uniform phi | Flights with spill | Estimated spilled passengers | Spill penalty USD | Total objective USD |
|---|---:|---:|---:|---:|
|1.00|0|0.00|0.00|3,201,237.68|
|1.05|0|0.00|0.00|3,201,237.68|
|1.10|18|86.66|16,770.41|3,218,008.08|
|1.20|54|820.36|160,620.61|3,361,858.29|

All four reached zero gap and passed operational checks. The spill-dollar
amounts remain conditional on the cost-recovery proxy, not measured DB1B fares.
The tests show sensitivity; they do not establish which demand multiplier is
true. Report the baseline and scenarios together. Do not choose a multiplier
merely to force positive spill. Real flight-level booking/denied-demand data
would be needed for stronger calibration.

JSON precedence is also corrected: an explicit `demand_adjustment` rule clears
the automatically generated per-route phi=1 values. Explicit per-route values
in the override still take precedence over that rule. The uniform CLI flag is
applied last. Existing baseline results are unchanged.

```bash
python run_model.py --validate-only
python run_model.py --mode strict --validate-only
python run_model.py --parameters parameters_example.json
python run_model.py --time-limit 600 --mip-gap 0.001
```

Strict mode applies no generated assumptions and reports76 missing inputs:
70 route fares,3 turnarounds and3 available-fleet counts. It does not require 787 cost.
Overrides merge with unspecified generated values;889overrides are rejected.
The example JSON is a scenario, not historical evidence.

Optional real directional fare CSVs use `origin,dest,fare_usd`, positive USD
prices, one row per route. They take precedence over proxies:

```bash
python run_model.py --fares my_real_route_fares.csv
```

Files can also be selected with `--on-time`, `--t100`, `--costs`. Their schema
and period must match the documented source fields. Source files are not edited.

## PDF-equivalent compact formulation

Compact mode removes unchanged inventory variables between local events. Cyclic
flow conserves total aircraft of each type, so duplicate fleet cuts are redundant.
All original common-event inventories and fleet caps are reconstructed and checked
after solving. This is exact elimination, not hourly discretization. Choosing
unused idle inventory zero preserves assignment feasibility/objectives because
the PDF has fleet upper bounds and no fixed initial distribution.

See `compact_model.py` and the full-versus-compact Gurobi tests. For the literal
shared-event formulation use `python run_model.py --formulation full`; it may
need a larger license. License failures are not called mathematical infeasibility.

## Results and tests

Each run creates `results/<UTC timestamp>/` with:

- `gurobi_results.xlsx` and `assignments.csv`: assigned types, dates, estimated
  demand/spill, penalty sources and costs. The PDF assigns types, not tail IDs.
- `ground_inventory.csv`: integer inventory at every shared event.
- `model.lp`, `gurobi.log`, `run_summary.json`, `RUN_REPORT.md`.
- `effective_parameters.json` and all source/estimate/exclusion audits in `prepared/`.
- An IIS file if Gurobi proves infeasibility.

Explicit nonempty output directories are not overwritten. Inspect the exact
status and gap; feasible time-limit incumbents are not called optimal.
Exit codes 0/1/2/3 mean validated-or-feasible/error/missing-inputs/no-incumbent.

```bash
python -m unittest -v test_prepare_data test_gurobi_model test_compact_model test_entrypoint
```

Demand-control regression tests are in `test_demand_controls.py`; the full
recorded suite including those tests has 36 passing tests. Actual comparison
evidence is included under `validation/demand_sensitivity/`.

Actual Gurobi evidence for this no-787 version is included in
`validation/no787_gurobi/`. Estimated outputs remain conditional scenarios,
not verified actual fares, costs, aircraft availability or rejected passengers.
