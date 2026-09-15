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
import unittest

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.codes.necb import hvac, path
from btap.codes.necb.hvac import efficiency
from tests.necb.hvac_helpers import load_fixture, proposed_with_hvac, sorted_zones
from tests.support import needs_sdk

WATER_COOLED_SYSTEM = 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard'


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

    def test_the_phrase_names_five_and_counts_the_rest(self):
        names = [f'Coil {i}' for i in range(7)]
        phrase = path._hard_sized_phrase(names)
        self.assertEqual(5, len(re.findall(r'Coil \d', phrase)))
        self.assertTrue(phrase.endswith('and 2 more'))


if __name__ == '__main__':
    unittest.main()
