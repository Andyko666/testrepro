"""Demand scenarios change model inputs without inventing observed demand.

Exercise the supplied workbooks through the actual validation-only CLI; these
checks do not require gurobipy or a Gurobi license.
"""
import builtins
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from run_model import ROOT, apply_uniform_demand_multiplier, main, merge_parameters


class DemandControlTests(unittest.TestCase):
    @staticmethod
    def source_bytes():
        return {name: (ROOT / "data" / name).read_bytes()
                for name in ("on_time.xlsx", "t100.xlsx", "costs.xlsx")}

    def validate(self, output, *arguments):
        """Assert validation never imports Gurobi or calls the optimizer."""
        original_import = builtins.__import__

        def import_without_gurobi(name, *args, **kwargs):
            if name == "gurobipy" or name.startswith("gurobipy."):
                raise AssertionError("Validation-only must not import gurobipy.")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_gurobi), \
                patch("run_model.solve_gurobi", side_effect=AssertionError("Validation must not optimize.")), \
                redirect_stdout(io.StringIO()):
            result = main([*arguments, "--validate-only", "--output", str(output)])
        self.assertEqual(result, 0)
        summary = json.loads((output / "run_summary.json").read_text())
        self.assertEqual(summary["status"], "INPUTS_VALIDATED_NO_OPTIMIZATION")
        self.assertEqual(summary["flights"], 204)
        return pd.read_csv(output / "calculated_flight_parameters.csv")

    def test_default_uses_selected_primary_phi_and_preserves_source_baseline(self):
        before = self.source_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "primary"
            flights = self.validate(output)
            self.assertTrue(flights.phi.eq(1.2).all())
            np.testing.assert_allclose(flights.demand, flights.observed_passengers_per_departure * 1.2)
            generated = json.loads((output / "prepared" / "generated_parameters.json").read_text())
            self.assertTrue(all(value == 1.0 for value in generated["route_demand_multipliers"].values()))
            summary = json.loads((output / "run_summary.json").read_text())
            self.assertIsNone(summary["demand_inputs"]["uniform_cli_phi"])
            self.assertIs(summary["primary_assumptions_applied"], True)
            self.assertEqual(summary["primary_assumptions_file"], "primary_assumptions.json")
            primary = json.loads((ROOT / summary["primary_assumptions_file"]).read_text())
            self.assertEqual(primary["demand_adjustment"]["multiplier_at_or_above"], 1.2)
            self.assertEqual(primary["demand_adjustment"]["multiplier_below"], 1.2)
        self.assertEqual(self.source_bytes(), before)

    def test_explicit_baseline_cli_overrides_primary_assumption(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline_benchmark"
            flights = self.validate(output, "--demand-multiplier", "1")
            self.assertTrue(flights.phi.eq(1.0).all())
            np.testing.assert_allclose(flights.demand, flights.observed_passengers_per_departure)
            summary = json.loads((output / "run_summary.json").read_text())
            self.assertIs(summary["primary_assumptions_applied"], True)
            self.assertEqual(summary["demand_inputs"]["uniform_cli_phi"], 1.0)

    def test_strict_mode_does_not_apply_primary_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "strict"
            with redirect_stdout(io.StringIO()), \
                    patch("run_model.solve_gurobi", side_effect=AssertionError("Strict validation must not optimize.")):
                result = main(["--mode", "strict", "--validate-only", "--output", str(output)])
            self.assertEqual(result, 2)
            summary = json.loads((output / "run_summary.json").read_text())
            self.assertEqual(summary["status"], "MISSING_INPUTS_NO_OPTIMIZATION")
            self.assertEqual(summary["missing_count"], 76)
            self.assertIs(summary["primary_assumptions_applied"], False)
            self.assertIsNone(summary["primary_assumptions_file"])
            effective = json.loads((output / "effective_parameters.json").read_text())
            self.assertEqual(effective, {})

    def test_uniform_cli_is_absolute_and_applies_after_json_rules(self):
        before = self.source_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = root / "overrides.json"
            overrides.write_text(json.dumps({
                "demand_adjustment": {"load_factor_threshold": 0.85,
                                      "multiplier_at_or_above": 1.4, "multiplier_below": 1.3},
                "route_demand_multipliers": {"HNL-LAX": 1.6},
            }))
            output = root / "scenario"
            flights = self.validate(output, "--parameters", str(overrides), "--demand-multiplier", "1.1")
            self.assertEqual(len(flights), 204)
            self.assertTrue(flights.phi.eq(1.1).all())
            np.testing.assert_allclose(flights.demand, flights.observed_passengers_per_departure * 1.1)
            generated = json.loads((output / "prepared" / "generated_parameters.json").read_text())
            effective = json.loads((output / "effective_parameters.json").read_text())
            self.assertTrue(all(value == 1.0 for value in generated["route_demand_multipliers"].values()))
            routes = {f"{row.origin}-{row.dest}" for row in flights.itertuples()}
            self.assertEqual(effective["route_demand_multipliers"], dict.fromkeys(routes, 1.1))
            self.assertIn("scenario", effective["estimation_metadata"]["demand"].lower())
            self.assertIn("not observed", effective["estimation_metadata"]["demand"].lower())
            summary = json.loads((output / "run_summary.json").read_text())
            self.assertEqual(summary["demand_inputs"]["uniform_cli_phi"], 1.1)

            # The public helper must also preserve the caller's parameter object.
            original = deepcopy(generated)
            adjusted = apply_uniform_demand_multiplier(
                generated, output / "prepared" / "Prepared_Model_Inputs.xlsx", 1.1)
            self.assertEqual(generated, original)
            self.assertEqual(adjusted["route_demand_multipliers"], dict.fromkeys(routes, 1.1))
        self.assertEqual(self.source_bytes(), before)

    def test_global_load_factor_override_removes_generated_route_defaults(self):
        base = {"route_demand_multipliers": {"HNL-LAX": 1.0, "LAX-HNL": 1.0},
                "available_fleet": {"608": 16}}
        original = deepcopy(base)
        rule = {"load_factor_threshold": 0.85, "multiplier_at_or_above": 1.1, "multiplier_below": 1.0}
        merged = merge_parameters(base, {"demand_adjustment": rule})
        self.assertEqual(merged["route_demand_multipliers"], {})
        self.assertEqual(merged["demand_adjustment"], rule)
        self.assertEqual(merged["available_fleet"], base["available_fleet"])
        self.assertEqual(base, original)
        with_route_exception = merge_parameters(base, {
            "demand_adjustment": rule, "route_demand_multipliers": {"HNL-LAX": 1.2}})
        self.assertEqual(with_route_exception["route_demand_multipliers"], {"HNL-LAX": 1.2})

    def test_json_load_factor_rule_and_route_exception_reach_prepared_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = root / "load_factor.json"
            overrides.write_text(json.dumps({
                "demand_adjustment": {"load_factor_threshold": 0.85,
                                      "multiplier_at_or_above": 1.1, "multiplier_below": 1.0},
                "route_demand_multipliers": {"HNL-LAX": 1.2},
            }))
            output = root / "scenario"
            flights = self.validate(output, "--parameters", str(overrides))
            exception = flights.origin.eq("HNL") & flights.dest.eq("LAX")
            self.assertTrue(exception.any())
            self.assertTrue(flights.loc[exception, "phi"].eq(1.2).all())
            ordinary = flights.loc[~exception]
            high = ordinary.load_factor.ge(0.85)
            self.assertTrue(high.any())
            self.assertTrue((~high).any())
            np.testing.assert_array_equal(ordinary.phi, np.where(high, 1.1, 1.0))
            np.testing.assert_allclose(flights.demand, flights.observed_passengers_per_departure * flights.phi)
            effective = json.loads((output / "effective_parameters.json").read_text())
            self.assertEqual(effective["route_demand_multipliers"], {"HNL-LAX": 1.2})

    def test_explicit_route_override_precedes_primary_uniform_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = root / "route_exception.json"
            overrides.write_text(json.dumps({"route_demand_multipliers": {"HNL-LAX": 1.3}}))
            output = root / "scenario"
            flights = self.validate(output, "--parameters", str(overrides))
            exception = flights.origin.eq("HNL") & flights.dest.eq("LAX")
            self.assertTrue(exception.any())
            self.assertTrue(flights.loc[exception, "phi"].eq(1.3).all())
            self.assertTrue(flights.loc[~exception, "phi"].eq(1.2).all())
            np.testing.assert_allclose(flights.demand, flights.observed_passengers_per_departure * flights.phi)

    def test_invalid_cli_multipliers_are_rejected_before_output_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            for number, value in enumerate(("0.9", "-1", "nan", "inf", "-inf", "not-a-number")):
                with self.subTest(value=value):
                    output = Path(directory) / f"invalid_{number}"
                    with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                        main([f"--demand-multiplier={value}", "--validate-only", "--output", str(output)])
                    self.assertEqual(caught.exception.code, 2)
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
