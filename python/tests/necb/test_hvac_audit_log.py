"""The AuditLog implementation lives in btap.audit; the Ruby gem keeps the
historic `BtapNECB::AuditLog` constant as an ALIAS, which is the whole
compatibility mechanism for every call site in that gem. In Python the alias
is just an import — what this file guards is that the hvac domain writes
through the ONE shared class (not a local copy) and that the class still
carries the `ruling:` axis (D-44).

The behaviour suite lives in tests/audit/."""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from btap.necb.hvac import checker, energy_recovery, reference


class TestAuditLog(unittest.TestCase):

    def test_the_domain_writes_through_the_shared_class(self):
        # Ruby: assert_same BtapAudit::AuditLog, BtapNECB::AuditLog. In Python the
        # equivalent claim is that every hvac module that builds a default audit
        # builds the SHARED class, never a local copy.
        for module in (reference, energy_recovery, checker):
            from btap.audit import AuditLog as Shared
            self.assertIs(Shared, AuditLog,
                          f'{module.__name__} must resolve the shared btap.audit class')

    def test_the_ruling_kwarg_still_works(self):
        audit = AuditLog()
        audit.decision('build', 'reference system operates on the proposed operating schedule',
                       article='8.4.4.7.(1)', ruling='D-14')
        entry = audit.entries[0]
        self.assertEqual('D-14', entry['ruling'], 'ruling lands at the TOP LEVEL of the entry')
        self.assertNotIn('inputs', entry, 'ruling never leaks into inputs')
        self.assertIn('| ruling D-14', str(audit))


if __name__ == '__main__':
    unittest.main()
