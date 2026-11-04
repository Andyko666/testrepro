"""Exact elimination of redundant variables and rows in the PDF fleet MILP.

This is the same cyclic assignment model, not an hourly approximation:

1. At an airport/type with no local departure or aircraft-ready event, flow
   forces ground inventory to remain constant. Keep inventory variables only
   after local events. Reconstruct every common-PDF-event inventory as the most
   recent local-event value, with a cyclic predecessor across midnight.
2. At an airport/type with no incident eligible flight, inventory is constant
   and unused. Set it to zero without loss of any feasible flight assignment:
   the PDF has no fixed initial distribution or minimum idle inventory, and
   fleet counts are upper bounds. This only removes irrelevant idle surplus.
3. For a type, ground inventory plus occupied daily flight copies is invariant.
   At a departure, ground decreases as occupation increases; at readiness, the
   opposite happens. Local flow therefore makes all common-event fleet limits
   equivalent. Keep one fleet-count cut per type and independently validate all
   original common-event cuts after solving.

Coverage, objective, binary assignments, continuous spill, integer inventory,
exact-ready connections, cyclic boundaries, and multi-day occupation retain the
PDF meanings. The full inventory view is returned for audit/export/validation.
"""
from __future__ import annotations

from bisect import bisect_right
import math

DAY = 1440


def active_copies(departure: int, ready: int, event: int) -> int:
    """Count occupied copies of a daily flight on [departure, ready)."""
    return (event-departure)//DAY - (event-ready)//DAY


def build_compact_model(data, gp, time_limit=300.0, mip_gap=0.0001, log_path=None):
    """Return (model, x, y_at_all_common_events, u) with exact sparse elimination."""
    if not math.isfinite(float(time_limit)) or float(time_limit) <= 0:
        raise ValueError("Time limit must be a finite positive number.")
    if not math.isfinite(float(mip_gap)) or float(mip_gap) < 0:
        raise ValueError("Relative MIP gap must be finite and nonnegative.")
    flights = data["flights"].to_dict("index")
    aircraft = data["aircraft"].to_dict("index")
    types = sorted(aircraft)
    airports = data["airports"]
    events = data["events"]
    pairs = data["pairs"]
    if not flights or not events or events != sorted(set(events)):
        raise ValueError("Nonempty flights and sorted unique common events are required.")
    incoming, outgoing, local_events = {}, {}, {}
    for i, k in pairs:
        f = flights[i]
        dep = int(f["dep_min"]) % DAY
        ready = int(f["arr_min"] + aircraft[k]["turn_minutes"]) % DAY
        if dep not in events or ready not in events:
            raise ValueError("A required departure/readiness event is missing from the common event set.")
        outgoing.setdefault((f["origin"], k, dep), []).append((i, k))
        incoming.setdefault((f["dest"], k, ready), []).append((i, k))
        local_events.setdefault((f["origin"], k), set()).add(dep)
        local_events.setdefault((f["dest"], k), set()).add(ready)
    local_events = {key: sorted(times) for key, times in local_events.items()}

    model = gp.Model("Hawaiian_PDF_Exact_Compact")
    if log_path is not None:
        model.Params.LogFile = str(log_path)
    model.Params.TimeLimit = float(time_limit)
    model.Params.MIPGap = float(mip_gap)
    x = model.addVars(pairs, vtype=gp.GRB.BINARY, name="x")
    u = model.addVars(list(flights), vtype=gp.GRB.CONTINUOUS, lb=0, name="u")
    ground_keys = [(a, k, t) for (a, k), times in sorted(local_events.items()) for t in times]
    ground = model.addVars(ground_keys, vtype=gp.GRB.INTEGER, lb=0,
                          ub={key: aircraft[key[1]]["fleet"] for key in ground_keys},
                          name="ground")
    # All inactive airport/type inventory views may share this constant zero.
    zero = model.addVar(vtype=gp.GRB.INTEGER, lb=0, ub=0, name="unused_idle_inventory_zero")
    y_full = {}
    for a in airports:
        for k in types:
            times = local_events.get((a, k))
            for m, event in enumerate(events):
                y_full[a, k, m] = (zero if times is None else
                                   ground[a, k, times[bisect_right(times, event)-1]])

    model.setObjective(
        gp.quicksum(aircraft[k]["cost_per_hour"] * flights[i]["airborne_hours"] * x[i,k]
                    for i, k in pairs)
        + gp.quicksum(flights[i]["fare_usd"] * u[i] for i in flights), gp.GRB.MINIMIZE)
    for i, f in flights.items():
        model.addConstr(gp.quicksum(x[i,k] for k in data["eligible"][i]) == 1,
                        name=f"coverage_{i}")
        model.addConstr(u[i] + gp.quicksum(aircraft[k]["capacity"] * x[i,k]
                                          for k in data["eligible"][i]) >= f["demand"],
                        name=f"spill_{i}")
    for (a, k), times in sorted(local_events.items()):
        for j, event in enumerate(times):
            previous = times[j-1]
            model.addConstr(
                ground[a,k,previous]
                + gp.quicksum(x[pair] for pair in incoming.get((a,k,event), []))
                == ground[a,k,event]
                + gp.quicksum(x[pair] for pair in outgoing.get((a,k,event), [])),
                name=f"local_flow_{a}_{k}_{event}")

    # At the first common event, y_full is AFTER all same-time events. Busy
    # copies likewise include departure and exclude exact readiness.
    cut = events[0]
    for k in types:
        occupation = []
        for i in flights:
            if k in data["eligible"][i]:
                count = active_copies(int(flights[i]["dep_min"]),
                                      int(flights[i]["arr_min"] + aircraft[k]["turn_minutes"]), cut)
                if count:
                    occupation.append((i, count))
        model.addConstr(gp.quicksum(y_full[a,k,0] for a in airports)
                        + gp.quicksum(count*x[i,k] for i,count in occupation)
                        <= aircraft[k]["fleet"], name=f"fleet_invariant_cut_{k}")
    model.update()
    return model, x, y_full, u
