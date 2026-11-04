# Hawaiian Airlines Gurobi Download

This branch contains the tested model excluding the Boeing787, as requested.
The model retains204flights and candidate types608(B717),696(A330),721(A321neo).
HA35PHX-HNL and HA36HNL-PHX are listed outside the scope because only787was
historically eligible for those directional routes in the supplied data.

Download [HA_Gurobi_No787.zip](downloads/HA_Gurobi_No787.zip) using GitHub's
**Download raw file** button. Unzip it and open the `HA_Gurobi_No787` folder in
VSCode. The same source files can be browsed in [the project folder](HA_Gurobi_No787).

From a terminal in that folder:

```bash
python -m pip install -r requirements.txt
python run_model.py
```

On Windows, `py` may replace `python`; on macOS/Linux use `python3` if needed.
Python3.11/3.12is recommended. A usable Gurobi license applies. The compact
formulation solved in the size-limited license tested with Gurobi13.0.3.

The selected primary case assumes phi=1.20, with demand 20% above historical
route-average carried passengers per departure. Actual Gurobi result:
USD 3,361,858.29 total, USD 160,620.61 spill penalty, 820.36 modeled spilled
passengers across 54 flights, 0% gap. 39 tests passed. The phi=1 benchmark is retained.
These are results under explicitly documented estimates, not verified historical
fare revenue or true lost passengers. Source data, parameter audits, exclusions,
modelLP, solverlog and result workbooks are included. Read the project README
for setup, assumptions and remaining data limitations.

## New demand controls

Download [the version with demand scenarios](downloads/HA_Gurobi_No787_DemandScenarios.zip).
It adds a uniform demand multiplier and a four-case comparison runner:

```bash
python run_model.py --demand-multiplier 1.10
python run_sensitivity.py
```

If you already installed the original package, replace `run_model.py` and add
`run_sensitivity.py` in your existing folder. Keep your data and Python virtual
environment. No additional dependencies are required.
These are assumption/sensitivity controls, not claims about actual unmet demand.

## Primary phi=1.20 package

Download [the selected primary-case version](downloads/HA_Gurobi_No787_Phi120.zip).
Its `primary_assumptions.json` automatically applies phi=1.20 in estimated mode;
`ASSUMPTIONS.md` provides the English assumption statement. Source PASSENGERS
remain unchanged. Run `python run_model.py` for the main case, or add
`--demand-multiplier 1.00` for the historical-average benchmark. New actual
results, including an XLSX with solver summary and assumption sheets, are in
`HA_Gurobi_No787/validation/primary_phi_1_20/`.
