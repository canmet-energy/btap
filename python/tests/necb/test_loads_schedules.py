"""P2 gate (standalone half): the schedule builder produces correct rulesets from
the vendored data — day values, design days, rule day-of-week flags, memoization,
loud unknown-name fallback.

Port of btap-necb/test/test_loads_schedules.rb. The parity half
(test_loads_schedules_parity.rb) needs the live Ruby oracle; its Leg-C
equivalent is test_oracle_goldens_loads.py.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestSchedules(unittest.TestCase):
    def hourly_values(self, day_schedule):
        import openstudio
        return [day_schedule.getValue(openstudio.Time(0, hour, 0, 0))
                for hour in range(1, 25)]

    def test_hourly_ruleset_day_values(self):
        import openstudio

        from btap.necb import loads
        model = openstudio.model.Model()
        schedule = loads.Schedules.add(model, 'NECB-A-Occupancy')
        ruleset = schedule.to_ScheduleRuleset().get()
        expected = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.7, 0.9, 0.9, 0.9, 0.5, 0.5,
                    0.9, 0.9, 0.9, 0.7, 0.3, 0.1, 0.1, 0.1, 0.1, 0.0]
        self.assertEqual(expected, self.hourly_values(ruleset.defaultDaySchedule()))

        saturday_rule = next((r for r in ruleset.scheduleRules() if r.applySaturday()), None)
        self.assertIsNotNone(saturday_rule)
        self.assertEqual([0.0] * 24, self.hourly_values(saturday_rule.daySchedule()))

    def test_design_days_and_setpoints(self):
        import openstudio

        from btap.necb import loads
        model = openstudio.model.Model()
        heating = loads.Schedules.add(
            model, 'NECB-A-Thermostat Setpoint-Heating').to_ScheduleRuleset().get()
        default = self.hourly_values(heating.defaultDaySchedule())
        self.assertEqual([18.0] * 6 + [20.0] + [22.0] * 14 + [18.0] * 3, default)

        # design-day schedules exist when the data carries WntrDsn/SmrDsn rows
        rows = [r for r in loads.table('2020', 'schedules')
                if r['name'] == 'NECB-A-Thermostat Setpoint-Heating']
        if any('WntrDsn' in str(r['day_types']) for r in rows):
            self.assertTrue(len(heating.winterDesignDaySchedule().values()) > 0)

    def test_memoized_and_activity_constant(self):
        import openstudio

        from btap.necb import loads
        model = openstudio.model.Model()
        first = loads.Schedules.add(model, 'NECB-Activity')
        again = loads.Schedules.add(model, 'NECB-Activity')
        self.assertEqual(first.handle(), again.handle(), 'same object returned on repeat')
        count = len([s for s in model.getScheduleRulesets() if s.nameString() == 'NECB-Activity'])
        self.assertEqual(1, count)

    def test_unknown_name_warns_never_silent(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import loads
        model = openstudio.model.Model()
        audit = AuditLog()
        schedule = loads.Schedules.add(model, 'NECB-Z-Nonsense', audit=audit)
        self.assertEqual(model.alwaysOnDiscreteSchedule().handle(), schedule.handle())
        warning = next((w for w in audit.warnings if "'NECB-Z-Nonsense'" in w['action']), None)
        self.assertIsNotNone(warning, 'unknown schedule warns (legacy is silent here)')

    def test_every_vendored_schedule_builds(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import loads
        model = openstudio.model.Model()
        audit = AuditLog()
        names = list(dict.fromkeys(r['name'] for r in loads.table('2020', 'schedules')))
        for name in names:
            schedule = loads.Schedules.add(model, name, audit=audit)
            self.assertIsNotNone(schedule, name)
        self.assertEqual(0, len(audit.warnings),
                         'no fallbacks while building the full catalog')
        # 'Always On' may alias
        self.assertGreaterEqual(len(model.getScheduleRulesets()), len(names) - 1)


if __name__ == '__main__':
    unittest.main()
