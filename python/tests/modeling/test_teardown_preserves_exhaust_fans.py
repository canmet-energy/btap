"""Issue #201 — the teardown must keep preserved exhaust fans CONNECTED.

`remove_hvac_from_zones` documents that "exhaust fans are preserved (they
represent code-required exhaust, not the system)". Preserving the OBJECT was
not enough: removing a zone component that occupies an exhaust port can clear
the zone's entire exhaust `PortList`, leaving the fan with an inlet-node
reference the zone no longer registers. EnergyPlus then reports "Node
Connection Error, Inlet node did not find an appropriate matching outlet node"
for each one — five extra Severes in a model generated from this archetype.

**This test uses the REAL archetype deliberately.** Nine hand-built
reproductions do NOT trigger the wipe: single zone and multi-zone, electric
and hydronic coils, both equipment add orders, with and without an air loop on
the zone, and through a save/`VersionTranslator` round trip. Each one removes
only the departing component's port and keeps the fan's. A synthetic fixture
here would pass against the unfixed code and prove nothing.
"""

from __future__ import annotations

import pathlib
import unittest

from tests.support import needs_sdk

ARCHETYPE = (pathlib.Path(__file__).resolve().parents[3] / 'models'
             / 'gagetown_coldlake_Office_pre-1960.osm')

#: The five zones whose other equipment is a `ZoneHVAC:UnitHeater`, which
#: occupies an exhaust port. These are the zones that broke.
UNIT_HEATER_ZONES = ('Paint Shop', 'Carpenter Shop', 'Machine Shop',
                     'RM Shop 1', 'RM Shop 2')

#: The control: their other equipment is a `ZoneHVAC:Baseboard:Convective:
#: Water`, which has no air inlet and so never occupies a port. These were
#: never affected, so they must not be what makes this test pass.
BASEBOARD_ZONES = ('Washrooms 1', 'Washroom 2')


@needs_sdk
@unittest.skipUnless(ARCHETYPE.is_file(), f'{ARCHETYPE.name} not present')
class TestTeardownKeepsExhaustFansConnected(unittest.TestCase):

    def setUp(self):
        import openstudio

        self.openstudio = openstudio
        translator = openstudio.osversion.VersionTranslator()
        self.model = translator.loadModel(
            openstudio.toPath(str(ARCHETYPE))).get()

    def unregistered(self):
        """Zone names whose exhaust fan's inlet node the zone does not list."""
        from btap._compat import opt

        out = []
        for fan in self.model.getFanZoneExhausts():
            zone = fan.thermalZone()
            if not zone.is_initialized():
                out.append(f'{fan.nameString()} (detached from its zone)')
                continue
            zone = opt(zone)
            inlet = fan.inletNode()
            registered = {node.nameString()
                          for node in zone.exhaustPortList().modelObjects()}
            if (not inlet.is_initialized()
                    or opt(inlet).nameString() not in registered):
                out.append(zone.nameString())
        return sorted(out)

    def fan_fields(self):
        return sorted((f.nameString(), round(f.fanTotalEfficiency(), 6),
                       round(f.pressureRise(), 4))
                      for f in self.model.getFanZoneExhausts())

    def zones_named(self, names):
        return [z for z in self.model.getThermalZones()
                if z.nameString() in names]

    def test_the_archetype_starts_consistent(self):
        """If this fails the premise is gone and the rest proves nothing."""
        self.assertEqual([], self.unregistered())
        self.assertEqual(7, len(self.model.getFanZoneExhausts()))

    def test_tearing_down_the_UNIT_HEATER_zones_keeps_the_fans_connected(self):
        from btap.modeling.hvac import teardown

        zones = self.zones_named(UNIT_HEATER_ZONES)
        self.assertEqual(len(UNIT_HEATER_ZONES), len(zones),
                         'the archetype no longer has these zones')

        teardown.remove_hvac_from_zones(self.model, zones)

        self.assertEqual(
            [], self.unregistered(),
            'a preserved exhaust fan must stay REGISTERED on its zone, not '
            'merely survive as an object: EnergyPlus reports a Node '
            'Connection Error for an inlet node the zone does not list')

    def test_the_repair_does_not_alter_the_fans_own_fields(self):
        """Re-attaching rebuilds the connection, not the fan."""
        from btap.modeling.hvac import teardown

        before = self.fan_fields()
        teardown.remove_hvac_from_zones(
            self.model, self.zones_named(UNIT_HEATER_ZONES))
        self.assertEqual(before, self.fan_fields())

    def test_CONTROL_the_baseboard_zones_were_never_the_ones_at_risk(self):
        """Tearing down ONLY the baseboard zones was always safe.

        So a fix that merely re-attached every fan everywhere would pass the
        test above while telling us nothing about the unit-heater case. This
        pins which zones carry the risk.
        """
        from btap.modeling.hvac import teardown

        zones = self.zones_named(BASEBOARD_ZONES)
        self.assertEqual(len(BASEBOARD_ZONES), len(zones))

        teardown.remove_hvac_from_zones(self.model, zones)
        self.assertEqual([], self.unregistered())
