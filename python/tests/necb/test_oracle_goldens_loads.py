"""Leg-C acceptance for the LOADS domain (D-78): the ported code reproduced
against the oracle values FROZEN from the pinned openstudio-standards revision.

Legs A and B (gem vs live oracle, gem vs port) can agree and still both be
wrong; this leg compares Python directly to the oracle, so a bug faithfully
ported from Ruby still fails here. The goldens are
btap-necb/test/goldens/oracle/{loads_schedules,loads_apply,loads_merged_tables}.json,
exported by scripts/export_oracle_goldens.rb through the same probe code the
Ruby parity gates run (test/support/oracle_probes.rb).

The signature builders below are the Python port of OracleProbes::Signatures —
they must quantize exactly as the Ruby side did (``.round(n)`` -> ruby_round),
because the frozen numbers were produced by that rounding.

Key-set equality is asserted in BOTH directions everywhere: a comparison that
silently shrank would otherwise pass.

Tolerances follow the Ruby gates (test_loads_schedules_parity.rb,
test_loads_apply_parity.rb): both compare signatures for EXACT equality, the
quantization to 6 (schedules) / 9 (loads) decimal places being the tolerance.
"""

from __future__ import annotations

import json
import unittest

from tests.support import needs_sdk, oracle_goldens_dir

GOLDENS = oracle_goldens_dir()

#: OracleProbes::Loads::PAIRS — the space types the apply golden was frozen for.
PAIRS = [
    ['Space Function', 'Office enclosed > 25 m2'],
    ['Space Function', 'Corridor/Transition area other-sch-A'],
    ['Space Function', 'Dining area - family dining'],
    ['Space Function', 'Food preparation area'],
    ['Space Function', 'Warehouse storage area medium to bulky palletized items'],
    ['Space Function', 'Classroom/Lecture hall/Training room other'],
    ['Space Function', 'Computer/Server room-sch-A'],
]

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def golden(name):
    return json.loads((GOLDENS / f"{name}.json").read_text(encoding="utf-8"))


# ----------------------------------------------------- OracleProbes::Signatures
def optional_f(value, digits=9):
    from btap._compat import ruby_round
    return ruby_round(value.get(), digits) if value.is_initialized() else None


def optional_name(optional):
    return optional.get().nameString() if optional.is_initialized() else None


def day_values(day_schedule):
    import openstudio

    from btap._compat import ruby_round
    return [ruby_round(day_schedule.getValue(openstudio.Time(0, hour, 0, 0)), 6)
            for hour in range(1, 25)]


def rule_signature(rule):
    return {'days': [getattr(rule, f"apply{d}")() for d in DAYS],
            'values': day_values(rule.daySchedule()),
            'start': str(rule.startDate().get()) if rule.startDate().is_initialized() else None,
            'end': str(rule.endDate().get()) if rule.endDate().is_initialized() else None}


def ruleset_signature(schedule):
    ruleset = schedule.to_ScheduleRuleset()
    if not ruleset.is_initialized():
        return {'fallback': schedule.nameString()}

    ruleset = ruleset.get()
    return {
        'default': day_values(ruleset.defaultDaySchedule()),
        'winter': (None if ruleset.isWinterDesignDayScheduleDefaulted()
                   else day_values(ruleset.winterDesignDaySchedule())),
        'summer': (None if ruleset.isSummerDesignDayScheduleDefaulted()
                   else day_values(ruleset.summerDesignDaySchedule())),
        'rules': sorted((rule_signature(r) for r in ruleset.scheduleRules()),
                        key=lambda s: ''.join('1' if b else '0' for b in s['days'])),
    }


def loads_signature(space_type):
    """The 17-field per-space-type loads signature (loads-apply gate)."""
    from btap._compat import ruby_round
    people = space_type.people()[0] if space_type.people() else None
    equip = space_type.electricEquipment()[0] if space_type.electricEquipment() else None
    gas = space_type.gasEquipment()[0] if space_type.gasEquipment() else None
    dsoa = space_type.designSpecificationOutdoorAir()
    infiltrations = space_type.spaceInfiltrationDesignFlowRates()
    infiltration = infiltrations[0] if infiltrations else None
    schedule_set = space_type.defaultScheduleSet()
    return {
        'people_per_m2': (optional_f(people.peopleDefinition().peopleperSpaceFloorArea())
                          if people else None),
        'people_frac_radiant': (ruby_round(people.peopleDefinition().fractionRadiant(), 9)
                                if people else None),
        'epd_w_m2': (optional_f(equip.electricEquipmentDefinition().wattsperSpaceFloorArea())
                     if equip else None),
        'epd_frac_latent': (ruby_round(equip.electricEquipmentDefinition().fractionLatent(), 9)
                            if equip else None),
        'epd_frac_radiant': (ruby_round(equip.electricEquipmentDefinition().fractionRadiant(), 9)
                             if equip else None),
        'epd_frac_lost': (ruby_round(equip.electricEquipmentDefinition().fractionLost(), 9)
                          if equip else None),
        'gas_w_m2': (optional_f(gas.gasEquipmentDefinition().wattsperSpaceFloorArea())
                     if gas else None),
        'oa_method': dsoa.get().outdoorAirMethod() if dsoa.is_initialized() else None,
        'oa_per_area': (ruby_round(dsoa.get().outdoorAirFlowperFloorArea(), 9)
                        if dsoa.is_initialized() else None),
        'oa_per_person': (ruby_round(dsoa.get().outdoorAirFlowperPerson(), 9)
                          if dsoa.is_initialized() else None),
        'oa_ach': (ruby_round(dsoa.get().outdoorAirFlowAirChangesperHour(), 9)
                   if dsoa.is_initialized() else None),
        'infil_per_ext': (optional_f(infiltration.flowperExteriorSurfaceArea())
                          if infiltration else None),
        'infil_per_wall': (optional_f(infiltration.flowperExteriorWallArea())
                           if infiltration else None),
        'infil_ach': optional_f(infiltration.airChangesperHour()) if infiltration else None,
        'occ_sch': (optional_name(schedule_set.get().numberofPeopleSchedule())
                    if schedule_set.is_initialized() else None),
        'act_sch': (optional_name(schedule_set.get().peopleActivityLevelSchedule())
                    if schedule_set.is_initialized() else None),
        'equip_sch': (optional_name(schedule_set.get().electricEquipmentSchedule())
                      if schedule_set.is_initialized() else None),
    }


