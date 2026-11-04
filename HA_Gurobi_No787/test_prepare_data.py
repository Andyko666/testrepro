"""Tests of local-file preparation and explicit observation/estimate separation."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from prepare_data import (FARE_COLUMN,COST_COLUMN,TURN_COLUMN,FLEET_COLUMN,
                          hhmm_minutes,scheduled_utc,prepare_data)

ROOT=Path(__file__).resolve().parent


class TimeConversionTests(unittest.TestCase):
    def test_bts_clock_validation_and_midnight(self):
        self.assertEqual(hhmm_minutes(2400),1440)
        self.assertEqual(hhmm_minutes(55),55)
        for invalid in [-1,2360,2500,123.5]:
            with self.subTest(value=invalid),self.assertRaises(ValueError):
                hhmm_minutes(invalid)

    def test_october_austin_honolulu_offsets(self):
        dep,arr=scheduled_utc("2024-10-16",1055,"AUS",500,1415,"HNL")
        self.assertEqual(dep.isoformat(),"2024-10-16T15:55:00+00:00")
        self.assertEqual(arr.isoformat(),"2024-10-17T00:15:00+00:00")

    def test_overnight_destination_date_and_clock_check(self):
        dep,arr=scheduled_utc("2024-10-16",2125,"HNL",320,545,"LAX")
        self.assertEqual(dep.isoformat(),"2024-10-17T07:25:00+00:00")
        self.assertEqual(arr.isoformat(),"2024-10-17T12:45:00+00:00")
        with self.assertRaisesRegex(ValueError,"arrival clock"):
            scheduled_utc("2024-10-16",2125,"HNL",320,645,"LAX")


class SourcePreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.paths=[ROOT/"data/on_time.xlsx",ROOT/"data/t100.xlsx",ROOT/"data/costs.xlsx"]
        cls.before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.paths}
        cls.workbook,cls.parameters_path,cls.summary=prepare_data(*cls.paths,Path(cls.tmp.name))
        cls.sheets=pd.read_excel(cls.workbook,sheet_name=None)
        cls.params=json.loads(cls.parameters_path.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_current_source_counts_and_no_mutation(self):
        self.assertEqual(self.summary["source_rows"],{"on_time":206,"t100":104,"costs":5})
        self.assertEqual((self.summary["flights"],self.summary["airports"],self.summary["routes"]),(204,18,70))
        self.assertEqual(self.summary["eligible_pairs"],341)
        self.assertTrue(self.summary["airport_totals_balanced"])
        for p in self.paths:
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.before[str(p)])

    def test_source_blanks_and_estimates_separated(self):
        self.assertTrue(self.sheets["DB1B_Route_Inputs"][FARE_COLUMN].isna().all())
        aircraft=self.sheets["Aircraft_Inputs"].set_index("aircraft_type_BTS_code")
        self.assertTrue(aircraft[TURN_COLUMN].isna().all())
        self.assertTrue(aircraft[FLEET_COLUMN].isna().all())
        self.assertEqual(set(aircraft.index),{608,696,721})
        self.assertTrue(aircraft[COST_COLUMN].notna().all())
        self.assertEqual(self.params["cost_per_airborne_hour_overrides"],{})
        self.assertEqual(self.params["turnaround_minutes"],{"608":30,"696":100,"721":75})
        self.assertEqual(self.params["available_fleet"],{"608":16,"696":16,"721":17})
        self.assertEqual(set(self.params["route_demand_multipliers"].values()),{1.0})
        self.assertIsNone(self.params["fare_proxy"])

    def test_rare_operations_and_repeated_keys_are_not_deleted(self):
        monthly=self.sheets["T100_Monthly"]
        pd.testing.assert_frame_equal(monthly,pd.read_excel(self.paths[1]))
        self.assertEqual(int((monthly.DEPARTURES_SCHEDULED.eq(0)&monthly.DEPARTURES_PERFORMED.gt(0)).sum()),10)
        pair=monthly[(monthly.ORIGIN=="HNL")&(monthly.DEST=="LAX")&(monthly.AIRCRAFT_TYPE==696)]
        self.assertEqual(len(pair),2)
        self.assertEqual(int(pair.DEPARTURES_PERFORMED.sum()),69)
        self.assertEqual(int(pair.PASSENGERS.sum()),17495)

    def test_negative_ground_interval_preserved_not_used(self):
        ground=self.sheets["Ground_Interval_Audit"]
        self.assertEqual(len(ground),155)
        bad=ground[ground.observed_scheduled_ground_minutes.lt(0)]
        self.assertEqual(len(bad),1)
        self.assertEqual(float(bad.iloc[0].observed_scheduled_ground_minutes),-15)
        self.assertFalse(bool(bad.iloc[0].used_in_turnaround_estimation))
        counts=self.sheets["Aircraft_Estimates"].set_index("aircraft_type").turnaround_positive_samples.to_dict()
        self.assertEqual(counts,{608:119,696:9,721:16})
        self.assertFalse(ground.loc[ground.sample_group_type.eq(889),"used_in_turnaround_estimation"].any())

    def test_cost_based_proxy_is_reproducible_not_observed_fare(self):
        monthly=pd.read_excel(self.paths[1])
        costs=pd.read_excel(self.paths[2]).set_index("AIRCRAFT_TYPE")["COST_PER_AIR_HOUR ($/hr)"].to_dict()
        group=monthly[(monthly.ORIGIN=="HNL")&(monthly.DEST=="LAX")&monthly.AIRCRAFT_TYPE.isin([608,696,721])]
        expected=sum(costs[int(r.AIRCRAFT_TYPE)]*r.AIR_TIME/60 for r in group.itertuples())/group.PASSENGERS.sum()
        self.assertAlmostEqual(self.params["route_spill_penalty_estimates"]["HNL-LAX"],expected)
        self.assertTrue(self.sheets["Route_Estimates"].penalty_status.str.contains("NOT_DB1B").all())

    def test_only_787_only_flights_are_excluded(self):
        excluded=self.sheets["Excluded_Flights"]
        self.assertEqual(set(excluded.flight_id),{"20241016_HA35_PHX_HNL","20241016_HA36_HNL_PHX"})
        retained=self.sheets["Schedule_UTC"]
        self.assertEqual(len(retained),204)
        self.assertFalse(retained.origin.eq("PHX").any()|retained.dest.eq("PHX").any())
        # The other observed787flights have non787eligible options; they remain
        # fixed scheduled services that may receive another aircraft type.
        original=self.sheets["Original_Schedule_UTC"]
        source_787=original[original.tail_number.isin(["N780HA","N781HA"])]
        self.assertEqual(len(source_787),4)
        self.assertEqual(len(retained[retained.tail_number.isin(["N780HA","N781HA"])]),2)

    def test_tail_inference_precedes_model_scope_filter(self):
        tails=self.sheets["Tail_Type_Estimates"].set_index("tail_number")
        self.assertEqual(int(tails.loc["N780HA","inferred_type"]),889)
        self.assertEqual(int(tails.loc["N781HA","inferred_type"]),889)
        self.assertFalse(bool(tails.loc["N780HA","included_in_candidate_fleet"]))
        self.assertFalse(bool(tails.loc["N781HA","included_in_candidate_fleet"]))
        self.assertEqual(self.summary["original_observed_tails"],51)
        self.assertEqual(self.summary["inferred_candidate_tails"],49)

    def test_demand_and_time_keep_four_type_history(self):
        monthly=pd.read_excel(self.paths[1])
        group=monthly[(monthly.ORIGIN=="HNL")&(monthly.DEST=="LAX")]
        self.assertTrue(group.AIRCRAFT_TYPE.eq(889).any())
        row=self.sheets["Route_Estimates"].query("origin=='HNL' and dest=='LAX'").iloc[0]
        self.assertAlmostEqual(row.observed_passengers_per_departure,group.PASSENGERS.sum()/group.DEPARTURES_PERFORMED.sum())
        self.assertAlmostEqual(row.airborne_hours_per_departure,group.AIR_TIME.sum()/60/group.DEPARTURES_PERFORMED.sum())
        self.assertEqual(row.demand_time_source,"FULL_FOUR_TYPE_HISTORY_INCLUDING_787")
        self.assertEqual(int(self.sheets["T100_Monthly"].AIRCRAFT_TYPE.eq(889).sum()),4)


if __name__=="__main__":
    unittest.main()
