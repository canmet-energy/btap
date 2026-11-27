"""A caller's `config` on a COMPOSITE row reaches the parts that read it, or is
refused — never silently dropped (#244).

Before this, `build_system(..., config=...)` merged the caller's keys into the
composite's own row, which builds nothing, and built every part with only the
part's `config`. So `per_zone`, a sizing block or a typo all built the
default. The rule is documented in `btap.modeling.hvac.builder` beside
`FAMILY_CONFIG_KEYS`.

SDK only; nothing here runs EnergyPlus.
"""

import re
import unittest
from pathlib import Path

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

SYSTEMS_DIR = (Path(__file__).resolve().parents[2]
               / 'src' / 'btap' / 'modeling' / 'hvac' / 'systems')


def _zones(model):
    from btap._compat import sorted_by_name
    return sorted_by_name(model.getThermalZones())


@needs_sdk
class TestCompositeConfigRouting(unittest.TestCase):

    def build(self, system, config=None, model=None, **kwargs):
        model = model or load_fixture()
        modeling.build_system(model, system, _zones(model), config=config, **kwargs)
        return model

    def test_an_accepted_key_reaches_the_part_that_reads_it(self):
        # `furnace` reads `per_zone` (default True: one loop per zone); the
        # baseboard part does not. Before #244 this built one loop per zone.
        default = self.build('splitac-dx-elecbb-nooa')
        shared = self.build('splitac-dx-elecbb-nooa', {'per_zone': False})
        zones = len(_zones(default))
        self.assertGreater(zones, 1)
        self.assertEqual(zones, len(default.getAirLoopHVACs()))
        self.assertEqual(1, len(shared.getAirLoopHVACs()),
                         'per_zone=False must reach the furnace part')
        self.assertEqual(zones, len(shared.getAirLoopHVACs()[0].thermalZones()))
        # ...and only that part: the baseboards are built as before.
        self.assertEqual(len(default.getZoneHVACBaseboardConvectiveElectrics()),
                         len(shared.getZoneHVACBaseboardConvectiveElectrics()))

    def test_the_callers_value_wins_over_the_parts_own_config(self):
        # The part says `heat_rejection: cooling_tower`; the caller says ground.
        model = self.build('doas-wshp-elec-gasboiler-tower',
                           {'heat_rejection': 'ground'})
        self.assertEqual(0, len(model.getCoolingTowerSingleSpeeds()))
        self.assertEqual(1, len(model.getGroundHeatExchangerVerticals()))

    def test_a_plant_key_reaches_a_part_whose_family_reads_it(self):
        # `wshp` builds its own loop boiler from `boiler_fuel` although the
        # row has no hot-water plant; the old plant routing dropped it.
        model = self.build('doas-wshp-elec-gasboiler-fluidcooler',
                           {'boiler_fuel': 'Electricity'})
        fuels = sorted(b.fuelType() for b in model.getBoilerHotWaters())
        self.assertEqual(['Electricity'], fuels)

    def test_a_key_no_part_reads_is_refused(self):
        for system, config in (
                ('splitac-dx-elecbb-nooa', {'no_such_option': 1}),
                # neither an evaporative cooler nor a baseboard reads per_zone
                ('evap-elecbb', {'per_zone': False}),
                # identity and plant structure are what the composite IS
                ('evap-elecbb', {'needs_boiler': True}),
                ('doas-vrf-elec', {'id': 'vrf'})):
            with self.subTest(system=system, config=config):
                with self.assertRaises(ValueError):
                    self.build(system, config)

    def test_a_refused_build_leaves_the_existing_system_intact(self):
        model = self.build('splitac-dx-elecbb-nooa')
        loops = len(model.getAirLoopHVACs())
        baseboards = len(model.getZoneHVACBaseboardConvectiveElectrics())
        with self.assertRaises(ValueError):
            modeling.build_system(model, 'evap-elecbb', _zones(model),
                                  remove_existing=True,
                                  config={'per_zone': False})
        self.assertEqual(loops, len(model.getAirLoopHVACs()),
                         'the refusal must come before the teardown')
        self.assertEqual(baseboards,
                         len(model.getZoneHVACBaseboardConvectiveElectrics()))

    def test_a_zone_erv_is_built_once_per_zone_not_once_per_part(self):
        model = self.build('splitac-dx-elecbb-nooa', {'needs_zone_erv': True})
        self.assertEqual(len(_zones(model)),
                         len(model.getZoneHVACEnergyRecoveryVentilators()))