def thermostat_signature(model, name):
    t = next((x for x in model.getThermostatSetpointDualSetpoints()
              if x.nameString() == name), None)
    if t is None:
        return None
    return {'heating': optional_name(t.heatingSetpointTemperatureSchedule()),
            'cooling': optional_name(t.coolingSetpointTemperatureSchedule())}


@needs_sdk
class TestOracleGoldensLoads(unittest.TestCase):
    maxDiff = None

    def test_merged_tables_equal_the_vendored_data(self):
        """test_loads_data_integrity.rb#test_structural_equality_vs_legacy_merged_tables,
        against the FROZEN merged runtime tables instead of the live oracle."""
        from btap.necb import loads
        expected = golden('loads_merged_tables')
        self.assertEqual({'space_types', 'schedules'}, set(expected))
        self.assertEqual(308, len(expected['space_types']))
        self.assertEqual(240, len(expected['schedules']))

        space_types = loads.table('2020', 'space_types')
        schedules = loads.table('2020', 'schedules')
        self.assertEqual(len(expected['space_types']), len(space_types))
        self.assertEqual(len(expected['schedules']), len(schedules))
        # Key-set equality in BOTH directions, record by record.
        for oracle_row, row in zip(expected['space_types'], space_types, strict=True):
            self.assertEqual(set(oracle_row), set(row))
        for oracle_row, row in zip(expected['schedules'], schedules, strict=True):
            self.assertEqual(set(oracle_row), set(row))
        self.assertEqual(expected['space_types'], space_types,
                         'vendored space types == legacy MERGED runtime table')
        self.assertEqual(expected['schedules'], schedules,
                         'vendored schedules == legacy MERGED runtime table')

    def test_every_schedule_builds_identically_to_the_oracle(self):
        """test_loads_schedules_parity.rb, Leg C: EVERY unique name in the
        vendored 2020 table builds the same ruleset the oracle's
        model_add_schedule did — default day values, design days, rule
        day-of-week flags and dates."""
        import openstudio

        from btap.necb import loads
        expected = golden('loads_schedules')
        names = list(dict.fromkeys(r['name'] for r in loads.table('2020', 'schedules')))
        self.assertGreaterEqual(len(names), 85,
                                'the full catalog is compared (86 unique names over 240 rows)')
        self.assertEqual(86, len(expected))
        self.assertEqual(set(expected), set(names), 'golden key set == vendored name set')

        mismatches = []
        for name in names:
            model = openstudio.model.Model()
            schedule = loads.Schedules.add(model, name)
            if ruleset_signature(schedule) != expected[name]:
                mismatches.append(name)
        self.assertEqual([], mismatches, f"schedule parity mismatches: {mismatches[:10]}")

    def test_per_object_loads_and_thermostats_match_the_oracle(self):
        """test_loads_apply_parity.rb, Leg C: per-object load values match the
        oracle's space_type_apply_internal_loads(set_lights: false) +
        schedule/thermostat applies on identically tagged models."""
        import openstudio

        from btap.necb import loads
        expected = golden('loads_apply')
        pairs = [p for p in PAIRS
                 if loads.SpaceTypes.find(building_type=p[0], space_type=p[1])]
        self.assertGreaterEqual(len(pairs), 4,
                                f"enough real space types to compare ({pairs})")
        self.assertEqual(7, len(expected))
        self.assertEqual(set(expected), {f"{bt} {st}" for bt, st in pairs},
                         'golden key set == compared space-type set')

        model = openstudio.model.Model()
        for building_type, space_type in pairs:
            st = openstudio.model.SpaceType(model)
            st.setName(f"{building_type} {space_type}")
            st.setStandardsBuildingType(building_type)
            st.setStandardsSpaceType(space_type)
        loads.apply_loads(model, vintage='2020')

        mismatches = []
        for building_type, space_type_name in pairs:
            full = f"{building_type} {space_type_name}"
            gem_st = next(s for s in model.getSpaceTypes() if s.nameString() == full)
            signature = loads_signature(gem_st)
            oracle = expected[full]['loads']
            self.assertEqual(set(oracle), set(signature),
                             f"{full}: signature field set")
            if signature != oracle:
                diff = [f"{k}: python={signature[k]!r} oracle={oracle[k]!r}"
                        for k in signature if signature[k] != oracle[k]]
                mismatches.append(f"{space_type_name}: {'; '.join(diff)}")
        self.assertEqual([], mismatches,
                         "per-object parity mismatches:\n" + "\n".join(mismatches))

        # thermostat schedule parity
        for building_type, space_type_name in pairs:
            full = f"{building_type} {space_type_name} Thermostat"
            signature = thermostat_signature(model, full)
            oracle = expected[f"{building_type} {space_type_name}"]['thermostat']
            self.assertIsNotNone(signature, full)
            self.assertIsNotNone(oracle, full)
            self.assertEqual(oracle['heating'], signature['heating'], full)
            self.assertEqual(oracle['cooling'], signature['cooling'], full)


if __name__ == '__main__':
    unittest.main()
