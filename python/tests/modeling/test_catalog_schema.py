"""Schema lint for data/systems.json — the catalog is a CLOSED, hand-maintained
vocabulary, so a typo'd key ('heating_coil_typ') or an invented value ('gas')
would otherwise sail through silently: builders read rows with ``[]``/``fetch``
defaults, so a misspelled key just means the default quietly wins.

The allowlists below were DERIVED FROM THE DATA as it stands (every key that
actually occurs in each family), then frozen. They are not aspirational — they
describe today's rows exactly. Adding a key to a row must therefore be a
CONSCIOUS act: add it here AND document it in lib/openstudio_hvac/data/README.md
(with its row count). Same for a new value in any closed vocabulary."""

import unittest
from collections import Counter

from btap.modeling.hvac import catalog

ROWS = catalog.rows()

# family => every key any row of that family may carry (frozen from the data)
FAMILY_KEYS = {
    'baseboards': ['baseboard_type', 'boiler_fuel', 'family', 'hw_source', 'name',
                   'needs_boiler', 'origin'],
    'composite': ['comment', 'family', 'name', 'needs_boiler', 'origin', 'parts'],
    'doas': ['comment', 'family', 'heating_type', 'name', 'needs_boiler', 'origin',
             'sizing'],
    'doas_pthp': ['comment', 'family', 'name', 'needs_boiler', 'origin', 'sizing',
                  'supp_htg_fuel', 'sys_abbr'],
    'ecm_ashp_baseboard': ['air_eqpt', 'baseboard_type', 'comment', 'family', 'name',
                           'needs_boiler', 'origin', 'sizing', 'supp_htg_fuel',
                           'sys_abbr', 'vent_type'],
    'ecm_doas_vrf': ['air_eqpt', 'comment', 'family', 'name', 'needs_boiler', 'origin',
                     'sizing', 'supp_htg_fuel', 'sys_abbr'],
    'ecm_hp_fancoils': ['air_eqpt', 'boiler_fuel', 'comment', 'family', 'name',
                        'needs_boiler', 'origin', 'plant_type', 'sizing',
                        'supp_htg_fuel', 'sys_abbr'],
    'evap_cooler': ['family', 'name', 'needs_boiler', 'origin'],
    'fan_coils': ['chiller_type', 'comment', 'family', 'fan_coil_type',
                  'mau_cooling_type', 'mau_heating_coil_type', 'name', 'needs_boiler',
                  'needs_chiller', 'sizing', 'sys_abbr'],
    'furnace': ['cooling', 'family', 'heating', 'name', 'needs_boiler', 'origin',
                'ventilation'],
    'mau_ptac': ['baseboard_type', 'comment', 'family', 'mau_heating_coil_type', 'name',
                 'needs_boiler', 'origin', 'reference_hp', 'sizing', 'supp_htg_fuel',
                 'sys_abbr'],
    # 'heat_source' is the reference-ASHP marker (was: heating_coil_type 'DX').
    'psz': ['baseboard_type', 'boiler_fuel', 'comment', 'family', 'heat_source',
            'heating_coil_type', 'name', 'needs_boiler', 'origin', 'per_zone', 'sizing',
            'supp_htg_fuel', 'sys_abbr'],
    'unit_heaters': ['family', 'heating_type', 'name', 'needs_boiler', 'origin'],
    'vav_reheat': ['baseboard_type', 'boiler_fuel', 'chiller_type', 'comment',
                   'cooling_type', 'family', 'heating_coil_type', 'name', 'needs_boiler',
                   'needs_chiller', 'origin', 'sizing', 'sys_abbr'],
    'vrf': ['comment', 'family', 'name', 'needs_boiler', 'origin', 'zone_ventilation'],
    'wshp': ['boiler_fuel', 'comment', 'family', 'name', 'needs_boiler', 'origin',
             'sizing', 'ventilation'],
    'zone_ervs': ['comment', 'family', 'name', 'needs_boiler', 'origin'],
    'zone_terminal': ['baseboard_type', 'boiler_fuel', 'comment', 'family',
                      'heating_type', 'name', 'needs_boiler', 'origin', 'unit_type'],
}

