"""Characterize ANY model's HVAC into a neutral facts dict — the inverse of the builder.

Works on arbitrary OSMs (structural loop-composition walk); gem-built systems are
recognized exactly via their air-loop names (default namer stamps the catalog name,
legacy NECB models are recognized by their sys_N pipe names).

The facts schema is a serializable contract consumed by NECB reference selection
(Table 8.4.4.7.-A needs heated/cooled, energy types, heat pumps, purchased energy,
cooling capacity) and by costing of foreign models.

    {
      'built_by_gem': True|False,
      'zone_groups': [
        { 'zones': ['Zone 1', ...], 'air_loop': 'name'|None,
          'family': 'psz'|None, 'catalog_name': 'PSZ RTU ...'|None,
          'family_guess': 'multizone_vav'|...,
          'heated': True, 'cooled': False,
          'heating_energy_types': ['NaturalGas'], 'cooling_energy_types': ['Electricity'],
          'heat_pump': False, 'heat_pump_sources': ['air'|'water_loop'|'external'],
          'nonplant_heat_pump': False,
          'heating_capable_plant_heat_pump': False,
          'unpaired_cooling_plant_heat_pumps': ['Cooling HP'],
          'terminal_type': 'vav_reheat'|'dual_duct_vav'|'cv_reheat'|'cv'|'none',
          'cooling_plants': ['Chilled Water Loop'],
          'design_cooling_kw': 42.0|None,
          'dcv': False, 'system_outdoor_air_method': 'ZoneSum'|None } ],
      'plants': [ { 'name':, 'type': 'hot_water'|'chilled_water'|'condenser'|'service_water'|'other',
                    'fuels': ['NaturalGas'],
                    'fuel_capacities_w': {'NaturalGas': 176000.0, 'Electricity': None},
                    'purchased': False, 'heat_pump': False,
                    'heat_pump_modes': ['heating'|'cooling'],
                    'heating_capable_heat_pump': False,
                    'unpaired_cooling_heat_pumps': ['Cooling HP'],
                    'chiller_types': ['electric_eir'|'absorption'|...] } ],
      'purchased_energy': { 'heating': False, 'cooling': False }
    }
"""

from __future__ import annotations

import re

from btap._compat import opt, sorted_by_name
from btap.modeling.hvac import catalog, equipment_class
from btap.modeling.hvac.components import coils
from btap.modeling.hvac.systems.plant_loops import DISTRICT_HEATING_TYPES

# Legacy NECB pipe-name prefix -> gem family (sys_2/5 are fan-coil systems, sys_1/4 MAU-based).
PIPE_NAME_FAMILIES = {
    'sys_1': 'mau_ptac', 'sys_2': 'fan_coils', 'sys_3': 'psz',
    'sys_4': 'psz', 'sys_5': 'fan_coils', 'sys_6': 'vav_reheat',
}


def _try_cast(obj, cast):
    """Ruby's duck-typed downcast probe, `respond_to?(cast) ? obj.send(cast) : nil`
    unwrapped: the downcast value, or None when the method is absent, the Optional
    is empty, or the receiver itself is None."""
    if obj is None or not hasattr(obj, cast):
        return None
    return opt(getattr(obj, cast)())


def _array(x):
    """Ruby Array(): Array(nil) == [], Array([a]) == [a], Array(x) == [x]."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _union(existing, additions):
    """Ruby's `list |= additions` in place (order-preserving set union)."""
    for item in additions:
        if item not in existing:
            existing.append(item)


def characterize(model, audit=None):
    """Characterize a model's HVAC into the neutral facts dict (schema above).

    :param model: openstudio.model.Model — any model (gem-built or foreign)
    :param audit: AuditLog or None
    :return: dict facts — { 'built_by_gem':, 'zone_groups': [...], 'plants': [...],
        'purchased_energy': { 'heating':, 'cooling': } } (see the module docstring)
    """
    plants = [_plant_facts(loop, audit) for loop in sorted_by_name(model.getPlantLoops())]
    plant_by_name = {p['name']: p for p in plants}
    _annotate_heat_pump_plants(model, plant_by_name)
    _annotate_absorption_chiller_plants(model, plant_by_name)

    groups = []
    served = {}
    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        group = _air_loop_group(air_loop, plant_by_name, audit)
        for z in air_loop.thermalZones():
            served[z.nameString()] = group
        groups.append(group)

    # zones without an air loop: zonal-equipment-only (or unconditioned) singleton groups
    for zone in sorted_by_name(model.getThermalZones()):
        group = served.get(zone.nameString())
        if group is not None:
            _merge_zonal_equipment(group, zone, plant_by_name, audit)
        else:
            groups.append(_zonal_group(zone, plant_by_name, audit))

    for group in groups:
        if not group['cooled']:
            group['design_cooling_kw'] = 0.0
        elif not group.pop('cooling_capacity_complete'):
            group['design_cooling_kw'] = None
            if audit is not None:
                audit.warn('characterize',
                           'cooling capacity unsized — design_cooling_kw unavailable (run a sizing run for kW-threshold rules)',
                           target=group['air_loop'] or group['zones'][0])
        group.pop('cooling_capacity_complete', None)

    # HP SOURCE loops are excluded from purchased-energy detection: a district
    # object standing in for a ground field / condenser water (the legacy
    # GLHX pattern) is not purchased heating for the building (D-58).
    hvac_plants = [p for p in plants
                   if not (p['type'] == 'service_water' or p.get('hp_source_loop'))]
    facts = {
        'built_by_gem': bool(groups) and all(
            g['air_loop'] is None or g['catalog_name'] is not None for g in groups),
        'zone_groups': groups,
        'plants': plants,
        'purchased_energy': {
            'heating': any(p['purchased'] and p['type'] == 'hot_water' for p in hvac_plants),
            'cooling': any(p['purchased'] and p['type'] == 'chilled_water' for p in hvac_plants),
        },
    }
    if audit is not None:
        audit.info('characterize', 'model characterized',
                   inputs={'zone_groups': len(groups), 'plants': len(plants),
                           'built_by_gem': facts['built_by_gem']})
    return facts


# ---------------- plants ----------------

ELECTRIC_CHILLER_CASTS = {
    'to_ChillerElectricEIR': 'electric_eir',
    'to_ChillerElectricReformulatedEIR': 'electric_reformulated_eir',
    'to_ChillerElectricASHRAE205': 'electric_ashrae205',
}
ABSORPTION_CHILLER_CASTS = {
    'to_ChillerAbsorption': 'absorption',
    'to_ChillerAbsorptionIndirect': 'absorption_indirect',
}

# cast -> (mode, source-kind, fuel). A ``None`` mode is resolved from the
# CentralHeatPumpSystem's load-loop connections; a ``None`` fuel is read from
# the unit. This is the one plant-HP registry: recognition, mode, source
# classification and fuel cannot drift into separate hand-kept lists.
PLANT_HP_CASTS = {
    'to_HeatPumpPlantLoopEIRHeating':
        ('heating', 'condenser', 'Electricity'),
    'to_HeatPumpWaterToWaterEquationFitHeating':
        ('heating', 'loop', 'Electricity'),
    'to_HeatPumpAirToWaterHeating':
        ('heating', 'air', 'Electricity'),
    'to_HeatPumpAirToWaterFuelFiredHeating':
        ('heating', 'air', None),
    'to_HeatPumpPlantLoopEIRCooling':
        ('cooling', 'condenser', 'Electricity'),
    'to_HeatPumpWaterToWaterEquationFitCooling':
        ('cooling', 'loop', 'Electricity'),
    'to_HeatPumpAirToWaterCooling':
        ('cooling', 'air', 'Electricity'),
    'to_HeatPumpAirToWaterFuelFiredCooling':
        ('cooling', 'air', None),
    'to_CentralHeatPumpSystem':
        (None, 'loop', 'Electricity'),
}


