"""Boundary and validation checks for historical route load-factor assumptions."""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

from gurobi_model import apply_load_factor_rule


class LoadFactorRuleTests(unittest.TestCase):
    def setUp(self):
        self.load_factor = pd.Series([0.85, 0.90, 0.900001, 0.95, 1.0],
                                     index=["low", "equal", "above", "high", "full"])
        self.rule = {"load_factor_threshold": 0.90, "comparison": ">",
                     "multiplier_above": 1.2, "multiplier_below_or_equal": 1.0}

    def test_strict_rule_excludes_threshold_equality_and_preserves_input(self):
        before_lf = self.load_factor.copy(deep=True)
        before_rule = deepcopy(self.rule)
        actual = apply_load_factor_rule(self.load_factor, self.rule)
        self.assertIsInstance(actual, pd.Series)
        self.assertTrue(actual.index.equals(self.load_factor.index))
        np.testing.assert_array_equal(actual, [1.0, 1.0, 1.2, 1.2, 1.2])
        pd.testing.assert_series_equal(self.load_factor, before_lf)
        self.assertEqual(self.rule, before_rule)

    def test_legacy_rule_retains_default_greater_than_or_equal_comparison(self):
        legacy = {"load_factor_threshold": 0.90,
                  "multiplier_at_or_above": 1.2, "multiplier_below": 1.0}
        np.testing.assert_array_equal(apply_load_factor_rule(self.load_factor, legacy),
                                      [1.0, 1.2, 1.2, 1.2, 1.2])

    def test_legacy_rule_retains_explicit_greater_than_or_equal_comparison(self):
        legacy = {"load_factor_threshold": 0.90, "comparison": ">=",
                  "multiplier_at_or_above": 1.1, "multiplier_below": 1.0}
        np.testing.assert_array_equal(apply_load_factor_rule(self.load_factor, legacy),
                                      [1.0, 1.1, 1.1, 1.1, 1.1])

    def test_threshold_endpoints_and_neutral_multiplier_are_allowed(self):
        lf = pd.Series([0.0, 0.9, 1.0])
        low_endpoint = dict(self.rule, load_factor_threshold=0.0)
        high_endpoint = dict(self.rule, load_factor_threshold=1.0)
        np.testing.assert_array_equal(apply_load_factor_rule(lf, low_endpoint), [1.0, 1.2, 1.2])
        np.testing.assert_array_equal(apply_load_factor_rule(lf, high_endpoint), [1.0, 1.0, 1.0])
        neutral = dict(self.rule, multiplier_above=1.0)
        np.testing.assert_array_equal(apply_load_factor_rule(lf, neutral), [1.0, 1.0, 1.0])

    def test_invalid_thresholds_are_rejected(self):
        for value in (True, False, None, -0.01, 1.01, float("nan"), float("inf"), "invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                apply_load_factor_rule(self.load_factor, dict(self.rule, load_factor_threshold=value))

    def test_invalid_comparisons_are_rejected(self):
        for value in (True, False, None, "<", "<=", "==", "gt", "> ", float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                apply_load_factor_rule(self.load_factor, dict(self.rule, comparison=value))

    def test_invalid_new_rule_multipliers_are_rejected(self):
        for key in ("multiplier_above", "multiplier_below_or_equal"):
            for value in (True, False, None, 0.99, -1, float("nan"), float("inf"), "invalid"):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    apply_load_factor_rule(self.load_factor, dict(self.rule, **{key: value}))

    def test_invalid_legacy_multipliers_are_rejected(self):
        legacy = {"load_factor_threshold": 0.90,
                  "multiplier_at_or_above": 1.2, "multiplier_below": 1.0}
        for key in ("multiplier_at_or_above", "multiplier_below"):
            for value in (True, False, None, 0.99, float("nan"), float("inf")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    apply_load_factor_rule(self.load_factor, dict(legacy, **{key: value}))

    def test_invalid_historical_load_factors_are_rejected(self):
        for value in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                apply_load_factor_rule(pd.Series([0.85, value]), self.rule)

    def test_conflicting_multiplier_aliases_are_rejected(self):
        for alias, value in (("multiplier_at_or_above", 1.3), ("multiplier_below", 1.1)):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                apply_load_factor_rule(self.load_factor, dict(self.rule, **{alias: value}))


if __name__ == "__main__":
    unittest.main()
