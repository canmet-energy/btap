"""The loads pass — port of the legacy NECB space_type_apply_internal_loads
(beps_compliance_path.rb) MINUS lights (the lighting domain's territory) and
of the parent space_type_apply_internal_load_schedules /
space_type_apply_thermostat_schedules (Standards.SpaceType.rb), against the
vendored data. Unit conversions are legacy-exact (data is IP; see the data
provenance block).
"""

from __future__ import annotations

import openstudio

from btap._compat import ruby_round, sorted_by_name
from btap.audit import AuditLog, emit_coverage
from btap.necb import loads as _loads
from btap.necb.loads import schedules as Schedules
from btap.necb.loads import space_types as SpaceTypes


def _f(value):
    """Ruby ``.to_f``: nil -> 0.0, numeric/string -> Float."""
    if value is None:
        return 0.0
    return float(value)


def _s(value):
    """Ruby ``.to_s``: nil -> ''."""
    return '' if value is None else str(value)


def assign_space_types(model, map, vintage='2020', audit=None):
    """Bare-geometry on-ramp: create/tag NECB space types and assign spaces.

    :param map: {space name -> [building_type, space_type]} (the pair must
        exist in the vendored data)
    """
    if audit is None:
        audit = AuditLog()
    cache = {}
    assigned = 0
    for space in sorted_by_name(model.getSpaces()):
        pair = map.get(space.nameString())
        if pair is None:
            continue

        record = SpaceTypes.record(building_type=pair[0], space_type=pair[1],
                                   vintage=vintage)
        key = tuple(pair)
        space_type = cache.get(key)
        if space_type is None:
            st = openstudio.model.SpaceType(model)
            st.setName(f"{pair[0]} {pair[1]}")
            st.setStandardsBuildingType(record['building_type'])
            st.setStandardsSpaceType(record['space_type'])
            space_type = cache[key] = st
        space.setSpaceType(space_type)
        assigned += 1
    unmapped = [s.nameString() for s in model.getSpaces()
                if s.nameString() not in map]
    audit.decision('loads', 'NECB space types assigned',
                   inputs={'spaces_assigned': assigned,
                           'space_types_created': len(cache),
                           'vintage': vintage})
    if unmapped:
        audit.warn('loads',
                   'spaces with no space-type mapping (no loads will be applied): '
                   + ', '.join(unmapped))
    return audit


def apply_loads(model, vintage='2020', audit=None):
    """Apply NECB internal loads + schedules + thermostats to every tagged space
    type in the model. NO Lights, NO service water heating (sibling gems)."""
    if audit is None:
        audit = AuditLog()
    rules = _loads.rules(vintage)
    prefix = rules['schedule_table_prefix']
    applied = 0

    for space_type in sorted_by_name(model.getSpaceTypes()):
        result = _apply_to_space_type(model, space_type, vintage, prefix, audit)
        if result:
            applied += 1
    audit.decision('loads', 'NECB internal loads applied (people, plug/gas equipment, '
                            'ventilation OA, modelling infiltration, schedules, thermostats '
                            '— lighting and SHW excluded by scope)',
                   inputs={'space_types_applied': applied, 'vintage': vintage},
                   article='8.4.3.2.(1)-(2)')
    _assign_zone_thermostats(model, audit)
    _emit_article_coverage(vintage, audit)
    return audit


def _apply_to_space_type(model, space_type, vintage, prefix, audit):
    name = space_type.nameString()
    standards_space_type = space_type.standardsSpaceType()
    if ('plenum' in name.lower()
            or (standards_space_type.is_initialized()
                and 'plenum' in standards_space_type.get().lower())):
        audit.info('loads', 'plenum space type skipped (legacy behavior)', target=name)
        return False

    building_type = (space_type.standardsBuildingType().get()
                     if space_type.standardsBuildingType().is_initialized() else None)
    standards_type = (standards_space_type.get()
                      if standards_space_type.is_initialized() else None)
    record = SpaceTypes.find(building_type=building_type, space_type=standards_type,
                             vintage=vintage)
    if record is None:
        audit.warn('loads', f"space type not in the NECB {vintage} data (standards tags "
                            f"[{_inspect(building_type)}, {_inspect(standards_type)}]) — "
                            'no loads applied', target=name)
        return False
    if SpaceTypes.is_undefined(record):
        audit.info('loads', "'- undefined -' space type — no loads applied (legacy behavior)",
                   target=name)
        return False

    apply_people(space_type, record, audit)
    apply_equipment(space_type, record, audit)
    _apply_ventilation(space_type, record, prefix, audit)
    _apply_infiltration(space_type, record, audit)
    apply_schedule_set(model, space_type, record, vintage, audit)
    apply_thermostat(model, space_type, record, vintage, audit)
    return True


