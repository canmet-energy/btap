"""Part 5 prescriptive QAQC checker (port of btap-necb's hvac/checker.rb).

First slice — WARNINGS ONLY, never modifies the model. Checks a PROPOSED design
against:
  5.2.2.8  air economizer capability on mechanically-cooled air systems
  5.2.10.1 heat/energy recovery where the Table 5.2.10.1.-A/-B airflow
           thresholds are met (the same table trigger the reference pass
           uses; needs hdd= and SIZED supply/OA flows)
  5.2.12   equipment minimum efficiencies — checked by applying the NECB
           efficiency pass to a CLONE and diffing: any proposed value
           below what the pass would set is below the Table 5.2.12.1
           minimum (reuses the full lookup machinery with zero drift)

Out of this slice (documented): duct/pipe insulation (5.2.2/5.2.5), fan power
limits 5.2.3, controls 5.2.8, VAV 5.2.11.
"""

from __future__ import annotations

import re

import openstudio

from btap._compat import ruby_round, sorted_by_name
from btap.modeling.hvac.components import coils as _coils
from btap.necb.hvac import efficiency as _efficiency
from btap.necb.hvac.energy_recovery import annual_availability_hours, erv_threshold_verdict
from btap.necb.hvac.reference import optional_flow, rules

TOLERANCE = 1e-3


def check_part5(model, vintage='2020', building=None, hdd=None, audit=None):
    """:param hdd: heating degree-days — enables the 5.2.10.1 heat-recovery check
        (skipped with an info note otherwise)
    :param building: unused (kept for call-site compatibility; the old 150 kW
        trigger read winter_design_temp_c from it)
    :return: AuditLog
    """
    from btap.audit import AuditLog

    audit = audit if audit is not None else AuditLog()
    check_economizers(model, audit)
    check_heat_recovery(model, vintage, hdd, audit)
    check_minimum_efficiencies(model, vintage, audit)
    audit.decision('check_part5', 'Part 5 prescriptive QAQC complete (economizers, heat recovery, '
                                  'minimum efficiencies; duct/pipe insulation, fan power limits and '
                                  'controls are outside this slice)',
                   inputs={'warnings': len(audit.warnings)},
                   article='5.2.2.8.; 5.2.10.1.; 5.2.12.')
    return audit


def check_economizers(model, audit):
    """5.2.2.8.(1): mechanically-cooled systems that could cool with outdoor
    air must be capable of up to 100% outdoor air."""
    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        oa_system = air_loop.airLoopHVACOutdoorAirSystem()
        if oa_system.empty():
            continue

        cooled = any(re.search(r'Coil_Cooling|CoilSystem_Cooling', c.iddObjectType().valueName())
                     for c in _coils.supply_components(air_loop))
        if not cooled:
            continue

        controller = oa_system.get().getControllerOutdoorAir()
        if controller.getEconomizerControlType() == 'NoEconomizer':
            # D-56: cooling with outside air can be satisfied INDIRECTLY. Where the
            # loop's chilled water already carries a 5.2.2.9 water-side economizer,
            # 5.2.2.9 is the applicable article and the absence of an AIR economizer
            # is not a finding — the old warning fired on exactly the loops the
            # reference builder now equips.
            economized = water_economizer_loops(air_loop)
            if economized:
                audit.info('check_part5',
                           'no air economizer, but the chilled water is cooled by a 5.2.2.9 water-side '
                           'economizer — cooling with outside air is provided indirectly',
                           target=air_loop.nameString(), inputs={'plant_loops': economized},
                           article='5.2.2.9.', ruling='D-56')
                continue
            audit.warn('check_part5',
                       'mechanically-cooled air system has NO economizer — 5.2.2.8.(1) requires the capability '
                       'to mix up to 100% outdoor air with differential reversion (5.2.2.8.(2))',
                       target=air_loop.nameString(), article='5.2.2.8.')
        else:
            audit.info('check_part5', f'economizer present ({controller.getEconomizerControlType()})',
                       target=air_loop.nameString(), article='5.2.2.8.')


def water_economizer_loops(air_loop):
    """Names of the chilled-water loops feeding this air loop's water cooling coils
    that carry a water-side economizer heat exchanger (D-56)."""
    names = []
    for component in _coils.supply_components(air_loop):
        if not (hasattr(component, 'to_CoilCoolingWater')
                and component.to_CoilCoolingWater().is_initialized()):
            continue

        plant = component.to_CoilCoolingWater().get().plantLoop()
        if not plant.is_initialized():
            continue
        if not len(plant.get().supplyComponents(
                openstudio.model.HeatExchangerFluidToFluid.iddObjectType())):
            continue

        name = plant.get().nameString()
        if name not in names:
            names.append(name)
    return names


