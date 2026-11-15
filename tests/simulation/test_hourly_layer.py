"""The hourly output layer: request, read, and the load duration curve.

Issue #147 M1-M3. Hourly output is OFF by default and this is the opt-in; the
cost is measured and tiered (see `HOURLY_METERS`). Three facts this file
exists to keep true, each of which cost a measurement to learn:

- a read must filter `EnvironmentType = 3`, or design days inflate it;
- a read must filter `ReportingFrequency = 'Hourly'`, or a model that also
  carries RunPeriod requests for the same variable name reads back EMPTY;
- the district-energy heat series is the BOILER summed across boilers, not
  `Heating:EnergyTransfer`, which excludes hydronic baseboards.
"""

import pathlib
import unittest

from tests.support import needs_engine

WEATHER = (pathlib.Path(__file__).resolve().parents[1] / "fixtures"
           / "weather")
EPW = WEATHER / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"
DDY = WEATHER / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"


class TestCurves(unittest.TestCase):
    """Pure functions — no SDK, no engine."""

    def setUp(self):
        from btap.simulation import runner

        self.runner = runner

    def test_the_curve_is_DURATION_versus_DEMAND_sloping_downward(self):
        """phylroy's definition: x is duration (hours or % of time), y is
        demand, and the curve slopes downward from peak to minimum."""
        curve = self.runner.load_duration_curve([1.0, 5.0, 3.0, 5.0, 0.0])
        self.assertEqual(
            [(1.0, 5.0), (2.0, 5.0), (3.0, 3.0), (4.0, 1.0), (5.0, 0.0)],
            curve)
        demands = [v for _d, v in curve]
        self.assertEqual(sorted(demands, reverse=True), demands,
                         "it must slope DOWNWARD, peak to minimum")
        self.assertEqual(5, len(curve), "every interval appears; duration is "
                                        "cumulative")

    def test_the_x_axis_can_be_PERCENTAGE_OF_TIME(self):
        curve = self.runner.load_duration_curve([1.0, 3.0, 2.0, 4.0],
                                                percent=True)
        self.assertEqual([25.0, 50.0, 75.0, 100.0], [d for d, _v in curve])
        self.assertEqual(4.0, curve[0][1], "the peak is still first")

    def test_a_NON_HOURLY_interval_still_gives_HOURS(self):
        """An earlier version returned a 1-based RANK and called it hours,
        which is true only for hourly input (Fable, `323` 6)."""
        quarter = self.runner.load_duration_curve([4.0, 1.0, 2.0, 3.0],
                                                  interval_hours=0.25)
        self.assertEqual([0.25, 0.5, 0.75, 1.0], [d for d, _v in quarter])

    def test_demand_comes_from_energy_by_the_INTERVAL(self):
        """A raw hourly meter is J/h, not W — they differ by 3600, so the
        y axis is not a demand until this conversion happens."""
        self.assertEqual([1000.0],
                         self.runner.demand_from_energy([3.6e6]))
        self.assertEqual([4000.0],
                         self.runner.demand_from_energy([3.6e6], 0.25))

    def test_sum_by_key_ADDS_two_firing_series(self):
        """The mutation that survived: on a lead/lag fixture one boiler is
        identically zero, so a sum is indistinguishable from a maximum
        (Fable, `323` M10). Two FIRING series separate them."""
        per_key = {
            "A": {"index": [(1, 1, 1), (1, 1, 2)], "values": [2.0, 10.0]},
            "B": {"index": [(1, 1, 1), (1, 1, 2)], "values": [3.0, 1.0]},
        }
        total = self.runner.sum_by_key(per_key)
        self.assertEqual([5.0, 11.0], total["values"],
                         "a maximum would give [3.0, 10.0]")
        self.assertEqual([(1, 1, 1), (1, 1, 2)], total["index"])
        self.assertEqual({"index": [], "values": []},
                         self.runner.sum_by_key({}))

    def test_the_curve_distinguishes_a_NEEDLE_from_a_PLATEAU(self):
        """The whole reason an LDC beats a peak value.

        Both series below have the same peak and the same number of hours. A
        peak value cannot tell them apart; the hours spent near the peak is
        what decides whether shaving is cheap, and the AREA above a threshold
        is the energy a store has to hold.
        """
        needle = [10.0] + [1.0] * 9
        plateau = [10.0] * 5 + [1.0] * 5
        self.assertEqual(self.runner.load_duration_curve(needle)[0][1],
                         self.runner.load_duration_curve(plateau)[0][1],
                         "same peak, by construction")

        above = self.runner.energy_above
        self.assertAlmostEqual(1.0, above(needle, 9.0))
        self.assertAlmostEqual(5.0, above(plateau, 9.0))
        self.assertAlmostEqual(
            1.25, above(plateau, 9.0, interval_hours=0.25),
            "a RATE series' excess scales with the interval")
        self.assertGreater(
            above(plateau, 9.0), above(needle, 9.0),
            "the plateau needs five times the stored energy for the same peak")

    def test_energy_above_counts_only_the_excess(self):
        self.assertAlmostEqual(0.0, self.runner.energy_above([1, 2, 3], 3))
        self.assertAlmostEqual(3.0, self.runner.energy_above([1, 2, 3], 1))
        self.assertAlmostEqual(0.0, self.runner.energy_above([], 1))

    def test_the_tier_lists_are_what_the_requirements_need(self):
        """Tier 1 must carry every end use a load-reduction study reads."""
        meters = set(self.runner.HOURLY_METERS)
        for required in ("Electricity:Facility", "InteriorLights:Electricity",
                         "Fans:Electricity", "Pumps:Electricity",
                         "InteriorEquipment:Electricity"):
            self.assertIn(required, meters)
        self.assertNotIn(
            "Heating:EnergyTransfer", meters,
            "deliberately absent: it is NOT the building's heat load — see "
            "hourly_hot_water_plant_heat")


