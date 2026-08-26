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
          'terminal_type': 'vav_reheat'|'cv_reheat'|'cv'|'none',
          'design_cooling_kw': 42.0|None,
          'dcv': False, 'system_outdoor_air_method': 'ZoneSum'|None } ],
      'plants': [ { 'name':, 'type': 'hot_water'|'chilled_water'|'condenser'|'service_water'|'other',
                    'fuels': ['NaturalGas'], 'purchased': False, 'heat_pump': False } ],
      'purchased_energy': { 'heating': False, 'cooling': False }
    }
"""

from __future__ import annotations

import re

from btap._compat import opt, sorted_by_name
from btap.modeling.hvac import catalog
from btap.modeling.hvac.components import coils

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

def _plant_facts(loop, audit):
    fuels = []
    purchased = False
    heat_pump = False
    has_boiler = has_chiller = has_rejection = False

    for comp in loop.supplyComponents():
        if comp.to_BoilerHotWater().is_initialized():
            has_boiler = True
            fuels.append(comp.to_BoilerHotWater().get().fuelType())
        elif comp.to_ChillerElectricEIR().is_initialized():
            has_chiller = True
            fuels.append('Electricity')
        elif comp.to_DistrictHeating().is_initialized() or _defined_district_heating_water(comp):
            purchased = True
            fuels.append('Purchased')
        elif comp.to_DistrictCooling().is_initialized():
            purchased = True
            fuels.append('Purchased')
        elif (comp.to_HeatPumpPlantLoopEIRHeating().is_initialized() or
              comp.to_HeatPumpWaterToWaterEquationFitHeating().is_initialized()):
            heat_pump = True
            fuels.append('Electricity')
        elif comp.to_HeatPumpPlantLoopEIRCooling().is_initialized():
            heat_pump = True
            fuels.append('Electricity')
        elif (comp.to_CoolingTowerSingleSpeed().is_initialized() or
              comp.to_EvaporativeFluidCoolerSingleSpeed().is_initialized() or
              comp.to_GroundHeatExchangerVertical().is_initialized()):
            has_rejection = True
        elif comp.to_WaterHeaterMixed().is_initialized():
            fuels.append(comp.to_WaterHeaterMixed().get().heaterFuelType())

    swh = any(c.to_WaterUseConnections().is_initialized() for c in loop.demandComponents())
    if swh:
        type_ = 'service_water'
    elif has_boiler or (purchased and _heating_loop(loop)) or (heat_pump and _heating_loop(loop)):
        type_ = 'hot_water'
    elif has_chiller or (purchased and not _heating_loop(loop)):
        type_ = 'chilled_water'
    elif has_rejection:
        type_ = 'condenser'
    elif heat_pump:
        type_ = 'hot_water'
    else:
        type_ = 'other'

    facts = {'name': loop.nameString(), 'type': type_,
             'fuels': list(dict.fromkeys(fuels)),
             'purchased': purchased, 'heat_pump': heat_pump}
    if audit is not None:
        audit.info('characterize', 'plant loop classified', target=loop.nameString(),
                   value=type_, inputs={'fuels': facts['fuels'], 'purchased': purchased})
    return facts


def _defined_district_heating_water(comp):
    """DistrictHeatingWater replaced DistrictHeating at OS 3.7; handle both SDKs."""
    return hasattr(comp, 'to_DistrictHeatingWater') and comp.to_DistrictHeatingWater().is_initialized()


def _heating_loop(loop):
    exit_c = loop.sizingPlant().designLoopExitTemperature()
    return exit_c > 30.0  # hot loops design well above chilled/condenser temperatures


# ---------------- air-loop groups ----------------

def _air_loop_group(air_loop, plant_by_name, audit):
    group = _base_group([z.nameString() for z in air_loop.thermalZones()],
                        air_loop.nameString())
    _recognize_gem_name(group, air_loop, audit)
    _outdoor_air_facts(group, air_loop, audit)

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
        audit.decision('characterize', 'zone group characterized', target=air_loop.nameString(),
                       inputs={'zones': len(group['zones']), 'terminal': group['terminal_type']},
                       value=group['family'] or group['family_guess'],
                       evidence='; '.join(group['evidence']))
    return group


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
HEATING_COILS = [
    ('to_CoilHeatingGas', lambda _c, _p: 'NaturalGas', False),
    ('to_CoilHeatingGasMultiStage', lambda _c, _p: 'NaturalGas', False),
    ('to_CoilHeatingDXMultiSpeed', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingElectric', lambda _c, _p: 'Electricity', None),
    ('to_CoilHeatingWater', lambda c, p: _hydronic_fuels(c, p), None),
    ('to_CoilHeatingDXSingleSpeed', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingDXVariableSpeed', lambda _c, _p: 'Electricity', 'air'),
    ('to_CoilHeatingWaterBaseboard', lambda c, p: _hydronic_fuels(c, p), None),
    ('to_CoilHeatingWaterToAirHeatPumpEquationFit', lambda _c, _p: 'Electricity', 'water_to_air'),
    ('to_CoilHeatingDXVariableRefrigerantFlow', lambda _c, _p: 'Electricity', 'air'),
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
    _union(group['heat_pump_sources'], [plant.get('hp_source') or 'water_loop'])
    _union(group['heat_pump_source_loops'],
           [n for n in [plant.get('hp_source_loop_name')] if n is not None])
    group['evidence'].append(
        f"plant heat pump on '{plant['name']}' (source {plant.get('hp_source') or 'water_loop'})")


def _zonal_water_heating_coil(unit):
    """The water heating coil a zonal unit draws from its plant, if any."""
    coil = unit.heatingCoil() if hasattr(unit, 'heatingCoil') else None
    if coil is not None and hasattr(coil, 'is_initialized') and coil.is_initialized():
        coil = coil.get()
    if coil is None or not hasattr(coil, 'to_CoilHeatingWater'):
        return None

    if coil.to_CoilHeatingWater().is_initialized():
        return coil.to_CoilHeatingWater().get()
    if (hasattr(coil, 'to_CoilHeatingWaterBaseboard') and
            coil.to_CoilHeatingWaterBaseboard().is_initialized()):
        return coil.to_CoilHeatingWaterBaseboard().get()

    return None


def _record_heat_pump(group, hp_kind, unit):
    """D-37 (Note A-8.4.4.13): heat-pump SOURCE matters for the 8.4.4.13
    reference redirect — water-LOOP (internal loop, aux boiler/tower
    allowed) stays on Table -A; air/water/ground-SOURCE redirects."""
    if not hp_kind:
        return

    group['heat_pump'] = True
    _union(group['heat_pump_sources'],
           [_water_to_air_hp_source(unit) if hp_kind == 'water_to_air' else 'air'])
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
                c.to_DistrictHeating().is_initialized() or
                c.to_DistrictCooling().is_initialized() or
                _defined_district_heating_water(c) or
                (hasattr(c, 'to_PlantComponentTemperatureSource') and
                 c.to_PlantComponentTemperatureSource().is_initialized())):
            return True
    return False


def _water_to_air_hp_source(coil):
    """Classify a water-to-air heat pump by its SOURCE loop per Note
    A-8.4.4.13 (see _external_source_loop)."""
    loop = opt(coil.plantLoop()) if coil is not None and hasattr(coil, 'plantLoop') else None
    if loop is None:
        return 'water_loop'

    return 'external' if _external_source_loop(loop) else 'water_loop'


PLANT_HP_CASTS = ('to_HeatPumpPlantLoopEIRHeating', 'to_HeatPumpWaterToWaterEquationFitHeating',
                  'to_HeatPumpPlantLoopEIRCooling', 'to_HeatPumpWaterToWaterEquationFitCooling')


def _annotate_heat_pump_plants(model, plant_by_name):
    """Classify each heat-pump PLANT's source per Note A-8.4.4.13 (D-58): the HP
    object's source-side loop carries the evidence — external components =>
    'external' (water/ground source); a plain internal loop => 'water_loop';
    no source loop at all (air-source condenser) => 'air'. The source loop is
    flagged (`hp_source_loop`) so purchased-energy detection skips it: a
    district object standing in for a ground field (the legacy GLHX pattern)
    is not purchased heating for the building."""
    for loop in model.getPlantLoops():
        plant = plant_by_name.get(loop.nameString())
        if not (plant and plant['heat_pump']):
            continue

        source = None
        for comp in loop.supplyComponents():
            for cast in PLANT_HP_CASTS:
                hp = _try_cast(comp, cast)
                if hp is None:
                    continue

                secondary = opt(hp.secondaryPlantLoop()) if hasattr(hp, 'secondaryPlantLoop') else None
                if secondary is None:
                    source = source or 'air'
                else:
                    src_plant = plant_by_name.get(secondary.nameString())
                    if src_plant is not None:
                        src_plant['hp_source_loop'] = True
                    plant['hp_source_loop_name'] = secondary.nameString()
                    source = 'external' if _external_source_loop(secondary) else (source or 'water_loop')
        plant['hp_source'] = source or 'water_loop'


def _scan_cooling_component(group, comp, plant_by_name, evidence):
    kw = None
    fuels = None
    hp = None
    hp_unit = None
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
    elif comp.to_CoilCoolingWater().is_initialized():
        c = comp.to_CoilCoolingWater().get()
        fuels = _hydronic_fuels(c, plant_by_name)
        kw = _optional_kw(None, c.autosizedDesignCoilLoad())
    elif comp.to_CoilCoolingWaterToAirHeatPumpEquationFit().is_initialized():
        c = comp.to_CoilCoolingWaterToAirHeatPumpEquationFit().get()
        fuels = 'Electricity'
        hp = 'water_to_air'
        hp_unit = c
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif comp.to_CoilCoolingDXVariableRefrigerantFlow().is_initialized():
        c = comp.to_CoilCoolingDXVariableRefrigerantFlow().get()
        fuels = 'Electricity'
        hp = 'air'
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif comp.to_EvaporativeCoolerDirectResearchSpecial().is_initialized():
        fuels = 'Electricity'
        kw = 0.0
    else:
        return False

    group['cooled'] = True
    _union(group['cooling_energy_types'], _array(fuels))
    _record_heat_pump(group, hp, hp_unit)
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


# ---------------- 8.4.4.13.(2)(g) heating-election inventory (D-52) ----------------

BASEBOARD_VARIABLE = 'Baseboard Total Heating Energy'
COIL_VARIABLE = 'Heating Coil Heating Energy'

DX_HEATING_CASTS = ('to_CoilHeatingDXSingleSpeed', 'to_CoilHeatingDXMultiSpeed',
                    'to_CoilHeatingDXVariableSpeed', 'to_CoilHeatingWaterToAirHeatPumpEquationFit',
                    'to_CoilHeatingDXVariableRefrigerantFlow')
AUX_COIL_FUELS = {
    'to_CoilHeatingGas': 'NaturalGas',
    'to_CoilHeatingGasMultiStage': 'NaturalGas',
    'to_CoilHeatingElectric': 'Electricity',
    'to_CoilHeatingWater': 'hydronic',
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
    ('to_AirTerminalSingleDuctVAVReheat', ('reheatCoil',)),
    ('to_AirTerminalSingleDuctConstantVolumeReheat', ('reheatCoil',)),
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
    'to_AirTerminalSingleDuctVAVReheat': 'vav_reheat',
    'to_AirTerminalSingleDuctVAVNoReheat': 'vav',
    'to_AirTerminalSingleDuctConstantVolumeReheat': 'cv_reheat',
    'to_AirTerminalSingleDuctConstantVolumeNoReheat': 'cv',
}


def _terminal_facts(group, eq, plant_by_name):
    for cast, kind in TERMINALS.items():
        optional = getattr(eq, cast)()
        if not optional.is_initialized():
            continue

        group['terminal_type'] = kind
        if kind in ('vav_reheat', 'cv_reheat'):
            coil = optional.get().reheatCoil()
            _scan_heating_component(group, coil, plant_by_name,
                                    f"reheat coil on terminal {eq.nameString()}")
        return True
    return False


# ---------------- zonal equipment ----------------

ZONAL = (
    ('to_ZoneHVACBaseboardConvectiveWater', {'heat': 'hydronic', 'kind': 'baseboard'}),
    ('to_ZoneHVACBaseboardConvectiveElectric', {'heat': 'Electricity', 'kind': 'baseboard'}),
    ('to_ZoneHVACPackagedTerminalAirConditioner', {'cool': 'Electricity', 'heat': 'coil', 'kind': 'ptac'}),
    ('to_ZoneHVACPackagedTerminalHeatPump', {'heat': 'Electricity', 'cool': 'Electricity', 'hp': True, 'kind': 'pthp'}),
    ('to_ZoneHVACFourPipeFanCoil', {'heat': 'coil', 'cool': 'coil', 'kind': 'fan_coil'}),
    ('to_ZoneHVACTerminalUnitVariableRefrigerantFlow', {'heat': 'Electricity', 'cool': 'Electricity', 'hp': True, 'kind': 'vrf_terminal'}),
    ('to_ZoneHVACUnitHeater', {'heat': 'coil', 'kind': 'unit_heater'}),
    ('to_ZoneHVACWaterToAirHeatPump', {'heat': 'Electricity', 'cool': 'Electricity', 'hp': True, 'kind': 'wshp'}),
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
                group['heated'] = True
                _union(group['heating_energy_types'],
                       _zonal_fuels(unit, roles['heat'], 'heat', plant_by_name))
                group['evidence'].append(f"heated: {evidence}")
                _record_plant_heat_pump(group, _zonal_water_heating_coil(unit), plant_by_name)
            if roles.get('cool'):
                group['cooled'] = True
                _union(group['cooling_energy_types'],
                       _zonal_fuels(unit, roles['cool'], 'cool', plant_by_name))
                group['evidence'].append(f"cooled: {evidence}")
                _add_zonal_cooling_capacity(group, unit)
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


def _zonal_fuels(unit, role, side, plant_by_name):
    if role == 'hydronic':
        coil = unit.heatingCoil()
        bb = coil.to_CoilHeatingWaterBaseboard()
        if bb.is_initialized():
            return _array(_hydronic_fuels(bb.get(), plant_by_name))
        return ['Unknown']
    if role == 'coil':
        coil = unit.heatingCoil() if side == 'heat' else unit.coolingCoil()
        if hasattr(coil, 'is_initialized') and coil.is_initialized():
            coil = coil.get()
        if coil is None:
            return ['Unknown']
        if coil.to_CoilHeatingGas().is_initialized():
            return ['NaturalGas']
        if (coil.to_CoilHeatingElectric().is_initialized() or
                coil.to_CoilCoolingDXSingleSpeed().is_initialized()):
            return ['Electricity']
        if coil.to_CoilHeatingWater().is_initialized():
            return _array(_hydronic_fuels(coil.to_CoilHeatingWater().get(), plant_by_name))
        if coil.to_CoilCoolingWater().is_initialized():
            return _array(_hydronic_fuels(coil.to_CoilCoolingWater().get(), plant_by_name))

        return ['Unknown']
    if isinstance(role, str):  # a literal energy type ('Electricity')
        return [role]
    return ['Unknown']


def _add_zonal_cooling_capacity(group, unit):
    coil = unit.coolingCoil() if hasattr(unit, 'coolingCoil') else None
    if coil is not None and hasattr(coil, 'is_initialized') and coil.is_initialized():
        coil = coil.get()
    if coil is None:
        return

    if coil.to_CoilCoolingDXSingleSpeed().is_initialized():
        c = coil.to_CoilCoolingDXSingleSpeed().get()
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif coil.to_CoilCoolingWater().is_initialized():
        kw = _optional_kw(None, coil.to_CoilCoolingWater().get().autosizedDesignCoilLoad())
    elif coil.to_CoilCoolingWaterToAirHeatPumpEquationFit().is_initialized():
        c = coil.to_CoilCoolingWaterToAirHeatPumpEquationFit().get()
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
    elif coil.to_CoilCoolingDXVariableRefrigerantFlow().is_initialized():
        c = coil.to_CoilCoolingDXVariableRefrigerantFlow().get()
        kw = _optional_kw(c.ratedTotalCoolingCapacity(), c.autosizedRatedTotalCoolingCapacity())
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
        if group['terminal_type'] in ('vav_reheat', 'vav'):
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