def _inspect(value):
    """Ruby ``String#inspect`` / ``nil.inspect`` for the audit message."""
    return 'nil' if value is None else f'"{value}"'


def apply_people(space_type, record, audit):
    """People: people/1000ft2 -> people/m2, FractionRadiant 0.3, comfort schedules."""
    occupancy_per_area = _f(record['occupancy_per_area'])
    if occupancy_per_area == 0:
        return

    def create():
        definition = openstudio.model.PeopleDefinition(space_type.model())
        definition.setName(f"{space_type.nameString()} People Definition")
        people = openstudio.model.People(definition)
        people.setName(f"{space_type.nameString()} People")
        people.setSpaceType(space_type)
        return people

    instance = _single_instance(space_type.people(), audit, create)
    definition = instance.peopleDefinition()
    definition.setPeopleperSpaceFloorArea(
        openstudio.convert(occupancy_per_area / 1000, 'people/ft^2', 'people/m^2').get())
    definition.setFractionRadiant(0.3)
    instance.setClothingInsulationSchedule(_comfort_schedule(space_type.model(), 'clothing'))
    instance.setAirVelocitySchedule(_comfort_schedule(space_type.model(), 'air_velocity'))
    instance.setWorkEfficiencySchedule(_comfort_schedule(space_type.model(), 'work_efficiency'))
    audit.info('loads', 'people set', target=space_type.nameString(),
               inputs={'occupancy_per_1000ft2': occupancy_per_area, 'fraction_radiant': 0.3},
               article='8.4.3.2.(2)')


def apply_equipment(space_type, record, audit):
    """Electric (W/ft2) and gas (Btu/hr.ft2) equipment with latent/radiant/lost
    fractions."""
    electric = _f(record['electric_equipment_per_area'])
    if electric != 0:
        def create_electric():
            definition = openstudio.model.ElectricEquipmentDefinition(space_type.model())
            definition.setName(f"{space_type.nameString()} Elec Equip Definition")
            equip = openstudio.model.ElectricEquipment(definition)
            equip.setName(f"{space_type.nameString()} Elec Equip")
            equip.setSpaceType(space_type)
            return equip

        instance = _single_instance(space_type.electricEquipment(), audit, create_electric)
        definition = instance.electricEquipmentDefinition()
        definition.setWattsperSpaceFloorArea(
            openstudio.convert(electric, 'W/ft^2', 'W/m^2').get())
        _set_fractions(definition, record, 'electric_equipment')
        audit.info('loads', 'electric equipment set', target=space_type.nameString(),
                   inputs={'w_per_ft2': electric}, article='8.4.3.2.(2)')

    gas = _f(record['gas_equipment_per_area'])
    if gas == 0:
        return

    def create_gas():
        definition = openstudio.model.GasEquipmentDefinition(space_type.model())
        definition.setName(f"{space_type.nameString()} Gas Equip Definition")
        equip = openstudio.model.GasEquipment(definition)
        equip.setName(f"{space_type.nameString()} Gas Equip")
        equip.setSpaceType(space_type)
        return equip

    instance = _single_instance(space_type.gasEquipment(), audit, create_gas)
    definition = instance.gasEquipmentDefinition()
    definition.setWattsperSpaceFloorArea(
        openstudio.convert(gas, 'Btu/hr*ft^2', 'W/m^2').get())
    _set_fractions(definition, record, 'gas_equipment')
    audit.info('loads', 'gas equipment set', target=space_type.nameString(),
               inputs={'btu_hr_ft2': gas}, article='8.4.3.2.(2)')