def _plant_heat_pump(comp, loop):
    """Return ``(unit, mode, fuel, source-kind)`` for a HP serving ``loop``."""
    for cast, (mode, source_kind, declared_fuel) in PLANT_HP_CASTS.items():
        unit = _try_cast(comp, cast)
        if unit is None:
            continue

        resolved_mode = mode
        if resolved_mode is None:
            heating = opt(unit.heatingPlantLoop())
            cooling = opt(unit.coolingPlantLoop())
            if heating is not None and heating.handle() == loop.handle():
                resolved_mode = 'heating'
            elif cooling is not None and cooling.handle() == loop.handle():
                resolved_mode = 'cooling'
            else:
                continue

        fuel = unit.fuelType() if declared_fuel is None else declared_fuel
        return unit, resolved_mode, fuel, source_kind
    return None


def _plant_heat_pump_has_heating_side(unit, mode):
    """Whether this plant heat-pump equipment carries a heating side."""
    if mode == 'heating':
        return True

    for accessor in (
            'companionHeatingHeatPump',
            'heatPumpAirToWater',
            'heatingPlantLoop'):
        method = getattr(unit, accessor, None)
        if method is not None and opt(method()) is not None:
            return True
    return False


def _plant_facts(loop, audit):
    fuels = []
    purchased = False
    heat_pump = False
    heat_pump_modes = []
    heating_capable_heat_pump = False
    unpaired_cooling_heat_pumps = []
    has_boiler = has_chiller = has_rejection = False
    chiller_types = []

    #: (fuel, watts|None) per heating device on this plant — see below.
    allocation = []
    for comp in loop.supplyComponents():
        if comp.to_BoilerHotWater().is_initialized():
            has_boiler = True
            boiler = comp.to_BoilerHotWater().get()
            fuels.append(boiler.fuelType())
            # 8.4.4.9.(5) ratios the proposed CAPACITY ALLOCATION per energy
            # type, so the allocation is recorded here beside the fuels rather
            # than re-derived later. Autosized capacity reads as None and the
            # consumer must say "unknown" rather than guess a fraction —
            # every multi-fuel plant in the sample corpus is autosized, so the
            # unknown case is the common one, not the edge (Sol, `110`).
            # ONLY ask for the autosized value when a sizing run exists.
            # `autosizedNominalCapacity()` on an unsized model emits
            # "This model has no sql file, cannot retrieve the autosized
            # value" to the console for EVERY boiler — noise on every run of
            # every model, single-fuel ones included, which the frozen stdout
            # baselines caught when six unrelated scenarios changed.
            watts = opt(boiler.nominalCapacity())
            if watts is None and loop.model().sqlFile().is_initialized():
                watts = opt(boiler.autosizedNominalCapacity())
            allocation.append((boiler.fuelType(),
                               float(watts) if watts is not None else None))
        else:
            chiller_type = next(
                (kind for cast, kind in ELECTRIC_CHILLER_CASTS.items()
                 if _try_cast(comp, cast) is not None),
                None)
            if chiller_type is not None:
                has_chiller = True
                chiller_types.append(chiller_type)
                fuels.append('Electricity')
                continue

            chiller_type = next(
                (kind for cast, kind in ABSORPTION_CHILLER_CASTS.items()
                 if _try_cast(comp, cast) is not None),
                None)
            if chiller_type is not None:
                has_chiller = True
                chiller_types.append(chiller_type)
                continue

            hp = _plant_heat_pump(comp, loop)
            if hp is not None:
                unit, mode, fuel, _source_kind = hp
                heat_pump = True
                heat_pump_modes.append(mode)
                if _plant_heat_pump_has_heating_side(unit, mode):
                    heating_capable_heat_pump = True
                elif mode == 'cooling':
                    unpaired_cooling_heat_pumps.append(unit.nameString())
                fuels.append(fuel)
                continue

            if _district_heating(comp):
                purchased = True
                fuels.append('Purchased')
            elif comp.to_DistrictCooling().is_initialized():
                purchased = True
                fuels.append('Purchased')
            elif (comp.to_CoolingTowerSingleSpeed().is_initialized() or
                  comp.to_EvaporativeFluidCoolerSingleSpeed().is_initialized() or
                  comp.to_GroundHeatExchangerVertical().is_initialized()):
                has_rejection = True
            elif comp.to_WaterHeaterMixed().is_initialized():
                fuels.append(comp.to_WaterHeaterMixed().get().heaterFuelType())

    swh = any(c.to_WaterUseConnections().is_initialized() for c in loop.demandComponents())
    if swh:
        type_ = 'service_water'
    elif has_boiler or (purchased and _heating_loop(loop)) or 'heating' in heat_pump_modes:
        type_ = 'hot_water'
    elif has_chiller or (purchased and not _heating_loop(loop)) or 'cooling' in heat_pump_modes:
        type_ = 'chilled_water'
    elif has_rejection:
        type_ = 'condenser'
    else:
        type_ = 'other'

    # Per-energy-type capacity, summed across devices of the same fuel. A
    # fuel whose devices are all autosized maps to None: the allocation is
    # UNKNOWN until a sizing run, not zero.
    by_fuel = {}
    for fuel, watts in allocation:
        if fuel not in by_fuel:
            by_fuel[fuel] = watts
        elif by_fuel[fuel] is not None and watts is not None:
            by_fuel[fuel] += watts
        else:
            by_fuel[fuel] = None
    facts = {'name': loop.nameString(), 'type': type_,
             'fuels': list(dict.fromkeys(fuels)),
             'fuel_capacities_w': by_fuel,
             # BOILERS on this plant, named for what it counts. `allocation`
             # holds only `BoilerHotWater`, so the earlier name
             # `heating_device_count` lied: a plant with one gas boiler and an
             # electric WaterHeaterMixed reported two fuels and a count of 1
             # (Sol, `120`, reproduced). Sentence (6) is about boilers, which
             # is the count the (5) disclosure needs, so the field keeps that
             # scope and says so.
             'boiler_count': len(allocation),
             'purchased': purchased, 'heat_pump': heat_pump,
             'heat_pump_modes': list(dict.fromkeys(heat_pump_modes)),
             'heating_capable_heat_pump': heating_capable_heat_pump,
             'unpaired_cooling_heat_pumps':
                 list(dict.fromkeys(unpaired_cooling_heat_pumps)),
             'chiller_types': list(dict.fromkeys(chiller_types))}
    if audit is not None:
        audit.info('characterize', 'plant loop classified', target=loop.nameString(),
                   value=type_, inputs={'fuels': facts['fuels'],
                                        'purchased': purchased})
    return facts


def _district_heating(comp):
    """Purchased heating in any medium. By IDD type, not by the typed casts:
    DistrictHeatingWater and DistrictHeatingSteam replaced DistrictHeating at
    OS 3.7, the SDK has no steam cast, and the deprecated to_DistrictHeating()
    logs to stdout on every call."""
    return comp.iddObjectType().valueName() in DISTRICT_HEATING_TYPES


