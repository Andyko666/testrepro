"""Compare exact compact elimination against the literal PDF Gurobi model."""
import unittest

import pandas as pd

from compact_model import build_compact_model
from gurobi_model import TYPES, build_full_model, validate_solution

try:
    import gurobipy as gp
except ImportError:
    gp = None


def tiny_data(rows, fleet=1, turnaround=30, extra_events=()):
    flights = pd.DataFrame(rows, columns=["origin", "dest", "dep_min", "arr_min", "demand"])
    flights["airborne_hours"] = 1.0
    flights["fare_usd"] = 10.0
    aircraft = pd.DataFrame({"capacity":[100.0]*len(TYPES), "cost_per_hour":[100.0]*len(TYPES),
                             "turn_minutes":[turnaround]*len(TYPES), "fleet":[fleet]+[0]*(len(TYPES)-1)}, index=TYPES)
    events = sorted(set(extra_events) | {int(t)%1440 for t in flights.dep_min}
                    | {int(t+turnaround)%1440 for t in flights.arr_min})
    return dict(flights=flights, aircraft=aircraft,
                airports=sorted(set(flights.origin)|set(flights.dest)), events=events,
                pairs=[(i,608) for i in flights.index], eligible={i:[608] for i in flights.index})


@unittest.skipIf(gp is None, "Install gurobipy to execute compact/full equivalence tests.")
class CompactEquivalenceTests(unittest.TestCase):
    def optimize(self, data, builder):
        model, x, y, u = builder(data, gp, time_limit=10, mip_gap=0)
        self.addCleanup(model.dispose)
        model.Params.OutputFlag = 0
        model.optimize()
        return model, x, y, u

    def compare(self, data, expected_status, expected_cost=None):
        full = self.optimize(data, build_full_model)
        compact = self.optimize(data, build_compact_model)
        self.assertEqual(full[0].Status, expected_status)
        self.assertEqual(compact[0].Status, expected_status)
        if expected_status == gp.GRB.OPTIMAL:
            self.assertAlmostEqual(full[0].ObjVal, compact[0].ObjVal, places=7)
            if expected_cost is not None:
                self.assertAlmostEqual(compact[0].ObjVal, expected_cost)
            for model, x, y, u in [full, compact]:
                checks = validate_solution(
                    data, {key:float(v.X) for key,v in x.items()},
                    {key:float(v.X) for key,v in y.items()},
                    {key:float(v.X) for key,v in u.items()}, model.ObjVal, True)
                self.assertTrue(checks["passed"], checks)
        return full, compact

    def test_exact_ready_spill_and_all_global_inventory_cuts(self):
        data = tiny_data([("A","B",0,60,120),("B","A",90,150,80)],
                         extra_events=(30,59,60,89,91,120,179,181,1000))
        full, compact = self.compare(data, gp.GRB.OPTIMAL, expected_cost=400)
        self.assertLess(compact[0].NumVars, full[0].NumVars)
        self.assertLess(compact[0].NumConstrs, full[0].NumConstrs)
        # A's next local event after departure0 is readiness180. Its ground
        # value is one shared variable at all intervening common-event cuts.
        indices = {t:m for m,t in enumerate(data["events"])}
        self.assertIs(compact[2]["A",608,indices[0]], compact[2]["A",608,indices[179]])

    def test_one_minute_before_readiness_is_infeasible(self):
        self.compare(tiny_data([("A","B",0,60,100),("B","A",89,150,100)]), gp.GRB.INFEASIBLE)

    def test_overnight_reconstruction_before_first_local_event(self):
        data = tiny_data([("A","B",60,120,100),("B","A",1410,1470,100)],
                         extra_events=(0,1,30,59,61,1000,1439))
        self.compare(data, gp.GRB.OPTIMAL, expected_cost=200)

    def test_multi_day_occupation_and_single_fleet_cut(self):
        rows = [("A","A",60,1510,100)]
        self.compare(tiny_data(rows,fleet=1,extra_events=(0,59,61,1000)), gp.GRB.INFEASIBLE)
        self.compare(tiny_data(rows,fleet=2,extra_events=(0,59,61,1000)), gp.GRB.OPTIMAL, expected_cost=100)

    def test_exact_two_day_occupation_with_same_modulo_event(self):
        # readiness=departure+2880, so local arrival/departure event labels
        # coincide, but two daily copies remain occupied at every cut.
        rows = [("A","A",60,2910,100)]
        self.compare(tiny_data(rows,fleet=1,extra_events=(0,59,61,1000)), gp.GRB.INFEASIBLE)
        self.compare(tiny_data(rows,fleet=2,extra_events=(0,59,61,1000)), gp.GRB.OPTIMAL)

    def test_imbalance_is_not_hidden_by_eliminating_events(self):
        self.compare(tiny_data([("A","B",100,200,100)],fleet=100,
                               extra_events=(0,50,101,500)), gp.GRB.INFEASIBLE)

    def test_no_incident_airport_type_inventory_is_zero_without_loss(self):
        data = tiny_data([("A","B",0,60,100),("B","A",90,150,100)])
        data["airports"].append("ISOLATED")
        _, compact = self.compare(data, gp.GRB.OPTIMAL, expected_cost=200)
        values = [compact[2]["ISOLATED",k,m] for k in TYPES for m in range(len(data["events"]))]
        self.assertTrue(all(v is values[0] for v in values))
        self.assertEqual(values[0].X, 0)

    def test_eligible_type_choice_and_capacity_cost_tradeoff_preserved(self):
        data = tiny_data([("A","B",0,60,140),("B","A",90,150,140)],extra_events=(1,30,59,179,181))
        data["aircraft"].loc[608,["capacity","cost_per_hour"]] = [80,50]
        data["aircraft"].loc[721,["capacity","cost_per_hour","fleet"]] = [150,90,1]
        data["pairs"] = [(i,k) for i in data["flights"].index for k in [608,721]]
        data["eligible"] = {i:[608,721] for i in data["flights"].index}
        _, compact = self.compare(data,gp.GRB.OPTIMAL,expected_cost=180)
        self.assertAlmostEqual(compact[1][0,721].X,1)
        self.assertAlmostEqual(compact[1][1,721].X,1)


if __name__ == "__main__":
    unittest.main()
