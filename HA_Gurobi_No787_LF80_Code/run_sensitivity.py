#!/usr/bin/env python3
"""Compare uniform demand stress scenarios, without changing source passengers.

These multipliers are assumptions, not inferred true demand. Every case reruns
the Gurobi model with the same supplied inputs and different absolute phi.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

from gurobi_model import plain_excel
from run_model import ROOT, demand_multiplier_argument, main as run_one


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--factors", nargs="+", type=demand_multiplier_argument, default=[1.0,1.05,1.10,1.20])
    p.add_argument("--output", type=Path)
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--mip-gap", type=float, default=0.0001)
    p.add_argument("--parameters", type=Path, help="Optional common overrides; uniform phi is applied last.")
    p.add_argument("--fares", type=Path)
    p.add_argument("--on-time", type=Path)
    p.add_argument("--t100", type=Path)
    p.add_argument("--costs", type=Path)
    a = p.parse_args(argv)
    output = a.output or ROOT / "results" / ("sensitivity_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC"))
    if output.exists() and any(output.iterdir()):
        print(f"Choose a new output directory: {output}", file=sys.stderr)
        return 1
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    all_optimal = True
    for index, factor in enumerate(dict.fromkeys(a.factors), 1):
        case = output / f"case_{index:02d}_phi_{factor:g}"
        arguments = ["--demand-multiplier", str(factor), "--time-limit", str(a.time_limit),
                     "--mip-gap", str(a.mip_gap), "--output", str(case)]
        for flag, path in [("--parameters",a.parameters),("--fares",a.fares),("--on-time",a.on_time),
                           ("--t100",a.t100),("--costs",a.costs)]:
            if path is not None:
                arguments += [flag,str(path)]
        print(f"\nDemand scenario phi={factor:g}: {case.name}", flush=True)
        exit_code = run_one(arguments)
        summary_file = case / "run_summary.json"
        result = json.loads(summary_file.read_text()) if summary_file.exists() else {}
        row = dict(demand_multiplier=factor, status=result.get("status","NO_RUN_SUMMARY"),
                   objective_usd=result.get("objective_usd"), operating_cost_usd=result.get("operating_cost_usd"),
                   spill_cost_usd=result.get("spill_cost_usd"), estimated_spilled_passengers=result.get("model_spilled_passengers"),
                   mip_gap=result.get("mip_gap"), flights_with_spill=None, case_directory=case.name,
                   demand_interpretation="Assumed demand stress, not observed true demand or actual denied boarding.")
        if (case / "assignments.csv").exists():
            assignments = pd.read_csv(case / "assignments.csv")
            row["flights_with_spill"] = int(assignments.model_spill_variable.gt(1e-5).sum())
        rows.append(row)
        all_optimal &= result.get("status") == "OPTIMAL_WITHIN_CONFIGURED_TOLERANCE"
        pd.DataFrame(rows).to_csv(output / "comparison.csv", index=False)
        if exit_code in (1,2):
            print("Stopping after an execution/missing-input error; see this case's run_summary.json.")
            break
    comparison = pd.DataFrame(rows)
    if not comparison.empty and comparison.iloc[0].demand_multiplier == 1 and pd.notna(comparison.iloc[0].objective_usd):
        baseline_cost = float(comparison.iloc[0].objective_usd)
        comparison["objective_change_vs_phi_1_usd"] = comparison.objective_usd - baseline_cost
    comparison.to_csv(output / "comparison.csv", index=False)
    notes = pd.DataFrame([
        ("Interpretation", "Uniform multipliers stress estimated average demand. They do not identify actual latent demand, overbooking or lost customers."),
        ("Baseline", "phi=1 uses supplied monthly route carried passengers/performed departures."),
        ("Remaining uncertainty", "Route-average demand still has no time-of-day variation. Penalties may be cost-recovery proxies rather than observed DB1B fares."),
        ("Status", "Use only completed feasible cases; confirm status and gap before claiming optimality. Missing/error values are not zero spill."),
    ], columns=["topic","explanation"])
    plain_excel(output / "Demand_Sensitivity.xlsx", {"Read_First":notes,"Scenario_Comparison":comparison})
    (output / "comparison.json").write_text(json.dumps(rows, indent=2, allow_nan=False)+"\n")
    print("\n" + comparison[["demand_multiplier","status","objective_usd","estimated_spilled_passengers","flights_with_spill"]].to_string(index=False))
    print(f"Comparison workbook: {(output / 'Demand_Sensitivity.xlsx').resolve()}")
    return 0 if all_optimal else 1


if __name__ == "__main__":
    sys.exit(main())
