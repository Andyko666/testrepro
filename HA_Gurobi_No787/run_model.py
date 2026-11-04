#!/usr/bin/env python3
"""Run the supplied data with candidate types608/696/721 and no787 assignment.

Default estimation is explicit and audited. No source workbook is modified.
Use --mode strict to reject missing inputs instead of using scenario estimates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
from openpyxl import load_workbook

from prepare_data import prepare_data
from gurobi_model import TYPES, FARE_COLUMN, MissingInputs, prepare_inputs, solve_gurobi

ROOT = Path(__file__).resolve().parent
ALLOWED_PARAMETERS = {"turnaround_minutes", "available_fleet", "cost_per_airborne_hour_overrides",
                      "fare_proxy", "demand_adjustment", "route_demand_multipliers",
                      "route_spill_penalty_estimates", "estimation_metadata"}


def merge_parameters(base, overrides):
    if not isinstance(overrides, dict):
        raise ValueError("Parameter JSON must be an object.")
    unknown = set(overrides) - ALLOWED_PARAMETERS
    if unknown:
        raise ValueError(f"Unknown parameter keys: {sorted(unknown)}")
    result = json.loads(json.dumps(base))
    for key, value in overrides.items():
        if key in {"turnaround_minutes", "available_fleet", "cost_per_airborne_hour_overrides"} and isinstance(value, dict):
            unsupported = set(value) - {str(k) for k in TYPES}
            if unsupported:
                raise ValueError(f"{key} includes excluded/unknown aircraft types {sorted(unsupported)}; this project excludes787.")
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result


def import_route_fares(workbook, csv_path):
    """Use locally provided positive directional fares; never guess USD units."""
    fares = pd.read_csv(csv_path)
    required = {"origin", "dest", "fare_usd"}
    if not required <= set(fares):
        raise ValueError("Fare CSV must contain origin,dest,fare_usd in USD per passenger.")
    for column in ["origin", "dest"]:
        fares[column] = fares[column].astype(str).str.strip().str.upper()
    if fares.duplicated(["origin", "dest"]).any():
        raise ValueError("Fare CSV must contain one row per directional route.")
    if fares.fare_usd.isna().any() or not fares.fare_usd.map(lambda v: float(v) > 0 and float(v) < float('inf')).all():
        raise ValueError("Fare CSV prices must be finite and positive.")
    mapping = {(r.origin, r.dest): float(r.fare_usd) for r in fares.itertuples()}
    w = load_workbook(workbook)
    s = w["DB1B_Route_Inputs"]
    header = {c.value: c.column for c in s[1]}
    matched = 0
    for row in range(2, s.max_row+1):
        key = (s.cell(row,header["origin"]).value, s.cell(row,header["dest"]).value)
        if key in mapping:
            s.cell(row,header[FARE_COLUMN]).value = mapping[key]
            matched += 1
    w.save(workbook)
    return dict(file=csv_path.name, sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                input_routes=len(fares), matched_routes=matched,
                note="User-provided directional USD fares; source credibility/weighting is the user's responsibility.")


def write_report(output, preparation, result, mode):
    lines = ["# Hawaiian Airlines: Local Gurobi Run", "",
             f"Outcome: **{result['status']}**.", "",
             "The PDF content is the complete Milestone4 model, although the attachment filename says Milestone3.",
             "At the user's request, candidate type889is excluded. Flights with no remaining historically eligible type are explicitly listed outside this run's model scope; other flights are retained.",
             f"Input mode: **{mode}**. Source and estimate audits are in `prepared/`.", ""]
    if "objective_usd" in result:
        lines += ["| Metric | Value |", "|---|---:|",
                  f"| Objective | USD {result['objective_usd']:,.2f} |",
                  f"| Operating expense | USD {result['operating_cost_usd']:,.2f} |",
                  f"| Spill penalty | USD {result['spill_cost_usd']:,.2f} |",
                  f"| Estimated spill variable | {result['model_spilled_passengers']:,.4f} |",
                  f"| MIP gap | {result['mip_gap']:.6%} |",
                  f"| Model variables / constraints | {result['variables']} / {result['constraints']} |", "",
                  "These are results under the documented inputs. Estimated spill and cost-based penalties do not establish actual lost passengers or fare revenue."]
    if result["status"] == "MISSING_INPUTS_NO_OPTIMIZATION":
        lines += ["", "Strict mode found missing parameters; see `missing_inputs.csv`. This is not mathematical infeasibility."]
    lines += ["", "## Remaining limitations", "",
              "- The three source Excel files contain no DB1B observations. Any optional local fare import is recorded separately and takes precedence. For uncovered routes, estimated mode uses monthly air-operating cost divided by carried passengers as a cost-recovery spill penalty. This is NOT inferred DB1B fare and explicitly differs from that requested PDF input source.",
              "- Type889is excluded, so no787operating-cost proxy is calculated or used. Type837also remains outside the candidate set. Its source cost is preserved but unused.",
              "- Turnaround proxies for608/696/721use the lower tail of positive scheduled ground dwells; dwell includes idle time and is not an approved operational minimum.",
              "- Available-fleet estimates use observed tails and route/type compatibility. Ambiguous types, maintenance, spares, and international commitments remain uncertain. No FAA verification is invented.",
              "- Demand and route airborne hours retain all historical aircraft observations, including787on retained routes. Removing an assignment option does not remove those passengers. Spill-penalty calibration uses only candidate aircraft with supplied costs, so no787cost is needed.",
              "- Demand is the PDF passengers/departures estimate with phi=1 unless explicitly changed. Monthly carried passengers do not identify unmet demand.",
              "- Ten monthly rows have scheduled departures0but performed departures>0. They are flagged and retained, not presumed wrong. All ratios use performed departures.",
              "- HNL-LAX/type696has two nonidentical rows. They are summed, not deleted as duplicates.",
              "- One planned ground overlap is flagged and excluded from positive-dwell estimates; original timestamps are preserved.",
              "- UTC conversions retain dates, use IANA time zones including Phoenix's no-DST rule, and reconcile destination clocks.", "",
              "## PDF-equivalent compact formulation", "",
              "Default compact mode removes equal ground-inventory variables at non-events and enforces the fleet cap at one time cut per type, since total fleet is conserved by flow. Every returned solution is then checked at ALL common PDF events. Use `--formulation full` for the literal shared-event formulation.",
              "A compact model keeps the same optimal flight assignments/objective while avoiding unnecessary model size; a size-limited Gurobi license may be sufficient for this dataset. Licensing behavior depends on the installed version and license.", ""]
    (output / "RUN_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--on-time", type=Path, default=ROOT / "data/on_time.xlsx")
    p.add_argument("--t100", type=Path, default=ROOT / "data/t100.xlsx")
    p.add_argument("--costs", type=Path, default=ROOT / "data/costs.xlsx")
    p.add_argument("--mode", choices=["estimated", "strict"], default="estimated")
    p.add_argument("--parameters", type=Path, help="Optional explicit JSON overrides; see parameters_example.json.")
    p.add_argument("--fares", type=Path, help="Optional CSV with origin,dest,fare_usd; observed fares take precedence over proxies.")
    p.add_argument("--formulation", choices=["compact", "full"], default="compact")
    p.add_argument("--validate-only", action="store_true", help="Validate all inputs without importing Gurobi or optimizing.")
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--mip-gap", type=float, default=0.0001)
    p.add_argument("--output", type=Path, help="New output directory; default is results/<UTC timestamp>.")
    a = p.parse_args(argv)
    output = a.output or ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC")
    if output.exists() and any(output.iterdir()):
        print(f"Choose a new output directory; refusing to mix results with existing files: {output}", file=sys.stderr)
        return 1
    output.mkdir(parents=True, exist_ok=True)
    preparation = {}
    try:
        print("Preparing the supplied three Excel files; originals remain unchanged.", flush=True)
        workbook, generated, preparation = prepare_data(a.on_time, a.t100, a.costs, output / "prepared")
        parameters = json.loads(generated.read_text()) if a.mode == "estimated" else {}
        if a.parameters:
            parameters = merge_parameters(parameters, json.loads(a.parameters.read_text()))
        (output / "effective_parameters.json").write_text(json.dumps(parameters, indent=2, allow_nan=False)+"\n")
        fare_import = import_route_fares(workbook, a.fares) if a.fares else None
        print(f"Input mode: {a.mode}. See prepared audits for every observation, estimate and limitation.", flush=True)
        data = prepare_inputs(workbook, parameters)
        data["formulation"] = a.formulation
        data["flights"].to_csv(output / "calculated_flight_parameters.csv", index=False)
        data["aircraft"].to_csv(output / "effective_aircraft_parameters.csv")
        data["audit"].to_csv(output / "parameter_provenance.csv", index=False)
        data["balance"].to_csv(output / "airport_balance.csv", index=False)
        counts = dict(flights=len(data["flights"]), airports=len(data["airports"]),
                      eligible_pairs=len(data["pairs"]), common_events=len(data["events"]))
        observed = data["flights"].fare_source.eq("SUPPLIED_DIRECTIONAL_MARKET_FARE")
        penalty_inputs = dict(supplied_fare_routes=len(data["flights"].loc[observed,["origin","dest"]].drop_duplicates()),
                              proxy_penalty_routes=len(data["flights"].loc[~observed,["origin","dest"]].drop_duplicates()))
        if data["balance"].net_departures.ne(0).any():
            print("WARNING: cyclic airport balance fails. Increasing aircraft counts cannot fix this scope conflict.", flush=True)
        if a.validate_only:
            result = dict(status="INPUTS_VALIDATED_NO_OPTIMIZATION", **counts)
        else:
            result = solve_gurobi(data, output, a.time_limit, a.mip_gap)
        result.update(mode=a.mode, preparation=preparation, parameters_file="effective_parameters.json",
                      prepared_workbook_sha256=hashlib.sha256(workbook.read_bytes()).hexdigest(),
                      fare_import=fare_import, penalty_inputs=penalty_inputs)
        exit_code = 0 if a.validate_only or result.get("solution_count", 0) > 0 else 3
    except MissingInputs as exc:
        pd.DataFrame(exc.missing).to_csv(output / "missing_inputs.csv", index=False)
        result = dict(status="MISSING_INPUTS_NO_OPTIMIZATION", missing_count=len(exc.missing),
                      message=str(exc), preparation=preparation)
        exit_code = 2
    except Exception as exc:
        result = dict(status="EXECUTION_ERROR_NO_COMPLETED_RESULT", error_type=type(exc).__name__,
                      message=str(exc), preparation=preparation)
        exit_code = 1
    (output / "run_summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    write_report(output, preparation, result, a.mode)
    print(f"Status: {result['status']}")
    if "objective_usd" in result:
        print(f"Objective: USD {result['objective_usd']:,.2f}; MIP gap: {result['mip_gap']:.6%}")
    if "message" in result:
        print(result["message"])
    print(f"Output: {output.resolve()}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
