"""D-111 / AHJ-26: the make-up-air terminal runs before the zone equipment.

#236: with the fan coil first, a System 2/5 zone's make-up air arrived after
the load was met and nothing corrected it (77 h of heating unmet in a January
week; terminal first, 4.0 h). With the baseboard first, authored PSZ zones
failed warmup convergence (8 Severe; terminal first, 0). The builders now
order the terminal first; the reference WITNESSES that for System 2/5 and
records it as AHJ-26, because the dispatch order is a question the Code does
not decide (AHJ-15's sibling).
"""

from __future__ import annotations

import unittest
import warnings

import btap.modeling as modeling
from btap.audit import AuditLog
from tests.support import load_fixture, needs_sdk

FAN_COIL_MAU = "FPFC MAU DX Coils with Scroll Chiller"
PSZ_BASEBOARD = "PSZ RTU Gas and DX Coils and Hot Water Baseboard"


def _built(name):
    model = load_fixture()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        modeling.build_system(model, name, sorted(model.getThermalZones(),
                                                  key=lambda z: z.nameString()))
    return model


def _first(zone):
    return zone.equipmentInHeatingOrder()[0].iddObjectType().valueName()


@needs_sdk
class TestTheBuildersPutTheTerminalFirst(unittest.TestCase):

    def test_fan_coil_zones(self):
        model = _built(FAN_COIL_MAU)
        for zone in model.getThermalZones():
            with self.subTest(zone=zone.nameString()):
                self.assertIn("AirTerminal", _first(zone))
                self.assertEqual("SequentialLoad", zone.loadDistributionScheme())

    def test_psz_baseboard_zones(self):
        model = _built(PSZ_BASEBOARD)
        for zone in model.getThermalZones():
            with self.subTest(zone=zone.nameString()):
                kinds = [e.iddObjectType().valueName() for e in zone.equipmentInHeatingOrder()]
                self.assertIn("AirTerminal", kinds[0])
                self.assertIn("Baseboard", kinds[1])


@needs_sdk
class TestTheReferenceWitnessesAndCites(unittest.TestCase):

    def _record(self, model):
        from btap.codes import resolve
        from btap.codes.necb.hvac.reference import _record_fan_coil_dispatch
        audit = AuditLog()
        _record_fan_coil_dispatch(list(model.getZoneHVACFourPipeFanCoils()), 2,
                                  resolve("necb2020"), audit)
        return [e for e in audit.entries if e.get("ahj") == "AHJ-26"]

    def test_the_built_order_is_recorded_with_its_referral(self):
        model = _built(FAN_COIL_MAU)
        cited = self._record(model)
        self.assertEqual(1, len(cited))
        entry = cited[0]
        self.assertEqual("D-111", entry["ruling"])
        self.assertIn("8.4.4.9.(3)", entry["article"])
        self.assertEqual(len(model.getThermalZones()), entry["inputs"]["zones"])

    def test_a_zone_in_the_legacy_order_is_REFUSED_not_recorded(self):
        model = _built(FAN_COIL_MAU)
        zone = sorted(model.getThermalZones(), key=lambda z: z.nameString())[0]
        terminal, fan_coil = list(zone.equipmentInHeatingOrder())[:2]
        zone.setHeatingPriority(fan_coil, 1)
        zone.setHeatingPriority(terminal, 2)
        with self.assertRaisesRegex(RuntimeError, "precedes the make-up-air terminal"):
            self._record(model)

    def test_fan_coils_with_no_make_up_air_terminal_cite_nothing(self):
        # The make-up-air terminal removed: a fan coil alone chose nothing.
        model = load_fixture()
        zone = sorted(model.getThermalZones(), key=lambda z: z.nameString())[0]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            modeling.build_system(model, FAN_COIL_MAU, [zone])
        for e in list(zone.equipment()):
            if "AirTerminal" in e.iddObjectType().valueName():
                e.remove()
        self.assertEqual([], self._record(model))


if __name__ == "__main__":
    unittest.main()
