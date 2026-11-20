"""`modeling.build_system` / `replace_system`: the audit trail and the #236 single-zone warning.

#236 built a 24-zone office from nothing and handed all its zones to
"PSZ RTU Gas and DX Coils and Hot Water Baseboard" in one call. That row does
not state `per_zone`, so the builder's shared default put ONE packaged
single-zone unit over the whole building, controlled from one zone, with no
word said: 60.7 cooling unmet hours in a January week against 0.0 per zone.

The default stays (flipping it collides two canonical names — see #236); the
facade now WARNS on exactly that case and records every build in the audit.
These tests pin the case that warns, the three that must not, and the record.
"""

from __future__ import annotations

import unittest
import warnings

import btap.modeling as modeling
from btap.audit import AuditLog
from tests.support import load_fixture, needs_sdk

#: A PSZ row that does NOT state `per_zone`: shared by the builder's default.
DEFAULT_SHARED = "PSZ RTU Gas and DX Coils and Hot Water Baseboard"
#: A PSZ row that states `per_zone: false` and says "Shared" in its name.
EXPLICIT_SHARED = "Shared PSZ with gas boiler coils and hot water baseboard"


def _zones(model):
    return sorted(model.getThermalZones(), key=lambda z: z.nameString())


def _build(name, zones_of=None, **kwargs):
    model = load_fixture()
    zones = (zones_of or _zones)(model)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = modeling.build_system(model, name, zones, **kwargs)
    ours = [w for w in caught if "#236" in str(w.message)]
    return result, zones, ours


@needs_sdk
class TestTheSingleZoneWarning(unittest.TestCase):

    def test_a_default_shared_row_across_several_zones_WARNS(self):
        result, zones, ours = _build(DEFAULT_SHARED)
        self.assertGreater(len(zones), 1)
        # The behaviour the warning describes is real: ONE unit for all zones.
        self.assertEqual(1, len(list(result.air_loops)))
        self.assertEqual(1, len(ours), [str(w.message) for w in ours])
        message = str(ours[0].message)
        self.assertIn(f"serves {len(zones)} zones", message)
        self.assertIn("config={'per_zone': True}", message)
        self.assertIs(UserWarning, ours[0].category)

    def test_per_zone_config_does_not_warn_and_builds_one_unit_per_zone(self):
        result, zones, ours = _build(DEFAULT_SHARED, config={"per_zone": True})
        self.assertEqual([], ours)
        self.assertEqual(len(zones), len(list(result.air_loops)))

    def test_an_explicitly_shared_row_does_not_warn(self):
        # Its data says `per_zone: false` and its name says "Shared": the
        # caller asked for exactly what they get.
        _, _, ours = _build(EXPLICIT_SHARED)
        self.assertEqual([], ours)

    def test_one_zone_does_not_warn(self):
        _, _, ours = _build(DEFAULT_SHARED, zones_of=lambda m: _zones(m)[:1])
        self.assertEqual([], ours)


@needs_sdk
class TestTheBuildIsAudited(unittest.TestCase):

    def test_build_system_records_the_build(self):
        audit = AuditLog()
        model = load_fixture()
        zones = _zones(model)[:1]
        modeling.build_system(model, DEFAULT_SHARED, zones, audit=audit)
        built = [e for e in audit.entries
                 if e["step"] == "hvac" and e["action"] == f"built {DEFAULT_SHARED}"]
        self.assertEqual(1, len(built), audit.entries)
        self.assertEqual(1, built[0]["inputs"]["zones"])
        self.assertEqual(1, built[0]["value"]["air_loops"])
        self.assertEqual("decision", built[0]["level"])

    def test_the_warning_lands_in_the_audit_too(self):
        audit = AuditLog()
        model = load_fixture()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            modeling.build_system(model, DEFAULT_SHARED, _zones(model), audit=audit)
        self.assertEqual(1, len([w for w in audit.warnings if "#236" in w["action"]]))

    def test_replace_system_records_a_replacement(self):
        audit = AuditLog()
        model = load_fixture()
        zones = _zones(model)[:1]
        modeling.build_system(model, DEFAULT_SHARED, zones)
        modeling.replace_system(model, EXPLICIT_SHARED, zones, audit=audit)
        self.assertTrue(any(e["action"] == f"replaced with {EXPLICIT_SHARED}"
                            for e in audit.entries), audit.entries)

    def test_no_audit_is_still_accepted(self):
        model = load_fixture()
        result = modeling.build_system(model, DEFAULT_SHARED, _zones(model)[:1])
        self.assertEqual(1, len(list(result.air_loops)))


if __name__ == "__main__":
    unittest.main()
