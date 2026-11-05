"""Issue #201 — the teardown must keep preserved exhaust fans CONNECTED.

`remove_hvac_from_zones` documents that "exhaust fans are preserved (they
represent code-required exhaust, not the system)". Preserving the OBJECT was
not enough: removing a zone component that occupies an exhaust port clears the
zone's entire exhaust `PortList`, leaving the fan with an inlet-node reference
the zone no longer registers. EnergyPlus then reports "Node Connection Error,
Inlet node did not find an appropriate matching outlet node" for each one.

## Why the fixture is a REDUCED REAL MODEL, not a hand-built one

Nine hand-built reproductions do NOT trigger the wipe — single zone and
multi-zone, electric and hydronic coils with a real boiler plant, both
equipment add orders, with and without an air loop, and through a
save/`VersionTranslator` round trip. Each removes only the departing
component's port and keeps the fan's. So a synthetic fixture would pass
against the UNFIXED code and prove nothing.

`fixtures/zone_unit_heater_with_exhaust_fan.osm` is therefore
`gagetown_coldlake_Office_pre-1960.osm` mechanically reduced to its Paint Shop
zone — 344 objects, 141 KB, from 2.4 MB — by removing the other zones, the
loops, orphaned spaces, geometry, loads and rendering objects and purging
unused resources. It still reproduces, which is what makes it a valid fixture.

**It is committed deliberately.** The first version of this test loaded the
archetype from `models/`, which is gitignored (`.gitignore:111`), so all four
tests SKIPPED in CI — including the `verify` lane. The fix merged in #204 had
no CI protection at all and the green signal did not cover it.
"""

from __future__ import annotations

import pathlib
import unittest

from tests.support import needs_sdk

FIXTURE = (pathlib.Path(__file__).resolve().parents[1] / 'fixtures'
           / 'zone_unit_heater_with_exhaust_fan.osm')

#: The zone's other equipment is a `ZoneHVAC:UnitHeater`, which occupies an
#: exhaust port. That is what makes the wipe happen; a
#: `ZoneHVAC:Baseboard:Convective:Water` has no air inlet and never occupies
#: one, which is why the two baseboard zones in the source archetype were
#: unaffected while these five were.
ZONE = 'Paint Shop'


@needs_sdk
class TestTeardownKeepsExhaustFansConnected(unittest.TestCase):

    def setUp(self):
        import openstudio

        self.assertTrue(FIXTURE.is_file(), f'{FIXTURE.name} is missing')
        translator = openstudio.osversion.VersionTranslator()
        self.model = translator.loadModel(
            openstudio.toPath(str(FIXTURE))).get()
        self.zone = next(z for z in self.model.getThermalZones()
                         if z.nameString() == ZONE)

    def fan(self):
        return next(e.to_FanZoneExhaust().get() for e in self.zone.equipment()
                    if e.to_FanZoneExhaust().is_initialized())

    def registered_ports(self):
        return {node.nameString()
                for node in self.zone.exhaustPortList().modelObjects()}

    def fan_is_registered(self):
        from btap._compat import opt

        inlet = self.fan().inletNode()
        return (inlet.is_initialized()
                and opt(inlet).nameString() in self.registered_ports())

    def test_the_fixture_starts_consistent_and_still_carries_the_hazard(self):
        """Without BOTH of these the rest of the file proves nothing."""
        kinds = {e.iddObjectType().valueName() for e in self.zone.equipment()}
        self.assertIn('OS_Fan_ZoneExhaust', kinds)
        self.assertIn('OS_ZoneHVAC_UnitHeater', kinds,
                      'the unit heater is what occupies the second exhaust '
                      'port; without it the wipe cannot be observed')
        self.assertEqual(2, len(self.registered_ports()))
        self.assertTrue(self.fan_is_registered())

    def test_the_teardown_keeps_the_fan_registered(self):
        from btap.modeling.hvac import teardown

        teardown.remove_hvac_from_zones(self.model, [self.zone])

        self.assertTrue(
            self.fan_is_registered(),
            'a preserved exhaust fan must stay REGISTERED on its zone, not '
            'merely survive as an object: EnergyPlus reports a Node '
            'Connection Error for an inlet node the zone does not list')

    def test_the_repair_does_not_alter_the_fans_own_fields(self):
        """Re-attaching rebuilds the connection, not the fan."""
        from btap.modeling.hvac import teardown

        fan = self.fan()
        before = (round(fan.fanTotalEfficiency(), 6),
                  round(fan.pressureRise(), 4))

        teardown.remove_hvac_from_zones(self.model, [self.zone])

        after = (round(self.fan().fanTotalEfficiency(), 6),
                 round(self.fan().pressureRise(), 4))
        self.assertEqual(before, after)

    def test_CONTROL_the_raw_SDK_removal_still_wipes_the_list(self):
        """Pins the HAZARD, so the test above cannot pass vacuously.

        If a future SDK release fixes `removeFromThermalZone`, this fails and
        the repair in `remove_hvac_from_zones` becomes removable. Until then it
        documents that the repair is load-bearing rather than defensive
        decoration.
        """
        unit_heater = next(e for e in self.zone.equipment()
                           if e.to_ZoneHVACUnitHeater().is_initialized())

        unit_heater.remove()

        self.assertFalse(
            self.fan_is_registered(),
            'the raw SDK removal no longer wipes the exhaust PortList — if '
            'this is a genuine SDK fix, the repair in '
            'remove_hvac_from_zones can go')