class TestRequestHelpers(unittest.TestCase):
    """The request helpers on a FRESH model — SDK only, no simulation.

    Separate from the engine class because that one calls
    `request_hourly_meters` TWICE (to assert idempotency), and the second
    call takes the UPGRADE branch, which repaired what a mutated CREATE
    branch left broken: removing `setMeterFileOnly(False)` from the create
    path passed all 25 engine tests. One call on a fresh model is the only
    place the create branch is observable.
    """

    def setUp(self):
        try:
            import openstudio
        except ImportError:  # pragma: no cover - the engine-free lane
            self.skipTest("the OpenStudio SDK is required")
        from btap.simulation import runner

        self.openstudio = openstudio
        self.runner = runner
        self.model = openstudio.model.Model()

    def test_ONE_call_sets_every_meter_to_hourly_and_NOT_file_only(self):
        added = self.runner.request_hourly_meters(self.model)
        self.assertEqual(len(self.runner.HOURLY_METERS), added)
        got = {m.name(): m for m in self.model.getOutputMeters()}
        self.assertEqual(len(self.runner.HOURLY_METERS), len(got),
                         "one meter per name")
        for name in self.runner.HOURLY_METERS:
            with self.subTest(meter=name):
                self.assertEqual("Hourly", got[name].reportingFrequency())
                self.assertFalse(
                    got[name].meterFileOnly(),
                    "`Output:Meter:MeterFileOnly` writes the .mtr file, and "
                    "whether it also reaches the SQL ReportData the readers "
                    "use is BUILD-DEPENDENT: this passed locally six times "
                    "and failed on the CI image")

    def test_a_coarser_existing_request_is_UPGRADED_not_duplicated(self):
        monthly = self.openstudio.model.OutputMeter(self.model)
        monthly.setName("Electricity:Facility")
        monthly.setReportingFrequency("Monthly")

        self.runner.request_hourly_meters(self.model)
        same = [m for m in self.model.getOutputMeters()
                if m.name() == "Electricity:Facility"]
        self.assertEqual(1, len(same),
                         "a duplicate is the nondeterminism — two same-name "
                         "meters at different frequencies resolved "
                         "differently on two xdist workers")
        self.assertEqual("Hourly", same[0].reportingFrequency())
        self.assertFalse(same[0].meterFileOnly())

    def test_a_name_OUTSIDE_tier_1_is_left_alone(self):
        other = self.openstudio.model.OutputMeter(self.model)
        other.setName("Cooling:EnergyTransfer")
        other.setReportingFrequency("Monthly")

        self.runner.request_hourly_meters(self.model)
        kept = [m for m in self.model.getOutputMeters()
                if m.name() == "Cooling:EnergyTransfer"]
        self.assertEqual(1, len(kept))
        self.assertEqual("Monthly", kept[0].reportingFrequency(),
                         "tier 1 must not touch a name it does not request")


