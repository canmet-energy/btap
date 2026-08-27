"""P2 gate: NECB 2020 Table 8.4.4.7.-A selection rules, one test per rule, each
quoting the code text it implements. Pure logic — synthetic facts, no OpenStudio
model needed (but the catalog resolution test touches the SDK-free catalog)."""

from __future__ import annotations

import copy
import unittest

from btap.audit import AuditLog
from btap.modeling.hvac import catalog
from btap.necb import hvac


def group(zones=None, heated=True, cooled=True, heat_fuels=None,
          heat_pump=False, heat_pump_sources=None, cooling_kw=10.0,
          family=None, family_guess=None):
    return {'zones': zones or ['Z1'], 'air_loop': 'L1', 'family': family,
            'catalog_name': None, 'family_guess': family_guess,
            'heated': heated, 'cooled': cooled,
            'heating_energy_types': ['NaturalGas'] if heat_fuels is None else heat_fuels,
            'cooling_energy_types': ['Electricity'] if cooled else [],
            'heat_pump': heat_pump, 'heat_pump_sources': heat_pump_sources or [],
            'terminal_type': 'none', 'design_cooling_kw': cooling_kw, 'evidence': []}


def facts_for(*groups):
    return {'built_by_gem': False, 'zone_groups': list(groups), 'plants': [],
            'purchased_energy': {'heating': False, 'cooling': False}}


def select(groups, zone_types, storeys=1, audit=None, **building_extra):
    building = {'storeys': storeys, 'zone_types': zone_types}
    building.update(building_extra)
    return hvac.select_reference_systems(facts=facts_for(*groups), building=building,
                                         vintage='2020', audit=audit)


