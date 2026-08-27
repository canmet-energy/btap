"""The NECB schedule builder — exact port of the legacy model_add_schedule /
model_add_vals_to_sch semantics against the vendored schedules table:
one ScheduleRuleset per name; per data row the day_types tokens map to the
default day (Default), winter/summer design days (WntrDsn/SmrDsn), and dated
ScheduleRules (Wkdy/Wknd/Sat/Sun/Mon..Fri); Hourly rows add a value at each
hour boundary where the value CHANGES (values are MIDNIGHT-FIRST, values[0] =
the hour ending 01:00... applied as until-(i+1):00); Constant rows a single
until-24:00 value.

DELIBERATE DEVIATION: legacy silently returns alwaysOnDiscreteSchedule for an
unknown name — this builder WARNS in the audit (never silent) and then returns
the same fallback, preserving downstream behavior.
"""

from __future__ import annotations

from datetime import datetime

import openstudio

from btap._compat import NullAudit, sorted_by_name
from btap.necb import loads as _loads

DAY_TOKENS = ['Wkdy', 'Wknd', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

_WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
_TOKEN_DAYS = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday',
               'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday',
               'Sun': 'Sunday'}


def add(model, name, vintage='2020', audit=None):
    """:param name: e.g. 'NECB-A-Occupancy'
    :return: the ruleset (or the always-on fallback)"""
    audit = audit if audit is not None else NullAudit()
    if name is None or str(name) == '':
        return None

    existing = next((s for s in sorted_by_name(model.getSchedules())
                     if s.nameString() == name), None)
    if existing is not None:
        return existing

    rows = [r for r in _loads.table(vintage, 'schedules') if r['name'] == name]
    if not rows:
        audit.warn('schedules',
                   f"no NECB {vintage} schedule data named '{name}' — falling back to Always On "
                   '(legacy fails silently here)',
                   target=name)
        return model.alwaysOnDiscreteSchedule()

    ruleset = openstudio.model.ScheduleRuleset(model)
    ruleset.setName(name)
    for row in rows:
        apply_row(model, ruleset, name, row)
    audit.info('schedules', 'NECB schedule built', target=name,
               inputs={'rows': len(rows), 'type': rows[0]['type']})
    return ruleset


def apply_row(model, ruleset, name, row):
    day_types = '' if row['day_types'] is None else str(row['day_types'])

    if 'Default' in day_types:
        day = ruleset.defaultDaySchedule()
        day.setName(f"{name} Default")
        add_values(day, row)
    if 'WntrDsn' in day_types:
        day = openstudio.model.ScheduleDay(model)
        ruleset.setWinterDesignDaySchedule(day)
        day = ruleset.winterDesignDaySchedule()
        day.setName(f"{name} Winter Design Day")
        add_values(day, row)
    if 'SmrDsn' in day_types:
        day = openstudio.model.ScheduleDay(model)
        ruleset.setSummerDesignDaySchedule(day)
        day = ruleset.summerDesignDaySchedule()
        day.setName(f"{name} Summer Design Day")
        add_values(day, row)
    if not any(token in day_types for token in DAY_TOKENS):
        return

    rule = openstudio.model.ScheduleRule(ruleset)
    day = rule.daySchedule()
    day.setName(f"{name} {day_types} Day")
    add_values(day, row)
    start_date = _parse_date(row['start_date'])
    end_date = _parse_date(row['end_date'])
    rule.setStartDate(openstudio.Date(openstudio.MonthOfYear(start_date.month),
                                      start_date.day))
    rule.setEndDate(openstudio.Date(openstudio.MonthOfYear(end_date.month),
                                    end_date.day))
    if 'Wknd' in day_types:
        rule.setApplySaturday(True)
        rule.setApplySunday(True)
    if 'Wkdy' in day_types:
        for d in _WEEKDAYS:
            getattr(rule, f"setApply{d}")(True)
    for token, method in _TOKEN_DAYS.items():
        if token in day_types:
            getattr(rule, f"setApply{method}")(True)


def add_values(day_schedule, row):
    values = row['values']
    if row['type'] == 'Constant':
        day_schedule.addValue(openstudio.Time(0, 24, 0, 0), float(values[0]))
    elif row['type'] == 'Hourly':
        for i in range(24):
            # Ruby indexes past the end for the last hour: values[24] is nil, so
            # the 24:00 value is ALWAYS added.
            nxt = values[i + 1] if i + 1 < len(values) else None
            if values[i] == nxt:
                continue
            day_schedule.addValue(openstudio.Time(0, i + 1, 0, 0), float(values[i]))
    else:
        raise ValueError(f"unknown schedule row type '{row['type']}' (Constant|Hourly)")
    day_schedule.setInterpolatetoTimestep(interpolate_off(day_schedule))


def interpolate_off(day_schedule):
    return (False if day_schedule.model().version() < openstudio.VersionString('3.8.0')
            else 'No')


def _parse_date(text):
    """Ruby's ``Date.parse`` over the vendored ISO-8601 stamps
    ('2014-01-01T00:00:00+00:00') — only month and day are read."""
    return datetime.fromisoformat(str(text))
