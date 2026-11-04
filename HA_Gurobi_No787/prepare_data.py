"""Prepare the three supplied Excel files for the PDF fleet-assignment model.

Source files are immutable. The generated workbook preserves missing empirical
inputs. Optional estimates are supplied separately in generated_parameters.json.
No FAA registration or year-end fleet evidence is assumed to have been supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment

TYPES = (608, 696, 721)
HISTORY_TYPES = (608, 696, 721, 889)
MODELS = {608: "Boeing 717-200", 696: "Airbus A330-200", 721: "Airbus A321neo", 889: "Boeing 787-9"}
COST_COLUMN = "cost_per_air_hour_from_provided_2024Q4_summary_USD"
TURN_COLUMN = "minimum_turnaround_minutes_INPUT_REQUIRED"
FLEET_COLUMN = "available_fleet_count_on_2024_10_16_INPUT_REQUIRED"
FARE_COLUMN = "DB1B_weighted_directional_market_fare_USD_INPUT_REQUIRED"
AIRPORT_ZONES = {**dict.fromkeys(["HNL", "OGG", "KOA", "ITO", "LIH"], "Pacific/Honolulu"),
                 **dict.fromkeys(["LAX", "LAS", "LGB", "OAK", "ONT", "PDX", "SAN", "SEA", "SFO", "SJC", "SMF", "FAT", "GEG"], "America/Los_Angeles"),
                 "PHX": "America/Phoenix", "SLC": "America/Denver", "AUS": "America/Chicago",
                 "BOS": "America/New_York", "JFK": "America/New_York", "PPG": "Pacific/Pago_Pago"}


def hhmm_minutes(value):
    """Convert BTS HHMM to elapsed minutes; 2400 denotes next-day midnight."""
    if pd.isna(value) or not float(value).is_integer():
        raise ValueError(f"Invalid whole-minute HHMM value: {value!r}")
    value = int(value)
    if value == 2400:
        return 1440
    hour, minute = divmod(value, 100)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"Invalid HHMM value: {value}")
    return hour*60+minute


def scheduled_utc(service_date, departure_hhmm, origin, elapsed_minutes, arrival_hhmm, dest):
    if origin not in AIRPORT_ZONES or dest not in AIRPORT_ZONES:
        raise ValueError(f"Unknown airport timezone for {origin}-{dest}; add an authoritative IANA mapping.")
    day = pd.Timestamp(service_date).date()
    local = datetime.combine(day, datetime.min.time()) + timedelta(minutes=hhmm_minutes(departure_hhmm))
    dep = local.replace(tzinfo=ZoneInfo(AIRPORT_ZONES[origin])).astimezone(timezone.utc)
    if not math.isfinite(float(elapsed_minutes)) or float(elapsed_minutes) <= 0 or not float(elapsed_minutes).is_integer():
        raise ValueError("Scheduled elapsed time must be positive finite whole minutes.")
    arr = dep + timedelta(minutes=float(elapsed_minutes))
    dest_local = arr.astimezone(ZoneInfo(AIRPORT_ZONES[dest]))
    if dest_local.hour*60+dest_local.minute != hhmm_minutes(arrival_hhmm) % 1440:
        raise ValueError(f"Scheduled arrival clock does not reconcile for {origin}-{dest}.")
    return dep, arr


def write_plain_excel(path, tables):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in tables.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            sheet = writer.sheets[name[:31]]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for row in sheet:
                for cell in row:
                    cell.font = Font(name="Calibri", size=11, color="000000", bold=cell.row == 1)
                    cell.fill = PatternFill(fill_type=None)
                    cell.alignment = Alignment(vertical="top")
            for column in sheet.iter_cols():
                sheet.column_dimensions[column[0].column_letter].width = min(60, max(12, max(len(str(c.value or "")) for c in list(column)[:50])+2))


def normalize_schedule(raw):
    required = {"FlightDate", "Reporting_Airline", "Tail_Number", "Flight_Number_Reporting_Airline", "Origin", "Dest", "CRSDepTime", "CRSArrTime", "CRSElapsedTime", "DepDelay", "ActualElapsedTime", "DepTime", "ArrTime", "AirTime", "TaxiOut", "TaxiIn", "Cancelled", "Diverted", "Distance"}
    if required - set(raw):
        raise ValueError(f"On-Time missing columns: {sorted(required-set(raw))}")
    raw = raw.copy()
    if pd.api.types.is_numeric_dtype(raw.FlightDate):
        raw["FlightDate"] = pd.to_datetime(raw.FlightDate, unit="D", origin="1899-12-30")
    else:
        raw["FlightDate"] = pd.to_datetime(raw.FlightDate, errors="raise")
    key = ["FlightDate", "Reporting_Airline", "Flight_Number_Reporting_Airline", "Origin", "Dest"]
    if raw[key].isna().any().any() or raw.duplicated(key).any():
        raise ValueError("Missing/duplicate scheduled-flight identifiers require source review.")
    if raw.empty or not raw.Reporting_Airline.eq("HA").all() or raw.FlightDate.dt.date.nunique() != 1:
        raise ValueError("Expected one nonempty Hawaiian representative service day.")
    if not (raw.Cancelled.eq(0) & raw.Diverted.eq(0)).all():
        raise ValueError("Canceled/diverted records require an explicit modeling-scope decision.")
    rows = []
    for source_row, r in enumerate(raw.itertuples(index=False), 2):
        dep, arr = scheduled_utc(r.FlightDate, r.CRSDepTime, r.Origin, r.CRSElapsedTime, r.CRSArrTime, r.Dest)
        actual_dep = dep + timedelta(minutes=float(r.DepDelay))
        actual_arr = actual_dep + timedelta(minutes=float(r.ActualElapsedTime))
        for instant, airport, clock in [(actual_dep, r.Origin, r.DepTime), (actual_arr, r.Dest, r.ArrTime)]:
            local = instant.astimezone(ZoneInfo(AIRPORT_ZONES[airport]))
            if local.hour*60+local.minute != hhmm_minutes(clock) % 1440:
                raise ValueError(f"Actual clock does not reconcile at source row {source_row}.")
        if not math.isclose(float(r.ActualElapsedTime), float(r.AirTime+r.TaxiOut+r.TaxiIn), abs_tol=1e-7):
            raise ValueError(f"Airborne plus taxi time does not match actual duration at row {source_row}.")
        number = int(r.Flight_Number_Reporting_Airline)
        rows.append(dict(flight_id=f"{r.FlightDate:%Y%m%d}_HA{number}_{r.Origin}_{r.Dest}", flight_date=f"{r.FlightDate:%Y-%m-%d}",
                         carrier="HA", flight_number=number, tail_number=r.Tail_Number, origin=r.Origin, dest=r.Dest,
                         scheduled_dep_UTC=dep.strftime("%Y-%m-%d %H:%M:%S"), scheduled_arr_UTC=arr.strftime("%Y-%m-%d %H:%M:%S"),
                         actual_dep_UTC=actual_dep.strftime("%Y-%m-%d %H:%M:%S"), actual_arr_UTC=actual_arr.strftime("%Y-%m-%d %H:%M:%S"),
                         CRSElapsedTime_minutes=r.CRSElapsedTime, Distance_miles=r.Distance, Cancelled=r.Cancelled, Diverted=r.Diverted,
                         origin_timezone=AIRPORT_ZONES[r.Origin], destination_timezone=AIRPORT_ZONES[r.Dest], source_excel_row=source_row))
    return pd.DataFrame(rows)


def ground_intervals(schedule):
    rows = []
    for tail, fs in schedule.groupby("tail_number"):
        fs = fs.sort_values("actual_dep_UTC")
        for before, after in zip(fs.iloc[:-1].to_dict("records"), fs.iloc[1:].to_dict("records")):
            planned = (pd.Timestamp(after["scheduled_dep_UTC"])-pd.Timestamp(before["scheduled_arr_UTC"])).total_seconds()/60
            actual = (pd.Timestamp(after["actual_dep_UTC"])-pd.Timestamp(before["actual_arr_UTC"])).total_seconds()/60
            rows.append(dict(tail_number=tail, prior_flight_id=before["flight_id"], next_flight_id=after["flight_id"],
                             connecting_airport=before["dest"], location_match="YES" if before["dest"] == after["origin"] else "NO",
                             time_status="OK" if actual >= 0 else "NEGATIVE_ACTUAL_INTERVAL",
                             observed_scheduled_ground_minutes=planned, observed_actual_ground_minutes=actual))
    return pd.DataFrame(rows)


def infer_tail_types(schedule, monthly):
    counts = monthly.groupby(["ORIGIN", "DEST", "AIRCRAFT_TYPE"]).DEPARTURES_PERFORMED.sum()
    totals = monthly.groupby(["ORIGIN", "DEST"]).DEPARTURES_PERFORMED.sum()
    eligible = monthly.groupby(["ORIGIN", "DEST"]).AIRCRAFT_TYPE.agg(lambda v:set(map(int,v))).to_dict()
    rows = []
    for tail, fs in schedule.groupby("tail_number"):
        try:
            candidates = sorted(set.intersection(*(eligible[(r.origin,r.dest)] for r in fs.itertuples())))
        except KeyError as exc:
            raise ValueError(f"Flight route missing from T100: {exc}") from exc
        if not candidates:
            raise ValueError(f"No common historical type is compatible with tail {tail}.")
        log_scores = {k:sum(math.log(float(counts.loc[r.origin,r.dest,k])/float(totals.loc[r.origin,r.dest])) for r in fs.itertuples()) for k in candidates}
        highest = max(log_scores.values())
        weights = {k:math.exp(v-highest) for k,v in log_scores.items()}
        total = sum(weights.values())
        scores = {k:v/total for k,v in weights.items()}
        chosen = max(scores, key=scores.get)
        rows.append(dict(tail_number=tail, observed_flights=len(fs), compatible_types=";".join(map(str,candidates)),
                         inferred_type=chosen, candidate_count=len(candidates), normalized_route_score=scores[chosen],
                         candidate_scores_json=json.dumps({str(k):v for k,v in scores.items()}),
                         source="UNIQUE_ROUTE_COMPATIBILITY_NOT_REGISTRY_VERIFIED" if len(candidates)==1 else "UNCALIBRATED_ROUTE_LIKELIHOOD_NOT_REGISTRY_VERIFIED"))
    return pd.DataFrame(rows), eligible


def prepare_data(on_time_path, t100_path, cost_path, output_dir):
    paths = {"on_time":Path(on_time_path), "t100":Path(t100_path), "costs":Path(cost_path)}
    original = {name:p.read_bytes() for name,p in paths.items()}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_excel(paths["on_time"])
    monthly_source = pd.read_excel(paths["t100"])
    costs_source = pd.read_excel(paths["costs"])
    original_schedule = normalize_schedule(raw)
    measures = ["DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "AIR_TIME", "RAMP_TO_RAMP"]
    monthly = monthly_source[(monthly_source.UNIQUE_CARRIER == "HA") & (monthly_source.YEAR == 2024) & (monthly_source.MONTH == 10)
                             & monthly_source.AIRCRAFT_TYPE.isin(HISTORY_TYPES) & (monthly_source.AIRCRAFT_CONFIG == 1)
                             & (monthly_source.DEPARTURES_PERFORMED > 0)].copy()
    if monthly.empty or not np.isfinite(monthly[measures].to_numpy(dtype=float)).all():
        raise ValueError("Usable T100 measures must be finite and nonempty.")
    if monthly_source.duplicated().any():
        raise ValueError("Exact duplicate T100 rows require source review; nonidentical route/type rows may be summed.")
    if (monthly.SEATS <= 0).any() or (monthly.PASSENGERS < 0).any() or (monthly.PASSENGERS > monthly.SEATS).any() or (monthly.AIR_TIME <= 0).any() or (monthly.AIR_TIME > monthly.RAMP_TO_RAMP).any():
        raise ValueError("Invalid T100 passenger/capacity/airborne/block measures.")
    if costs_source.AIRCRAFT_TYPE.duplicated().any():
        raise ValueError("Duplicate type-level costs require source aggregation review.")
    cost_index = costs_source.set_index("AIRCRAFT_TYPE")
    for k,r in cost_index.iterrows():
        numerator, denominator, hourly = r["TOT_AIR_OP_EXPENSES ($000)"], r["TOTAL_AIR_HOURS (000)"], r["COST_PER_AIR_HOUR ($/hr)"]
        if pd.notna(numerator) and pd.notna(denominator):
            if denominator <= 0 or numerator < 0 or (pd.notna(hourly) and not math.isclose(numerator/denominator,hourly,rel_tol=1e-5,abs_tol=.02)):
                raise ValueError(f"Provided cost ratio/units do not reconcile for type {k}.")
    totals = monthly.groupby("AIRCRAFT_TYPE")[["SEATS", "DEPARTURES_PERFORMED"]].sum()
    capacities = {k:float(totals.loc[k,"SEATS"]/totals.loc[k,"DEPARTURES_PERFORMED"]) for k in TYPES}
    observed_costs = {k:float(cost_index.loc[k,"COST_PER_AIR_HOUR ($/hr)"]) if k in cost_index.index else np.nan for k in TYPES}
    effective_costs = observed_costs.copy()
    if any(not math.isfinite(v) or v <= 0 for v in effective_costs.values()):
        raise ValueError("A positive supplied cost is required for each candidate type608/696/721.")
    # Physical tail evidence comes from the FULL original daily observations and
    # all four historical types. Never reclassify a known787-compatible tail as
    # an A330 merely because its787-only route has been omitted from this model.
    tails, original_eligible = infer_tail_types(original_schedule,monthly)
    candidate_monthly = monthly[monthly.AIRCRAFT_TYPE.isin(TYPES)].copy()
    eligible = candidate_monthly.groupby(["ORIGIN","DEST"]).AIRCRAFT_TYPE.agg(lambda values:set(map(int,values))).to_dict()
    supported = original_schedule.apply(lambda r: bool(eligible.get((r.origin,r.dest))),axis=1)
    excluded = original_schedule[~supported].copy()
    excluded["exclusion_reason"] = "NO_ELIGIBLE_TYPE_AFTER_USER_EXCLUDED_787"
    excluded["historical_eligible_types"] = (excluded.apply(lambda r:";".join(map(str,sorted(original_eligible[r.origin,r.dest]))),axis=1)
                                              if not excluded.empty else pd.Series(dtype=str))
    schedule = original_schedule[supported].copy().reset_index(drop=True)
    if schedule.empty:
        raise ValueError("No scheduled flights remain after excluding787-only routes.")
    tails["included_in_candidate_fleet"] = tails.inferred_type.isin(TYPES)
    unique_tail_types = tails[tails.candidate_count.eq(1)].set_index("tail_number").inferred_type.to_dict()
    ground = ground_intervals(original_schedule)
    ground["sample_group_type"] = ground.tail_number.map(unique_tail_types)
    ground["used_in_turnaround_estimation"] = ground.sample_group_type.isin(TYPES) & ground.location_match.eq("YES") & ground.time_status.eq("OK") & ground.observed_scheduled_ground_minutes.gt(0)
    aircraft_rows, turns, fleets = [], {}, {}
    for k in TYPES:
        sample = ground.loc[ground.used_in_turnaround_estimation & ground.sample_group_type.eq(k),"observed_scheduled_ground_minutes"]
        if sample.empty:
            raise ValueError(f"No unambiguous positive planned-dwell sample for type{k}; supply a documented turnaround override.")
        percentile = float(sample.quantile(.10))
        turns[str(k)] = int(5*math.ceil(percentile/5))
        fleets[str(k)] = int(tails.inferred_type.eq(k).sum())
        aircraft_rows.append(dict(aircraft_type=k,aircraft_model=MODELS[k],capacity=capacities[k],
                                  supplied_cost_per_airborne_hour=observed_costs[k],estimated_cost_per_airborne_hour=effective_costs[k],
                                  cost_source="SUPPLIED_PROCESSED_SUMMARY",
                                  inferred_active_tail_count=fleets[str(k)],turnaround_positive_samples=len(sample),
                                  scheduled_dwell_p10=percentile,turnaround_minutes=turns[str(k)]))
    aircraft_estimates = pd.DataFrame(aircraft_rows)
    # Demand and airborne duration retain ALL historical passengers and flights,
    # including787observations on still-retained routes. Excluding an aircraft
    # option must not make passenger demand disappear. Cost-penalty calibration
    # uses only the comparable candidate types with observed hourly costs.
    candidate_monthly["candidate_monthly_operating_cost_usd"] = candidate_monthly.AIRCRAFT_TYPE.map(effective_costs)*candidate_monthly.AIR_TIME/60
    route = monthly.groupby(["ORIGIN","DEST"])[measures].sum().reset_index().rename(columns={"ORIGIN":"origin","DEST":"dest"})
    candidate_totals = candidate_monthly.groupby(["ORIGIN","DEST"])[["PASSENGERS","DEPARTURES_PERFORMED","AIR_TIME","candidate_monthly_operating_cost_usd"]].sum().reset_index().rename(
        columns={"ORIGIN":"origin","DEST":"dest","PASSENGERS":"candidate_passengers","DEPARTURES_PERFORMED":"candidate_departures","AIR_TIME":"candidate_airtime_minutes"})
    route = route.merge(candidate_totals,on=["origin","dest"],how="left",validate="one_to_one")
    active = schedule[["origin","dest"]].drop_duplicates()
    route = active.merge(route,on=["origin","dest"],how="left",validate="one_to_one")
    if route.DEPARTURES_PERFORMED.isna().any() or route.PASSENGERS.le(0).any():
        raise ValueError("Every scheduled directional route requires positive monthly departures and passengers for estimation.")
    route["observed_passengers_per_departure"] = route.PASSENGERS/route.DEPARTURES_PERFORMED
    route["airborne_hours_per_departure"] = route.AIR_TIME/(60*route.DEPARTURES_PERFORMED)
    if route.candidate_passengers.isna().any() or route.candidate_passengers.le(0).any():
        raise ValueError("Each retained route needs positive candidate-type passengers for cost-penalty calibration.")
    route["cost_recovery_spill_penalty_usd"] = route.candidate_monthly_operating_cost_usd/route.candidate_passengers
    # Historical baseline before primary/user/CLI demand assumptions are applied.
    route["phi"] = 1.0
    route["penalty_status"] = "CANDIDATE_TYPE_COST_RECOVERY_PROXY_NOT_DB1B_FARE"
    route["demand_time_source"] = "FULL_FOUR_TYPE_HISTORY_INCLUDING_787"
    fares = active.copy()
    fares[FARE_COLUMN] = np.nan
    fares["source_status"] = "MISSING_DB1B_OBSERVATIONS"
    inputs = pd.DataFrame([{ "aircraft_type_BTS_code":k,"aircraft_model":MODELS[k],COST_COLUMN:observed_costs[k],TURN_COLUMN:np.nan,FLEET_COLUMN:np.nan} for k in TYPES])
    airports = sorted(set(schedule.origin)|set(schedule.dest))
    balance = pd.DataFrame({"airport":airports})
    balance["departures"] = balance.airport.map(schedule.origin.value_counts()).fillna(0).astype(int)
    balance["arrivals"] = balance.airport.map(schedule.dest.value_counts()).fillna(0).astype(int)
    balance["net_departures"] = balance.departures-balance.arrivals
    issues = []
    def issue(level,subject,detail,pdf):
        issues.append(dict(severity=level,issue=subject,detail=detail,pdf_reference=pdf))
    issue("SCOPE_CHANGE","787 excluded by user",f"Candidate types are608/696/721. {len(excluded)} flights have no remaining historically eligible type and are explicitly omitted; other flights remain reassignable. Source787monthly rows remain intact as historical evidence.","User-requested change from PDF K={608,696,721,889}; no unpriced787is assigned.")
    issue("ESTIMATE_REQUIRED","Missing directional fare observations",f"{len(route)} route fares are absent; observed candidate-type air-operating cost/passenger is an explicit proxy, not a DB1B fare or lost revenue. Full four-type history remains the demand/time source.","Section2.1 p_f: this substitutes for the requested DB1B input source.")
    issue("ESTIMATE_REQUIRED","Turnaround minima unavailable","Positive planned-dwell P10 rounded up to5minutes is a provisional scenario, not an approved airline minimum.","Section2.1 requires operational data or documented assumption.")
    issue("ESTIMATE_REQUIRED","Daily available fleet unavailable","Tail inference uses original206flights and full four-type history before scope changes; inferred787tails are excluded from candidate availability, never relabeled as A330. Unused spares, international flying and maintenance remain unknown.","Section2.1 requires a documented fleet-count source.")
    issue("ASSUMPTION","Demand multiplier","phi=1 uses the PDF's route monthly passengers/performed-departures estimate; no unobserved demand uplift is invented.","Section2.1 q_f and phi_f>=1.")
    ambiguous = int(tails.candidate_count.gt(1).sum())
    if ambiguous:
        issue("LIMITATION","Ambiguous tail types",f"{ambiguous} tails have multiple compatible types; route-share likelihood is uncalibrated inference, not FAA verification.","Aircraft are modeled as type counts; individual registered types are not observed here.")
    negative_ground = int(ground.observed_scheduled_ground_minutes.lt(0).sum())
    if negative_ground:
        issue("WARNING","Negative planned ground intervals",f"{negative_ground} planned interval(s) are negative in actual-tail sequence; preserve and flag, exclude from turn estimates, do not invent a correction.","No source-data repair prescribed by PDF.")
    zero_scheduled = int((monthly_source.DEPARTURES_SCHEDULED.eq(0)&monthly_source.DEPARTURES_PERFORMED.gt(0)).sum())
    if zero_scheduled:
        issue("WARNING","Zero scheduled but positive performed departures",f"{zero_scheduled} monthly source rows are retained; use performed departures as denominator. Such rows do not prove bad data or ferry flights.","Historical directional eligibility follows types that operated the route.")
    outside = sorted(set(map(int,costs_source.AIRCRAFT_TYPE))-set(TYPES))
    if outside:
        issue("INFO","Cost types outside candidate set",f"Types{outside} remain in the source summary but are not model candidates. Missing889cost is not required or estimated in this scope.","User-requested three-type scope differs from PDF K.")
    repeated = int(monthly.duplicated(["ORIGIN","DEST","AIRCRAFT_TYPE"],keep=False).sum())
    if repeated:
        issue("INFO","Repeated nonidentical route/type source keys",f"{repeated} monthly rows share a route/type key; sum additive measures rather than deleting them as duplicates.","Route statistics are aggregate inputs.")
    if balance.net_departures.ne(0).any():
        issue("STRUCTURAL_INFEASIBILITY","Cyclic airport imbalance",balance[balance.net_departures.ne(0)].to_json(orient="records"),"Section3.3-3.4 cyclic inventory and flow.")
    else:
        issue("PASS","Cyclic airport totals",f"All{len(airports)} airports have matching daily arrivals/departures; timing/type/fleet feasibility still requires optimization.","Section3.3-3.5.")
    issue("INFO","Consistent cost/time units","Expense$000 / airborne-hours000 cancels scales; objective uses cost/airborne-hour times airborne hours, not block hours.","Section2.1 and objective.")
    issue("SOURCE_LIMITATION","Source provenance","Only the three supplied workbooks are used; costs are processed summaries, no official refresh or FAA/SEC evidence is claimed.","PDF source labels do not authenticate provided summaries.")
    params = dict(turnaround_minutes=turns,available_fleet=fleets,
                  cost_per_airborne_hour_overrides={},fare_proxy=None,
                  route_spill_penalty_estimates={f"{r.origin}-{r.dest}":float(r.cost_recovery_spill_penalty_usd) for r in route.itertuples()},
                  route_demand_multipliers={f"{r.origin}-{r.dest}":1.0 for r in route.itertuples()},
                  estimation_metadata={"mode":"DATA_CONDITIONED_ASSUMPTIONS_NOT_OBSERVED_FACTS", "candidate_types":list(TYPES),
                                       "fare_proxy":"candidate-type historical route airborne operating cost divided by candidate-type monthly carried passengers; NOT DB1B fare",
                                       "turnaround":"P10 positive planned dwell from original observations, unique route-compatible tail groups only; rounded up to5minutes",
                                       "fleet":"original observed tail evidence inferred using four-type history before scope filtering; inferred787tails excluded, never reclassified; not verified availability",
                                       "cost889":"not required or estimated; type889excluded by user",
                                       "demand":"FULL four-type historical route passengers/performed departures; phi=1; h_f also retains all types",
                                       "excluded_flights":excluded.flight_id.tolist(),
                                       "no_external_registration_or_yearend_inventory_used":True})
    params_path = output_dir/"generated_parameters.json"
    params_path.write_text(json.dumps(params,indent=2,allow_nan=False)+"\n")
    epoch = pd.Timestamp("2024-10-16",tz="UTC")
    events = set()
    pair_count=0
    for f in schedule.itertuples():
        events.add(int((pd.Timestamp(f.scheduled_dep_UTC,tz="UTC")-epoch).total_seconds()/60)%1440)
        for k in eligible[f.origin,f.dest]:
            pair_count+=1
            ready=pd.Timestamp(f.scheduled_arr_UTC,tz="UTC")+pd.Timedelta(minutes=turns[str(k)])
            events.add(int((ready-epoch).total_seconds()/60)%1440)
    summary=dict(source_sha256={name:hashlib.sha256(b).hexdigest() for name,b in original.items()},
                 source_rows={"on_time":len(raw),"t100":len(monthly_source),"costs":len(costs_source)},
                 flights=len(schedule),original_flights=len(original_schedule),excluded_flights=excluded.flight_id.tolist(),
                 excluded_flight_count=len(excluded),candidate_types=list(TYPES),airports=len(airports),routes=len(route),monthly_rows=len(monthly_source),
                 eligible_pairs=pair_count,common_events=len(events),observed_tails=int(original_schedule.tail_number.nunique()),
                 original_observed_tails=int(original_schedule.tail_number.nunique()),inferred_candidate_tails=int(tails.included_in_candidate_fleet.sum()),
                 inferred_787_tails_excluded=tails.loc[tails.inferred_type.eq(889),"tail_number"].tolist(),
                 inferred_fleet=fleets,turnaround_minutes=turns,ambiguous_tail_count=ambiguous,negative_planned_ground_intervals=negative_ground,
                 zero_scheduled_positive_performed_rows=zero_scheduled,airport_totals_balanced=bool(balance.net_departures.eq(0).all()),
                 assumptions_are_separate_from_source_values=True)
    issues_frame=pd.DataFrame(issues)
    readme=pd.DataFrame([("Sources","Only supplied on_time.xlsx,t100.xlsx,costs.xlsx; source files unchanged."),
                         ("User scope","Aircraft889is excluded. Only flights with no eligible type among608/696/721are omitted and separately audited; no further cancellations occur in optimization."),
                         ("Observed versus estimated","Aircraft_Inputs and DB1B_Route_Inputs retain missing empirical cells. Estimates are in separate audit tables and generated_parameters.json."),
                         ("Demand stage","Route_Estimates and generated_parameters.json retain the historical phi=1 baseline before primary/user/CLI assumptions. See the run root calculated_flight_parameters.csv and effective_parameters.json for the actual demand and phi used in optimization."),
                         ("Penalty caveat","Candidate-type cost-recovery penalty is a substitute for missing DB1B fares, not ticket prices or lost revenue. No787cost is imputed."),
                         ("Demand/time source","Use full historical route passengers and airborne hours, including787records. Excluding an aircraft option does not delete those historical passengers."),
                         ("Tail inference","Infer original206observed tails from all four historical types before filtering the model. Two inferred787tails do not become A330s."),
                         ("Model","Fixed schedule, cyclic integer inventories, type-ready events and no repositioning follow the supplied PDF."),
                         ("Raw monthly preservation","All supplied monthly source rows retained. Directional model matching selects only routes in the scheduled flight set.")],columns=["topic","detail"])
    workbook=output_dir/"Prepared_Model_Inputs.xlsx"
    write_plain_excel(workbook,{"README":readme,"Issues":issues_frame,"Schedule_UTC":schedule,"T100_Monthly":monthly_source,
                               "DB1B_Route_Inputs":fares,"Aircraft_Inputs":inputs,"Costs_Source":costs_source,
                               "OnTime_Source":raw,"Route_Estimates":route,"Aircraft_Estimates":aircraft_estimates,
                               "Tail_Type_Estimates":tails,"Ground_Interval_Audit":ground,"Airport_Balance":balance,
                               "Excluded_Flights":excluded,"Original_Schedule_UTC":original_schedule})
    for name,frame in [("route_estimates",route),("aircraft_estimates",aircraft_estimates),("tail_type_estimates",tails),("ground_intervals",ground),("issues",issues_frame),("airport_balance",balance)]:
        frame.to_csv(output_dir/f"{name}.csv",index=False)
    excluded.to_csv(output_dir/"excluded_flights.csv",index=False)
    (output_dir/"preparation_summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    for name,path in paths.items():
        if path.read_bytes()!=original[name]:
            raise RuntimeError("An input file changed unexpectedly.")
    return workbook,params_path,summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--on-time",type=Path,default=Path("data/on_time.xlsx"))
    parser.add_argument("--t100",type=Path,default=Path("data/t100.xlsx"))
    parser.add_argument("--costs",type=Path,default=Path("data/costs.xlsx"))
    parser.add_argument("--output",type=Path,default=Path("prepared"))
    a=parser.parse_args()
    _,_,s=prepare_data(a.on_time,a.t100,a.costs,a.output)
    print(json.dumps(s,indent=2))
