"""D-90: the reference plant's capacity follows the reference's own sizing.

The efficiency pass hard-sets boiler and chiller capacities (8.4.4.9.(6) /
8.4.4.10.(6) staging; 2025: 8.4.5.9.(6) / 8.4.5.10.(6)) and hardens cooling-tower
hydraulics. Before D-90 nothing released those values, so on a reference clone the
plant stayed at the capacity the FIRST pass read — the proposed's sizing — through
every 8.4.1.2.(5) increase, a two-boiler plant was halved again on each pass, and
every pass appended another capacity suffix to the name.

The contract pinned here: a pass records what it set and from what
(``additionalProperties`` ownership features); a repeat pass stages from the same
basis; ``prepare_for_resizing`` releases what the pass derived from sizing and never
a capacity the model supplied as an input; ownership carried in with an input model
is not used by the reference; and the 8.4.1.2.(5) warnings name only capacities the
pipeline does not own.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

import openstudio

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.codes.necb import hvac, path
from btap.codes.necb.hvac import efficiency
from btap.simulation import runner
from tests.necb.hvac_helpers import attach_weather, load_fixture, proposed_with_hvac, sorted_zones
from tests.support import needs_engine, needs_sdk

WATER_COOLED_SYSTEM = 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard'
FPFC = 'FPFC MAU Chilled Water Coils with Scroll Chiller'


def plant(boiler_w=None, chiller_w=None):
    model = load_fixture()
    modeling.build_system(model, WATER_COOLED_SYSTEM, sorted_zones(model))
    if boiler_w is not None:
        for boiler in model.getBoilerHotWaters():
            boiler.setNominalCapacity(boiler_w)
    if chiller_w is not None:
        for chiller in model.getChillerElectricEIRs():
            chiller.setReferenceCapacity(chiller_w)
    return model


def boilers(model):
    primary = next(b for b in model.getBoilerHotWaters() if 'Primary' in b.nameString())
    secondary = next(b for b in model.getBoilerHotWaters() if 'Secondary' in b.nameString())
    return primary, secondary


def apply_passes(model, passes, code='necb2020'):
    audit = AuditLog()
    for _ in range(passes):
        hvac.apply_efficiencies(model, code=code, audit=audit)
    return audit


def feature(component, name):
    value = component.additionalProperties().getFeatureAsString(name)
    return value.get() if value.is_initialized() else None


@needs_sdk
class TestStagingIsRepeatable(unittest.TestCase):

    def test_two_boiler_plant_is_not_halved_on_a_second_pass(self):
        # 300 kW: 8.4.4.9.(6)(c), two boilers of equal capacity
        model = plant(boiler_w=300_000.0)
        apply_passes(model, 2)
        primary, secondary = boilers(model)
        self.assertAlmostEqual(150_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(150_000.0, secondary.nominalCapacity().get(), delta=1.0)

    def test_modulating_plant_above_352_kw_is_stable(self):
        # 400 kW: 8.4.4.9.(6)(d), one boiler modulating to 25 %
        model = plant(boiler_w=400_000.0)
        apply_passes(model, 2)
        primary, secondary = boilers(model)
        self.assertAlmostEqual(400_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-6)
        self.assertEqual('LeavingSetpointModulated', primary.boilerFlowMode())
        self.assertAlmostEqual(0.25, primary.minimumPartLoadRatio(), delta=1e-6)

    def test_single_boiler_plant_is_stable(self):
        model = plant(boiler_w=100_000.0)
        apply_passes(model, 2)
        primary, secondary = boilers(model)
        self.assertAlmostEqual(100_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-6)

    def test_name_carries_one_capacity_suffix_after_three_passes(self):
        model = plant(boiler_w=100_000.0)
        apply_passes(model, 3)
        primary, secondary = boilers(model)
        for boiler, base in ((primary, 'Primary Boiler'), (secondary, 'Secondary Boiler')):
            self.assertEqual(1, boiler.nameString().count('kBtu/hr'), boiler.nameString())
            self.assertTrue(boiler.nameString().startswith(base + ' '), boiler.nameString())
            self.assertEqual(base, feature(boiler, efficiency.BASE_NAME_FEATURE))

    def test_a_hard_capacity_is_recorded_as_an_input(self):
        model = plant(boiler_w=300_000.0)
        audit = apply_passes(model, 1)
        entry = next(e for e in audit.entries
                     if e['action'] == 'boiler efficiency applied'
                     and e['target'] == 'Primary Boiler')
        self.assertEqual('input', entry['inputs']['capacity_source'])
        self.assertAlmostEqual(300.0, entry['inputs']['design_capacity_kw'], delta=0.1)
        self.assertAlmostEqual(150.0, entry['inputs']['capacity_kw'], delta=0.1)
        self.assertIn('D-90', entry['ruling'].split())

    def test_large_two_chiller_plant_is_not_halved_on_a_second_pass(self):
        # 3 MW: 8.4.4.10.(6), above 2100 kW the plant is two equal chillers
        model = plant(chiller_w=3_000_000.0)
        chillers = list(model.getChillerElectricEIRs())
        if len(chillers) < 2:
            self.skipTest('the catalog system builds a single chiller')
        apply_passes(model, 2)
        for chiller in model.getChillerElectricEIRs():
            self.assertAlmostEqual(1_500_000.0, chiller.referenceCapacity().get(), delta=1.0)
            self.assertEqual(1, chiller.nameString().count('tons'), chiller.nameString())


@needs_sdk
@needs_sdk
class TestStagedPairIdentity(unittest.TestCase):
    """DF-13. The 8.4.x.9.(6) bands describe a PLANT, but the pass applies them
    per boiler, and it used to decide which boiler was which by matching
    'Primary Boiler' / 'Secondary Boiler' in the NAME. Sol ruled (2026-09-16)
    that staging does reach a plant the reference copied, so the defect was not
    that copied plants get staged — it was that a two-boiler plant named
    anything else was never staged at all, missing (6)(c) entirely."""

    def foreign_named_plant(self, capacity_w):
        """Two boilers on one hot-water loop, named as no builder here names
        them, each carrying the plant's design capacity."""
        model = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(model)
        loop_.sizingPlant().setLoopType('Heating')
        boilers = []
        for name in ('Chaudiere A', 'Chaudiere B'):
            boiler = openstudio.model.BoilerHotWater(model)
            boiler.setName(name)
            boiler.setNominalCapacity(capacity_w)
            loop_.addSupplyBranchForComponent(boiler)
            boilers.append(boiler)
        return model, boilers

    def test_an_unnamed_two_boiler_plant_is_staged_by_its_topology(self):
        model, boilers = self.foreign_named_plant(300_000.0)  # (6)(c) band
        hvac.apply_efficiencies(model, code='necb2020', audit=AuditLog())

        self.assertEqual([150_000.0, 150_000.0],
                         [b.nominalCapacity().get() for b in boilers],
                         'two boilers of equal capacity — (6)(c) reached without the names')

    def test_the_modulating_band_reaches_an_unnamed_plant_too(self):
        model, boilers = self.foreign_named_plant(400_000.0)  # (6)(d) band
        hvac.apply_efficiencies(model, code='necb2020', audit=AuditLog())

        primary, secondary = boilers
        self.assertEqual(400_000.0, primary.nominalCapacity().get())
        self.assertEqual('LeavingSetpointModulated', primary.boilerFlowMode())
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-9,
                               msg='(6)(d) is one modulating boiler')

    def test_a_lone_boiler_is_not_half_of_a_pair(self):
        model = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(model)
        loop_.sizingPlant().setLoopType('Heating')
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.setName('Chaudiere Seule')
        boiler.setNominalCapacity(300_000.0)
        loop_.addSupplyBranchForComponent(boiler)
        hvac.apply_efficiencies(model, code='necb2020', audit=AuditLog())

        self.assertEqual(300_000.0, boiler.nominalCapacity().get(),
                         'a single boiler is the whole plant, never halved')

    def test_a_builder_plant_keeps_its_role_after_the_pass_renames_it(self):
        """The pass rewrites every boiler's name with a capacity suffix each
        round, so the name is the one thing that cannot carry the identity."""
        model = load_fixture()
        modeling.build_system(model, WATER_COOLED_SYSTEM, sorted_zones(model))
        for boiler in model.getBoilerHotWaters():
            boiler.setNominalCapacity(300_000.0)
        hvac.apply_efficiencies(model, code='necb2020', audit=AuditLog())

        renamed = [b.nameString() for b in model.getBoilerHotWaters()]
        self.assertTrue(all('kBtu/hr' in n for n in renamed),
                        'precondition: the pass has rewritten the names')
        self.assertEqual({'primary', 'secondary'},
                         {efficiency._plant_role(b, efficiency._base_name(b))
                          for b in model.getBoilerHotWaters()},
                         'the builder feature still says which boiler is which')