def _heating_loop(loop):
    exit_c = loop.sizingPlant().designLoopExitTemperature()
    return exit_c > 30.0  # hot loops design well above chilled/condenser temperatures


# ---------------- air-loop groups ----------------

def _air_loop_group(air_loop, plant_by_name, audit):
    group = _base_group([z.nameString() for z in air_loop.thermalZones()],
                        air_loop.nameString())
    _recognize_gem_name(group, air_loop, audit)
    _outdoor_air_facts(group, air_loop, audit)

    # Two equipment-IDENTITY facts, read from the RAW supply path and the sizing
    # object because `coils.supply_components` below is lossy by design.
    _equipment_class_facts(group, air_loop, audit)

    # coils.supply_components descends into AirLoopHVACUnitarySystem containers
    # (staged NECB reference systems) — otherwise a staged sys 3/4 reads as an
    # air loop with no coils at all.
    for comp in coils.supply_components(air_loop):
        evidence = f"{comp.iddObjectType().valueName()} on {air_loop.nameString()}"
        _scan_heating_component(group, comp, plant_by_name, evidence)
        _scan_cooling_component(group, comp, plant_by_name, evidence)

    for zone in sorted_by_name(air_loop.thermalZones()):
        for eq in zone.equipment():
            _terminal_facts(group, eq, plant_by_name)

    if group['family_guess'] is None:
        group['family_guess'] = _structural_family_guess(group)
    if audit is not None:
        audit.decision(
            'characterize', 'zone group characterized',
            target=air_loop.nameString(),
            inputs={'zones': len(group['zones']),
                    'terminal': group['terminal_type']},
            value=group['family'] or group['family_guess'],
            evidence='; '.join(group['evidence']))
    return group


def _equipment_class_facts(group, air_loop, audit):
    """Whether the loop's cooling is PACKAGED equipment, and whether it is a
    VENTILATION system rather than a zone-cooling one.

    Both are generic modelling facts about the OSM, not NECB judgements — the
    code-side meaning (Table 8.4.4.7.-A's "air-cooled unitary" branch) lives in
    `btap.codes`. They exist because the facts a classifier needs here are
    DESTROYED by the time the coil scan runs:

    - `coils.supply_components` REPLACES an AirLoopHVACUnitarySystem (or either
      unitary heat-pump wrapper) with the coils inside it, which it must do to
      find a staged reference system's coils at all. A real packaged unit and a
      field-erected built-up DX coil then both read as `loop_dx_cooling`, and
      nothing downstream can tell them apart: `_structural_family_guess` reads
      zone count and terminals, which are not equipment identity.
    - A ventilation system's coil TEMPERS make-up air; it is not the equipment
      that cools the space. `SizingSystem` records that intent directly, and a
      bare coil scan cannot see it.

    An arbitrary OSM is exactly where this matters. A model we authored is
    recognized by its loop NAME (`_recognize_gem_name`), so it carries its
    family regardless; a model from anywhere else has only its structure, and
    the standard OpenStudio way to model a packaged rooftop unit is the very
    container the flattener unwraps.
    """
    # A DECLARED class outranks everything inferred from topology, and is the
    # only route that works for a model this library did not build: see
    # `equipment_class` for why a loop name and a zone count do not.
    group['declared_equipment_class'] = equipment_class.read(air_loop)
    if group['declared_equipment_class'] is not None:
        group['evidence'].append(
            f"{air_loop.nameString()} declares equipment_class "
            f"{group['declared_equipment_class']!r}")
    else:
        # A declaration we cannot read is NOT the same as no declaration, and
        # staying silent about the difference sends the author back to retype
        # the value they already typed: the run refuses for the same reason and
        # nothing says a declaration was seen (Fable, PR #161 review).
        # `read` cannot raise — anyone may set the feature directly, and a
        # vocabulary we do not know is not grounds to refuse a model — so this
        # is a WARNING naming both the value and the accepted set.
        raw = equipment_class.read_raw(air_loop)
        if raw is not None and audit is not None:
            audit.warn(
                'characterize',
                f"equipment_class {raw!r} on {air_loop.nameString()} is NOT a "
                f"recognized value, so it is read as NO declaration",
                target=air_loop.nameString(),
                inputs={'declared': raw, 'accepted': list(equipment_class.VALUES)})

    for comp in air_loop.supplyComponents():
        for caster in ('to_AirLoopHVACUnitarySystem',
                       'to_AirLoopHVACUnitaryHeatPumpAirToAir',
                       'to_AirLoopHVACUnitaryHeatPumpAirToAirMultiSpeed'):
            if not hasattr(comp, caster):
                continue
            if getattr(comp, caster)().is_initialized():
                group['packaged_unitary'] = True
                group['evidence'].append(
                    f"{comp.iddObjectType().valueName()} container on "
                    f"{air_loop.nameString()} (packaged equipment)")
                break
        if group['packaged_unitary']:
            break

    # THREE fields, not one. `typeofLoadtoSizeOn` alone states the sizing BASIS
    # and does not prove the loop is all outdoor air, so concluding "its coil
    # only tempers make-up air" from it is a stronger claim than the field
    # carries (Sol, `329`). Every DOAS profile in `data/sizing.json` sets all
    # three, and `BaseSystem.apply_system_sizing` writes all three onto
    # SizingSystem, so the conjunction is available wherever the weaker proxy
    # was. A 100%-OA loop sized on Sensible is NOT caught here and falls to the
    # inference below with its warning, which is the honest outcome.
    sizing = air_loop.sizingSystem()
    if (sizing.typeofLoadtoSizeOn() == 'VentilationRequirement'
            and sizing.allOutdoorAirinCooling()
            and sizing.allOutdoorAirinHeating()):
        group['ventilation_sized'] = True
        group['evidence'].append(
            f"{air_loop.nameString()} is sized on the ventilation requirement "
            f"with all outdoor air in cooling and heating, so its coils temper "
            f"make-up air")


def _recognize_gem_name(group, air_loop, audit):
    name = air_loop.nameString()
    candidate = name.split(' | ')[0]
    try:
        row = catalog.resolve(candidate)
        group['catalog_name'] = row['name']
        group['family'] = row['family']
        group['evidence'].append(f"air loop name resolves to catalog entry '{row['name']}'")
        return
    except ValueError:
        pass  # not a gem catalog name
    m = re.match(r'(sys_\d)\|', name)
    if m:
        group['family_guess'] = PIPE_NAME_FAMILIES.get(m.group(1))
        group['evidence'].append(f"legacy NECB pipe name ({m.group(1)})")
        if audit is not None:
            audit.info('characterize', 'legacy NECB pipe-named loop recognized',
                       target=name, value=group['family_guess'])


def _base_group(zone_names, air_loop_name):
    return {'zones': zone_names, 'air_loop': air_loop_name,
            'family': None, 'catalog_name': None, 'family_guess': None,
            'heated': False, 'cooled': False,
            'heating_energy_types': [], 'cooling_energy_types': [],
            'heat_pump': False, 'heat_pump_sources': [], 'heat_pump_source_loops': [],
            'terminal_type': 'none',
            'zonal_units': [], 'loop_dx_cooling': False,
            'packaged_unitary': False, 'ventilation_sized': False,
            'declared_equipment_class': None,
            'cooling_plants': [],
            'design_cooling_kw': 0.0, 'cooling_capacity_complete': True,
            'dcv': False, 'system_outdoor_air_method': None,
            'evidence': []}