def _apply_ventilation(space_type, record, prefix, audit):
    """DesignSpecificationOutdoorAir (method Sum) with the legacy per-person
    RESCALE: the ventilation standard's occupant density differs from NECB's,
    so per-person is scaled by (ventilation occupancy)/(NECB occupancy) so the
    summed OA total matches the ventilation-standard intent at NECB occupancy."""
    per_area = _f(record['ventilation_per_area'])
    per_person = _f(record['ventilation_per_person'])
    ach = _f(record['ventilation_air_changes'])
    vent_occupancy = _f(record['ventilation_occupancy_rate_people_per_1000ft2'])
    occupancy_per_area = _f(record['occupancy_per_area'])

    ventilation = space_type.designSpecificationOutdoorAir()
    if ventilation.is_initialized():
        ventilation = ventilation.get()
    else:
        dsoa = openstudio.model.DesignSpecificationOutdoorAir(space_type.model())
        dsoa.setName(f"{space_type.nameString()} Ventilation")
        space_type.setDesignSpecificationOutdoorAir(dsoa)
        ventilation = dsoa

    if per_area == 0 and per_person == 0 and ach == 0:
        # every space type needs a DSOA (zeros) for ventilation controls
        ventilation.setOutdoorAirFlowperFloorArea(0)
        ventilation.setOutdoorAirFlowperPerson(0)
        ventilation.setOutdoorAirFlowAirChangesperHour(0)
        audit.info('loads', 'no ventilation data — zero DSOA created (required for OA controls)',
                   target=space_type.nameString())
        return

    ventilation.setOutdoorAirMethod('Sum')
    if per_area != 0:
        ventilation.setOutdoorAirFlowperFloorArea(
            openstudio.convert(per_area, 'ft^3/min*ft^2', 'm^3/s*m^2').get())
    mod_per_person = None
    if per_person != 0:
        mod_per_person = per_person * vent_occupancy / occupancy_per_area
        ventilation.setOutdoorAirFlowperPerson(
            openstudio.convert(mod_per_person, 'ft^3/min*person', 'm^3/s*person').get())
    if ach != 0:
        ventilation.setOutdoorAirFlowAirChangesperHour(ach)

    notes = ventilation.additionalProperties()
    notes.setFeature('Ref OA per area', per_area)
    notes.setFeature('Ref OA per person', per_person)
    notes.setFeature('Ref OA ach', ach)
    notes.setFeature('Ref occupancy per 1000ft2', vent_occupancy)
    notes.setFeature('Ref standard', _s(record['ventilation_occupancy_standard']))
    notes.setFeature('Ref space type', _s(record['ventilation_standard_space_type']))

    audit.info('loads', 'ventilation outdoor air set',
               target=space_type.nameString(),
               inputs={'cfm_per_ft2': per_area, 'cfm_per_person_standard': per_person,
                       'cfm_per_person_rescaled':
                           None if mod_per_person is None else ruby_round(mod_per_person, 4),
                       'ach': ach,
                       'ventilation_standard': record['ventilation_standard']},
               value=None if per_person == 0 else
               'per-person rescaled x (standard occupancy / NECB occupancy) so summed OA '
               'matches the standard at NECB density',
               article=f"8.4.3.2.(1)-(2); OA basis {record['ventilation_standard']}")


def _apply_infiltration(space_type, record, audit):
    """Space-type modelling infiltration (NOT the envelope domain's 8.4.3.3
    air-leakage rule)."""
    per_ext_area = _f(record['infiltration_per_exterior_area'])
    per_ext_wall = _f(record['infiltration_per_exterior_wall_area'])
    ach = _f(record['infiltration_air_changes'])
    if per_ext_area == 0 and per_ext_wall == 0 and ach == 0:
        return

    def create():
        infiltration = openstudio.model.SpaceInfiltrationDesignFlowRate(space_type.model())
        infiltration.setName(f"{space_type.nameString()} Infiltration")
        infiltration.setSpaceType(space_type)
        return infiltration

    instance = _single_instance(space_type.spaceInfiltrationDesignFlowRates(), audit, create)
    if per_ext_area != 0:
        instance.setFlowperExteriorSurfaceArea(
            openstudio.convert(per_ext_area, 'ft^3/min*ft^2', 'm^3/s*m^2').get())
    if per_ext_wall != 0:
        instance.setFlowperExteriorWallArea(
            openstudio.convert(per_ext_wall, 'ft^3/min*ft^2', 'm^3/s*m^2').get())
    if ach != 0:
        instance.setAirChangesperHour(ach)
    schedule_name = record['infiltration_schedule']
    if schedule_name is not None:  # Ruby truthiness: only nil/false are falsy
        instance.setSchedule(Schedules.add(space_type.model(), schedule_name, audit=audit))
    audit.info('loads',
               'space-type modelling infiltration set (distinct from envelope 8.4.3.3 air leakage)',
               target=space_type.nameString(),
               inputs={'cfm_per_ft2_exterior': per_ext_area,
                       'cfm_per_ft2_ext_wall': per_ext_wall, 'ach': ach})


def apply_schedule_set(model, space_type, record, vintage, audit):
    """DefaultScheduleSet wiring: occupancy + activity + equipment (NOT lighting)."""
    if space_type.defaultScheduleSet().is_initialized():
        schedule_set = space_type.defaultScheduleSet().get()
    else:
        schedule_set = openstudio.model.DefaultScheduleSet(model)
        schedule_set.setName(f"{space_type.nameString()} Schedule Set")
        space_type.setDefaultScheduleSet(schedule_set)

    def wire(key, setter):
        name = record[key]
        if name is None:
            return
        getattr(schedule_set, setter)(
            Schedules.add(model, name, vintage=vintage, audit=audit))

    wire('occupancy_schedule', 'setNumberofPeopleSchedule')
    wire('occupancy_activity_schedule', 'setPeopleActivityLevelSchedule')
    wire('electric_equipment_schedule', 'setElectricEquipmentSchedule')
    wire('gas_equipment_schedule', 'setGasEquipmentSchedule')
    audit.info('loads',
               f"schedule set wired (letter {record['necb_schedule_type']}; "
               'lighting schedule excluded by scope)',
               target=space_type.nameString(), article='8.4.3.2.(1)')


