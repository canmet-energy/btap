"""NECB 5.2.10.1 energy recovery: the post-sizing airflow-threshold trigger and
the reference ERV recipe (port of btap-necb's hvac/energy_recovery.rb).

Extends the HVAC domain defined in reference.py, whose optional_flow / rules
this module uses.
"""

from __future__ import annotations

import openstudio

from btap._compat import ruby_round, sorted_by_name
from btap.necb.hvac.reference import optional_flow, rules


def apply_energy_recovery(model, vintage='2020', *, hdd, audit=None):
    """8.4.4.19 (2020) / 8.4.5.19 (2025): where Subsection 5.2.10 applies, the
    reference system shall be modeled with energy recovery, used to preheat
    the outside air — via NECB 2020/2025 Tables 5.2.10.1.-A/-B: the
    airflow-threshold trigger, evaluated POST-SIZING (it needs the sized
    supply and minimum-OA flows), called by the umbrella after the reference
    sizing run. Replaces the NECB 2011 150 kW exhaust-heat-content trigger
    previously implemented here — wrong vintage, and divergent exactly where
    it matters: a small high-%OA system is "R (required at all flow rates)"
    under 2020 while the 2011 formula waves it through (permissive).
    Idempotent: loops already carrying an HX are skipped.

    :param model: SIZED openstudio.model.Model (needs supply/OA flows; modified in place)
    :param vintage: NECB vintage ('2020' or '2025')
    :param hdd: heating degree-days below 18 degC for the location
    :param audit: AuditLog or None (a new one is created if None)
    :return: AuditLog — carrying the per-loop 5.2.10.1 determinations
    """
    from btap.audit import AuditLog

    audit = audit if audit is not None else AuditLog()
    rule = rules(vintage).get('energy_recovery')
    if rule is None:
        return audit

    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        oa_system = air_loop.airLoopHVACOutdoorAirSystem()
        if oa_system.empty():
            continue  # no OA intake: 5.2.10 does not apply
        if any(c.to_HeatExchangerAirToAirSensibleAndLatent().is_initialized()
               for c in oa_system.get().oaComponents()):
            continue

        supply = (optional_flow(air_loop.designSupplyAirFlowRate())
                  or optional_flow(air_loop.autosizedDesignSupplyAirFlowRate()))
        ctrl = oa_system.get().getControllerOutdoorAir()
        min_oa = (optional_flow(ctrl.minimumOutdoorAirFlowRate())
                  or optional_flow(ctrl.autosizedMinimumOutdoorAirFlowRate()))
        if supply is None or min_oa is None or supply == 0:
            audit.warn('rules', '5.2.10.1 energy-recovery trigger needs SIZED supply/OA flows — not evaluated '
                                '(run sizing first)',
                       target=air_loop.nameString(), article=rule['trigger_article'], ruling='D-06')
            continue

        supply_l_s = supply * 1000.0
        oa_pct = 100.0 * min_oa / supply
        hours = annual_availability_hours(air_loop)
        if hours is None:
            audit.warn('rules', 'fan availability hours not computable — conservatively classified CONTINUOUS',
                       target=air_loop.nameString(), article=rule['trigger_article'], ruling='D-06')
        mode = ('continuous' if hours is None or hours >= rule['continuous_hours_per_year']
                else 'non_continuous')
        required, threshold_desc = erv_threshold_verdict(rule, mode, hdd, oa_pct, supply_l_s)
        inputs = {'supply_l_s': ruby_round(supply_l_s), 'min_oa_l_s': ruby_round(min_oa * 1000),
                  'oa_pct': ruby_round(oa_pct, 1), 'operation': mode,
                  'annual_hours': None if hours is None else ruby_round(hours),
                  'hdd': hdd, 'threshold': threshold_desc}
        if required:
            erv = _add_energy_recovery(air_loop, oa_system.get(), rule)
            pct = ruby_round(rule['effectiveness'] * 100)
            audit.decision('rules', 'energy recovery added to reference system (Table 5.2.10.1 threshold met)',
                           target=air_loop.nameString(), inputs=inputs,
                           value=f'rotary HX @ {pct}% sensible+latent effectiveness '
                                 f'(= {pct}% ENTHALPY effectiveness by identity, '
                                 f'the 5.2.10.1.(4) minimum) with 5.2.10.1.(6) overshoot control '
                                 f'({erv.nameString()})',
                           article=f"{rule['article']}; {rule['trigger_article']}; 5.2.10.1.(4); 5.2.10.1.(6)",
                           ruling='D-06 D-15')
        else:
            audit.decision('rules', 'energy recovery not required (below the Table 5.2.10.1 threshold)',
                           target=air_loop.nameString(), inputs=inputs,
                           article=rule['trigger_article'], ruling='D-06')
    return audit


def erv_threshold_verdict(rule, mode, hdd, oa_pct, supply_l_s):
    """Table row by HDD, band by %OA. Cells: 'R' = required at all flow rates,
    'NR' = never, numeric = required at/above that supply flow (L/s).
    Below the smallest band (<10% OA) is outside the Tables entirely -> NR.

    :param rule: the ruleset's 'energy_recovery' block
    :param mode: 'continuous' or 'non_continuous' operation
    :param hdd: heating degree-days below 18 degC
    :param oa_pct: minimum outdoor air as a percentage of supply (0-100)
    :param supply_l_s: design supply flow in L/s
    :return: (required?, threshold description)
    """
    bands = rule['oa_bands_pct']
    if oa_pct < bands[0]:
        return False, 'below 10% OA (outside Tables 5.2.10.1.-A/-B)'

    row = next(r for r in rule['thresholds_l_s'][mode] if hdd < r['hdd_max'])
    # Ruby Array#rindex: the LAST band the %OA reaches.
    index = max(i for i, b in enumerate(bands) if oa_pct >= b)
    cell = row['bands'][index]
    if cell == 'R':
        return True, 'R (required at all flow rates)'
    if cell == 'NR':
        return False, 'NR (not required at any flow rate)'
    return supply_l_s >= cell, f'>= {cell} L/s'


