"""Equipment, plant and sizing sections of a recipe.

Covers osruby's `ecm_fans`, `ecm_pumps`, `ecm_dhw`, `ecm_hotwater_boilers`,
`ecm_cooling_cop`, `ecm_sizing` and `ecm_exhaust_fans`, and campus's three
motor/fan efficiency measures and `upgrade_dhw_plant`.

Grouped BY CLASS rather than by object, per phylroy's constraint: forty fans
in a building are one `fan_total_eff` in a recipe, not forty. The spread is
reported so a reader can see when that single number is a poor summary.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name
from btap.modeling.hvac.efficiency import fan_design_flow, fan_pressure_rise

SPREAD_WARNING_RATIO = 1.5


def _num(value):
    if value is None:
        return None
    if hasattr(value, 'is_initialized'):
        value = opt(value)
        if value is None:
            return None
    return float(value)


def _weighted_aggregate(pairs, label, weight_name):
    """A WEIGHTED mean of `(value, weight)` pairs, with its provenance.

    phylroy, 2026-11-06: **weighted averages are the way** — and the envelope
    section has always known it, aggregating U by AREA because the effective U
    of an assembly set is sum(U*A)/sum(A). This brings the equipment section
    into line.

    MEASURED, and the reason this exists (#202): fan power is P x Q, so an
    UNWEIGHTED mean of pressure is wrong whenever flows differ. On
    `Office_pre-1960` the seven exhaust fans are one 658.2 Pa fan moving
    6.8 m3/s and six 100 Pa fans moving at most 1.12 — the big one is 88% of
    the class's fan power. Unweighted mean 179.74 Pa; FLOW-WEIGHTED 403.39.
    Applying the unweighted value cost 172 GJ/yr and made the round trip
    WORSE than the global average it replaced (-6.49% against -5.23%).

    When any member lacks a weight — an autosized fan has no authored flow —
    this falls back to the UNWEIGHTED mean and says so in the provenance,
    because weighting by an invented number is worse than declining to weight.
    """
    present = [(v, w) for v, w in pairs if v is not None]
    if not present:
        return None

    weights = [w for _v, w in present]
    unweighable = [w for w in weights if w is None or w <= 0]
    values = [v for v, _w in present]

    if unweighable:
        out = _aggregate(values, label)
        if out is not None:
            out['from']['weighting'] = (
                f'UNWEIGHTED — {len(unweighable)} of {len(present)} carry no '
                f'{weight_name}, so an unweighted mean was used. Fan power is '
                'flow-weighted, so this value understates it.')
        return out

    total = sum(weights)
    mean = sum(v * w for v, w in present) / total
    lo, hi = min(values), max(values)
    out = {'value': round(mean, 6),
           'from': {'objects': len(present), 'min': round(lo, 6),
                    'max': round(hi, 6),
                    'weighting': f'weighted by {weight_name}',
                    f'total_{weight_name}': round(total, 6)}}
    if lo:
        ratio = hi / lo
        out['from']['spread_ratio'] = round(ratio, 2)
        if ratio > SPREAD_WARNING_RATIO:
            out['from']['spread_warning'] = (
                f'{len(present)} {label} span {round(ratio, 2)}x; the '
                f'{weight_name}-weighted mean preserves the aggregate they '
                'drive, but no single value reproduces each object')
    return out


def _aggregate(values, label):
    present = [v for v in values if v is not None]
    if not present:
        return None
    mean = sum(present) / len(present)
    lo, hi = min(present), max(present)
    out = {'value': round(mean, 6),
           'from': {'objects': len(present), 'min': round(lo, 6),
                    'max': round(hi, 6)}}
    if lo:
        ratio = hi / lo
        out['from']['spread_ratio'] = round(ratio, 2)
        if ratio > SPREAD_WARNING_RATIO:
            out['from']['spread_warning'] = (
                f'{len(present)} {label} span {round(ratio, 2)}x, so one '
                'value is a lossy summary')
    return out


def _fans(model):
    """Fan total and motor efficiency, by class.

    `FanZoneExhaust` has no motor-efficiency field and `FanComponentModel` has
    neither scalar — both measured in #192's cluster 1 — so each class is read
    for what it actually carries rather than through a duck-typed getattr
    that would silently report nothing.
    """
    classes = (
        ('FanConstantVolume', model.getFanConstantVolumes, True),
        ('FanVariableVolume', model.getFanVariableVolumes, True),
        ('FanOnOff', model.getFanOnOffs, True),
        ('FanSystemModel', model.getFanSystemModels, True),
        ('FanZoneExhaust', model.getFanZoneExhausts, False),
    )
    out, counts = {}, {}
    totals, motors = [], []
    pressure_by_class = {}
    for name, getter, has_motor in classes:
        fans = sorted_by_name(getter())
        if not fans:
            continue
        counts[name] = len(fans)
        totals += [_num(f.fanTotalEfficiency()) for f in fans]
        if has_motor:
            motors += [_num(f.motorEfficiency()) for f in fans]
        # Pressure rise is aggregated PER CLASS, not globally, and that is the
        # whole point. Read via the per-class accessor because `FanSystemModel`
        # spells it `designPressureRise`, so a duck-typed `pressureRise` would
        # skip it silently.
        #
        # MEASURED (#202, round trip against the repaired source archetype):
        # a GLOBAL average loses 138 GJ/yr, 62% of the remaining -5.23% gap.
        # `Office_pre-1960` carries 27 fans spanning 100-658 Pa with its
        # constant-volume SUPPLY fans at 500 Pa; the global mean is 278.1, so
        # rebuilt supply fans dropped 500 -> 278 while unit-heater fans rose
        # 100 -> 278. Fan power is FLOW-WEIGHTED and the supply fans move by
        # far the most air, so an unweighted average of pressure does not
        # preserve fan energy. One value per CLASS keeps the recipe's declared
        # design — one value per class of thing, not forty — while preserving
        # the distinction that carries the energy.
        pairs = [(fan_pressure_rise(f), fan_design_flow(f)) for f in fans]
        if any(v is not None for v, _w in pairs):
            pressure_by_class[name] = pairs

    detailed = model.getFanComponentModels()
    if detailed:
        counts['FanComponentModel'] = len(detailed)

    total = _aggregate(totals, 'fans')
    if total is not None:
        out['fan_total_eff'] = total
    motor = _aggregate(motors, 'fan motors')
    if motor is not None:
        out['fan_motor_eff'] = motor
    pressures = {}
    for name, pairs in pressure_by_class.items():
        aggregate = _weighted_aggregate(
            pairs, f'{name} pressure rise', 'design_flow_m3_s')
        if aggregate is not None:
            pressures[name] = aggregate
    if pressures:
        out['fan_pressure_rise_pa_by_class'] = pressures
    if not out:
        return None
    out['from'] = {'by_class': counts}
    if detailed:
        out['from']['note'] = (
            f'{len(detailed)} FanComponentModel fan(s) carry no scalar '
            'efficiency — their performance is in curves and is NOT included '
            'in these values')
    return out


def _pumps(model):
    classes = (('PumpConstantSpeed', model.getPumpConstantSpeeds),
               ('PumpVariableSpeed', model.getPumpVariableSpeeds),
               ('HeaderedPumpsConstantSpeed',
                model.getHeaderedPumpsConstantSpeeds),
               ('HeaderedPumpsVariableSpeed',
                model.getHeaderedPumpsVariableSpeeds))
    values, counts, speed_types = [], {}, []
    for name, getter in classes:
        pumps = sorted_by_name(getter())
        if not pumps:
            continue
        counts[name] = len(pumps)
        values += [_num(p.motorEfficiency()) for p in pumps]
        speed_types.append('variable' if 'Variable' in name else 'constant')
    agg = _aggregate(values, 'pumps')
    if agg is None:
        return None
    return {'pump_motor_eff': agg,
            'pump_speed_type': sorted(set(speed_types)),
            'from': {'by_class': counts}}


def _water_heaters(model):
    """SHW plant: thermal efficiency, fuel, and the mixed-tank UA.

    Only a `WaterHeaterMixed` carries the on/off-cycle ambient-loss pair; a
    `WaterHeaterStratified` parameterises loss differently (flue versus skin,
    skin per unit area), so its UA is NOT read into the same field. #192's
    cluster 3 established that asymmetry.
    """
    mixed = sorted_by_name(model.getWaterHeaterMixeds())
    stratified = sorted_by_name(model.getWaterHeaterStratifieds())
    if not mixed and not stratified:
        return None

    out = {}
    efficiency = _aggregate(
        [_num(h.heaterThermalEfficiency()) for h in mixed]
        + [_num(h.heaterThermalEfficiency()) for h in stratified],
        'water heaters')
    if efficiency is not None:
        out['shw_thermal_eff'] = efficiency

    fuels = sorted({h.heaterFuelType() for h in mixed}
                   | {h.heaterFuelType() for h in stratified})
    if fuels:
        out['shw_heater_fuel_type'] = fuels

    ua = _aggregate(
        [_num(h.offCycleLossCoefficienttoAmbientTemperature()) for h in mixed],
        'mixed tanks')
    if ua is not None:
        out['shw_off_cycle_ua_w_per_k'] = ua

    # MIXED tanks only, and for the same reason as the UA above: a
    # `WaterHeaterStratified` has no single `setpointTemperatureSchedule()` —
    # measured, its schedule accessors are per-heater plus
    # `indirectAlternateSetpointTemperatureSchedule`. Reading a stratified
    # tank's "setpoint" into this field would merge two different quantities.
    setpoints = sorted({opt(h.setpointTemperatureSchedule()).nameString()
                        for h in mixed
                        if opt(h.setpointTemperatureSchedule()) is not None})
    if setpoints:
        out['shw_setpoint_sched_name'] = setpoints

    out['from'] = {'WaterHeaterMixed': len(mixed),
                   'WaterHeaterStratified': len(stratified)}
    if stratified:
        out['from']['note'] = (
            f'{len(stratified)} stratified tank(s) are included in the '
            'efficiency but NOT in the UA or the setpoint schedule: they '
            'split flue from skin loss and express skin per unit area, and '
            'their setpoints are per-heater — neither is the mixed-tank '
            'quantity those fields hold')
    return out


def _boilers(model):
    boilers = sorted_by_name(model.getBoilerHotWaters())
    if not boilers:
        return None
    out = {}
    efficiency = _aggregate(
        [_num(b.nominalThermalEfficiency()) for b in boilers], 'boilers')
    if efficiency is not None:
        out['hw_boiler_thermal_eff'] = efficiency
    # NOT osruby's `hw_boiler_design_water_outlet_temperature`. `BoilerHotWater`
    # has no such field — measured, it carries
    # `waterOutletUpperTemperatureLimit()`, which is a LIMIT, not a design
    # setpoint. The design outlet temperature is a property of the plant loop's
    # setpoint manager, so mapping osruby's field to this one would label a
    # different quantity with its name. Reported under its own name instead,
    # and osruby's field is declared unmapped below.
    limit = _aggregate(
        [_num(b.waterOutletUpperTemperatureLimit()) for b in boilers],
        'boilers')
    if limit is not None:
        out['hw_boiler_water_outlet_upper_temperature_limit'] = limit
    out['hw_boiler_fuel_type'] = sorted({b.fuelType() for b in boilers})
    out['hw_boiler_flow_mode'] = sorted({b.boilerFlowMode()
                                         for b in boilers})
    out['from'] = {'boilers': len(boilers)}
    out['not_mapped'] = [
        {'field': 'hw_boiler_design_water_outlet_temperature',
         'why': 'BoilerHotWater has no design-outlet-temperature field; the '
                'design supply temperature belongs to the plant loop setpoint '
                'manager, so it is not a boiler property to read'},
    ]
    return out


def _cooling(model):
    """Cooling COP, by equipment class — osruby's `ecm_cooling_cop`.

    THE GAP A SIMULATION FOUND. The writer carried no cooling efficiency at
    all, so a reader that rebuilt the HVAC got the catalogue default: measured
    on `Office_pre-1960`, every DX coil in the source model is COP 2.50 and
    every rebuilt one came out 3.00 — a 20% efficiency gift the recipe had no
    way to prevent, and the field was in the inventory
    (`ecm_cooling_cop: ['cop']`) the whole time.

    All three accessors are plain doubles, not optionals — `ratedCOP()`,
    `ratedHighSpeedCOP()`, `referenceCOP()` — which is worth stating because
    `opt()` on any of them raises.
    """
    out = {}
    single = [c.ratedCOP() for c in sorted_by_name(
        model.getCoilCoolingDXSingleSpeeds())]
    agg = _aggregate(single, 'DX single-speed coils')
    if agg is not None:
        out['dx_single_speed_cop'] = agg

    two_high = [c.ratedHighSpeedCOP() for c in sorted_by_name(
        model.getCoilCoolingDXTwoSpeeds())]
    agg = _aggregate(two_high, 'DX two-speed coils')
    if agg is not None:
        out['dx_two_speed_high_cop'] = agg
    two_low = [c.ratedLowSpeedCOP() for c in sorted_by_name(
        model.getCoilCoolingDXTwoSpeeds())]
    agg = _aggregate(two_low, 'DX two-speed coils')
    if agg is not None:
        out['dx_two_speed_low_cop'] = agg

    chillers = [c.referenceCOP() for c in sorted_by_name(
        model.getChillerElectricEIRs())]
    agg = _aggregate(chillers, 'chillers')
    if agg is not None:
        out['chiller_cop'] = agg
        out['chiller_type'] = sorted({c.condenserType() for c in
                                      model.getChillerElectricEIRs()})
    return out or None


def _sizing(model):
    sizing = model.getSizingParameters()
    out = {}
    for field, reader in (
            ('heating_sizing_factor', 'heatingSizingFactor'),
            ('cooling_sizing_factor', 'coolingSizingFactor')):
        value = _num(getattr(sizing, reader)())
        if value is not None:
            out[field] = value

    zone_heating, zone_cooling = [], []
    for zone in sorted_by_name(model.getThermalZones()):
        # `SizingZone sizingZone()` — by value, NOT an optional, so no
        # `opt()`. Its two factors ARE `boost::optional<double>`, which `_num`
        # absorbs.
        zone_sizing = zone.sizingZone()
        zone_heating.append(_num(
            zone_sizing.zoneHeatingSizingFactor()))
        zone_cooling.append(_num(
            zone_sizing.zoneCoolingSizingFactor()))
    for field, values in (('zone_heating_sizing_factor', zone_heating),
                          ('zone_cooling_sizing_factor', zone_cooling)):
        agg = _aggregate(values, 'zones')
        if agg is not None:
            out[field] = agg
    return out or None


def equipment_section(model, audit=None):
    """The recipe's equipment, plant and sizing section.

    A sub-section is omitted when the model has none of that equipment, and
    present-but-unreadable fields are left out of their sub-section rather
    than defaulted.
    """
    section = {}
    for key, reader in (('fans', _fans), ('pumps', _pumps),
                        ('water_heaters', _water_heaters),
                        ('boilers', _boilers), ('cooling', _cooling),
                        ('sizing', _sizing)):
        got = reader(model)
        if got is not None:
            section[key] = got
    if audit is not None:
        audit.info('recipe', 'equipment and plant read',
                   inputs={'sections': sorted(section)})
    return section