def _outdoor_air_facts(group, air_loop, audit):
    """8.4.4.15.(2) (2025: 8.4.5.15.(2)): the demand-control-ventilation strategy of
    the PROPOSED air loop has to be reproduced in the reference building, so the
    facts dict has to carry it across the teardown that replaces the loop.
    EnergyPlus expresses the strategy on Controller:MechanicalVentilation as the
    DCV flag plus the system outdoor-air method (ZoneSum = occupancy-based,
    IndoorAirQualityProcedure = CO2-based) — both are recorded."""
    oa_system = opt(air_loop.airLoopHVACOutdoorAirSystem())
    if oa_system is None:
        return

    mech = oa_system.getControllerOutdoorAir().controllerMechanicalVentilation()
    group['dcv'] = mech.demandControlledVentilation()
    group['system_outdoor_air_method'] = mech.systemOutdoorAirMethod()
    if not group['dcv']:
        return

    group['evidence'].append(
        f"demand-controlled ventilation enabled ({group['system_outdoor_air_method']})")
    if audit is not None:
        audit.info('characterize', 'proposed air loop carries demand-controlled ventilation',
                   target=air_loop.nameString(), value=group['system_outdoor_air_method'],
                   inputs={'demand_controlled_ventilation': True})


# (cast, fuel_of(coil, plant_by_name), hp_kind) — hp_kind False means "never a
# heat pump AND never a plant heat pump" (gas coils), None means "not a heat
# pump itself but its plant may BE one" (electric/hydronic coils), exactly the
# Ruby false/nil split.
HYDRONIC_HEATING_COIL_CASTS = (
    'to_CoilHeatingWater',
    'to_CoilHeatingWaterBaseboard',
    'to_CoilHeatingWaterBaseboardRadiant',
    'to_CoilHeatingFourPipeBeam',
    'to_CoilHeatingLowTempRadiantConstFlow',
    'to_CoilHeatingLowTempRadiantVarFlow',
)
HYDRONIC_COOLING_COILS = {
    'to_CoilCoolingWater': 'autosized_load',
    'to_CoilCoolingCooledBeam': None,
    'to_CoilCoolingFourPipeBeam': None,
    'to_CoilCoolingLowTempRadiantConstFlow': None,
    'to_CoilCoolingLowTempRadiantVarFlow': 'design_capacity',
    'to_CoilCoolingWaterPanelRadiant': 'design_capacity',
}


def _hydronic_coil_fuels(coil, plant_by_name):
    return _hydronic_fuels(coil, plant_by_name)