def apply_thermostat(model, space_type, record, vintage, audit):
    """A dual-setpoint thermostat per space type from the setpoint schedules
    (legacy: created unattached; _assign_zone_thermostats hooks zones lacking one)."""
    wanted = f"{space_type.nameString()} Thermostat"
    existing = next((t for t in model.getThermostatSetpointDualSetpoints()
                     if t.nameString() == wanted), None)
    if existing is not None:
        return

    thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
    thermostat.setName(wanted)
    heating = record['heating_setpoint_schedule']
    cooling = record['cooling_setpoint_schedule']
    if heating is not None:  # Ruby truthiness: only nil/false are falsy
        thermostat.setHeatingSetpointTemperatureSchedule(
            Schedules.add(model, heating, vintage=vintage, audit=audit))
    if cooling is not None:
        thermostat.setCoolingSetpointTemperatureSchedule(
            Schedules.add(model, cooling, vintage=vintage, audit=audit))
    audit.info('loads', 'space-type thermostat created', target=space_type.nameString(),
               inputs={'heating': heating, 'cooling': cooling}, article='8.4.3.2.(1)')


def _assign_zone_thermostats(model, audit):
    """Zones without a thermostat get their (dominant) space type's thermostat —
    makes bare-geometry models simulable; never overwrites an existing one."""
    hooked = 0
    for zone in sorted_by_name(model.getThermalZones()):
        if zone.thermostatSetpointDualSetpoint().is_initialized():
            continue

        spaces = zone.spaces()
        space = min(spaces, key=lambda s: s.nameString()) if spaces else None
        if space is None or not space.spaceType().is_initialized():
            continue

        name = f"{space.spaceType().get().nameString()} Thermostat"
        thermostat = next((t for t in model.getThermostatSetpointDualSetpoints()
                           if t.nameString() == name), None)
        if thermostat is None:
            continue

        zone.setThermostatSetpointDualSetpoint(thermostat)
        hooked += 1
    if hooked > 0:
        audit.info('loads', 'space-type thermostats assigned to zones lacking one',
                   inputs={'zones': hooked})


def _emit_article_coverage(vintage, audit):
    emit_coverage(_loads.rules(vintage)['article_coverage'], audit)


def _single_instance(instances, audit, create):
    """Ruby's block form: ``create`` is the block that builds the first instance."""
    instances = sorted(instances)
    if not instances:
        return create()
    for extra in instances[1:]:
        audit.info('loads', f"removed duplicate load instance {extra.nameString()}")
        extra.remove()
    return instances[0]


def _set_fractions(definition, record, key):
    latent = _f(record[f"{key}_fraction_latent"])
    radiant = _f(record[f"{key}_fraction_radiant"])
    lost = _f(record[f"{key}_fraction_lost"])
    if latent != 0:
        definition.setFractionLatent(latent)
    if radiant != 0:
        definition.setFractionRadiant(radiant)
    if lost != 0:
        definition.setFractionLost(lost)


COMFORT_SCHEDULES = {
    'clothing': 'Clothing Schedule', 'air_velocity': 'Air Velocity Schedule',
    'work_efficiency': 'Work Efficiency Schedule',
}


def _comfort_schedule(model, kind):
    name = COMFORT_SCHEDULES[kind]
    existing = model.getScheduleRulesetByName(name)
    if existing.is_initialized():
        return existing.get()

    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName(name)
    if kind == 'clothing':
        schedule.defaultDaySchedule().setName('Clothing Schedule Default Winter Clothes')
        schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 1.0)
        rule = openstudio.model.ScheduleRule(schedule)
        rule.daySchedule().setName('Clothing Schedule Summer Clothes')
        rule.daySchedule().addValue(openstudio.Time(0, 24, 0, 0), 0.5)
        rule.setStartDate(openstudio.Date(openstudio.MonthOfYear(5), 1))
        rule.setEndDate(openstudio.Date(openstudio.MonthOfYear(9), 30))
    elif kind == 'air_velocity':
        schedule.defaultDaySchedule().setName('Air Velocity Schedule Default')
        schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 0.2)
    elif kind == 'work_efficiency':
        schedule.defaultDaySchedule().setName('Work Efficiency Schedule Default')
        schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), 0)
    return schedule