def check_heat_recovery(model, vintage, hdd, audit):
    """5.2.10.1: same Table 5.2.10.1.-A/-B trigger as the reference ERV rule."""
    if hdd is None:
        audit.info('check_part5', '5.2.10.1 heat-recovery check skipped — pass hdd: to evaluate the '
                                  'Table 5.2.10.1.-A/-B airflow thresholds')
        return

    rule = rules(vintage).get('energy_recovery')
    if rule is None:
        return

    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        oa_system = air_loop.airLoopHVACOutdoorAirSystem()
        if oa_system.empty():
            continue

        supply = (optional_flow(air_loop.designSupplyAirFlowRate())
                  or optional_flow(air_loop.autosizedDesignSupplyAirFlowRate()))
        ctrl = oa_system.get().getControllerOutdoorAir()
        min_oa = (optional_flow(ctrl.minimumOutdoorAirFlowRate())
                  or optional_flow(ctrl.autosizedMinimumOutdoorAirFlowRate()))
        if supply is None or min_oa is None or supply == 0:
            audit.info('check_part5', '5.2.10.1 heat-recovery check needs SIZED supply/OA flows — not evaluated '
                                      '(run sizing first)', target=air_loop.nameString())
            continue

        oa_pct = 100.0 * min_oa / supply
        hours = annual_availability_hours(air_loop)
        mode = ('continuous' if hours is None or hours >= rule['continuous_hours_per_year']
                else 'non_continuous')
        required, threshold_desc = erv_threshold_verdict(rule, mode, hdd, oa_pct, supply * 1000.0)
        if not required:
            continue

        has_recovery = any(re.search(r'HeatExchanger', c.iddObjectType().valueName())
                           for c in oa_system.get().oaComponents())
        if has_recovery:
            continue

        audit.warn('check_part5',
                   f"supply {ruby_round(supply * 1000)} L/s at {ruby_round(oa_pct, 1)}% OA "
                   f"({mode.replace('_', '-')}) meets the "
                   f'Table 5.2.10.1 trigger ({threshold_desc}) but NO heat/energy recovery is present — '
                   '5.2.10.1 requires it',
                   target=air_loop.nameString(), article=rule['trigger_article'])


def check_minimum_efficiencies(model, vintage, audit):
    """5.2.12: apply the NECB efficiency pass to a clone; any proposed value
    BELOW the applied value is below the code minimum. Capacity-binned
    rows need SIZED equipment — unsized items are skipped by the pass
    (run a sizing run first for full coverage)."""
    clone = model.clone(True).to_Model()
    _efficiency.apply(clone, vintage=vintage)
    unsized = sum(1 for c in model.getCoilCoolingDXSingleSpeeds()
                  if c.ratedTotalCoolingCapacity().empty()
                  and not c.autosizedRatedTotalCoolingCapacity().is_initialized())
    for c in model.getCoilCoolingDXMultiSpeeds():
        stages = c.stages()
        top = stages[-1] if len(stages) else None
        if top is None or (top.grossRatedTotalCoolingCapacity().empty()
                           and not top.autosizedGrossRatedTotalCoolingCapacity().is_initialized()):
            unsized += 1
    if unsized > 0:
        audit.info('check_part5', f'{unsized} DX coil(s) unsized — capacity-binned 5.2.12 minimums cannot be '
                                  'checked for them; run sizing first for full coverage')

    pairs = [
        ('getBoilerHotWaters', lambda b: b.nominalThermalEfficiency(),
         'boiler nominal thermal efficiency'),
        ('getChillerElectricEIRs', lambda c: c.referenceCOP(), 'chiller reference COP'),
        ('getCoilCoolingDXSingleSpeeds', _dx_cooling_rated_cop, 'DX cooling rated COP'),
        ('getCoilHeatingDXSingleSpeeds', lambda c: c.ratedCOP(), 'DX heating rated COP'),
        ('getCoilHeatingGass', lambda c: c.gasBurnerEfficiency(), 'gas coil burner efficiency'),
        # staged coils carry their performance on the STAGES; the efficiency
        # pass writes one row's value to every stage, so the top stage is
        # representative of the whole coil
        ('getCoilCoolingDXMultiSpeeds', lambda c: _top_stage(c, 'grossRatedCoolingCOP'),
         'staged DX cooling rated COP'),
        ('getCoilHeatingDXMultiSpeeds', lambda c: _top_stage(c, 'grossRatedHeatingCOP'),
         'staged DX heating rated COP'),
        ('getCoilHeatingGasMultiStages', lambda c: _top_stage(c, 'gasBurnerEfficiency'),
         'staged gas coil burner efficiency'),
    ]
    for getter, reader, label in pairs:
        proposed_items = sorted_by_name(getattr(model, getter)())
        minimum_items = sorted_by_name(getattr(clone, getter)())
        for i, proposed in enumerate(proposed_items):
            minimum = minimum_items[i] if i < len(minimum_items) else None
            if minimum is None:
                continue

            current = safe_value(reader, proposed)
            floor = safe_value(reader, minimum)
            if current is None or floor is None:
                continue
            if current >= floor - TOLERANCE:
                continue

            audit.warn('check_part5',
                       f'{label} {ruby_round(current, 3)} is BELOW the NECB {vintage} minimum '
                       f'{ruby_round(floor, 3)}',
                       target=proposed.nameString(), article='5.2.12.; Table 5.2.12.1.')


def _dx_cooling_rated_cop(coil):
    """Ruby: `c.ratedCOP.respond_to?(:get) && c.ratedCOP.is_initialized ? c.ratedCOP.get
    : c.ratedCOP` — the SDK returned an OptionalDouble on older versions and a plain
    double now."""
    value = coil.ratedCOP()
    if hasattr(value, 'is_initialized'):
        return value.get() if value.is_initialized() else value
    return value


def _top_stage(coil, attribute):
    """Ruby's `c.stages.last&.<attribute>`."""
    stages = coil.stages()
    if not len(stages):
        return None
    return getattr(stages[-1], attribute)()


def safe_value(reader, item):
    try:
        value = reader(item)
        if hasattr(value, 'is_initialized') and value.is_initialized():
            value = value.get()
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    except Exception:
        return None