# Closed value vocabularies. Exact-match strings — case included (the dialects
# differ by source vocabulary: 'Gas' vs 'dx' vs 'ashp'; see data/README.md).
ENUMS = {
    'family': list(FAMILY_KEYS.keys()),
    'heating_coil_type': ['Gas', 'Electric', 'Hot Water'],  # 'DX' RETIRED -> heat_source
    'heat_source': ['ashp'],
    'baseboard_type': ['Hot Water', 'Electric', 'None'],
    'chiller_type': ['Scroll', 'Centrifugal', 'Rotary Screw', 'Reciprocating'],
    'mau_cooling_type': ['DX', 'Hydronic'],  # DX IS a real coil type here — cooling
    'unit_type': ['ptac', 'pthp', 'window_ac'],
    'origin': ['cbecs', 'generic', 'necb_ecm', 'necb_reference_hp'],
}


class TestCatalogSchema(unittest.TestCase):
    def test_every_family_has_an_allowlist(self):
        families = sorted({r['family'] for r in ROWS})
        self.assertEqual(
            sorted(FAMILY_KEYS.keys()), families,
            'a family appeared/disappeared in systems.json — add or remove its key '
            'allowlist here')

    def test_row_keys_are_allowlisted(self):
        for row in ROWS:
            allowed = FAMILY_KEYS[row['family']]
            unknown = [k for k in row if k not in allowed]
            self.assertEqual(
                unknown, [],
                f"'{row['name']}' ({row['family']}) carries unknown key(s) {unknown!r}. "
                'If deliberate: add them to FAMILY_KEYS here and to data/README.md.')

    def test_every_row_has_the_universal_keys(self):
        for row in ROWS:
            for key in ['name', 'family', 'needs_boiler']:
                self.assertIn(key, row,
                              f"'{row.get('name', row)!r}' is missing required key '{key}'")
            self.assertIsInstance(row['name'], str)
            self.assertIn(row['needs_boiler'], [True, False],
                          f"'{row['name']}': needs_boiler must be a boolean")

    def test_names_are_unique(self):
        names = [r['name'] for r in ROWS]
        duplicates = [n for n, c in Counter(names).items() if c > 1]
        self.assertEqual(duplicates, [], f"duplicate catalog names: {duplicates!r}")

    def test_closed_vocabularies(self):
        for row in ROWS:
            for key, allowed in ENUMS.items():
                if key not in row:
                    continue

                self.assertIn(
                    row[key], allowed,
                    f"'{row['name']}': {key} = {row[key]!r} is outside the closed "
                    f"vocabulary {allowed!r}")

    def test_sizing_blocks_resolve(self):
        blocks = catalog.sizing_blocks()
        for row in ROWS:
            if 'sizing' not in row:
                continue

            self.assertIn(row['sizing'], blocks,
                          f"'{row['name']}': sizing block '{row['sizing']}' is not in "
                          'sizing.json')

    # ---- the heat_source rename (the reference-ASHP marker) ----

    def test_reference_ashp_rows_carry_heat_source(self):
        ashp = [r for r in ROWS if r.get('heat_source') == 'ashp']
        self.assertEqual(8, len(ashp), 'expected the 8 psz sys3/sys4 reference-ASHP rows')
        for row in ashp:
            self.assertEqual('psz', row['family'],
                             f"'{row['name']}': heat_source is a psz-family key")
            self.assertEqual('necb_reference_hp', row['origin'],
                             f"'{row['name']}': heat_source rows are reference-HP rows")
            self.assertNotIn(
                'heating_coil_type', row,
                f"'{row['name']}': heat_source rows must NOT also carry heating_coil_type")
            self.assertIn(row['supp_htg_fuel'], ['Gas', 'Electric'],
                          f"'{row['name']}': an ASHP build needs a supplemental coil fuel")
        self.assertEqual(['sys_3', 'sys_4'],
                         sorted({r['sys_abbr'] for r in ashp}))

    def test_no_row_uses_dx_as_a_heating_coil_type(self):
        offenders = [r['name'] for r in ROWS if r.get('heating_coil_type') == 'DX']
        self.assertEqual(
            offenders, [],
            "'DX' is not a heating coil type — it was the old spelling of the "
            "reference-ASHP marker. Use heat_source: 'ashp'. "
            f"Offending rows: {offenders!r}")

    def test_reference_hp_flag_is_confined_to_mau_ptac(self):
        """mau_ptac keeps its own older marker by ruling — pinned so it neither spreads
        to other families nor silently disappears."""
        flagged = [r for r in ROWS if 'reference_hp' in r]
        self.assertEqual(4, len(flagged))
        self.assertTrue(all(r['family'] == 'mau_ptac' and r['reference_hp'] is True
                            for r in flagged))


if __name__ == '__main__':
    unittest.main()