HEATING_COILS = [
    ('to_CoilHeatingGas', lambda _c, _p: 'NaturalGas', False),
    ('to_CoilHeatingGasMultiStage', lambda _c, _p: 'NaturalGas', False),
    ('to_CoilHeatingDXMultiSpeed', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingElectric', lambda _c, _p: 'Electricity', None),
    ('to_CoilHeatingElectricMultiStage', lambda _c, _p: 'Electricity', None),
    ('to_CoilHeatingDesuperheater', lambda _c, _p: 'Electricity', False),
    ('to_CoilHeatingDXSingleSpeed', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingDXVariableSpeed', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingWaterToAirHeatPumpEquationFit', lambda _c, _p: 'Electricity', 'water_to_air'),
    ('to_CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
     lambda _c, _p: 'Electricity', 'water_to_air'),
    ('to_CoilHeatingDXVariableRefrigerantFlow', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingDXVariableRefrigerantFlowFluidTemperatureControl',
     lambda _c, _p: 'Electricity', 'air'),
] + [
    (cast, _hydronic_coil_fuels, None)
    for cast in HYDRONIC_HEATING_COIL_CASTS
]


def _scan_heating_component(group, comp, plant_by_name, evidence):
    for cast, fuel_of, hp_kind in HEATING_COILS:
        coil = _try_cast(comp, cast)
        if coil is None:
            continue

        group['heated'] = True
        _union(group['heating_energy_types'], _array(fuel_of(coil, plant_by_name)))
        _record_heat_pump(group, hp_kind, coil)
        if hp_kind is None:  # hydronic coils: plant may BE a heat pump
            _record_plant_heat_pump(group, coil, plant_by_name)
        group['evidence'].append(f"heated: {evidence}")
        return True
    return False


def _record_plant_heat_pump(group, coil, plant_by_name):
    """8.4.4.13.(2) reaches a heat pump that "supplies ... conditioned water to a
    hydronic loop" — a PLANT heat pump serving coils/baseboards/fan coils, not
    just a coil-level unit. When the plant a hydronic coil draws from carries
    a heat pump, the group is a heat-pump group and the plant's annotated
    source kind ('air' / 'external' / 'water_loop') governs the D-37 redirect
    split (D-58)."""
    if coil is None:
        return

    loop = opt(coil.plantLoop()) if hasattr(coil, 'plantLoop') else None
    if loop is None:
        return

    plant = plant_by_name.get(loop.nameString())
    if not (plant and plant['heat_pump']):
        return

    group['heat_pump'] = True
    if plant.get('heating_capable_heat_pump'):
        group['heating_capable_plant_heat_pump'] = True
    unpaired = group.setdefault('unpaired_cooling_plant_heat_pumps', [])
    _union(unpaired, plant.get('unpaired_cooling_heat_pumps') or [])
    source = plant.get('hp_source')
    if source is not None:
        _union(group['heat_pump_sources'], [source])
    _union(group['heat_pump_source_loops'],
           [n for n in [plant.get('hp_source_loop_name')] if n is not None])
    group['evidence'].append(
        f"plant heat pump on '{plant['name']}' "
        f"(source {source or 'unclassified'})")


def _record_hydronic_plant(group, coil, key):
    if coil is None or not hasattr(coil, 'plantLoop'):
        return
    loop = opt(coil.plantLoop())
    if loop is not None:
        _union(group[key], [loop.nameString()])


def _record_heat_pump(group, hp_kind, unit):
    """D-37 (Note A-8.4.4.13): heat-pump SOURCE matters for the 8.4.4.13
    reference redirect — water-LOOP (internal loop, aux boiler/tower
    allowed) stays on Table -A; air/water/ground-SOURCE redirects."""
    if not hp_kind:
        return

    group['heat_pump'] = True
    group['nonplant_heat_pump'] = True
    source = (_water_to_air_hp_source(unit)
              if hp_kind == 'water_to_air' else 'air')
    if source is not None:
        _union(group['heat_pump_sources'], [source])
    # 8.4.4.13.(2)(g)(ii) needs "all the heat pumps connected to the same
    # water loop" — record the source-loop NAME so the aux-fuel election can
    # aggregate across zone groups sharing it (D-52).
    if not (hp_kind == 'water_to_air' and hasattr(unit, 'plantLoop')):
        return

    loop = unit.plantLoop()
    if loop.is_initialized():
        _union(group['heat_pump_source_loops'], [loop.get().nameString()])


GROUND_HX_CASTS = ('to_GroundHeatExchangerVertical', 'to_GroundHeatExchangerHorizontalTrench')


def _external_source_loop(loop):
    """Note A-8.4.4.13's boundary evidence: ground HX / district / temperature-
    source components mean the loop is fed by EXTERNAL water or ground
    (water-/ground-source); otherwise it is an internal water loop (aux
    boiler and/or heat-rejection device explicitly allowed)."""
    for c in loop.supplyComponents():
        if (any(_try_cast(c, cast) is not None for cast in GROUND_HX_CASTS) or
                _district_heating(c) or
                c.to_DistrictCooling().is_initialized() or
                (hasattr(c, 'to_PlantComponentTemperatureSource') and
                 c.to_PlantComponentTemperatureSource().is_initialized())):
            return True
    return False


def _water_to_air_hp_source(coil):
    """Classify a water-to-air heat pump by its SOURCE loop per Note
    A-8.4.4.13 (see _external_source_loop)."""
    loop = opt(coil.plantLoop()) if coil is not None and hasattr(coil, 'plantLoop') else None
    if loop is None:
        return None

    return 'external' if _external_source_loop(loop) else 'water_loop'


def _annotate_heat_pump_plants(model, plant_by_name):
    """Classify each heat-pump PLANT's source per Note A-8.4.4.13 (D-58): the HP
    object's source-side loop carries the evidence — external components =>
    'external' (water/ground source); a plain internal loop => 'water_loop';
    an air-source equipment class => 'air'; no loop on a water-source class
    leaves the source unclassified under D-37. The source loop is flagged
    (`hp_source_loop`) so purchased-energy detection skips it: a district
    object standing in for a ground field (the legacy GLHX pattern)
    is not purchased heating for the building."""
    for loop in model.getPlantLoops():
        plant = plant_by_name.get(loop.nameString())
        if not (plant and plant['heat_pump']):
            continue

        source = None
        for comp in loop.supplyComponents():
            hp_facts = _plant_heat_pump(comp, loop)
            if hp_facts is None:
                continue
            hp, _mode, _fuel, source_kind = hp_facts

            if source_kind == 'air':
                source = source or 'air'
                continue
            if (source_kind == 'condenser'
                    and hasattr(hp, 'condenserType')
                    and hp.condenserType() != 'WaterSource'):
                source = source or 'air'
                continue
            if hasattr(hp, 'sourcePlantLoop'):
                secondary = opt(hp.sourcePlantLoop())
            elif hasattr(hp, 'secondaryPlantLoop'):
                secondary = opt(hp.secondaryPlantLoop())
            else:
                secondary = None
            if secondary is None:
                continue

            src_plant = plant_by_name.get(secondary.nameString())
            if src_plant is not None:
                src_plant['hp_source_loop'] = True
            plant['hp_source_loop_name'] = secondary.nameString()
            source = ('external' if _external_source_loop(secondary)
                      else (source or 'water_loop'))
        plant['hp_source'] = source


def _annotate_absorption_chiller_plants(model, plant_by_name):
    """Attribute an absorption chiller's generator energy to its cooling loop."""
    for loop in model.getPlantLoops():
        plant = plant_by_name.get(loop.nameString())
        if not (plant and any(t.startswith('absorption')
                              for t in plant['chiller_types'])):
            continue

        generator_fuels = []
        for comp in loop.supplyComponents():
            chiller = next(
                (unit for cast in ABSORPTION_CHILLER_CASTS
                 if (unit := _try_cast(comp, cast)) is not None),
                None)
            if chiller is None:
                continue
            generator = opt(chiller.generatorLoop())
            if generator is None:
                continue
            source = plant_by_name.get(generator.nameString())
            if source is not None:
                _union(generator_fuels, source['fuels'])

        _union(plant['fuels'], generator_fuels or ['Unknown'])


def _hydronic_cooling_coil(comp):
    for cast, capacity_kind in HYDRONIC_COOLING_COILS.items():
        coil = _try_cast(comp, cast)
        if coil is not None:
            return coil, capacity_kind
    return None


def _scan_cooling_component(group, comp, plant_by_name, evidence):
    kw = None
    fuels = None
    hp = None
    hp_unit = None
    plant_coil = None
    if comp.to_CoilCoolingDXSingleSpeed().is_initialized():
        c = comp.to_CoilCoolingDXSingleSpeed().get()
        fuels = 'Electricity'
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif comp.to_CoilCoolingDXMultiSpeed().is_initialized():
        # a staged coil's TOTAL capacity is its TOP stage (E+ stages are cumulative)
        stages = comp.to_CoilCoolingDXMultiSpeed().get().stages()
        top = stages[-1] if stages else None
        fuels = 'Electricity'
        kw = (_optional_kw(top.grossRatedTotalCoolingCapacity(),
                           top.autosizedGrossRatedTotalCoolingCapacity())
              if top is not None else None)
    elif comp.to_CoilCoolingDXTwoSpeed().is_initialized():
        c = comp.to_CoilCoolingDXTwoSpeed().get()
        fuels = 'Electricity'
        kw = _optional_kw(c.ratedHighSpeedTotalCoolingCapacity(),
                          c.autosizedRatedHighSpeedTotalCoolingCapacity())
    elif comp.to_CoilCoolingDXVariableSpeed().is_initialized():
        c = comp.to_CoilCoolingDXVariableSpeed().get()
        fuels = 'Electricity'
        kw = _optional_kw(c.grossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel(),
                          c.autosizedGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel())
    elif (hydronic := _hydronic_cooling_coil(comp)) is not None:
        c, capacity_kind = hydronic
        fuels = _hydronic_fuels(c, plant_by_name)
        plant_coil = c
        if capacity_kind == 'autosized_load':
            kw = _optional_kw(None, c.autosizedDesignCoilLoad())
        elif capacity_kind == 'design_capacity':
            kw = _optional_kw(c.coolingDesignCapacity(),
                              _autosized_when_sized(
                                  c, 'autosizedCoolingDesignCapacity'))
        else:
            kw = None
    elif comp.to_CoilCoolingWaterToAirHeatPumpEquationFit().is_initialized():
        c = comp.to_CoilCoolingWaterToAirHeatPumpEquationFit().get()
        fuels = 'Electricity'
        hp = 'water_to_air'
        hp_unit = c
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif comp.to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit().is_initialized():
        c = comp.to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit().get()
        fuels = 'Electricity'
        hp = 'water_to_air'
        hp_unit = c
        kw = _optional_kw(
            c.grossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel(),
            _autosized_when_sized(
                c,
                'autosizedGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel'))
    elif comp.to_CoilCoolingDXVariableRefrigerantFlow().is_initialized():
        c = comp.to_CoilCoolingDXVariableRefrigerantFlow().get()
        fuels = 'Electricity'
        hp = 'air'
        kw = _optional_kw(
            c.ratedTotalCoolingCapacity(),
            _autosized_when_sized(c, 'autosizedRatedTotalCoolingCapacity'))
    elif comp.to_CoilCoolingDXVariableRefrigerantFlowFluidTemperatureControl().is_initialized():
        c = comp.to_CoilCoolingDXVariableRefrigerantFlowFluidTemperatureControl().get()
        fuels = 'Electricity'
        hp = 'air'
        kw = _optional_kw(
            c.ratedTotalCoolingCapacity(),
            _autosized_when_sized(c, 'autosizedRatedTotalCoolingCapacity'))
    elif comp.to_EvaporativeCoolerDirectResearchSpecial().is_initialized():
        fuels = 'Electricity'
        kw = 0.0
    else:
        return False

    group['cooled'] = True
    _union(group['cooling_energy_types'], _array(fuels))
    _record_heat_pump(group, hp, hp_unit)
    _record_hydronic_plant(group, plant_coil, 'cooling_plants')
    _record_plant_heat_pump(group, plant_coil, plant_by_name)
    # The Table 8.4.4.7.-A residential parenthetical needs to know whether the
    # LOOP's own DX cools the zones (an air-cooled unitary/packaged shape) —
    # a fact, where the family string is only a name (D-58).
    if re.search(r'Coil_Cooling_DX', comp.iddObjectType().valueName()):
        group['loop_dx_cooling'] = True
    group['evidence'].append(f"cooled: {evidence}")
    if kw is None:
        group['cooling_capacity_complete'] = False
    else:
        group['design_cooling_kw'] += kw
    return True


def _hydronic_fuels(coil, plant_by_name):
    loop = coil.plantLoop()
    if not loop.is_initialized():
        return 'Unknown'

    plant = plant_by_name.get(loop.get().nameString())
    if plant is None or not plant['fuels']:
        return 'Unknown'

    return plant['fuels']


def _optional_kw(hard, autosized):
    for value in (hard, autosized):
        if value is None:
            continue
        if not hasattr(value, 'is_initialized'):
            return float(value) / 1000.0
        if value.is_initialized():
            return float(value.get()) / 1000.0
    return None


def _autosized_when_sized(component, accessor):
    if not component.model().sqlFile().is_initialized():
        return None
    return getattr(component, accessor)()


# ---------------- 8.4.4.13.(2)(g) heating-election inventory (D-52) ----------------

BASEBOARD_VARIABLE = 'Baseboard Total Heating Energy'
COIL_VARIABLE = 'Heating Coil Heating Energy'

DX_HEATING_CASTS = ('to_CoilHeatingDXSingleSpeed', 'to_CoilHeatingDXMultiSpeed',
                    'to_CoilHeatingDXVariableSpeed', 'to_CoilHeatingWaterToAirHeatPumpEquationFit',
                    'to_CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
                    'to_CoilHeatingDXVariableRefrigerantFlow',
                    'to_CoilHeatingDXVariableRefrigerantFlowFluidTemperatureControl')
AUX_COIL_FUELS = {
    'to_CoilHeatingGas': 'NaturalGas',
    'to_CoilHeatingGasMultiStage': 'NaturalGas',
    'to_CoilHeatingElectric': 'Electricity',
    'to_CoilHeatingElectricMultiStage': 'Electricity',
    'to_CoilHeatingDesuperheater': 'Electricity',
    **{cast: 'hydronic' for cast in HYDRONIC_HEATING_COIL_CASTS},
}


def heating_election_inventory(model):
    """The SDK-side half of the 8.4.4.13.(2)(g) auxiliary-fuel election: which
    equipment on the PROPOSED delivers space heating, under which EnergyPlus
    output variable, and on which energy type. The umbrella joins these names
    with the proposed annual run's SQL sums (this package never simulates) and
    hands the joined data back to reference_hvac as `proposed_annual`.

    :param model: openstudio.model.Model — the PROPOSED model
    :return: dict
        'loops' — { air loop name: { 'hp': [coil names], 'aux': [{'name':, 'fuel':}] } }
        'zones' — { zone name: [{'name':, 'fuel':, 'variable':, 'role': 'aux' | 'hp'}] }
        All heating quantities the election compares are DELIVERED heat
        (Heating Coil Heating Energy / Baseboard Total Heating Energy), one
        consistent basis across fuels.
    """
    plants = [_plant_facts(loop, None) for loop in sorted_by_name(model.getPlantLoops())]
    plant_by_name = {p['name']: p for p in plants}

    loops = {}
    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        entry = {'hp': [], 'aux': []}
        for comp in coils.supply_components(air_loop):
            if any(_try_cast(comp, cast) is not None for cast in DX_HEATING_CASTS):
                entry['hp'].append(comp.nameString())
            else:
                aux = _aux_coil_entry(comp, plant_by_name)
                if aux is not None:
                    entry['aux'].append(aux)
        if entry['hp'] or entry['aux']:
            loops[air_loop.nameString()] = entry

    zones = {}
    for zone in sorted_by_name(model.getThermalZones()):
        entries = []
        for eq in zone.equipment():
            entries.extend(_zonal_heating_entries(eq, plant_by_name))
        if entries:
            zones[zone.nameString()] = entries
    return {'loops': loops, 'zones': zones}


def _aux_coil_entry(comp, plant_by_name):
    for cast, fuel in AUX_COIL_FUELS.items():
        coil = _try_cast(comp, cast)
        if coil is None:
            continue

        resolved = ('+'.join(_array(_hydronic_fuels(coil, plant_by_name)))
                    if fuel == 'hydronic' else fuel)
        return {'name': coil.nameString(), 'fuel': resolved}
    return None


def _zonal_heating_entries(eq, plant_by_name):
    if (eq.to_ZoneHVACBaseboardConvectiveElectric().is_initialized() or
            (hasattr(eq, 'to_ZoneHVACBaseboardRadiantConvectiveElectric') and
             eq.to_ZoneHVACBaseboardRadiantConvectiveElectric().is_initialized())):
        return [{'name': eq.nameString(), 'fuel': 'Electricity',
                 'variable': BASEBOARD_VARIABLE, 'role': 'aux'}]

    water_baseboard = next(
        (o for o in (getattr(eq, cast)() for cast in
                     ('to_ZoneHVACBaseboardConvectiveWater', 'to_ZoneHVACBaseboardRadiantConvectiveWater')
                     if hasattr(eq, cast))
         if o.is_initialized()),
        None)
    if water_baseboard is not None:
        coil = water_baseboard.get().heatingCoil()
        fuel = '+'.join(_array(_hydronic_fuels(coil, plant_by_name)))
        return [{'name': eq.nameString(), 'fuel': fuel,
                 'variable': BASEBOARD_VARIABLE, 'role': 'aux'}]

    entries = []
    for coil, role in _zonal_heating_coils(eq):
        if role == 'hp':
            entries.append({'name': coil.nameString(), 'fuel': 'Electricity',
                            'variable': COIL_VARIABLE, 'role': 'hp'})
        else:
            aux = _aux_coil_entry(coil, plant_by_name)
            if aux is not None:
                entries.append({**aux, 'variable': COIL_VARIABLE, 'role': 'aux'})
    return entries


ZONAL_HEATING_UNITS = (
    ('to_ZoneHVACPackagedTerminalAirConditioner', ('heatingCoil',)),
    ('to_ZoneHVACPackagedTerminalHeatPump', ('heatingCoil', 'supplementalHeatingCoil')),
    ('to_ZoneHVACWaterToAirHeatPump', ('heatingCoil', 'supplementalHeatingCoil')),
    ('to_ZoneHVACFourPipeFanCoil', ('heatingCoil',)),
    ('to_ZoneHVACUnitHeater', ('heatingCoil',)),
    ('to_ZoneHVACUnitVentilator', ('heatingCoil',)),
    ('to_ZoneHVACLowTempRadiantConstFlow', ('heatingCoil',)),
    ('to_ZoneHVACLowTempRadiantVarFlow', ('heatingCoil',)),
    ('to_AirTerminalSingleDuctVAVReheat', ('reheatCoil',)),
    ('to_AirTerminalSingleDuctConstantVolumeReheat', ('reheatCoil',)),
    ('to_AirTerminalSingleDuctParallelPIUReheat', ('reheatCoil',)),
    ('to_AirTerminalSingleDuctSeriesPIUReheat', ('reheatCoil',)),
    ('to_AirTerminalSingleDuctVAVHeatAndCoolReheat', ('reheatCoil',)),
    ('to_AirTerminalSingleDuctConstantVolumeFourPipeBeam', ('heatingCoil',)),
    ('to_AirTerminalSingleDuctConstantVolumeFourPipeInduction', ('heatingCoil',)),
)


def _zonal_heating_coils(eq):
    """(coil, 'hp' | 'aux') pairs for a zonal unit or terminal. The unit's DX
    heating coil is the heat pump itself; its supplemental coil and every
    non-DX heating coil are terminal/auxiliary heating."""
    pairs = []
    for cast, accessors in ZONAL_HEATING_UNITS:
        unit = _try_cast(eq, cast)
        if unit is None:
            continue

        for accessor in accessors:
            if not hasattr(unit, accessor):
                continue

            coil = getattr(unit, accessor)()
            if hasattr(coil, 'is_initialized') and coil.is_initialized():
                coil = coil.get()
            if not hasattr(coil, 'nameString'):
                continue

            hp = any(_try_cast(coil, c) is not None for c in DX_HEATING_CASTS)
            pairs.append((coil, 'hp' if hp else 'aux'))
        break
    return pairs


TERMINALS = {
    'to_AirTerminalDualDuctConstantVolume': ('dual_duct_cv', ()),
    'to_AirTerminalDualDuctVAV': ('dual_duct_vav', ()),
    'to_AirTerminalDualDuctVAVOutdoorAir': ('dual_duct_vav_outdoor_air', ()),
    'to_AirTerminalSingleDuctVAVReheat': (
        'vav_reheat', (('reheatCoil', 'heat'),)),
    'to_AirTerminalSingleDuctVAVNoReheat': ('vav', ()),
    'to_AirTerminalSingleDuctVAVHeatAndCoolReheat': (
        'vav_heat_cool_reheat', (('reheatCoil', 'heat'),)),
    'to_AirTerminalSingleDuctVAVHeatAndCoolNoReheat': (
        'vav_heat_cool', ()),
    'to_AirTerminalSingleDuctParallelPIUReheat': (
        'parallel_piu_reheat', (('reheatCoil', 'heat'),)),
    'to_AirTerminalSingleDuctSeriesPIUReheat': (
        'series_piu_reheat', (('reheatCoil', 'heat'),)),
    'to_AirTerminalSingleDuctInletSideMixer': ('inlet_side_mixer', ()),
    'to_AirTerminalSingleDuctConstantVolumeReheat': (
        'cv_reheat', (('reheatCoil', 'heat'),)),
    'to_AirTerminalSingleDuctConstantVolumeNoReheat': ('cv', ()),
    'to_AirTerminalSingleDuctConstantVolumeCooledBeam': (
        'chilled_beam', (('coilCoolingCooledBeam', 'cool'),)),
    'to_AirTerminalSingleDuctConstantVolumeFourPipeBeam': (
        'four_pipe_beam',
        (('heatingCoil', 'heat'), ('coolingCoil', 'cool'))),
    'to_AirTerminalSingleDuctConstantVolumeFourPipeInduction': (
        'four_pipe_induction',
        (('heatingCoil', 'heat'), ('coolingCoil', 'cool'))),
}


def _terminal_facts(group, eq, plant_by_name):
    for cast, (kind, coil_accessors) in TERMINALS.items():
        unit = _try_cast(eq, cast)
        if unit is None:
            continue

        group['terminal_type'] = kind
        for accessor, side in coil_accessors:
            coil = getattr(unit, accessor)()
            if hasattr(coil, 'is_initialized'):
                coil = opt(coil)
            if coil is None:
                continue
            evidence_kind = {
                'reheatCoil': 'reheat coil',
                'coilCoolingCooledBeam': 'cooled-beam coil',
            }.get(accessor, accessor)
            evidence = f"{evidence_kind} on terminal {eq.nameString()}"
            if side == 'heat':
                _scan_heating_component(group, coil, plant_by_name, evidence)
            else:
                _scan_cooling_component(group, coil, plant_by_name, evidence)
        return True
    return False


# ---------------- zonal equipment ----------------

ZONAL = (
    ('to_ZoneHVACBaseboardConvectiveWater', {'heat': 'hydronic', 'kind': 'baseboard'}),
    ('to_ZoneHVACBaseboardConvectiveElectric', {'heat': 'Electricity', 'kind': 'baseboard'}),
    ('to_ZoneHVACBaseboardRadiantConvectiveWater', {'heat': 'hydronic', 'kind': 'baseboard'}),
    ('to_ZoneHVACBaseboardRadiantConvectiveElectric', {'heat': 'Electricity', 'kind': 'baseboard'}),
    ('to_ZoneHVACPackagedTerminalAirConditioner', {'cool': 'Electricity', 'heat': 'coil', 'kind': 'ptac'}),
    ('to_ZoneHVACPackagedTerminalHeatPump', {'heat': 'Electricity', 'cool': 'Electricity', 'hp': True, 'kind': 'pthp'}),
    ('to_ZoneHVACFourPipeFanCoil', {'heat': 'coil', 'cool': 'coil', 'kind': 'fan_coil'}),
    ('to_ZoneHVACTerminalUnitVariableRefrigerantFlow', {'heat': 'Electricity', 'cool': 'Electricity', 'hp': True, 'kind': 'vrf_terminal'}),
    ('to_ZoneHVACUnitHeater', {'heat': 'coil', 'kind': 'unit_heater'}),
    ('to_ZoneHVACUnitVentilator', {'heat': 'coil', 'cool': 'coil', 'kind': 'unit_ventilator'}),
    ('to_ZoneHVACWaterToAirHeatPump', {'heat': 'Electricity', 'cool': 'Electricity', 'hp': True, 'kind': 'wshp'}),
    ('to_ZoneHVACCoolingPanelRadiantConvectiveWater', {'cool': 'hydronic', 'kind': 'radiant'}),
    ('to_ZoneHVACLowTempRadiantConstFlow', {'heat': 'coil', 'cool': 'coil', 'kind': 'radiant'}),
    ('to_ZoneHVACLowTempRadiantVarFlow', {'heat': 'coil', 'cool': 'coil', 'kind': 'radiant'}),
    ('to_ZoneHVACEvaporativeCoolerUnit', {'cool': 'Electricity', 'kind': 'evap_cooler'}),
    ('to_ZoneHVACHighTemperatureRadiant', {'heat': 'Electricity', 'kind': 'radiant'}),
    ('to_ZoneHVACLowTemperatureRadiantElectric', {'heat': 'Electricity', 'kind': 'radiant'}),
)


def _merge_zonal_equipment(group, zone, plant_by_name, _audit):
    for eq in zone.equipment():
        if _terminal_like(eq):
            continue

        for cast, roles in ZONAL:
            unit = _try_cast(eq, cast)
            if unit is None:
                continue

            evidence = f"{eq.iddObjectType().valueName()} in {zone.nameString()}"
            if roles.get('kind'):
                _union(group['zonal_units'], [roles['kind']])
            if roles.get('heat'):
                fuels = _zonal_fuels(
                    unit, roles['heat'], 'heat', plant_by_name)
                if fuels is not None:
                    group['heated'] = True
                    _union(group['heating_energy_types'], fuels)
                    group['evidence'].append(f"heated: {evidence}")
                    _record_plant_heat_pump(
                        group, _zonal_water_coil(unit, 'heat'),
                        plant_by_name)
            if roles.get('cool'):
                fuels = _zonal_fuels(
                    unit, roles['cool'], 'cool', plant_by_name)
                if fuels is not None:
                    group['cooled'] = True
                    _union(group['cooling_energy_types'], fuels)
                    group['evidence'].append(f"cooled: {evidence}")
                    _add_zonal_cooling_capacity(group, unit)
                    water_coil = _zonal_water_coil(unit, 'cool')
                    _record_hydronic_plant(
                        group, water_coil, 'cooling_plants')
                    _record_plant_heat_pump(
                        group, water_coil, plant_by_name)
            _record_heat_pump(group,
                              _zonal_hp_kind(unit) if roles.get('hp') else None,
                              _zonal_hp_coil(unit))
            break
    return group


def _terminal_like(eq):
    return any(hasattr(eq, cast) and getattr(eq, cast)().is_initialized()
               for cast in TERMINALS)


def _zonal_hp_kind(unit):
    """PTHP/VRF terminals are air-source; ZoneHVAC WSHP units are water-to-air
    (their SOURCE loop decides 'water_loop' vs 'external' — see
    _water_to_air_hp_source)."""
    return 'water_to_air' if unit.to_ZoneHVACWaterToAirHeatPump().is_initialized() else 'air'


WTA_COIL_CASTS = ('to_CoilCoolingWaterToAirHeatPumpEquationFit',
                  'to_CoilHeatingWaterToAirHeatPumpEquationFit',
                  'to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit',
                  'to_CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit')


def _zonal_hp_coil(unit):
    wshp = opt(unit.to_ZoneHVACWaterToAirHeatPump())
    if wshp is None:
        return None

    for coil in (wshp.coolingCoil(), wshp.heatingCoil()):
        for cast in WTA_COIL_CASTS:
            c = _try_cast(coil, cast)
            if c is not None:
                return c
    return None


def _zonal_child_coil(unit, side):
    accessor = 'heatingCoil' if side == 'heat' else 'coolingCoil'
    if not hasattr(unit, accessor):
        return None
    coil = getattr(unit, accessor)()
    if hasattr(coil, 'is_initialized'):
        coil = opt(coil)
    return coil


def _zonal_water_coil(unit, side):
    """The hydronic child coil a zonal unit draws from its plant, if any."""
    coil = _zonal_child_coil(unit, side)
    casts = (HYDRONIC_HEATING_COIL_CASTS
             if side == 'heat' else HYDRONIC_COOLING_COILS)
    return next(
        (water_coil for cast in casts
         if (water_coil := _try_cast(coil, cast)) is not None),
        None)


def _zonal_fuels(unit, role, side, plant_by_name):
    if role in ('hydronic', 'coil'):
        coil = _zonal_child_coil(unit, side)
        if coil is None:
            return None
        if side == 'heat':
            for cast, fuel_of, _hp_kind in HEATING_COILS:
                heating_coil = _try_cast(coil, cast)
                if heating_coil is not None:
                    return _array(fuel_of(heating_coil, plant_by_name))
        else:
            water_coil = _zonal_water_coil(unit, side)
            if water_coil is not None:
                return _array(_hydronic_fuels(water_coil, plant_by_name))
            if any(_try_cast(coil, cast) is not None for cast in (
                    'to_CoilCoolingDXSingleSpeed',
                    'to_CoilCoolingDXMultiSpeed',
                    'to_CoilCoolingDXTwoSpeed',
                    'to_CoilCoolingDXVariableSpeed',
                    'to_CoilCoolingWaterToAirHeatPumpEquationFit',
                    'to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit',
                    'to_CoilCoolingDXVariableRefrigerantFlow',
                    'to_CoilCoolingDXVariableRefrigerantFlowFluidTemperatureControl')):
                return ['Electricity']
        return ['Unknown']
    if isinstance(role, str):  # a literal energy type ('Electricity')
        return [role]
    return ['Unknown']


def _add_zonal_cooling_capacity(group, unit):
    coil = _zonal_child_coil(unit, 'cool')
    if coil is None:
        group['cooling_capacity_complete'] = False
        return

    if coil.to_CoilCoolingDXSingleSpeed().is_initialized():
        c = coil.to_CoilCoolingDXSingleSpeed().get()
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif coil.to_CoilCoolingWater().is_initialized():
        kw = _optional_kw(None, coil.to_CoilCoolingWater().get().autosizedDesignCoilLoad())
    elif coil.to_CoilCoolingWaterToAirHeatPumpEquationFit().is_initialized():
        c = coil.to_CoilCoolingWaterToAirHeatPumpEquationFit().get()
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif coil.to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit().is_initialized():
        c = coil.to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit().get()
        kw = _optional_kw(
            c.grossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel(),
            _autosized_when_sized(
                c,
                'autosizedGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel'))
    elif coil.to_CoilCoolingDXVariableRefrigerantFlow().is_initialized():
        c = coil.to_CoilCoolingDXVariableRefrigerantFlow().get()
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif coil.to_CoilCoolingDXVariableRefrigerantFlowFluidTemperatureControl().is_initialized():
        c = coil.to_CoilCoolingDXVariableRefrigerantFlowFluidTemperatureControl().get()
        kw = _optional_kw(
            c.ratedTotalCoolingCapacity(),
            _autosized_when_sized(c, 'autosizedRatedTotalCoolingCapacity'))
    elif coil.to_CoilCoolingWaterPanelRadiant().is_initialized():
        c = coil.to_CoilCoolingWaterPanelRadiant().get()
        kw = _optional_kw(c.coolingDesignCapacity(),
                          _autosized_when_sized(
                              c, 'autosizedCoolingDesignCapacity'))
    elif coil.to_CoilCoolingLowTempRadiantVarFlow().is_initialized():
        c = coil.to_CoilCoolingLowTempRadiantVarFlow().get()
        kw = _optional_kw(c.coolingDesignCapacity(),
                          _autosized_when_sized(
                              c, 'autosizedCoolingDesignCapacity'))
    else:
        kw = None
    if kw is None:
        group['cooling_capacity_complete'] = False
    else:
        group['design_cooling_kw'] += kw


def _zonal_group(zone, plant_by_name, audit):
    group = _base_group([zone.nameString()], None)
    _merge_zonal_equipment(group, zone, plant_by_name, audit)
    group['family_guess'] = _structural_family_guess(group)
    if audit is not None:
        audit.decision('characterize', 'zonal-only group characterized', target=zone.nameString(),
                       inputs={'heated': group['heated'], 'cooled': group['cooled']},
                       value=group['family_guess'],
                       evidence='; '.join(group['evidence']))
    return group


def _structural_family_guess(group):
    """Coarse structural guess for foreign systems (gem-built groups carry exact 'family')."""
    if group['air_loop'] is not None:
        if group['terminal_type'] in (
                'chilled_beam', 'four_pipe_beam', 'four_pipe_induction'):
            return 'chilled_beam'
        if group['terminal_type'].startswith('dual_duct'):
            return 'dual_duct_vav'
        if group['terminal_type'] in (
                'vav_reheat', 'vav', 'vav_heat_cool_reheat',
                'vav_heat_cool', 'parallel_piu_reheat',
                'series_piu_reheat'):
            return 'multizone_vav'
        if group['terminal_type'] == 'cv_reheat':
            return 'multizone_cv'
        return 'central_doas_or_cv' if len(group['zones']) > 1 else 'packaged_single_zone'
    if group['heated'] and group['cooled']:
        return 'zonal_heat_cool'
    if group['heated']:
        return 'zonal_heating_only'
    if group['cooled']:
        return 'zonal_cooling_only'
    return 'unconditioned'
