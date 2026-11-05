"""Check local CLI input handling without requiring a Gurobi license."""
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from run_model import ROOT, main, merge_parameters


class EntryPointTests(unittest.TestCase):
    def test_strict_mode_lists_missing_inputs_instead_of_optimizing(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/"strict"
            self.assertEqual(main(["--mode","strict","--validate-only","--output",str(output)]),2)
            result=json.loads((output/"run_summary.json").read_text())
            self.assertEqual(result["status"],"MISSING_INPUTS_NO_OPTIMIZATION")
            self.assertEqual(result["missing_count"],76)

    def test_local_fare_import_precedes_generated_proxy(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            fares=root/"fares.csv"
            pd.DataFrame([dict(origin="HNL",dest="LAX",fare_usd=321.0)]).to_csv(fares,index=False)
            output=root/"run"
            self.assertEqual(main(["--fares",str(fares),"--validate-only","--output",str(output)]),0)
            result=json.loads((output/"run_summary.json").read_text())
            self.assertEqual(result["penalty_inputs"]["supplied_fare_routes"],1)
            self.assertEqual(result["penalty_inputs"]["proxy_penalty_routes"],69)
            f=pd.read_csv(output/"calculated_flight_parameters.csv")
            rows=f[f.origin.eq("HNL") & f.dest.eq("LAX")]
            self.assertTrue(rows.fare_usd.eq(321.0).all())
            self.assertTrue(rows.fare_source.eq("SUPPLIED_DIRECTIONAL_MARKET_FARE").all())
            self.assertEqual(main(["--validate-only","--output",str(output)]),1)

    def test_parameter_overrides_preserve_unspecified_types(self):
        merged=merge_parameters({"available_fleet":{"608":16,"721":17}},
                                {"available_fleet":{"721":18}})
        self.assertEqual(merged["available_fleet"],{"608":16,"721":18})
        with self.assertRaises(ValueError):
            merge_parameters({}, {"available_flet":{}})
        with self.assertRaises(ValueError):
            merge_parameters({}, {"available_fleet":{"889":2}})


if __name__=="__main__":
    unittest.main()
