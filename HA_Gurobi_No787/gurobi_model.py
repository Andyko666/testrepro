#!/usr/bin/env python3
"""Run the Milestone 4 cyclic fleet-assignment MILP using Gurobi.

The cleaned workbook contains source records and missing-input placeholders only.
All explicit assumptions belong in a separate parameter JSON, never in raw cells.
No estimate is silently invented: missing fare, cost, fleet or turnaround inputs
stop execution with a detailed missing-input report. Gurobi is imported only
after validation, so --validate-only does not require a Gurobi installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DAY = 1440
TYPES = (608, 696, 721)
FARE_COLUMN = "DB1B_weighted_directional_market_fare_USD_INPUT_REQUIRED"
COST_COLUMN = "cost_per_air_hour_from_provided_2024Q4_summary_USD"
TURN_COLUMN = "minimum_turnaround_minutes_INPUT_REQUIRED"
FLEET_COLUMN = "available_fleet_count_on_2024_10_16_INPUT_REQUIRED"


class MissingInputs(ValueError):
    def __init__(self, missing):
        self.missing = missing
        super().__init__(f"{len(missing)} required inputs remain missing. See missing_inputs.csv.")


def finite_number(value, label, minimum=0.0, strictly_positive=False, integer=False):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric, not boolean.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a finite number.") from None
    if not math.isfinite(result) or result < minimum or (strictly_positive and result <= 0):
        raise ValueError(f"{label} is outside its permitted finite range.")
    if integer and not result.is_integer():
        raise ValueError(f"{label} must be a whole number; this implementation uses whole minutes.")
    return int(result) if integer else result


def active_copies(departure, ready, event):
    """Count daily copies occupying [departure, ready) at an event cut.

    Full dates are retained until occupation is established. This includes
    departure, excludes exact readiness, and handles occupation longer than a day.
    """
    return (event - departure) // DAY - (event - ready) // DAY


def prepare_inputs(workbook: Path, parameters: dict):
    sheets = pd.read_excel(workbook, sheet_name=None)
    required = {"Schedule_UTC", "T100_Monthly", "DB1B_Route_Inputs", "Aircraft_Inputs"}
    if required - set(sheets):
        raise ValueError(f"Workbook is missing sheets: {sorted(required - set(sheets))}")
    f = sheets["Schedule_UTC"].copy().reset_index(drop=True)
    raw = sheets["T100_Monthly"].copy()
    aircraft = sheets["Aircraft_Inputs"].copy()
    if f.empty or f.flight_id.duplicated().any():
        raise ValueError("The schedule must contain unique nonempty flight records.")
    if aircraft.aircraft_type_BTS_code.duplicated().any():
        raise ValueError("Aircraft type inputs must be unique.")
    aircraft = aircraft.set_index("aircraft_type_BTS_code")
    if set(aircraft.index) != set(TYPES):
        raise ValueError("This no-787 project expects aircraft types 608, 696 and 721.")
    if not (f.Cancelled.eq(0) & f.Diverted.eq(0)).all():
        raise ValueError("Canceled/diverted flights need an explicit scope decision before solving.")
    dep = pd.to_datetime(f.scheduled_dep_UTC, utc=True, errors="raise")
    arr = pd.to_datetime(f.scheduled_arr_UTC, utc=True, errors="raise")
    if dep.isna().any() or arr.isna().any():
        raise ValueError("Scheduled UTC timestamps cannot be missing.")
    if (dep.dt.second.ne(0) | arr.dt.second.ne(0)
            | dep.dt.microsecond.ne(0) | arr.dt.microsecond.ne(0)).any():
        raise ValueError("Scheduled timestamps must use whole minutes.")
    base = dep.min().normalize()
    f["dep_min"] = ((dep-base).dt.total_seconds()/60).astype(int)
    f["arr_min"] = ((arr-base).dt.total_seconds()/60).astype(int)
    duration = f.arr_min-f.dep_min
    if (duration <= 0).any() or not np.array_equal(duration, f.CRSElapsedTime_minutes):
        raise ValueError("Full UTC durations must be positive and match scheduled elapsed minutes.")
    # Monthly source rows are aggregated ONCE. The expanded flight/type matches
    # are not new monthly observations and must never be summed as such.
    raw = raw[(raw.UNIQUE_CARRIER == "HA") & (raw.YEAR == 2024) & (raw.MONTH == 10)
              & (raw.AIRCRAFT_CONFIG == 1)
              & (raw.DEPARTURES_PERFORMED > 0)].copy()
    if raw.empty:
        raise ValueError("No usable October 2024 HA passenger T100 observations.")
    measure_cols = ["PASSENGERS", "SEATS", "DEPARTURES_PERFORMED", "AIR_TIME"]
    if not np.isfinite(raw[measure_cols].to_numpy(dtype=float)).all():
        raise ValueError("Monthly T100 measures must be finite.")
    if (raw.PASSENGERS < 0).any() or (raw.SEATS <= 0).any() or (raw.AIR_TIME <= 0).any():
        raise ValueError("T100 passengers must be nonnegative; seats and airborne time positive.")
    routes = raw.groupby(["ORIGIN", "DEST"])[measure_cols].sum()
    routes["observed_passengers_per_departure"] = routes.PASSENGERS/routes.DEPARTURES_PERFORMED
    routes["load_factor"] = routes.PASSENGERS/routes.SEATS
    # The PDF uses AIR_TIME and cost per AIRBORNE hour. RAMP_TO_RAMP/block
    # hours are preserved as source data but are not substituted into the cost.
    routes["airborne_hours"] = routes.AIR_TIME/(60*routes.DEPARTURES_PERFORMED)
    f = f.merge(routes[["observed_passengers_per_departure", "load_factor", "airborne_hours"]],
                left_on=["origin", "dest"], right_index=True, how="left", validate="many_to_one")
    if f.observed_passengers_per_departure.isna().any():
        raise ValueError("A scheduled directional route lacks T100 demand or time observations.")
    f = f.reset_index(drop=True)
    rule = parameters.get("demand_adjustment")
    if rule is None:
        # Explicit baseline assumption, not a fact recovered from flown demand.
        # The PDF permits phi>=1 but supplies no threshold or multiplier.
        f["phi"] = 1.0
        demand_source = "BASELINE_ASSUMPTION_phi_1_NO_UNOBSERVED_DEMAND_INFLATION"
    else:
        threshold = finite_number(rule.get("load_factor_threshold"), "load_factor_threshold")
        if threshold > 1:
            raise ValueError("load_factor_threshold must lie in [0,1].")
        high = finite_number(rule.get("multiplier_at_or_above"), "multiplier_at_or_above", minimum=1)
        low = finite_number(rule.get("multiplier_below", 1.0), "multiplier_below", minimum=1)
        f["phi"] = np.where(f.load_factor >= threshold, high, low)
        demand_source = "EXPLICIT_PARAMETER_SCENARIO_NOT_OBSERVED_DEMAND"
    # Optional route-level demand multipliers are explicit estimates from the
    # separate estimator, not values silently inferred inside optimization.
    route_phi = parameters.get("route_demand_multipliers", {})
    for i, row in f.iterrows():
        key = f"{row.origin}-{row.dest}"
        if key in route_phi:
            f.loc[i, "phi"] = finite_number(route_phi[key], f"route_demand_multipliers.{key}", minimum=1.0)
    f["demand"] = f.observed_passengers_per_departure*f.phi
    f["demand_source"] = demand_source
    if route_phi:
        f["demand_source"] = "EXPLICIT_ROUTE_DEMAND_ESTIMATE_SEE_ESTIMATION_METADATA"
    fares = sheets["DB1B_Route_Inputs"][["origin", "dest", FARE_COLUMN]].copy()
    if fares.duplicated(["origin", "dest"]).any():
        raise ValueError("Directional route fares must be unique.")
    f = f.merge(fares, on=["origin", "dest"], how="left", validate="many_to_one")
    f["fare_usd"] = f[FARE_COLUMN]
    f["fare_source"] = "SUPPLIED_DIRECTIONAL_MARKET_FARE"
    # A cost-per-carried-passenger estimate is a spill-penalty scenario, NOT a
    # recovered DB1B market fare. Prefer genuine source fares when available.
    route_penalties = parameters.get("route_spill_penalty_estimates", {})
    for i, row in f.iterrows():
        key = f"{row.origin}-{row.dest}"
        if pd.isna(row.fare_usd) and key in route_penalties:
            f.loc[i, "fare_usd"] = finite_number(
                route_penalties[key], f"route_spill_penalty_estimates.{key}", strictly_positive=True)
            f.loc[i, "fare_source"] = "COST_RECOVERY_SPILL_PENALTY_PROXY_NOT_DB1B_FARE"
    fare_proxy = parameters.get("fare_proxy")
    if fare_proxy is not None:
        # OPTIONAL ILLUSTRATIVE ASSUMPTION. A distance formula does not recover
        # missing DB1B observations or actual flight-level ticket prices.
        base_fare = finite_number(fare_proxy.get("base_usd"), "fare_proxy.base_usd")
        slope = finite_number(fare_proxy.get("per_mile_usd"), "fare_proxy.per_mile_usd")
        mask = f.fare_usd.isna()
        f.loc[mask, "fare_usd"] = base_fare+slope*f.loc[mask, "Distance_miles"]
        f.loc[mask, "fare_source"] = "EXPLICIT_ILLUSTRATIVE_DISTANCE_PROXY_NOT_DB1B"
    missing, audit = [], []
    for route in f.loc[f.fare_usd.isna(), ["origin", "dest"]].drop_duplicates().itertuples(index=False):
        missing.append(dict(parameter="directional_fare_usd", key=f"{route.origin}-{route.dest}",
                            solution="Supply a positive DB1B market fare or explicitly configure fare_proxy.",
                            pdf_reference="Section 2, p_f and p_f>0; no numerical route fares supplied."))
    for i in f.index[f.fare_usd.notna()]:
        f.loc[i, "fare_usd"] = finite_number(f.loc[i, "fare_usd"], f"fare[{f.loc[i,'flight_id']}]", strictly_positive=True)
    totals = raw.groupby("AIRCRAFT_TYPE")[["SEATS", "DEPARTURES_PERFORMED"]].sum()
    for k in TYPES:
        if k not in totals.index:
            raise ValueError(f"No T100 capacity observations for aircraft type {k}.")
        aircraft.loc[k, "capacity"] = totals.loc[k, "SEATS"]/totals.loc[k, "DEPARTURES_PERFORMED"]
        for out_col, source_col, parameter_name, positive, integer in [
            ("turn_minutes", TURN_COLUMN, "turnaround_minutes", False, True),
            ("fleet", FLEET_COLUMN, "available_fleet", False, True),
            ("cost_per_hour", COST_COLUMN, "cost_per_airborne_hour_overrides", True, False),
        ]:
            configured = (parameters.get(parameter_name) or {}).get(str(k))
            original = aircraft.loc[k, source_col]
            value = configured if configured is not None else original
            source = "EXPLICIT_PARAMETER_VALUE_OR_SCENARIO" if configured is not None else "SUPPLIED_WORKBOOK_INPUT"
            if pd.isna(value):
                missing.append(dict(parameter=parameter_name, key=str(k),
                                    solution=f"Fill Aircraft_Inputs.{source_col} or {parameter_name}.{k} in the JSON.",
                                    pdf_reference="Section 2: document sources/assumptions for t_k, n_k and missing cost proxies."))
                aircraft.loc[k, out_col] = np.nan
                source = "MISSING"
            else:
                aircraft.loc[k, out_col] = finite_number(value, f"{parameter_name}.{k}", strictly_positive=positive, integer=integer)
            audit.append(dict(parameter=out_col, key=str(k), value=aircraft.loc[k, out_col], source=source))
        audit.append(dict(parameter="capacity", key=str(k), value=aircraft.loc[k, "capacity"],
                          source="T100_TYPE_SUM_SEATS_DIVIDED_BY_SUM_DEPARTURES"))
    if missing:
        raise MissingInputs(missing)
    # Historical 787 passengers still describe demand on retained routes. Only
    # assignment eligibility is restricted to the three candidate types.
    route_types = raw[raw.AIRCRAFT_TYPE.isin(TYPES)].groupby(["ORIGIN", "DEST"]).AIRCRAFT_TYPE.agg(lambda values: sorted(set(map(int, values)))).to_dict()
    eligible = {i: route_types.get((r.origin, r.dest), []) for i, r in f.iterrows()}
    if any(not values for values in eligible.values()):
        raise ValueError("Every retained flight must have at least one historically eligible type.")
    airports = sorted(set(f.origin)|set(f.dest))
    balance = pd.DataFrame({"airport": airports})
    balance["departures"] = balance.airport.map(f.origin.value_counts()).fillna(0).astype(int)
    balance["arrivals"] = balance.airport.map(f.dest.value_counts()).fillna(0).astype(int)
    balance["net_departures"] = balance.departures-balance.arrivals
    pairs = [(i,k) for i in f.index for k in eligible[i]]
    events = sorted({int(f.loc[i,"dep_min"])%DAY for i in f.index}
                    | {int(f.loc[i,"arr_min"]+aircraft.loc[k,"turn_minutes"])%DAY for i,k in pairs})
    return dict(flights=f, aircraft=aircraft, eligible=eligible, pairs=pairs,
                airports=airports, events=events, balance=balance,
                audit=pd.DataFrame(audit), parameters=parameters)


def build_full_model(data, gp, time_limit=300.0, mip_gap=0.0001, log_path=None):
    """Use all PDF common events and integer airport/type ground inventories."""
    GRB = gp.GRB
    f, ac = data["flights"].to_dict("index"), data["aircraft"].to_dict("index")
    airports, events, pairs = data["airports"], data["events"], data["pairs"]
    model = gp.Model("Hawaiian_Milestone4_Cyclic_Fleet_Assignment")
    if log_path is not None:
        model.Params.LogFile = str(log_path)
    model.Params.TimeLimit = finite_number(time_limit, "time_limit", strictly_positive=True)
    model.Params.MIPGap = finite_number(mip_gap, "mip_gap")
    x = model.addVars(pairs, vtype=GRB.BINARY, name="x")
    y_keys = [(a,k,m) for a in airports for k in TYPES for m in range(len(events))]
    y = model.addVars(y_keys, vtype=GRB.INTEGER, lb=0,
                      ub={key: ac[key[1]]["fleet"] for key in y_keys}, name="y")
    u = model.addVars(list(f), vtype=GRB.CONTINUOUS, lb=0, name="u")
    model.setObjective(gp.quicksum(ac[k]["cost_per_hour"]*f[i]["airborne_hours"]*x[i,k] for i,k in pairs)
                       + gp.quicksum(f[i]["fare_usd"]*u[i] for i in f), GRB.MINIMIZE)
    for i in f:
        model.addConstr(gp.quicksum(x[i,k] for k in data["eligible"][i]) == 1, name=f"coverage_{i}")
        model.addConstr(u[i]+gp.quicksum(ac[k]["capacity"]*x[i,k] for k in data["eligible"][i]) >= f[i]["demand"], name=f"spill_{i}")
    indices = {event:m for m,event in enumerate(events)}
    inbound, outbound = {}, {}
    for i,k in pairs:
        dep_event = indices[int(f[i]["dep_min"])%DAY]
        ready_event = indices[int(f[i]["arr_min"]+ac[k]["turn_minutes"])%DAY]
        inbound.setdefault((f[i]["dest"],k,ready_event), []).append((i,k))
        outbound.setdefault((f[i]["origin"],k,dep_event), []).append((i,k))
    for a,k,m in y_keys:
        # Modulo predecessor enforces y_ak0=y_akM exactly, without a duplicate
        # variable. Ready arrivals may depart at this same event minute.
        model.addConstr(y[a,k,(m-1)%len(events)]
                        + gp.quicksum(x[pair] for pair in inbound.get((a,k,m),[]))
                        == y[a,k,m] + gp.quicksum(x[pair] for pair in outbound.get((a,k,m),[])),
                        name=f"flow_{a}_{k}_{m}")
    for k in TYPES:
        for m,event in enumerate(events):
            busy = [(i,active_copies(int(f[i]["dep_min"]), int(f[i]["arr_min"]+ac[k]["turn_minutes"]), event))
                    for i in f if k in data["eligible"][i]]
            model.addConstr(gp.quicksum(y[a,k,m] for a in airports)
                            + gp.quicksum(count*x[i,k] for i,count in busy if count)
                            <= ac[k]["fleet"], name=f"fleet_{k}_{m}")
    model.update()
    return model,x,y,u


def build_model(data, gp, time_limit=300.0, mip_gap=0.0001, log_path=None):
    """Select an equivalent compact formulation or the literal shared-event PDF."""
    if data.get("formulation", "compact") == "full":
        return build_full_model(data, gp, time_limit, mip_gap, log_path)
    from compact_model import build_compact_model
    return build_compact_model(data, gp, time_limit, mip_gap, log_path)


def validate_solution(data, xv, yv, uv, objective, optimal):
    """Check operational residuals independently of Gurobi's assembled rows."""
    f, ac = data["flights"].to_dict("index"), data["aircraft"].to_dict("index")
    events, airports = data["events"], data["airports"]
    checks = dict(coverage=0.0, integrality=0.0, spill_lower_bound=0.0,
                  exact_spill_error=0.0, cyclic_flow=0.0, fleet_excess=0.0,
                  fleet_variation=0.0, nonnegative=0.0, binary_upper_bound=0.0)
    checks["coverage"] = max(abs(sum(xv[i,k] for k in data["eligible"][i])-1) for i in f)
    integer_values = list(xv.values())+list(yv.values())
    checks["integrality"] = max(abs(v-round(v)) for v in integer_values)
    checks["nonnegative"] = max(0.0, -min(integer_values+list(uv.values())))
    checks["binary_upper_bound"] = max(0.0, max(xv.values())-1)
    for i in f:
        expected = max(f[i]["demand"]-sum(ac[k]["capacity"]*xv[i,k] for k in data["eligible"][i]),0)
        checks["spill_lower_bound"] = max(checks["spill_lower_bound"], expected-uv[i])
        checks["exact_spill_error"] = max(checks["exact_spill_error"], abs(expected-uv[i]))
    fleet_present = {}
    for k in TYPES:
        totals=[]
        for m,event in enumerate(events):
            occupied=0.0
            for i in f:
                if (i,k) not in xv:
                    continue
                d=int(f[i]["dep_min"])
                r=int(f[i]["arr_min"]+ac[k]["turn_minutes"])
                # Enumerate daily copies independently of the floor identity
                # used to build the fleet constraints.
                occupied += xv[i,k]*sum(d+DAY*z <= event < r+DAY*z
                    for z in range(math.floor((event-r)/DAY)-1, math.floor((event-d)/DAY)+2))
            total=occupied+sum(yv[a,k,m] for a in airports)
            totals.append(total)
            checks["fleet_excess"]=max(checks["fleet_excess"],total-ac[k]["fleet"])
            for a in airports:
                incoming=sum(xv[i,k] for i in f if (i,k) in xv and f[i]["dest"]==a
                             and int(f[i]["arr_min"]+ac[k]["turn_minutes"])%DAY==event)
                outgoing=sum(xv[i,k] for i in f if (i,k) in xv and f[i]["origin"]==a
                             and int(f[i]["dep_min"])%DAY==event)
                residual=yv[a,k,(m-1)%len(events)]+incoming-outgoing-yv[a,k,m]
                checks["cyclic_flow"]=max(checks["cyclic_flow"],abs(residual))
        checks["fleet_variation"]=max(checks["fleet_variation"], max(totals)-min(totals))
        fleet_present[str(k)]=int(round(max(totals)))
    op=sum(ac[k]["cost_per_hour"]*f[i]["airborne_hours"]*value for (i,k),value in xv.items())
    spill=sum(f[i]["fare_usd"]*uv[i] for i in f)
    checks["objective_error"]=abs(op+spill-objective)
    # Feasible time-limit incumbents may have slack u: only an optimum with
    # positive fare penalties forces exact positive-part spill. Never mistake
    # such an incumbent for an optimal cost/spill result.
    required = {key:value for key,value in checks.items() if optimal or key!="exact_spill_error"}
    checks["passed"]=all(value <= 1e-5 for value in required.values())
    checks["fleet_present_not_minimum_fleet"]=fleet_present
    return checks


