"""Minimal SDK-only schedule helpers."""

from __future__ import annotations

import openstudio


def constant_ruleset(model, name, value):
    """Constant-value ruleset schedule (24h default day).

    :param model: openstudio.model.Model
    :param name: str
    :param value: numeric
    :return: openstudio.model.ScheduleRuleset
    """
    existing = next((s for s in model.getScheduleRulesets() if s.nameString() == name), None)
    if existing is not None:
        return existing

    sch = openstudio.model.ScheduleRuleset(model)
    sch.setName(name)
    sch.defaultDaySchedule().setName(f"{name} Default")
    sch.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), value)
    return sch


def always_off(model):
    """Always-off on/off schedule (0 all year).

    :return: openstudio.model.ScheduleRuleset
    """
    return constant_ruleset(model, 'Always Off', 0)


def seasonal_availability(model):
    """Two-pipe fan-coil seasonal availability schedules: heating Jan-Jun + Nov-Dec,
    cooling Jul-Oct (port of NECB create_heating_cooling_on_off_availability_schedule).

    :return: (cooling_availability, heating_availability) ScheduleRuleset pair
    """
    existing_clg = next((s for s in model.getScheduleRulesets()
                         if s.nameString() == 'tpfc_clg_availability'), None)
    existing_htg = next((s for s in model.getScheduleRulesets()
                         if s.nameString() == 'tpfc_htg_availability'), None)
    if existing_clg is not None and existing_htg is not None:
        return existing_clg, existing_htg

    seasons = [
        {'start_month': 1, 'start_day': 1, 'end_month': 6, 'end_day': 30, 'htg': 1, 'clg': 0},
        {'start_month': 7, 'start_day': 1, 'end_month': 10, 'end_day': 31, 'htg': 0, 'clg': 1},
        {'start_month': 11, 'start_day': 1, 'end_month': 12, 'end_day': 31, 'htg': 1, 'clg': 0},
    ]

    def build(name, key):
        sch = openstudio.model.ScheduleRuleset(model)
        sch.setName(name)
        for season in seasons:
            rule = openstudio.model.ScheduleRule(sch)
            rule.setName(f"{name}_sch_rule")
            rule.setStartDate(model.getYearDescription().makeDate(
                season['start_month'], season['start_day']))
            rule.setEndDate(model.getYearDescription().makeDate(
                season['end_month'], season['end_day']))
            for setter in ('setApplySunday', 'setApplyMonday', 'setApplyTuesday',
                           'setApplyWednesday', 'setApplyThursday', 'setApplyFriday',
                           'setApplySaturday'):
                getattr(rule, setter)(True)
            day = rule.daySchedule()
            day.setName(f"{name}_sch_rule_day")
            day.addValue(openstudio.Time(0, 24, 0, 0), season[key])
        return sch

    return build('tpfc_clg_availability', 'clg'), build('tpfc_htg_availability', 'htg')
