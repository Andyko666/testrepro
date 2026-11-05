"""Small, independently checkable regression tests for the Gurobi formulation.

Run: python -m unittest -v test_gurobi
The small optimization cases fit a standard size-limited Gurobi license.
"""
import unittest

import pandas as pd

from gurobi_model import TYPES, active_copies, build_model, validate_solution

try:
    import gurobipy as gp
except ImportError:
    gp = None


def tiny_data(rows, fleet=1, turnaround=30):
    f = pd.DataFrame(rows, columns=["origin", "dest", "dep_min", "arr_min", "demand"])
    f["airborne_hours"] = 1.0
    f["fare_usd"] = 10.0
    ac = pd.DataFrame({"capacity": [100.0]*len(TYPES), "cost_per_hour": [100.0]*len(TYPES),
                       "turn_minutes": [turnaround]*len(TYPES), "fleet": [fleet]+[0]*(len(TYPES)-1)}, index=TYPES)
    events = sorted(set(int(x)%1440 for x in f.dep_min)
                    | set(int(x+turnaround)%1440 for x in f.arr_min))
    return dict(flights=f, aircraft=ac, airports=sorted(set(f.origin)|set(f.dest)),
                events=events, pairs=[(i,608) for i in f.index],
                eligible={i:[608] for i in f.index})


class ActiveCopyTests(unittest.TestCase):
    def test_departure_included_and_readiness_excluded(self):
        self.assertEqual(active_copies(100,200,99),0)
        self.assertEqual(active_copies(100,200,100),1)
        self.assertEqual(active_copies(100,200,199),1)
        self.assertEqual(active_copies(100,200,200),0)

    def test_overnight_and_more_than_one_day(self):
        self.assertEqual(active_copies(1380,1500,0),1)
        self.assertEqual(active_copies(1380,1500,60),0)
        self.assertEqual(active_copies(0,1500,0),2)
        self.assertEqual(active_copies(0,1500,60),1)

    def test_count_matches_explicit_daily_copy_enumeration(self):
        for dep in (-200,0,60,1439,1600):
            for duration in (1,30,1440,1500,3000):
                for event in (0,1,59,60,100,1439):
                    expected=sum(dep+1440*z <= event < dep+duration+1440*z
                                 for z in range(-10,11))
                    with self.subTest(dep=dep,duration=duration,event=event):
                        self.assertEqual(active_copies(dep,dep+duration,event),expected)


@unittest.skipIf(gp is None,"Install gurobipy and configure a valid license to execute optimization tests.")
class GurobiModelTests(unittest.TestCase):
    def optimize(self,data):
        model,x,y,u=build_model(data,gp,time_limit=10,mip_gap=0)
        self.addCleanup(model.dispose)
        model.Params.OutputFlag=0
        model.optimize()
        return model,x,y,u

    def values(self,variables):
        return {key:float(value.X) for key,value in variables.items()}

    def test_exactly_ready_cyclic_case_has_expected_cost_and_spill(self):
        data=tiny_data([("A","B",0,60,120),("B","A",90,150,80)])
        model,x,y,u=self.optimize(data)
        self.assertEqual(model.Status,gp.GRB.OPTIMAL)
        self.assertAlmostEqual(model.ObjVal,400)
        self.assertAlmostEqual(u[0].X,20)
        self.assertAlmostEqual(u[1].X,0)
        checks=validate_solution(data,self.values(x),self.values(y),self.values(u),model.ObjVal,True)
        self.assertTrue(checks["passed"],checks)

    def test_one_minute_before_readiness_is_infeasible(self):
        data=tiny_data([("A","B",0,60,100),("B","A",89,150,100)])
        model,_,_,_=self.optimize(data)
        self.assertEqual(model.Status,gp.GRB.INFEASIBLE)

    def test_overnight_connection_is_available_next_day(self):
        data=tiny_data([("A","B",60,120,100),("B","A",1410,1470,100)])
        model,x,y,u=self.optimize(data)
        self.assertEqual(model.Status,gp.GRB.OPTIMAL)
        self.assertTrue(validate_solution(data,self.values(x),self.values(y),self.values(u),model.ObjVal,True)["passed"])

    def test_occupation_longer_than_day_needs_two_aircraft(self):
        rows=[("A","A",60,1510,100)]
        model,_,_,_=self.optimize(tiny_data(rows,fleet=1))
        self.assertEqual(model.Status,gp.GRB.INFEASIBLE)
        data=tiny_data(rows,fleet=2)
        model,x,y,u=self.optimize(data)
        self.assertEqual(model.Status,gp.GRB.OPTIMAL)
        self.assertTrue(validate_solution(data,self.values(x),self.values(y),self.values(u),model.ObjVal,True)["passed"])

    def test_airport_imbalance_cannot_be_fixed_by_large_fleet(self):
        data=tiny_data([("A","B",100,200,100)],fleet=100)
        model,_,_,_=self.optimize(data)
        self.assertEqual(model.Status,gp.GRB.INFEASIBLE)

    def test_independent_validator_rejects_corrupted_solution(self):
        data=tiny_data([("A","B",0,60,120),("B","A",90,150,80)])
        model,x,y,u=self.optimize(data)
        self.assertEqual(model.Status,gp.GRB.OPTIMAL)
        original_x,original_y,original_u=self.values(x),self.values(y),self.values(u)
        xbad=dict(original_x);xbad[0,608]-=0.5
        ybad=dict(original_y);ybad["A",608,0]+=1
        ubad=dict(original_u);ubad[0]+=1
        for xv,yv,uv in [(xbad,original_y,original_u),(original_x,ybad,original_u),(original_x,original_y,ubad)]:
            self.assertFalse(validate_solution(data,xv,yv,uv,model.ObjVal,True)["passed"])


if __name__=="__main__":
    unittest.main()