def plain_excel(path, tables):
    """Plain black text, white background; no colored tables or charts."""
    from openpyxl.styles import Font, PatternFill
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name,frame in tables.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            sheet=writer.sheets[name[:31]]
            sheet.freeze_panes="A2"
            sheet.auto_filter.ref=sheet.dimensions
            for row in sheet:
                for cell in row:
                    cell.font=Font(name="Calibri",size=11,color="000000",bold=(cell.row==1))
                    cell.fill=PatternFill(fill_type=None)


def solve_gurobi(data, output, time_limit, mip_gap):
    try:
        import gurobipy as gp
    except ImportError:
        raise RuntimeError("gurobipy is not installed. Run python -m pip install gurobipy, then configure a suitable Gurobi license.") from None
    model,x,y,u=build_model(data,gp,time_limit,mip_gap,output/"gurobi.log")
    model.write(str(output/"model.lp"))
    model.optimize()
    if model.Status==gp.GRB.INF_OR_UNBD:
        model.Params.DualReductions=0
        model.optimize()
    names={gp.GRB.OPTIMAL:"OPTIMAL_WITHIN_CONFIGURED_TOLERANCE",gp.GRB.INFEASIBLE:"INFEASIBLE",
           gp.GRB.UNBOUNDED:"UNBOUNDED",gp.GRB.INF_OR_UNBD:"INFEASIBLE_OR_UNBOUNDED",
           gp.GRB.TIME_LIMIT:"TIME_LIMIT",gp.GRB.INTERRUPTED:"INTERRUPTED",
           gp.GRB.SUBOPTIMAL:"SUBOPTIMAL"}
    result=dict(status=names.get(model.Status,f"GUROBI_STATUS_{model.Status}"),gurobi_status=int(model.Status),
                formulation=data.get("formulation", "compact"),gurobi_version=".".join(map(str,gp.gurobi.version())),
                solution_count=int(model.SolCount),runtime_seconds=float(model.Runtime),
                variables=model.NumVars,constraints=model.NumConstrs,retained_flights=len(data["flights"]),
                airports=len(data["airports"]),common_events=len(data["events"]),
                parameters=data["parameters"])
    if model.Status==gp.GRB.INFEASIBLE:
        model.computeIIS()
        model.write(str(output/"infeasibility.ilp"))
        result["iis_file"]="infeasibility.ilp"
    if model.SolCount>0:
        result.update(objective_usd=float(model.ObjVal),mip_gap=float(model.MIPGap),dual_bound_usd=float(model.ObjBound))
        xv={key:float(variable.X) for key,variable in x.items()}
        yv={key:float(variable.X) for key,variable in y.items()}
        uv={key:float(variable.X) for key,variable in u.items()}
        checks=validate_solution(data,xv,yv,uv,result["objective_usd"],model.Status==gp.GRB.OPTIMAL)
        if not checks["passed"]:
            raise RuntimeError(f"Independent solution validation failed: {checks}")
        result["validation"]=checks
        rows=[]
        for i,f in data["flights"].iterrows():
            k=max(data["eligible"][i],key=lambda k:xv[i,k])
            ac=data["aircraft"].loc[k]
            op=ac.cost_per_hour*f.airborne_hours
            rows.append(dict(flight_id=f.flight_id,origin=f.origin,dest=f.dest,
                             scheduled_departure_UTC=f.get("scheduled_dep_UTC"),
                             scheduled_arrival_UTC=f.get("scheduled_arr_UTC"),
                             aircraft_type=k,capacity=ac.capacity,demand=f.demand,
                             phi=f.phi,airborne_hours=f.airborne_hours,
                             spill_penalty_usd=f.fare_usd,penalty_source=f.fare_source,
                             estimated_capacity_shortfall=max(f.demand-ac.capacity,0),
                             model_spill_variable=uv[i],operating_cost_usd=op,
                             spill_cost_usd=uv[i]*f.fare_usd,total_cost_usd=op+uv[i]*f.fare_usd))
        assignments=pd.DataFrame(rows)
        inventories=pd.DataFrame([dict(airport=a,aircraft_type=k,event_minute_UTC=data["events"][m],
                                       inventory=int(round(value))) for (a,k,m),value in yv.items()])
        assignments.to_csv(output/"assignments.csv",index=False)
        inventories.to_csv(output/"ground_inventory.csv",index=False)
        result.update(operating_cost_usd=float(assignments.operating_cost_usd.sum()),
                      spill_cost_usd=float(assignments.spill_cost_usd.sum()),
                      model_spilled_passengers=float(assignments.model_spill_variable.sum()),
                      estimated_capacity_shortfall=float(assignments.estimated_capacity_shortfall.sum()))
        plain_excel(output/"gurobi_results.xlsx",{"Assignments":assignments,"Ground_Inventory":inventories,
                    "Aircraft_Parameters":data["aircraft"].reset_index(),"Parameter_Provenance":data["audit"]})
    model.dispose()
    return result


