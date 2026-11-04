#!/usr/bin/env python3
"""Compare the historical mean and strict historical LF threshold demand rules."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

from gurobi_model import plain_excel
from run_model import ROOT, demand_multiplier_argument, load_factor_threshold_argument, main as run_one


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--thresholds", nargs="+", type=load_factor_threshold_argument, default=[0.90,0.95])
    p.add_argument("--high-load-multiplier", type=demand_multiplier_argument, default=1.20)
    p.add_argument("--output", type=Path)
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--mip-gap", type=float, default=0.0001)
    p.add_argument("--parameters", type=Path)
    p.add_argument("--fares", type=Path)
    a = p.parse_args(argv)
    output = a.output or ROOT / "results" / ("load_factor_comparison_"+datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC"))
    if output.exists() and any(output.iterdir()):
        print(f"Choose a new output directory: {output}",file=sys.stderr)
        return 1
    output.mkdir(parents=True,exist_ok=True)
    cases = [("historical_mean",None,["--demand-multiplier","1.0"])]
    for cutoff in dict.fromkeys(a.thresholds):
        cases.append((f"lf_strictly_above_{cutoff:g}",cutoff,
                      ["--load-factor-threshold",str(cutoff),"--high-load-multiplier",str(a.high_load_multiplier)]))
    rows=[]
    all_optimal=True
    for index,(name,cutoff,control) in enumerate(cases,1):
        case=output/f"case_{index:02d}_{name}"
        args=control+["--output",str(case),"--time-limit",str(a.time_limit),"--mip-gap",str(a.mip_gap)]
        if a.parameters:args += ["--parameters",str(a.parameters)]
        if a.fares:args += ["--fares",str(a.fares)]
        print(f"\nRunning {name}",flush=True)
        code=run_one(args)
        f=case/"run_summary.json"
        result=json.loads(f.read_text()) if f.exists() else {}
        demand=result.get("demand_inputs",{})
        row=dict(scenario=name,strict_historical_lf_threshold=cutoff,
                 high_load_multiplier=None if cutoff is None else a.high_load_multiplier,
                 status=result.get("status","NO_RUN_SUMMARY"),uplifted_routes=demand.get("uplifted_routes"),
                 uplifted_flights=demand.get("uplifted_flights"),estimated_total_demand=demand.get("total_estimated_demand"),
                 objective_usd=result.get("objective_usd"),spill_cost_usd=result.get("spill_cost_usd"),
                 estimated_spill=result.get("model_spilled_passengers"),flights_with_spill=None,
                 mip_gap=result.get("mip_gap"),case_directory=case.name)
        if (case/"assignments.csv").exists():
            assignments=pd.read_csv(case/"assignments.csv")
            row["flights_with_spill"]=int(assignments.model_spill_variable.gt(1e-5).sum())
        rows.append(row)
        all_optimal &= result.get("status")=="OPTIMAL_WITHIN_CONFIGURED_TOLERANCE"
        pd.DataFrame(rows).to_csv(output/"comparison.csv",index=False)
        if code in (1,2):break
    notes=pd.DataFrame([
        ("Rule","LF=sum historical directional route PASSENGERS/sum historical directional route SEATS. Strict LF>threshold:phi=high multiplier; otherwise1."),
        ("Weighting","Sum passenger/seat observations first, including historical787operations on retained routes. Do not average aircraft-type LF ratios."),
        ("Timing","LF is fixed before optimization. Do not use assigned capacity or inflated demand to trigger uplift."),
        ("Interpretation","Threshold/uplift are team assumptions consistent with the PDF's documented rule requirement, not measured lost demand."),
        ("At0.95","If no route has historical LF>0.95, this scenario equals the unadjusted baseline; no uplift is expected."),
    ],columns=["topic","explanation"])
    comparison=pd.DataFrame(rows)
    comparison.to_csv(output/"comparison.csv",index=False)
    (output/"comparison.json").write_text(json.dumps(rows,indent=2,allow_nan=False)+"\n")
    plain_excel(output/"Load_Factor_Comparison.xlsx",{"Read_First":notes,"Scenario_Comparison":comparison})
    print(comparison.to_string(index=False))
    print(f"Comparison: {(output/'Load_Factor_Comparison.xlsx').resolve()}")
    return 0 if all_optimal else 1


if __name__=="__main__":
    sys.exit(main())