class TestNecbSelector(unittest.TestCase):

    # "General Area: office, banking, healthcare clinic, library, retail/mall ...
    #  Maximum 2 storeys -> System 3; More than 2 storeys -> System 6" (Table 8.4.4.7.-A)
    def test_general_area_storey_split(self):
        low = select([group()], {'Z1': 'Office - enclosed'}, storeys=2)[0]
        self.assertEqual(3, low.reference_system)
        high = select([group()], {'Z1': 'Office - enclosed'}, storeys=3)[0]
        self.assertEqual(6, high.reference_system)
        self.assertRegex(''.join(high.articles), r'8\.4\.4\.7')

    # "Assembly Area ... Maximum 4 storeys -> System 3; More than 4 storeys -> System 6"
    def test_assembly_area_storey_split(self):
        self.assertEqual(3, select([group()], {'Z1': 'Classroom/lecture/training'},
                                   storeys=4)[0].reference_system)
        self.assertEqual(6, select([group()], {'Z1': 'Classroom/lecture/training'},
                                   storeys=5)[0].reference_system)

    # "Data Processing Area ... Where the proposed building or space has a cooling capacity
    #  exceeding 20 kW, the reference building or space shall use System 2; otherwise ...
    #  System 1." (Table 8.4.4.7.-A)
    def test_data_centre_cooling_threshold(self):
        big = select([group(cooling_kw=25.0)], {'Z1': 'Data centre'})[0]
        self.assertEqual(2, big.reference_system)
        small = select([group(cooling_kw=15.0)], {'Z1': 'Data centre'})[0]
        self.assertEqual(1, small.reference_system)
        # exactly 20 kW does NOT exceed 20 kW
        at = select([group(cooling_kw=20.0)], {'Z1': 'Data centre'})[0]
        self.assertEqual(1, at.reference_system)

    def test_data_centre_unsized_warns_and_takes_smaller_branch(self):
        audit = AuditLog()
        a = select([group(cooling_kw=None)], {'Z1': 'Data centre'}, audit=audit)[0]
        self.assertEqual(1, a.reference_system)
        self.assertTrue(any('needs a sized model' in w['action'] for w in audit.warnings))

    # "Automotive Area: repair garage or storage garage ... All sizes -> System 4"
    def test_automotive_area(self):
        self.assertEqual(4, select([group()], {'Z1': 'Storage garage'})[0].reference_system)

    # "Warehouse Area ... All sizes of non-refrigerated space -> System 4;
    #  All sizes of refrigerated space -> System 5"
    def test_warehouse_refrigerated_split(self):
        dry = select([group()], {'Z1': 'Warehouse - med/blk'})[0]
        self.assertEqual(4, dry.reference_system)
        cold = select([group()], {'Z1': 'Warehouse - med/blk'}, refrigerated_zones=['Z1'])[0]
        self.assertEqual(5, cold.reference_system)

    # "Supermarket/Food Service Area ... food preparation without kitchen hood -> System 3;
    #  food preparation with kitchen hood or vented appliance -> System 4"
    def test_food_service_kitchen_hood_split(self):
        no_hood = select([group()], {'Z1': 'Food preparation'})[0]
        self.assertEqual(3, no_hood.reference_system)
        hooded = select([group()], {'Z1': 'Food preparation'}, kitchen_hood_zones=['Z1'])[0]
        self.assertEqual(4, hooded.reference_system)

    # "Residential/Accommodation Area ... Where the proposed building or space is heated
    #  only, the reference building or space shall use System 1."
    def test_residential_heated_only(self):
        a = select([group(heated=True, cooled=False, cooling_kw=0.0)],
                   {'Z1': 'Dwelling units general'})[0]
        self.assertEqual(1, a.reference_system)
        self.assertEqual('build', a.action)

    # "Where ... heated as well as being cooled with an air-cooled unitary, packaged
    #  terminal or room air conditioner (or heat pumps), or fan coils, the reference ...
    #  shall be modeled as being identical to that of the proposed building or space"
    def test_residential_compatible_cooling_copies_proposed(self):
        a = select([group(family='zone_terminal')], {'Z1': 'Hotel/Motel - rooms'})[0]
        self.assertEqual('copy_proposed', a.action)
        self.assertIsNone(a.catalog_name)

    # D-34 (A1 ruled follow-legacy): a residential group WITH a heat pump takes
    # the 8.4.4.7.(4) ASHP redirect — never the copy rule, even though its
    # cooling family would otherwise qualify as compatible.
    def test_residential_heat_pump_redirects_not_copies(self):
        a = select([group(heat_pump=True, family='zone_terminal')],
                   {'Z1': 'Multi-unit residential'})[0]
        self.assertEqual('build', a.action)
        self.assertEqual('hp', a.reference_system)

    # D-37 (A2 ruled: printed split per Note A-8.4.4.13): a water-LOOP heat pump
    # (internal loop, aux boiler/tower allowed) KEEPS its Table -A selection —
    # 8.4.4.13.(1). Only air/water/ground-SOURCE heat pumps redirect ((2)).
    def test_water_loop_heat_pump_keeps_table_a_selection(self):
        a = select([group(heat_pump=True, heat_pump_sources=['water_loop'], family='wshp')],
                   {'Z1': 'Office - enclosed'})[0]
        self.assertEqual(3, a.reference_system, 'WLHP office stays on the General Area row')

    def test_external_source_heat_pump_redirects(self):
        a = select([group(heat_pump=True, heat_pump_sources=['external'], family='wshp')],
                   {'Z1': 'Office - enclosed'})[0]
        self.assertEqual('hp', a.reference_system,
                         'ground/water-source HP takes the 8.4.4.13.(2) redirect')

    def test_mixed_hp_sources_redirect(self):
        a = select([group(heat_pump=True, heat_pump_sources=['water_loop', 'air'])],
                   {'Z1': 'Office - enclosed'})[0]
        self.assertEqual('hp', a.reference_system,
                         'any non-water-loop HP in the group triggers the redirect')

    def test_hp_without_source_evidence_still_redirects(self):
        a = select([group(heat_pump=True, heat_pump_sources=[])],
                   {'Z1': 'Office - enclosed'})[0]
        self.assertEqual('hp', a.reference_system,
                         'unclassifiable source keeps the conservative redirect')

    # D-37 + D-34 composition: a residential WATER-LOOP HP is not a redirecting
    # heat pump, so it falls to the Table -A residential rules — and 'wshp' is
    # compatible cooling -> reference identical to proposed.
    def test_residential_water_loop_hp_copies_proposed(self):
        a = select([group(heat_pump=True, heat_pump_sources=['water_loop'], family='wshp')],
                   {'Z1': 'Multi-unit residential'})[0]
        self.assertEqual('copy_proposed', a.action)

    # D-39 (A4 ruled conditional): Table -B System 5 heating "None" governs when
    # the proposed block is UNHEATED (cooling-only TPFC config); 8.4.4.1.(5)
    # overrides presence when the proposed block IS heated.
    def test_system5_unheated_proposed_builds_cooling_only(self):
        a = select([group(heated=False)], {'Z1': 'Warehouse - refrigerated'},
                   refrigerated_zones=['Z1'])[0]
        self.assertEqual(5, a.reference_system)
        self.assertEqual('none', a.config['heating'], 'Table -B "None" honoured')
        self.assertEqual(False, a.config['needs_boiler'])

    def test_system5_heated_proposed_keeps_heating(self):
        audit = AuditLog()
        a = select([group(heated=True)], {'Z1': 'Warehouse - refrigerated'},
                   refrigerated_zones=['Z1'], audit=audit)[0]
        self.assertEqual(5, a.reference_system)
        self.assertNotEqual('none', (a.config or {}).get('heating'),
                            '8.4.4.1.(5) presence override')
        self.assertTrue(any('8.4.4.1.(5)' in str(e.get('article') or '') for e in audit.entries))

    # "otherwise, the reference building or space shall use through-the-wall systems."
    def test_residential_otherwise_through_the_wall(self):
        a = select([group(family='vav_reheat', family_guess='multizone_vav')],
                   {'Z1': 'Multi-unit residential'})[0]
        self.assertEqual('through_the_wall', a.action)
        self.assertEqual(1, a.reference_system)

    # "Where the proposed building's HVAC system includes an air-source, water-source or
    #  ground-source heat pump ..., the reference building's HVAC system for that thermal
    #  block shall be an air-source heat pump described in Table 8.4.4.13." (8.4.4.13.(2))
    def test_heat_pump_override(self):
        a = select([group(heat_pump=True)], {'Z1': 'Office - enclosed'})[0]
        self.assertEqual('hp', a.reference_system)
        self.assertRegex(''.join(a.articles), r'8\.4\.4\.13')
        self.assertRegex(a.catalog_name, r'ASHP')

    # Table 8.4.4.13: "System 2 -> See Table 8.4.4.7.-B" (HP override does not apply)
    def test_heat_pump_does_not_override_system_2(self):
        a = select([group(heat_pump=True, cooling_kw=30.0)], {'Z1': 'Museum archives'})[0]
        self.assertEqual(2, a.reference_system)

    # 8.4.4.9.(4): "the energy type of the reference building's heating system shall be
    #  modeled as being identical to the energy type of the proposed building's heating system"
    def test_energy_type_follows_proposed(self):
        gas = select([group(heat_fuels=['NaturalGas'])], {'Z1': 'Office'})[0]
        self.assertEqual('gas', gas.energy_type)
        self.assertRegex(gas.catalog_name, r'Gas|Hot Water')
        elec = select([group(heat_fuels=['Electricity'])], {'Z1': 'Office'})[0]
        self.assertEqual('electric', elec.energy_type)
        self.assertRegex(elec.catalog_name, r'Electric')

    # 8.4.4.6.(1): "one gas-fired modulating boiler ... shall be used to represent the
    #  purchased energy equipment"
    def test_purchased_heating_becomes_gas(self):
        a = select([group(heat_fuels=['Purchased'])], {'Z1': 'Office'})[0]
        self.assertEqual('gas', a.energy_type)

    # 8.4.4.7.(3): "If the building or space type ... is not listed in Table 8.4.4.7.-A,
    #  the type that most closely corresponds ... shall be used" (default + warning)
    def test_unlisted_space_type_defaults_with_warning(self):
        audit = AuditLog()
        a = select([group()], {'Z1': 'Zamboni staging pit'}, audit=audit)[0]
        self.assertEqual('General Area', a.category)
        self.assertTrue(any('8.4.4.7.(3)' in str(w.get('article') or '')
                            for w in audit.warnings))

    def test_unconditioned_groups_get_no_assignment(self):
        a = select([group(heated=False, cooled=False, heat_fuels=[], cooling_kw=0.0)],
                   {'Z1': 'Office'})
        self.assertEqual([], a)

    # provenance lint: every selection rule block that sets a system carries article
    # citations at the file level, and all catalog names in system_definitions resolve
    def test_rules_provenance_and_catalog_names_resolve(self):
        rules = hvac.rules('2020')
        self.assertIn('8.4.4.7', rules['provenance']['articles'])
        for block in ('oversizing', 'heating_plant', 'furnace_staging', 'cooling_plant',
                      'dx_staging', 'fans', 'hydronic_pumps'):
            self.assertTrue(rules[block]['article'], f'{block} missing article citation')
        for key, defn in rules['system_definitions'].items():
            if key == 'table':
                continue

            for fuel in ('gas', 'electric'):
                name = defn[fuel]['name']
                self.assertTrue(catalog.resolve(name),
                                f'unresolvable catalog name for system {key}/{fuel}')

    # D-45 (Table 8.4.4.7.-A): "Historical Collections Area: archival library,
    # museum and gallery archives" is a COLLECTIONS row — the archives OF museums
    # and galleries. A museum's public exhibition gallery is the "exhibit space"
    # of the Assembly Area row. Both directions pinned, and pinned so they do NOT
    # depend on the order the categories happen to sit in the ruleset.
    def test_museum_exhibition_is_assembly_and_restoration_is_collections(self):
        audit = AuditLog()
        gallery = select([group(zones=['Z1'])],
                         {'Z1': 'Museum general exhibition area'}, audit=audit)
        self.assertEqual('Assembly Area', gallery[0].category)
        self.assertEqual(3, gallery[0].reference_system, 'exhibit space, <= 4 storeys -> System 3')

        restoration = select([group(zones=['Z1'])],
                             {'Z1': 'Museum restoration room'}, audit=audit)
        self.assertEqual('Historical Collections Area', restoration[0].category)
        self.assertEqual(2, restoration[0].reference_system, 'collections space -> System 2')

        # A convention exhibit hall is an exhibit space too, with no museum wording.
        convention = select([group(zones=['Z1'])], {'Z1': 'Convention centre exhibit space'})
        self.assertEqual('Assembly Area', convention[0].category)

        # Order-independence: the gallery must NOT rely on Assembly Area being
        # scanned before Historical Collections. Reverse the category list and the
        # answers must not move (the bare 'museum' keyword used to decide this).
        ruleset = copy.deepcopy(hvac.rules('2020'))
        ruleset['selection']['categories'].reverse()
        reversed_row = next(cat for cat in ruleset['selection']['categories']
                            if any(kw.lower() in 'museum general exhibition area'
                                   for kw in cat['keywords']))
        self.assertEqual('Assembly Area', reversed_row['category'],
                         'gallery still elects Assembly Area with the category list reversed')

        museum_notes = [e for e in audit.entries if e.get('ruling') == 'D-45']
        self.assertEqual(2, len(museum_notes),
                         'each museum election records which row it took')
        self.assertTrue(all(e.get('article') == '8.4.4.7.(1)' for e in museum_notes))


if __name__ == '__main__':
    unittest.main()