@needs_sdk
class TestStagingBandCrossing(unittest.TestCase):
    """Each pass sets the complete control state of the band the plant lands in:
    between the build-time pass (the proposed's sizing) and the post-sizing pass
    (the reference's) a plant can cross 352 kW in either direction."""

    def restage(self, first_w, second_w):
        model = plant(boiler_w=first_w)
        apply_passes(model, 1)
        for boiler in model.getBoilerHotWaters():
            boiler.setNominalCapacity(second_w)  # a new sizing, not the value the pass applied
        apply_passes(model, 1)
        return boilers(model)

    def assert_not_modulating(self, boiler):
        self.assertEqual('ConstantFlow', boiler.boilerFlowMode())
        self.assertTrue(boiler.isMinimumPartLoadRatioDefaulted())

    def test_crossing_down_to_one_boiler_drops_the_modulating_controls(self):
        primary, secondary = self.restage(400_000.0, 100_000.0)
        self.assertAlmostEqual(100_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-6)
        self.assert_not_modulating(primary)
        self.assert_not_modulating(secondary)

    def test_crossing_down_to_two_equal_boilers_drops_the_modulating_controls(self):
        primary, secondary = self.restage(400_000.0, 300_000.0)
        self.assertAlmostEqual(150_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(150_000.0, secondary.nominalCapacity().get(), delta=1.0)
        self.assert_not_modulating(primary)
        self.assert_not_modulating(secondary)

    def test_crossing_up_above_352_kw_modulates_the_primary(self):
        primary, secondary = self.restage(100_000.0, 400_000.0)
        self.assertAlmostEqual(400_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertEqual('LeavingSetpointModulated', primary.boilerFlowMode())
        self.assertAlmostEqual(0.25, primary.minimumPartLoadRatio(), delta=1e-6)
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-6)
        self.assert_not_modulating(secondary)


@needs_sdk
class TestPrepareForResizing(unittest.TestCase):

    def test_releases_capacity_derived_from_sizing_and_keeps_inputs(self):
        model = plant(boiler_w=200_000.0)
        apply_passes(model, 1)
        primary, secondary = boilers(model)
        # what a pass over a SIZED model records: basis from the autosized value
        efficiency._record_capacity(primary, 200_000.0, 'autosized',
                                    primary.nominalCapacity().get(), 'Primary Boiler')

        audit = AuditLog()
        hvac.prepare_for_resizing(model, audit=audit)

        self.assertTrue(primary.isNominalCapacityAutosized())
        self.assertFalse(secondary.isNominalCapacityAutosized(), 'an input capacity is never released')
        self.assertIsNone(feature(primary, efficiency.CAPACITY_SOURCE_FEATURE))
        self.assertEqual('Primary Boiler', feature(primary, efficiency.BASE_NAME_FEATURE))
        entry = next(e for e in audit.entries if e.get('ruling') == 'D-90')
        self.assertEqual({'boilers': 1, 'chillers': 0, 'towers': 0}, entry['inputs'])
        self.assertRegex(entry['article'], r'8\.4\.4\.9\.\(6\)\(a\).*8\.4\.1\.2\.\(5\)')

    def test_the_release_cites_the_active_editions_articles(self):
        for code, prefix in (('necb2020', '8.4.4'), ('necb2025', '8.4.5')):
            with self.subTest(code=code):
                model = plant(boiler_w=200_000.0)
                apply_passes(model, 1, code=code)
                primary, _ = boilers(model)
                efficiency._record_capacity(primary, 200_000.0, 'autosized',
                                            primary.nominalCapacity().get(), 'Primary Boiler')
                # the pump transfer hard-sets power only on a SIZED model, so set one
                # here: the release entry beside the plant's cites the same edition
                for pump_ in (list(model.getPumpVariableSpeeds())
                              + list(model.getPumpConstantSpeeds())):
                    pump_.setRatedPowerConsumption(500.0)

                audit = AuditLog()
                hvac.prepare_for_resizing(model, audit=audit, code=code)
                entry = next(e for e in audit.entries if e.get('ruling') == 'D-90')
                self.assertEqual(f'{prefix}.9.(6)(a); {prefix}.10.(6); 8.4.1.2.(5)',
                                 entry['article'])
                # the pump release in the same function cites the same edition
                pump = next(e for e in audit.entries if 'pump power released' in e['action'])
                self.assertEqual(f'{prefix}.14.(1)-(3)', pump['article'])

    def test_nothing_owned_emits_no_plant_release(self):
        model = plant()
        audit = AuditLog()
        hvac.prepare_for_resizing(model, audit=audit)
        self.assertFalse([e for e in audit.entries if e.get('ruling') == 'D-90'])

    def test_hardened_tower_fields_are_released(self):
        model = plant()
        towers = list(model.getCoolingTowerSingleSpeeds())
        if not towers:
            self.skipTest('the catalog system builds no single-speed tower')
        tower = towers[0]
        tower.setDesignWaterFlowRate(0.01)
        tower.setFanPoweratDesignAirFlowRate(20_000.0)
        tower.additionalProperties().setFeature(
            efficiency.TOWER_HARDENED_FEATURE,
            'autosizeDesignWaterFlowRate;autosizeFanPoweratDesignAirFlowRate')

        audit = AuditLog()
        hvac.prepare_for_resizing(model, audit=audit)

        self.assertTrue(tower.isDesignWaterFlowRateAutosized())
        self.assertTrue(tower.isFanPoweratDesignAirFlowRateAutosized())
        self.assertIsNone(feature(tower, efficiency.TOWER_HARDENED_FEATURE))
        entry = next(e for e in audit.entries if e.get('ruling') == 'D-90')
        self.assertEqual(1, entry['inputs']['towers'])


@needs_sdk
class TestReferenceCloneHygiene(unittest.TestCase):

    def test_ownership_carried_in_with_the_model_is_not_used(self):
        proposed = proposed_with_hvac('Baseboard gas boiler')
        for boiler in proposed.getBoilerHotWaters():
            boiler.setNominalCapacity(50_000.0)
            efficiency._record_capacity(boiler, 50_000.0, 'autosized', 50_000.0, 'Stale Name')

        audit = AuditLog()
        result = hvac.reference_hvac(proposed, code='necb2020',
                                     building={'storeys': 1}, audit=audit)

        cleared = [e for e in audit.entries
                   if e.get('ruling') == 'D-90' and e['step'] == 'build']
        self.assertEqual(1, len(cleared))
        self.assertGreaterEqual(cleared[0]['inputs']['components'], 1)
        for boiler in result.model.getBoilerHotWaters():
            self.assertNotEqual('Stale Name', feature(boiler, efficiency.BASE_NAME_FEATURE))
            self.assertFalse(boiler.nameString().startswith('Stale Name'))


@needs_sdk
class TestHardSizedDetection(unittest.TestCase):

    def test_lists_input_capacities_but_not_capacity_the_pipeline_owns(self):
        model = plant(boiler_w=100_000.0)
        primary, secondary = boilers(model)
        names = path._hard_sized_capacities(model)
        self.assertIn(primary.nameString(), names)
        self.assertIn(secondary.nameString(), names)

        efficiency._record_capacity(primary, 100_000.0, 'autosized', 100_000.0, 'Primary Boiler')
        names = path._hard_sized_capacities(model)
        self.assertNotIn(primary.nameString(), names)
        self.assertIn(secondary.nameString(), names)

    def test_an_autosized_model_lists_nothing(self):
        self.assertEqual([], path._hard_sized_capacities(plant()))

    def failing_report(self, hard=None):
        report = {'proposed': {'unmet_occupied_hours': {'heating': 500.0, 'cooling': 0.0},
                               'mechanical_cooling': False},
                  'reference': {'unmet_occupied_hours': {'heating': 10.0, 'cooling': 0.0}},
                  'capacity_iterations': []}
        if hard:
            report['proposed']['hard_sized_capacities'] = hard
        return report

    def capacity_warning(self, report):
        audit = AuditLog()
        path.evaluate_unmet(report, efficiency.resolve('necb2020'), audit)
        return next(e for e in audit.entries
                    if e['level'] == 'warning' and e.get('article') == '8.4.1.2.(5)')['action']

    def test_an_empty_result_says_which_equipment_was_checked(self):
        text = self.capacity_warning(self.failing_report())
        self.assertIn('no hard-sized capacity was detected among', text)
        self.assertIn('staged coils are not checked', text)

    def test_detected_capacities_are_named(self):
        text = self.capacity_warning(self.failing_report(['Coil Heating Gas 1']))
        self.assertIn('Coil Heating Gas 1', text)
        self.assertNotIn('no hard-sized capacity was detected', text)

    def test_the_phrase_names_five_and_counts_the_rest(self):
        names = [f'Coil {i}' for i in range(7)]
        phrase = path._hard_sized_phrase(names)
        self.assertEqual(5, len(re.findall(r'Coil \d', phrase)))
        self.assertTrue(phrase.endswith('and 2 more'))


@needs_engine
class TestPublicReferenceIsReadyToSize(unittest.TestCase):
    """Sol, PR #49 P1: the public reference_hvac() tells callers to size the returned
    reference directly, but its build-time efficiency pass reads the proposed's
    sizing through the clone and hard-sets the plant. The returned model must be
    ready to size: a direct sizing run sees no user-specified boiler capacity."""

    def test_a_direct_sizing_run_of_the_returned_reference_sizes_its_own_plant(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        proposed = load_fixture()
        attach_weather(proposed)
        modeling.build_system(proposed, 'Baseboard gas boiler', sorted_zones(proposed))
        out = runner.run_energyplus(proposed, str(Path(tmp.name) / 'proposed'), sizing_only=True)
        self.assertTrue(runner.is_clean_run(out), 'proposed sizing run completes cleanly')
        self.assertTrue(proposed.sqlFile().is_initialized(), 'the proposed carries its sizing SQL')

        audit = AuditLog()
        result = hvac.reference_hvac(proposed, code='necb2025', building={'storeys': 1}, audit=audit)
        reference = result.model

        boilers_ = list(reference.getBoilerHotWaters())
        self.assertTrue(boilers_, 'fixture precondition: a hot-water reference plant')
        for boiler in boilers_:
            self.assertTrue(boiler.isNominalCapacityAutosized(), boiler.nameString())
        release = [e for e in audit.entries if e.get('ruling') == 'D-90' and e['step'] == 'efficiency'
                   and e['level'] == 'info']
        self.assertEqual(1, len(release), 'the build-time capacities were released before returning')
        self.assertEqual('8.4.5.9.(6)(a); 8.4.5.10.(6); 8.4.1.2.(5)', release[0]['article'])

        attach_weather(reference)
        out = runner.run_energyplus(reference, str(Path(tmp.name) / 'reference'), sizing_only=True)
        self.assertTrue(runner.is_clean_run(out), 'direct reference sizing run completes cleanly')
        with sqlite3.connect(str(Path(tmp.name) / 'reference' / 'run' / 'eplusout.sql')) as con:
            rows = con.execute(
                "select CompName, Description from ComponentSizes "
                "where CompType like 'Boiler:HotWater%' and Description like '%Nominal Capacity%'"
            ).fetchall()
        self.assertTrue(rows, 'the direct sizing run sized the reference boilers')
        self.assertFalse([r for r in rows if r[1].startswith('User-Specified')], rows)


@needs_sdk
class TestCopiedPlantPumpPowerIsReleased(unittest.TestCase):
    """The follow-up review of D-90: plant CAPACITY is ownership-tracked, but pump
    POWER is not — ``reference_hvac`` releases every hard-set pump power, including
    one carried in with a plant the reference COPIES from the proposed (the D-58
    residential identity), where the model, not the pass, supplied the value.

    That asymmetry is deliberate, and this pins it so it cannot be "fixed" into
    ownership tracking by symmetry with the capacity rules: the reference re-sizes
    those copied loops, and a frozen power and head meeting a freshly sized flow
    makes EnergyPlus FATAL on "Calculated Pump Efficiency > 100%" (found on the
    SmallHotel gas variant). The documented consequence for a direct API caller —
    pump power comes back autosized, so re-apply efficiencies with ``proposed=``
    after sizing — is pinned with it."""

    def pumps(self, model):
        return list(model.getPumpVariableSpeeds()) + list(model.getPumpConstantSpeeds())

    def copied_residential(self):
        """A multi-unit residential proposed, whose reference D-58 copies whole —
        so its plant, and the hard pump power on it, are the PROPOSED's."""
        model = load_fixture()
        modeling.build_system(model, FPFC, sorted_zones(model))
        pumps = self.pumps(model)
        self.assertTrue(pumps, 'fixture precondition: the residential plant has pumps')
        for pump in pumps:
            pump.setRatedPowerConsumption(500.0)
        return model

    def reference(self, model, code='necb2025'):
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, code=code,
            building={'storeys': 3,
                      'zone_types': {z.nameString(): 'Multi-unit residential'
                                     for z in model.getThermalZones()}},
            audit=audit)
        self.assertEqual(['copy_proposed'], sorted({a.action for a in result.assignments}),
                         'precondition: D-58 copies the proposed systems, plant and all')
        return result, audit

    def test_a_copied_plants_hard_pump_power_comes_back_autosized(self):
        result, audit = self.reference(self.copied_residential())

        pumps = self.pumps(result.model)
        self.assertTrue(pumps, 'the copied reference carries the proposed\'s pumps')
        for pump in pumps:
            self.assertTrue(pump.isRatedPowerConsumptionAutosized(),
                            f'{pump.nameString()} kept a hard power the reference sizing run would '
                            f'fatal on')
        release = [e for e in audit.entries if e.get('ruling') == 'D-11 D-27']
        self.assertEqual(1, len(release), 'one pump-release entry, on the way out of reference_hvac')
        self.assertEqual('8.4.5.14.(1)-(3)', release[0]['article'])
        self.assertEqual(len(pumps), release[0]['inputs']['pumps'],
                         'the entry counts the pumps it released')

    def test_a_service_water_circulators_hard_power_is_not_released(self):
        """DF-12, closed by D-92: the release is scoped to the pumps 8.4.x.14
        governs. D-27 puts an SWH circulator outside the Article and the pump
        pass leaves it 'as built', so releasing it would strand it autosized
        with nothing to re-establish it. Tested on prepare_for_resizing
        DIRECTLY — the existing SWH test only exercises the efficiency pass."""
        model = load_fixture()
        hvac_loop = openstudio.model.PlantLoop(model)
        hvac_loop.sizingPlant().setLoopType('Heating')
        hvac_pump = openstudio.model.PumpVariableSpeed(model)
        hvac_pump.setRatedPowerConsumption(500.0)
        hvac_pump.addToNode(hvac_loop.supplyInletNode())

        swh_loop = openstudio.model.PlantLoop(model)
        swh_loop.sizingPlant().setLoopType('Heating')
        openstudio.model.WaterHeaterMixed(model).addToNode(swh_loop.supplyOutletNode())
        swh_pump = openstudio.model.PumpConstantSpeed(model)
        swh_pump.setRatedPowerConsumption(8.0)
        swh_pump.addToNode(swh_loop.supplyInletNode())

        audit = AuditLog()
        hvac.prepare_for_resizing(model, audit=audit, code='necb2020')

        self.assertTrue(hvac_pump.isRatedPowerConsumptionAutosized(),
                        'the HVAC hydronic pump is released for the re-sizing run')
        self.assertFalse(swh_pump.isRatedPowerConsumptionAutosized(),
                         'the service-water circulator keeps the power it was built with')
        self.assertAlmostEqual(8.0, swh_pump.ratedPowerConsumption().get(), delta=1e-9)
        release = [e for e in audit.entries if e.get('ruling') == 'D-11 D-27']
        self.assertEqual(1, len(release))
        self.assertEqual(1, release[0]['inputs']['pumps'],
                         'only the HVAC pump is counted as released')

    def test_the_documented_recovery_re_establishes_power_from_the_sized_flow(self):
        """The docstring on reference_hvac tells a direct caller to re-apply
        efficiencies with the sized proposed. Pin that it is a real recovery: the
        8.4.4.14.(1)-(3) transfer puts power back, derived from the proposed's
        W/(L/s), not from the released value."""
        proposed = self.copied_residential()
        for pump in self.pumps(proposed):
            pump.setRatedFlowRate(0.004)  # 500 W / 4 L/s = 125 W/(L/s)
        result, _ = self.reference(proposed)
        # Size the reference's own pumps to DOUBLE the proposed's flow. Without
        # this the transfer lands on 125 W/(L/s) x 4 L/s = the released 500 W,
        # and the test cannot tell a derivation from a restoration.
        reference_pumps = self.pumps(result.model)
        for pump in reference_pumps:
            pump.setRatedFlowRate(0.008)

        audit = AuditLog()
        efficiency.apply_efficiencies(result.model, code='necb2025', proposed=proposed, audit=audit)
        # D-92: the pass states head/coefficient/motor efficiency and leaves
        # power autosized, so the recovery is checked as the power E+ will
        # derive — 125 W/(L/s) x 8 L/s — not as a number written into the model.
        self.assertEqual([1000.0] * len(reference_pumps),
                         sorted(round(efficiency._pump_power_from_triple(p, 0.008), 6)
                                for p in reference_pumps),
                         'power is DERIVED at the reference flow, not restored to the released value')
        transfer = [e for e in audit.entries if e['level'] == 'decision'
                    and e.get('article') == '8.4.5.14.(1)-(3)']
        self.assertEqual(len(reference_pumps), len(transfer),
                         'one transfer decision per pump, citing the ACTIVE edition')
        # The head reconciliation this test used to pin is gone with the
        # mechanism that needed it: nothing hard-sets power, so no inherited
        # head can contradict one.
        self.assertEqual([], [e for e in audit.entries
                              if e.get('ruling') == 'D-27' and e['level'] == 'warning'],
                         'no reconciliation: the stated efficiency is physical by construction')
        for pump in reference_pumps:
            self.assertGreaterEqual(pump.designShaftPowerPerUnitFlowRatePerUnitHead(), 1.0,
                                    f'{pump.nameString()}: stated efficiency a pump can have')


if __name__ == '__main__':
    unittest.main()