@needs_engine
class TestHourlyAgainstTheTabularTruth(unittest.TestCase):
    """One annual run, then every claim checked against the tabular reports.

    The tabular End Uses rows are EnergyPlus's own totals, so they are the
    only check that cannot be argued with: if an hourly sum matches one, the
    `EnvironmentType` and frequency filters are both right.
    """

    @classmethod
    def setUpClass(cls):
        import openstudio

        from btap import simulation
        from btap.simulation import runner
        from tests.necb.support import proposed_with_hvac

        cls.runner = runner
        # Hot-water baseboards AND an air-side heating coil, so the
        # zone-side-versus-plant-side difference is present to be measured.
        model = proposed_with_hvac(
            "MZ BU RTU Hot Water Heating Coil Scroll Chiller "
            "and Hot Water Baseboard")
        # A `|` in an object name is legal in OpenStudio and survives
        # translation. It used to truncate the key and turn the value into a
        # silent 0.0 for 8760 hours (`323` 1.1).
        zone = sorted(model.getThermalZones(),
                      key=lambda z: z.nameString())[0]
        cls.piped_zone = "Thermal Zone 1|X"
        zone.setName(cls.piped_zone)
        # And one with an APOSTROPHE, because a malformed query and a
        # correct query for an absent name both return empty — so only a name
        # that EXISTS and contains a quote can tell the escaping apart from
        # its absence (`323` 1.2 survived a test that asserted empty).
        quoted = sorted(model.getThermalZones(),
                        key=lambda z: z.nameString())[1]
        cls.quoted_zone = "Bob's Zone"
        quoted.setName(cls.quoted_zone)

        # A MONTHLY meter for a name tier 1 also wants, because this is the
        # commonest pre-existing request in a user OSM and a name-only
        # idempotency check skipped the hourly one, reporting success while
        # the later read came back EMPTY (`323` 5.1).
        monthly = openstudio.model.OutputMeter(model)
        monthly.setName("Electricity:Facility")
        monthly.setReportingFrequency("Monthly")

        # And a meter requested ONLY monthly, for a name tier 1 never asks
        # for. Without it, `hourly_names` filtered and unfiltered return the
        # same set on this fixture and dropping its frequency filter passes
        # every test — the divergent fixture IS the test.
        # NOT a tier-1 name, so `request_hourly_meters` leaves it alone and
        # it stays monthly-only — which is what the catalogue filter needs.
        cls.monthly_only = "Cooling:EnergyTransfer"
        only = openstudio.model.OutputMeter(model)
        only.setName(cls.monthly_only)
        only.setReportingFrequency("Monthly")

        cls.added = runner.request_hourly_meters(model)
        cls.added_again = runner.request_hourly_meters(model)
        # EXPLICITLY, because `HOURLY_METERS` deliberately excludes it — this
        # class has to request the zone-side meter in order to demonstrate why
        # it is excluded. The precondition in that test caught its absence.
        runner.request_hourly_meters(model, ["Heating:EnergyTransfer"])
        runner.request_hourly_zone_variables(model)
        # A RunPeriod request for the SAME name as an hourly one, because the
        # NECB aux-fuel election does exactly this and it is what broke the
        # reader: the RunPeriod rows have NULL time columns.
        runner.request_run_period_variables(
            model, [runner.BOILER_HEAT_VARIABLE])
        # The documented helper, and AFTER the RunPeriod request on purpose:
        # with the frequency-keyed fix both orders must work, where a
        # name-only check skipped whichever came second (`323` 5.2).
        cls.plant_added = runner.request_hourly_plant_variables(model)

        import tempfile
        cls._tmp = tempfile.TemporaryDirectory(prefix="hourly-layer-")
        simulation.run(model, run_dir=str(pathlib.Path(cls._tmp.name) / "run"),
                       weather={"epw": str(EPW), "ddy": str(DDY)})
        cls.model = model
        cls.sql_path = sorted(
            pathlib.Path(cls._tmp.name).rglob("eplusout.sql"))[0]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _tabular_gj(self, row, column):
        import sqlite3

        cur = sqlite3.connect(f"file:{self.sql_path}?mode=ro",
                              uri=True).cursor()
        cur.execute("""SELECT Value FROM TabularDataWithStrings
                       WHERE ReportName=
                             'AnnualBuildingUtilityPerformanceSummary'
                         AND TableName='End Uses' AND RowName=?
                         AND ColumnName=?""", (row, column))
        found = cur.fetchone()
        self.assertIsNotNone(found, f"no tabular row {row!r}/{column!r}")
        return float(found[0])

    def test_requesting_meters_UPGRADES_a_coarser_request(self):
        """A pre-existing MONTHLY meter is raised to hourly, not duplicated.

        Two same-name meters at different frequencies are legal and resolve
        NONDETERMINISTICALLY through this path: CI ran this class on two xdist
        workers and one honoured the hourly request while the other honoured
        the monthly sibling, reading back zero hours. Upgrading in place
        leaves one meter per name.
        """
        self.assertEqual(len(self.runner.HOURLY_METERS), self.added,
                         "the Monthly Electricity:Facility request counts as "
                         "upgraded, not skipped")
        same = [m for m in self.model.getOutputMeters()
                if m.name() == "Electricity:Facility"]
        self.assertEqual(1, len(same),
                         "exactly ONE meter per name — a duplicate is the "
                         "nondeterminism")
        self.assertEqual("Hourly", same[0].reportingFrequency())

        # EVERY tier-1 meter, not just the one with a monthly sibling. That
        # one takes the UPGRADE branch; the other twelve take CREATE, and
        # asserting only the first left the create branch unprotected — the
        # mutation that removed `setMeterFileOnly(False)` there passed all 25
        # tests.
        requested = {m.name(): m for m in self.model.getOutputMeters()}
        for name in self.runner.HOURLY_METERS:
            with self.subTest(meter=name):
                meter = requested.get(name)
                self.assertIsNotNone(meter, f"{name} must be requested")
                self.assertEqual("Hourly", meter.reportingFrequency())
                self.assertFalse(
                    meter.meterFileOnly(),
                    "meterFileOnly translates to Output:Meter:MeterFileOnly, "
                    "whose presence in the SQL ReportData is build-dependent "
                    "— this is why the first version passed locally six times "
                    "and failed on the CI image")
        self.assertEqual(0, self.added_again,
                         "a second call at the same frequency adds nothing")
        self.assertEqual(2, self.plant_added,
                         "the plant variables were requested after a "
                         "RunPeriod sibling and must still be added")

    def test_the_monthly_sibling_did_not_blank_the_hourly_read(self):
        """The front-door form of the silent-empty failure (`323` 5.1)."""
        series = self.runner.hourly_series(self.model, "Electricity:Facility")
        self.assertEqual(8760, len(series["values"]))

    def test_a_PIPE_in_a_key_survives_the_parse(self):
        """It used to truncate the key and read 8760 zeros (`323` 1.1)."""
        by_key = self.runner.hourly_series_by_key(
            self.model, "Zone Mean Air Temperature")
        upper = self.piped_zone.upper()
        self.assertIn(upper, by_key,
                      f"the piped key must arrive whole; got "
                      f"{sorted(by_key)[:3]}")
        values = by_key[upper]["values"]
        self.assertEqual(8760, len(values))
        self.assertTrue(any(v != 0.0 for v in values),
                        "a truncated parse reads every hour as 0.0")

    def test_a_quoted_KEY_round_trips_through_the_result(self):
        """A quote in an object NAME is legal and must survive the read.

        It arrives through the result rather than the query, so this is about
        the parse, not about SQL.
        """
        by_key = self.runner.hourly_series_by_key(
            self.model, "Zone Mean Air Temperature")
        upper = self.quoted_zone.upper()
        self.assertIn(upper, by_key,
                      f"the apostrophe key must arrive; got {sorted(by_key)}")
        self.assertEqual(8760, len(by_key[upper]["values"]))

    def test_a_quoted_VARIABLE_name_is_REFUSED(self):
        """Two attempts to test the escaping both passed without it.

        Escaping a quote is the correct SQLite form and could not be tested
        through this API: a malformed literal and a correct query for an
        absent name both return empty. No EnergyPlus name contains a quote,
        so refusing is both honest and testable (`323` 1.2).
        """
        for bad in ("Bob's Meter", 'say "hi"', "x; DROP TABLE Time"):
            with self.subTest(name=bad):
                with self.assertRaises(ValueError):
                    self.runner.hourly_series(self.model, bad)

    def test_an_intensive_variable_is_REFUSED_not_summed(self):
        """Summing five zone temperatures gave a plottable lie (`323` 2)."""
        with self.assertRaises(ValueError) as caught:
            self.runner.hourly_series(self.model, "Zone Mean Air Temperature")
        self.assertIn("reduce deliberately", str(caught.exception))

    def test_the_hourly_sum_equals_the_TABULAR_TOTAL(self):
        """The EnvironmentType = 3 filter, checked the only way that counts.

        Unfiltered, this fixture's three sizing periods inflate the total by
        1.8% and the tabular row does NOT match.
        """
        series = self.runner.hourly_series(self.model, "Electricity:Facility")
        self.assertEqual(8760, len(series["values"]),
                         "a full weather year, with no design days mixed in")
        mine = sum(series["values"]) / 3.6e9
        truth = self._tabular_gj("Total End Uses", "Electricity") / 3.6
        self.assertAlmostEqual(truth, mine, delta=truth * 0.001,
                               msg="hourly must reconcile to the tabular row")

    def test_a_RUNPERIOD_request_for_the_same_name_does_not_blank_the_read(self):
        """The regression that cost a whole annual run to find.

        `Boiler Heating Energy` was present as 8832 hourly rows AND 4 RunPeriod
        rows. Without `ReportingFrequency = 'Hourly'` the query matched both,
        the RunPeriod rows' NULL month/day/hour made SQLite return NULL for the
        whole concatenated row, and the read came back as ZERO HOURS — not as
        junk, as nothing.
        """
        series = self.runner.hourly_hot_water_plant_heat(self.model)
        self.assertEqual(8760, len(series["values"]),
                         "the hourly series must survive a RunPeriod sibling")
        self.assertGreater(sum(series["values"]), 0.0)

    def test_the_plant_heat_series_SUMS_the_boilers(self):
        """A lead/lag pair reports the idle boiler as zero.

        Taking the first boiler would read the whole load on this model and
        nothing on one whose boilers are ordered the other way.
        """
        per_key = self.runner.hourly_series_by_key(
            self.model, self.runner.BOILER_HEAT_VARIABLE)
        self.assertGreater(len(per_key), 1, "this fixture has two boilers")
        idle = [k for k, s in per_key.items() if sum(s["values"]) == 0.0]
        self.assertTrue(idle, "one of the lead/lag pair must be idle here")

        summed = self.runner.hourly_hot_water_plant_heat(self.model)
        self.assertAlmostEqual(
            sum(sum(s["values"]) for s in per_key.values()),
            sum(summed["values"]), delta=1.0,
            msg="the plant series is every boiler, not the first")

    def test_the_boiler_FUEL_series_reconciles_to_the_gas_row(self):
        """One model, two readings: the DE case and the on-site-boiler case."""
        fuel = self.runner.sum_by_key(self.runner.hourly_series_by_key(
            self.model, self.runner.BOILER_FUEL_VARIABLE))
        mine = sum(fuel["values"]) / 3.6e9
        truth = self._tabular_gj("Heating", "Natural Gas") / 3.6
        self.assertAlmostEqual(truth, mine, delta=truth * 0.001)

    def test_an_ABSENT_name_raises_and_names_what_IS_there(self):
        """A misspelling used to return empty, and `energy_above([], t)` is a
        cheerful 0.0 — so the mistake propagated as a number (`323` Q2)."""
        with self.assertRaises(KeyError) as caught:
            self.runner.hourly_series(self.model, "Electricty:Facility")
        message = str(caught.exception)
        self.assertIn("Electricty:Facility", message, "name the mistake")
        self.assertIn("Electricity:Facility", message,
                      "and name a real one, so the typo is obvious")
        self.assertIn("request_hourly_meters", message,
                      "and say how to fix it")

        with self.assertRaises(KeyError):
            self.runner.hourly_series_by_key(self.model, "No Such Variable")

    def test_the_hourly_CATALOGUE_lists_only_HOURLY_names(self):
        names = self.runner.hourly_names(self.model)
        self.assertIn("Electricity:Facility", names)
        self.assertIn("Zone Mean Air Temperature", names)
        self.assertEqual(sorted(names), names, "sorted, for a reader")
        self.assertNotIn(
            self.monthly_only, names,
            f"{self.monthly_only!r} is requested MONTHLY only and must not "
            f"appear in an hourly catalogue")

    def test_a_name_requested_at_ANOTHER_frequency_still_raises(self):
        """`Cooling:EnergyTransfer` is requested monthly and never hourly.

        It reports — so it is in the SQL — but not at this frequency, and a
        reader asking for it hourly has made the same mistake as a
        misspelling.
        """
        with self.assertRaises(KeyError) as caught:
            self.runner.hourly_series(self.model, self.monthly_only)
        self.assertIn("never requested hourly", str(caught.exception))

    def test_a_REQUESTED_name_with_nothing_to_report_is_not_an_error(self):
        """The boundary, and it refines what we first agreed.

        `ExteriorLights:Electricity` is in tier 1, and a building with no
        exterior lights never reports it at all — EnergyPlus does not create
        a meter with no contributing objects, so it is ABSENT rather than
        zero. Raising on every absence would make iterating the tier
        impossible, so the model's own requests decide: requested and silent
        is an empty series, never requested is a KeyError.
        """
        self.assertIn("ExteriorLights:Electricity",
                      self.runner.HOURLY_METERS, "tier 1 asks for it")
        self.assertNotIn("ExteriorLights:Electricity",
                         self.runner.hourly_names(self.model),
                         "and this fixture never reports it")
        self.assertEqual(
            {"index": [], "values": []},
            self.runner.hourly_series(
                self.model, "ExteriorLights:Electricity"))
        self.assertEqual(
            {}, self.runner.hourly_series_by_key(
                self.model, "ExteriorLights:Electricity"))

    def test_sum_by_key_REFUSES_a_ragged_set(self):
        """It used to clip to the first key's length, silently (`323`)."""
        with self.assertRaises(ValueError) as caught:
            self.runner.sum_by_key({
                "A": {"index": [(1, 1, 1), (1, 1, 2)], "values": [1.0, 2.0]},
                "B": {"index": [(1, 1, 1)], "values": [5.0]},
            })
        self.assertIn("cannot be added", str(caught.exception))

    def test_run_period_sums_does_NOT_double_count_an_hourly_sibling(self):
        """A 2x error in a NECB reader, with no test of its own (`323` 5.3).

        `run_period_sums` feeds `_heating_election_data` in
        `codes/necb/path.py` — the D-52 auxiliary-fuel election. It had no
        `ReportingFrequency` filter, so once anything requested the same
        variable HOURLY its 8760 rows were added to the RunPeriod row:
        measured 152.62 MWh against a true 76.31. Nothing could trigger that
        before `request_hourly_meters` existed, which is why the reader
        survived untested.

        This model carries both requests for `Boiler Heating Energy`, so the
        RunPeriod read and the hourly read must AGREE — they are the same
        annual total by two routes.
        """
        election = self.runner.run_period_sums(
            self.model, self.runner.BOILER_HEAT_VARIABLE)
        self.assertTrue(election, "the RunPeriod request must have reported")
        by_route = self.runner.sum_by_key(self.runner.hourly_series_by_key(
            self.model, self.runner.BOILER_HEAT_VARIABLE))
        hourly_total = sum(by_route["values"])
        self.assertGreater(hourly_total, 0.0)
        self.assertAlmostEqual(
            hourly_total, sum(election.values()),
            delta=hourly_total * 0.002,
            msg="the RunPeriod sum must not include the hourly rows — "
                "without the frequency filter this is exactly 2x")

    def test_the_plant_side_read_can_FAR_EXCEED_the_zone_side(self):
        """Why a hydronic plant is read at the plant, not at the zones.

        `Heating:EnergyTransfer` is the facility sum of `Zone Air System
        Sensible Heating Energy` — the zone air balance's NET sensible
        heating. It does NOT exclude hydronic baseboards: on a baseboard-only
        system the meter, the baseboard meter and the summed variable are all
        33.40 MWh. An earlier version of this docstring said it excluded them,
        which was false (`323` 3).

        The gap is simultaneous cooling-then-reheat and the heating of
        ventilation air to supply temperature — plant heat that offsets
        cooling or outdoor air and never arrives as net zone sensible
        heating. A VAV with NO baseboards shows it at 2.17x.

        THE RATIO IS SYSTEM-DEPENDENT, measured from 0.98 on a baseboard-only
        system to 2.17 on a VAV with reheat, so this asserts the gap on THIS
        fixture and nothing general. What is general is the direction: a
        zone-side net term cannot see a hydronic plant's obligation.
        """
        plant = sum(self.runner.hourly_hot_water_plant_heat(
            self.model)["values"])
        zone = sum(self.runner.hourly_series(
            self.model, "Heating:EnergyTransfer")["values"])
        self.assertGreater(zone, 0.0, "the zone-side meter was requested")
        self.assertGreater(
            plant, zone * 1.5,
            f"the plant side must materially exceed the zone side on a "
            f"system with hydronic baseboards; got plant={plant / 3.6e9:.1f} "
            f"MWh vs zone={zone / 3.6e9:.1f} MWh")


if __name__ == "__main__":
    unittest.main()