class TestStructureKeysAreRefusedEvenWhereAPartReadsThem(unittest.TestCase):
    """Rule 3, witnessed where it is the ONLY thing refusing: `dual_duct`
    reads `needs_boiler`, so without the identity/structure refusal a
    composite holding one would route it there. No shipped composite does,
    which is why this uses a synthetic one; no model is built."""

    def test_needs_boiler_is_refused_on_a_composite(self):
        from btap.modeling.hvac import builder

        composite = {'id': 'synthetic', 'family': 'composite',
                     'parts': [{'id': 'ddvav-hw-gasboiler-scrollchiller'}]}
        self.assertIn('needs_boiler', builder.FAMILY_CONFIG_KEYS['dual_duct'])
        with self.assertRaises(ValueError):
            builder._route_composite_config(composite, {'needs_boiler': False})
        # ...while a key the part reads does reach it.
        routed = builder._route_composite_config(composite, {'sys_abbr': 'x'})
        self.assertEqual({'sys_abbr': 'x'}, routed['parts'][0]['config'])


class _Recording(dict):
    """A config that records every key its reader asks for."""

    def __init__(self, data, sink):
        super().__init__(data)
        self._sink = sink

    def __getitem__(self, key):
        self._sink.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._sink.add(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._sink.add(key)
        return super().__contains__(key)



#: `config.get('x'`, `config['x'`, and helpers called as `fn(self.config, 'x'`.
_LITERAL_READ = re.compile(r"config(?:\.get\(|\[|,)\s*'(\w+)'")
#: `sizing` is read through `BaseSystem.sizing` and its `apply_*` helpers.
_SIZING_READ = re.compile(
    r'self\.sizing\b|apply_(?:system|zone|doas_zone)_sizing|match_central_heating_to_zones')


def _module_reads(module):
    source = (SYSTEMS_DIR / f'{module}.py').read_text(encoding='utf-8')
    reads = set(_LITERAL_READ.findall(source))
    if _SIZING_READ.search(source):
        reads.add('sizing')
    return reads


class TestFamilyConfigKeysAreWhatBuildersRead(unittest.TestCase):
    """`FAMILY_CONFIG_KEYS` is a declaration; these hold it to the builders.

    A builder reading a key the table does not declare is exactly the silent
    drop #244 fixed, reintroduced for that key; a declared key nothing reads
    would let a composite accept a key and then ignore it.
    """

    def test_every_literal_read_in_a_family_module_is_declared(self):
        from btap.modeling.hvac import builder

        for family, (module, _cls) in builder.FAMILIES.items():
            with self.subTest(family=family):
                undeclared = (_module_reads(module) - {'id'}
                              - builder.FAMILY_CONFIG_KEYS[family])
                self.assertEqual(set(), undeclared)

    def test_every_declared_key_is_read(self):
        from btap.modeling.hvac import builder

        for family, (module, _cls) in builder.FAMILIES.items():
            with self.subTest(family=family):
                unread = (builder.FAMILY_CONFIG_KEYS[family] - _module_reads(module)
                          - builder._CENTRAL_ERV_KEYS)
                self.assertEqual(set(), unread)


def _recorded_reads(family):
    """Build every catalogue row of `family` with a recording config, and
    return the keys its builder class asked for. Run, not parsed: this sees
    reads through helpers in other modules, which the source scan cannot."""
    from btap.modeling.hvac import builder, catalog

    original = builder._system_class
    reads = set()

    def recording(name):
        cls = original(name)
        if cls is None:
            return None

        class Recorded(cls):
            def __init__(self, config, *args, **kwargs):
                super().__init__(_Recording(config, reads), *args, **kwargs)
        return Recorded

    builder._system_class = recording
    try:
        built = 0
        for row in catalog.rows():
            if row['family'] != family:
                continue
            model = load_fixture()
            modeling.build_system(model, row['id'], _zones(model))
            built += 1
    finally:
        builder._system_class = original
    return built, reads


@needs_sdk
class TestEveryKeyReadWhileBuildingIsDeclared(unittest.TestCase):
    """One test per family, so xdist can spread the ~100 builds."""


def _make_family_test(family):
    def test(self):
        from btap.modeling.hvac import builder

        built, reads = _recorded_reads(family)
        self.assertGreater(built, 0, 'the probe must have built something')
        self.assertEqual(set(), reads - {'id'} - builder.FAMILY_CONFIG_KEYS[family])
    return test


def _catalogue_families():
    from btap.modeling.hvac import catalog
    return sorted({r['family'] for r in catalog.rows()} - {'composite'})


for _family in _catalogue_families():
    setattr(TestEveryKeyReadWhileBuildingIsDeclared,
            f'test_{_family}_reads_only_declared_keys',
            _make_family_test(_family))


if __name__ == '__main__':
    unittest.main()
