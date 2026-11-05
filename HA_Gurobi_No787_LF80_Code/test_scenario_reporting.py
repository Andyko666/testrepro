"""Effective scenario labels must agree across reports and Excel summaries."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

import run_load_factor_comparison as comparison
from run_model import describe_effective_demand, write_report


class ScenarioReportingTests(unittest.TestCase):
    def report(self, output, rule=None, uniform=None):
        parameters = {"demand_adjustment": rule} if rule else {}
        demand = describe_effective_demand(parameters, uniform_cli_phi=uniform)
        demand.update(minimum_phi=1.0, maximum_phi=uniform or 1.2,
                      uniform_cli_phi=uniform, uplifted_routes=0, uplifted_flights=0)
        result = dict(status="INPUTS_VALIDATED_NO_OPTIMIZATION", parameters=parameters,
                      demand_inputs=demand, primary_assumptions_applied=True,
                      primary_demand_rule_is_effective=uniform is None)
        workbook = Workbook()
        workbook.active.title = "Assignments"
        workbook.save(output / "gurobi_results.xlsx")
        write_report(output, {}, result, "estimated")
        workbook = load_workbook(output / "gurobi_results.xlsx", data_only=True)
        self.addCleanup(workbook.close)
        summary = dict(workbook["Run_Summary"].iter_rows(min_row=2, values_only=True))
        return (output / "RUN_REPORT.md").read_text(), summary

    def test_conditional_report_and_excel_show_effective_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            rule = dict(load_factor_threshold=0.80, comparison=">",
                        multiplier_above=1.2, multiplier_below_or_equal=1.0)
            report, summary = self.report(output, rule=rule)
            self.assertRegex(report, r"LF > 0\.80?(?=[: ;])")
            self.assertNotIn("LF>0.90", report)
            self.assertEqual(summary["load_factor_threshold"], 0.80)
            self.assertEqual(summary["load_factor_comparison"], ">")
            self.assertEqual(summary["multiplier_above"], 1.2)
            self.assertEqual(summary["multiplier_below_or_equal"], 1.0)
            self.assertRegex(summary["effective_demand_rule"], r"LF > 0\.80?(?=[: ;])")

    def test_uniform_report_has_no_active_conditional_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            report, summary = self.report(Path(directory), uniform=1.2)
            self.assertIn("Uniform phi=1.2", report)
            self.assertNotRegex(report, r"LF > 0\.80?(?=[: ;])")
            self.assertNotIn("LF>0.90", report)
            self.assertIsNone(summary["load_factor_threshold"])
            self.assertIsNone(summary["load_factor_comparison"])
            self.assertIsNone(summary["multiplier_above"])
            self.assertEqual(summary["uniform_cli_phi"], 1.2)
            self.assertFalse(summary["primary_demand_rule_is_effective"])


class ComparisonScenarioTests(unittest.TestCase):
    def run_comparison(self, output, *extra):
        calls = []

        def run_fake(arguments):
            calls.append(arguments)
            case = Path(arguments[arguments.index("--output") + 1])
            case.mkdir()
            (case / "run_summary.json").write_text(json.dumps({
                "status": "OPTIMAL_WITHIN_CONFIGURED_TOLERANCE", "mip_gap": 0.0,
                "objective_usd": 100.0, "spill_cost_usd": 0.0,
                "model_spilled_passengers": 0.0, "demand_inputs": {},
            }))
            return 0

        with patch.object(comparison, "run_one", side_effect=run_fake), redirect_stdout(io.StringIO()):
            result = comparison.main(["--output", str(output), *extra])
        self.assertEqual(result, 0)
        self.assertEqual(calls[0][calls[0].index("--demand-multiplier") + 1], "1.0")
        return [float(args[args.index("--load-factor-threshold") + 1]) for args in calls[1:]]

    def test_default_comparison_includes_current_primary_and_lf90_lf95(self):
        with tempfile.TemporaryDirectory() as directory:
            thresholds = self.run_comparison(Path(directory) / "comparison")
            self.assertEqual(thresholds, [0.80, 0.90, 0.95])

    def test_changed_primary_json_updates_comparison_and_deduplicates_cutoffs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "lf95.json"
            primary.write_text(json.dumps({"demand_adjustment": {
                "load_factor_threshold": 0.95, "comparison": ">",
                "multiplier_above": 1.2, "multiplier_below_or_equal": 1.0,
            }}))
            with patch.object(comparison, "PRIMARY_ASSUMPTIONS", primary):
                thresholds = self.run_comparison(root / "comparison")
            self.assertEqual(thresholds, [0.95, 0.90])

    def test_explicit_threshold_list_replaces_default_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            thresholds = self.run_comparison(Path(directory) / "comparison", "--thresholds", "0.85")
            self.assertEqual(thresholds, [0.85])


if __name__ == "__main__":
    unittest.main()
