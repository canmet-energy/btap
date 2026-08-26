"""The REUSABLE diagram API consumed by host reports (e.g. btap-necb's AHJ
compliance report): modeling.model_hvac_diagrams(model) draws the same
OpenStudio-App-style loop diagrams the catalog draws, for ANY model — plus the
self-contained icon defs + CSS a host document needs. SDK-only (no CLI).
"""

import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestModelDiagrams(unittest.TestCase):
    def built_model(self):
        """Build a hydronic boiler system on the fixture so there is a real hot-water
        loop (pump -> boiler supply, baseboard demand) to diagram."""
        import openstudio
        from btap._compat import sorted_by_name

        model = load_fixture()
        for z in model.getThermalZones():
            if z.thermostatSetpointDualSetpoint().is_initialized():
                continue

            z.setThermostatSetpointDualSetpoint(
                openstudio.model.ThermostatSetpointDualSetpoint(model))
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Baseboard gas boiler', zones)
        return model

    def test_model_hvac_diagrams_returns_loops_with_svg(self):
        bundle = modeling.model_hvac_diagrams(self.built_model())
        self.assertFalse(bundle['empty'], 'a boiler system has central loops')
        self.assertGreaterEqual(len(bundle['loops']), 1, 'at least one loop diagrammed')
        loop = bundle['loops'][0]
        self.assertTrue(loop['kind'], 'loop carries its kind')
        self.assertIsInstance(loop['label'], str)
        self.assertIn('<svg', loop['svg'], 'loop diagram is inline SVG')
        # the hot-water loop demand surfaces the served hydronic baseboards
        all_svg = ''.join(l['svg'] for l in bundle['loops'])
        self.assertIn('Baseboard (hydronic)', all_svg, 'demand branch lists served baseboards')
        # a boiler cell references the embedded boiler icon (resolves against icon_defs)
        self.assertIn('<use href="#icon-', all_svg, 'cells reference embedded OS App icons')

    def test_air_loop_label_names_its_served_zone(self):
        """A single-zone (PSZ) air handler's loop label names the zone it serves, so a
        host dropdown chooser can tell packaged single-zone units apart instead of
        listing several ambiguous "Air loop" entries."""
        import openstudio
        from btap._compat import sorted_by_name

        model = load_fixture()
        for z in model.getThermalZones():
            if z.thermostatSetpointDualSetpoint().is_initialized():
                continue

            z.setThermostatSetpointDualSetpoint(
                openstudio.model.ThermostatSetpointDualSetpoint(model))
        zone = sorted_by_name(model.getThermalZones())[0]
        modeling.build_system(model, 'PSZ RTU Gas and DX Coils and Hot Water Baseboard', [zone])
        bundle = modeling.model_hvac_diagrams(model)
        air = next((l for l in bundle['loops'] if l['kind'] == 'air'), None)
        self.assertIsNotNone(air, 'a PSZ builds an air loop')
        self.assertRegex(air['label'], r'\AAir loop — ',
                         "single-zone air loop is labelled with its served zone, "
                         f"got {air['label']!r}")
        self.assertIn(zone.nameString(), air['label'],
                      'the label carries the served zone name')

    def test_model_hvac_diagrams_never_raises_on_empty_model(self):
        import openstudio

        bundle = modeling.model_hvac_diagrams(openstudio.model.Model())
        self.assertTrue(bundle['empty'], 'a bare model has no HVAC')
        self.assertEqual([], bundle['loops'])
        self.assertIsNone(bundle['zone_equipment_svg'])

    def test_icon_defs_are_embedded_once_and_self_contained(self):
        defs = modeling.hvac_icon_defs()
        self.assertIn('<symbol id="icon-', defs, 'icon symbols defined')
        self.assertIn('data:image/png;base64,', defs, 'icons embedded as data-URIs')
        # self-contained: no url(), no <link>/@import, no remote src/href
        self.assertNotRegex(defs, r'@import|<link')
        self.assertNotRegex(defs, r'url\(')
        self.assertNotRegex(defs, r'(src|href)\s*=\s*"https?://')

    def test_diagram_css_is_self_contained_and_sizes_svgs(self):
        from btap.modeling.hvac.catalog_report import DIAGRAM_CSS

        css = DIAGRAM_CSS
        self.assertRegex(css, r'\.diagram\s*\{[^}]*overflow-x:\s*auto', 'scroll container')
        self.assertRegex(css, r'\.diagram\s+svg\s*\{[^}]*width:\s*auto',
                         'intrinsic-size override')
        self.assertRegex(css, r'break-inside:\s*avoid', 'print-friendly')
        self.assertNotRegex(css, r'url\(|@import', 'no external references')


if __name__ == '__main__':
    unittest.main()