def annual_availability_hours(air_loop):
    """Annual fan-availability hours from the air loop's availability schedule
    (>= 8000 h/yr = continuously operating per the Table notes). Constant
    schedules (incl. the SDK's Always On) count directly; rulesets are summed
    hourly across the year; anything else is not computable (None).

    :param air_loop: openstudio.model.AirLoopHVAC
    :return: int or None — annual availability hours, or None when not computable
    """
    schedule = air_loop.availabilitySchedule()
    constant = schedule.to_ScheduleConstant()
    if constant.is_initialized():
        return 8760 if constant.get().value() > 0 else 0

    ruleset = schedule.to_ScheduleRuleset()
    if not ruleset.is_initialized():
        return None

    y = air_loop.model().getYearDescription().assumedYear()
    days = ruleset.get().getDaySchedules(
        openstudio.Date(openstudio.MonthOfYear(1), 1, y),
        openstudio.Date(openstudio.MonthOfYear(12), 31, y))
    return sum(sum(1 for h in range(1, 25)
                   if d.getValue(openstudio.Time(0, h, 0, 0)) > 0)
               for d in days)


def _add_energy_recovery(air_loop, oa_system, rule):
    """Legacy air_loop_hvac_apply_energy_recovery_ventilator recipe: rotary HX, 50%
    effectiveness at all conditions, economizer lockout, ExhaustOnly frost control,
    -23.3 degC threshold, and an OA-pretreat setpoint manager on the HX outlet."""
    model = air_loop.model()
    hx = rule['hx']
    erv = openstudio.model.HeatExchangerAirToAirSensibleAndLatent(model)
    erv.setName(f'{air_loop.nameString()} ERV')
    erv.setHeatExchangerType(hx['type'])
    erv.setEconomizerLockout(hx['economizer_lockout'])
    erv.setSupplyAirOutletTemperatureControl(True)
    erv.setFrostControlType(hx['frost_control'])
    eff = rule['effectiveness']
    erv.setSensibleEffectivenessat100HeatingAirFlow(eff)
    erv.setLatentEffectivenessat100HeatingAirFlow(eff)
    erv.setSensibleEffectivenessat100CoolingAirFlow(eff)
    erv.setLatentEffectivenessat100CoolingAirFlow(eff)
    if hasattr(erv, 'setSensibleEffectivenessat75HeatingAirFlow'):
        erv.setSensibleEffectivenessat75HeatingAirFlow(eff)
        erv.setLatentEffectivenessat75HeatingAirFlow(eff)
        erv.setSensibleEffectivenessat75CoolingAirFlow(eff)
        erv.setLatentEffectivenessat75CoolingAirFlow(eff)
    erv.setThresholdTemperature(hx['threshold_temperature_c'])
    erv.setInitialDefrostTimeFraction(hx['initial_defrost_time_fraction'])
    erv.setRateofDefrostTimeFractionIncrease(hx['rate_of_defrost_increase'])
    erv.addToNode(oa_system.outboardOANode().get())

    # T6 (audit 2026-07-25): the wheel is not free — PNNL-20405 surrogate
    # for rotary-HX fan/motor parasitics (legacy parity), computed from the
    # sized min OA; and the OA controller must bypass the wheel when OA
    # exceeds minimum (economizer-compatible behaviour on mixed systems).
    ctrl = oa_system.getControllerOutdoorAir()
    oa_flow = (ctrl.minimumOutdoorAirFlowRate().get()
               if ctrl.minimumOutdoorAirFlowRate().is_initialized() else None)
    if oa_flow is None:
        oa_flow = (ctrl.autosizedMinimumOutdoorAirFlowRate().get()
                   if ctrl.autosizedMinimumOutdoorAirFlowRate().is_initialized() else None)
    if oa_flow:
        erv.setNominalElectricPower((oa_flow * 212.5 / 0.5) + (oa_flow * 0.9 * 162.5 / 0.5) + 50.0)
    ctrl.setHeatRecoveryBypassControlType('BypassWhenOAFlowGreaterThanMinimum')

    spm = openstudio.model.SetpointManagerOutdoorAirPretreat(model)
    spm.setMinimumSetpointTemperature(-99.0)
    spm.setMaximumSetpointTemperature(99.0)
    spm.setMinimumSetpointHumidityRatio(0.00001)
    spm.setMaximumSetpointHumidityRatio(1.0)
    mixed_air_node = oa_system.mixedAirModelObject().get().to_Node().get()
    spm.setReferenceSetpointNode(mixed_air_node)
    spm.setMixedAirStreamNode(mixed_air_node)
    spm.setOutdoorAirStreamNode(oa_system.outboardOANode().get())
    spm.setReturnAirStreamNode(oa_system.returnAirModelObject().get().to_Node().get())
    spm.addToNode(erv.primaryAirOutletModelObject().get().to_Node().get())
    return erv
