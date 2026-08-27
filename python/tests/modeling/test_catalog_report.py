"""Full-coverage render: builds all 97 catalog systems on the fixture, extracts
their real topology, and asserts the self-contained HTML catalog contains every
system, draws most of them, and makes NO external requests. Building 97 models
takes ~30-60s (no CLI needed — topology builds are SDK-only). The whole suite
renders ONCE (memoized, written to a temp path so the write path is exercised too).
"""

import os
import re
import tempfile
import unittest
from pathlib import Path

import btap.modeling as modeling
from tests.support import needs_sdk

OUT_PATH = os.path.join(tempfile.gettempdir(), f'catalog_report_{os.getpid()}.html')


@needs_sdk
class TestCatalogReport(unittest.TestCase):
    _html = None

    # Single render for the whole suite: also exercises the write-to-path branch.
    @classmethod
    def render_html(cls):
        if cls._html is None:
            cls._html = modeling.catalog_html(OUT_PATH)
        return cls._html

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(OUT_PATH):
            os.remove(OUT_PATH)

    def html(self):
        return self.render_html()

    def rows(self):
        from btap.modeling.hvac import catalog
        return catalog.rows()

    def esc(self, s):
        from btap.modeling.hvac.catalog_report import esc
        return esc(s)

    def test_returns_a_string(self):
        html = self.html()
        self.assertIsInstance(html, str)
        self.assertRegex(html, r'(?i)<html')
        self.assertRegex(html, r'(?i)</html>')

    def test_contains_every_argument_name(self):
        html = self.html()
        missing = [r['name'] for r in self.rows() if self.esc(r['name']) not in html]
        self.assertEqual([], missing,
                         f'argument names missing from catalog HTML: {missing!r}')

    def test_contains_every_canonical_name(self):
        from btap.modeling.hvac import canonical
        html = self.html()
        missing = [canonical.name(r) for r in self.rows()
                   if self.esc(canonical.name(r)) not in html]
        self.assertEqual([], missing,
                         f'canonical names missing from catalog HTML: {missing!r}')

    def test_draws_most_systems(self):
        svg_count = self.html().count('<svg')
        self.assertGreaterEqual(svg_count, 60,
                                f'expected >= 60 inline <svg blocks, got {svg_count}')

    def test_loops_render_at_fixed_natural_size(self):
        html = self.html()
        # Every loop <svg> now carries explicit width/height attributes equal to its
        # viewBox so it renders 1:1 (consistent box size across systems, no zoom).
        svg_with_width = len(re.findall(r'<svg[^>]*\bwidth="', html))
        self.assertGreaterEqual(
            svg_with_width, 60,
            f'expected most <svg> blocks to carry a width attribute, got {svg_with_width}')
        # Wide loops scroll in their container instead of shrinking to fit...
        self.assertRegex(html, r'\.diagram\s*\{[^}]*overflow-x:\s*auto',
                         'diagram container scrolls horizontally')
        # ...and the svg rule must NOT stretch the diagram to full container width.
        self.assertNotRegex(html, r'svg\s*\{[^}]*width:\s*100%',
                            'svg must not be stretched to 100% width')

    def test_family_groups_start_collapsed(self):
        html = self.html()
        # Each family group is a collapsible toggle and starts COLLAPSED on load.
        collapsed = html.count('class="nav-family collapsed"')
        titles = html.count('class="nav-family-title"')
        self.assertGreaterEqual(collapsed, 11,
                                f'family groups should render collapsed on load, got {collapsed}')
        self.assertEqual(titles, collapsed,
                         'every family group carries the collapsed class on load')
        self.assertRegex(html, r'class="nav-family-title"',
                         'family header is a clickable toggle')

    def test_no_external_references(self):
        html = self.html()
        self.assertNotRegex(html, r'(?i)src\s*=\s*["\']https?:', 'no remote src')
        self.assertNotRegex(html, r'(?i)<link\b', 'no <link> (external stylesheet/asset)')
        self.assertNotRegex(html, r'(?i)@import', 'no CSS @import')
        self.assertNotRegex(html, r'(?i)url\(', 'no CSS url() references')
        self.assertNotRegex(html, r'(?i)https?://(?!www\.w3\.org)',
                            'no external URLs except the SVG xmlns namespace')

    def test_embedded_os_app_icons(self):
        html = self.html()
        # The real OpenStudio Application component icons are embedded as base64
        # PNG data-URIs — ONCE each, in the hidden master <defs> — and referenced by
        # component cells via <use>. Each data-URI must appear exactly once (embed
        # once, reference many), so the count of data-URIs equals the count of
        # <symbol>/<image> definitions and is far below the number of <use> refs.
        data_uris = html.count('data:image/png;base64,')
        self.assertGreaterEqual(data_uris, 20,
                                f'expected >= 20 embedded PNG icons, got {data_uris}')
        symbols = len(re.findall(r'<symbol id="icon-', html))
        images = html.count('<image ')
        self.assertEqual(data_uris, symbols,
                         'each icon data-URI is defined once as a <symbol>')
        self.assertEqual(data_uris, images,
                         'each icon data-URI is embedded once in an <image>')

        # ...and the icons are actually USED, many more times than they are embedded.
        uses = html.count('<use ')
        self.assertGreaterEqual(uses, 1, 'embedded icons are referenced via <use>')
        self.assertGreater(uses, data_uris,
                           'icons are referenced far more often than embedded (embed once, reference many)')

        # Spot-check the mapping: a boiler cell references the boiler icon, a
        # variable-volume fan the fan_variable icon, a water-source heat pump the
        # water-to-water HP icon (NOT a pump icon), district heating its own icon.
        for icon_id in ['icon-boiler', 'icon-fan_variable',
                        'icon-heatpump_watertowater_equationfit_heating',
                        'icon-districtheating', 'icon-chiller_air']:
            self.assertIn(f'<symbol id="{icon_id}"', html, f'{icon_id} is embedded')
            self.assertIn(f'<use href="#{icon_id}"', html, f'{icon_id} is referenced by a cell')

    def test_icon_attribution_present(self):
        html = self.html()
        # BSD-3-Clause requires attribution: a visible footer credit to the source.
        self.assertRegex(html, r'(?i)Component icons .* OpenStudio Application',
                         'footer credits the OpenStudio Application icons')
        self.assertIn('BSD-3-Clause', html, 'footer names the icon license')

    def test_script_is_inline_only(self):
        html = self.html()
        # Inline <script> is now required (master-detail/search/tabs are JS-driven),
        # but it must never reference an external file — no src= on any script tag.
        self.assertRegex(html, r'(?i)<script\b',
                         'inline <script> is required for the interactive UX')
        self.assertNotRegex(html, r'(?i)<script[^>]*\bsrc=',
                            'the script must be inline (no src= attribute)')

    def test_master_detail_search_and_tabs(self):
        html = self.html()
        # Master-detail scaffolding: the searchable left nav and the right detail pane.
        self.assertRegex(html, r'id="system-search"', 'search input present')
        self.assertRegex(html, r'class="[^"]*\bsystem-detail\b',
                         'system-detail containers present')
        self.assertRegex(html, r'class="[^"]*\bsidebar\b', 'left sidebar present')
        self.assertRegex(html, r'class="[^"]*\bnav-family\b', 'family-grouped nav present')

        # Per-system tab controls exist (systems with multiple loops render >1 tab).
        self.assertRegex(html, r'class="[^"]*\btab-bar\b', 'tab bar present')
        self.assertGreaterEqual(len(re.findall(r'class="tab(?: active)?"', html)), 2,
                                'multiple tab controls present')

        # Native SVG <title> hover tooltips on components/demand boxes (many of them).
        self.assertGreaterEqual(html.count('<title>'), 60, 'SVG <title> tooltips present')

    def test_plant_demand_enumerates_served_loads(self):
        html = self.html()
        # A plant loop's demand side now enumerates the served loads, INCLUDING the
        # zone-level hydronic equipment. A hot-water system that feeds baseboards
        # (e.g. 'Baseboard gas boiler', or any '... Hot Water Baseboard' system) must
        # surface a "Baseboard (hydronic)" demand branch in its loop diagram.
        self.assertIn('Baseboard (hydronic)', html,
                      'hot-water loop demand lists served hydronic baseboards')
        # Four-pipe fan-coil systems surface their zone-level fan-coil coils, and
        # air-handler water coils still surface as heating/cooling coils.
        self.assertIn('Fan-coil coil', html, 'plant demand lists zone-level fan-coil coils')

    def test_condenser_loop_demand_shows_served_chillers(self):
        html = self.html()
        # A water-cooled chiller's condenser IS the load its condenser-water loop
        # serves. That loop's demand must surface the chillers it cools, labelled by
        # compressor type + "(condenser)", instead of collapsing to "No loads".
        self.assertIn('Rotary-screw chiller (condenser)', html,
                      'condenser loop demand surfaces the rotary-screw chillers it cools')
        self.assertRegex(html, r'chiller \(condenser\)',
                         'a chiller-condenser demand label is present')
        # No plant loop that genuinely has demand equipment should render "No loads".
        # (The chiller condensers were the equipment previously being dropped.)
        self.assertNotRegex(html, r'Rotary-screw chiller \(condenser\)[\s\S]{0,400}No loads',
                            'the condenser loop no longer shows "No loads"')

    def test_plant_demand_coils_labelled_with_their_zone(self):
        html = self.html()
        # Zone-served plant coils are drawn as their OWN demand branch labelled with
        # the zone (not collapsed into one "×2" group), so the diagram shows WHERE
        # each coil is — consistent with the per-zone air-loop demand.
        self.assertIn('Fan-coil coil — Thermal Zone 1', html,
                      'hot/chilled water loop demand shows a zone-labelled fan-coil coil')
        self.assertIn('Fan-coil coil — Thermal Zone 2', html,
                      'the second served zone is its own demand branch')

    def test_air_loop_demand_shows_zone_level_components(self):
        html = self.html()
        # The air-loop demand is drawn as one branch PER served zone; each zone cell
        # is headed by the served zone's name and shows its air terminal (its own
        # upstream cell) plus its zone-level HVAC equipment.
        self.assertIn('Zone:', html,
                      'air-loop demand draws a per-zone cell headed by the zone name')
        self.assertRegex(html, r'(?i)terminal|Diffuser',
                         'the demand branch shows the served zone air terminal')
        # Zone-level equipment (baseboards on a PSZ) appears inside the zone cell.
        self.assertRegex(html, r'(?i)baseboard', 'zone cell shows zone-level equipment')

    def test_supply_components_carry_specific_type_labels(self):
        html = self.html()
        # Every supply cell reflects the component's SPECIFIC type, never the coarse
        # kind — so equipment sharing a kind is told apart and nothing is merged.

        # hs09 (ASHP + backup): the DX heat-pump heating coil and the electric backup
        # coil are DISTINCT series cells, not one merged "heating coil ×2".
        self.assertIn('DX heating coil', html, 'DX heat-pump heating coil labelled specifically')
        self.assertIn('Electric heating coil', html, 'electric backup coil labelled specifically')
        self.assertIn('DX cooling coil', html, 'DX cooling coil labelled specifically')

        # Fans carry their control type (constant- vs variable-volume matters).
        self.assertIn('Constant-volume fan', html, 'constant-volume fan labelled specifically')
        self.assertIn('Variable-volume fan', html, 'variable-volume fan labelled specifically')

        # Pumps carry their control type.
        self.assertIn('Variable-speed pump', html, 'variable-speed pump labelled specifically')

    def test_water_source_heat_pump_not_mislabeled_pump(self):
        # A plant water-source heat pump must classify as a heat pump, NEVER be
        # swallowed by the pump regex. Its cell reads "Heat pump (heating)".
        self.assertIn('Heat pump (heating)', self.html(),
                      'plant water-source heat pump surfaces as a heat pump, not a pump')

    def test_district_energy_surfaces_on_condenser_loop(self):
        html = self.html()
        # District heating/cooling on a plant supply must appear, not vanish.
        self.assertIn('District heating', html, 'district heating source surfaces')
        self.assertIn('District cooling', html, 'district cooling source surfaces')

    def test_chiller_variants_distinguished_by_compressor_type(self):
        html = self.html()
        # The fan-coil / VAV systems differ ONLY by chiller compressor type, so the
        # chiller cells must be labelled by that type parsed from the object name.
        self.assertIn('Centrifugal chiller', html,
                      'centrifugal chiller labelled by compressor type')
        self.assertIn('Scroll chiller', html, 'scroll chiller labelled by compressor type')

    def test_parallel_boilers_render_as_two_cells(self):
        html = self.html()
        # Two boilers are genuine parallel equipment: they render as two distinct
        # cells (Primary + Secondary), never a collapsed "Boiler ×2".
        self.assertIn('Primary boiler', html, 'lead boiler is its own cell')
        self.assertIn('Secondary boiler', html, 'lag boiler is its own cell')
        self.assertNotRegex(html, r'Boiler\s*×2',
                            'boilers are not collapsed into a counted cell')

    def test_cascade_has_center_band_labels(self):
        html = self.html()
        # The vertical cascade mirrors the OpenStudio App's GridItem.cpp layout: a
        # center connector band between the supply row and the demand block carries
        # the "Supply Equipment" and "Demand Equipment" labels.
        self.assertIn('Supply Equipment', html,
                      'center band carries the Supply Equipment label')
        self.assertIn('Demand Equipment', html,
                      'center band carries the Demand Equipment label')

    def test_demand_splitter_mixer_and_stacked_branches(self):
        html = self.html()
        # The demand block is a splitter -> parallel branches (stacked vertically) ->
        # mixer, matching the OS App. The splitter/mixer nodes and each stacked branch
        # carry a marker class so the structure is assertable without pixel coords.
        self.assertRegex(html, r'class="demand-splitter"', 'demand splitter node present')
        self.assertRegex(html, r'class="demand-mixer"', 'demand mixer node present')
        branches = html.count('class="demand-branch"')
        self.assertGreaterEqual(branches, 2,
                                f'vertically-stacked demand branches present, got {branches}')

    def test_writes_file_matching_return_value(self):
        # reference first: the memoized render is what writes OUT_PATH (order-independent)
        rendered = self.html()
        self.assertTrue(os.path.exists(OUT_PATH),
                        'catalog_html writes a file when a path is given')
        with open(OUT_PATH, encoding='utf-8') as f:
            written = f.read()
        self.assertEqual(rendered, written, 'written file equals the returned string')
        for r in self.rows():
            self.assertIn(self.esc(r['name']), written,
                          "written file contains argument name {}".format(r['name']))


if __name__ == '__main__':
    unittest.main()


@needs_sdk
class TestSeedModelContracts(unittest.TestCase):
    """Two independent contracts, split deliberately (review, 2026-08-27).

    The default seed model must resolve from wherever the package is
    installed, AND an unreadable path must fail loudly. They are separate
    because the original defect satisfied neither: the default pointed
    outside the package (absent from a wheel) and the failure was silent,
    so a wheel user got a 1 MB catalog with 97 'diagram unavailable' cards
    that looked like a successful report.
    """

    def test_default_seed_resolves_through_the_package(self):
        from btap.modeling.hvac import catalog_report
        seed = Path(catalog_report.FIXTURE)
        self.assertTrue(seed.is_file(), f"packaged seed model missing: {seed}")
        # It must live INSIDE the package, not be reached by walking out of it.
        package_root = Path(catalog_report.__file__).resolve().parent
        self.assertTrue(seed.resolve().is_relative_to(package_root),
                        f"seed model is outside the package: {seed}")

    def test_unreadable_seed_raises_instead_of_degrading(self):
        from btap.modeling.hvac import catalog_report
        with self.assertRaises(ValueError) as ctx:
            catalog_report.to_html(fixture="/nonexistent/seed.osm")
        self.assertIn("/nonexistent/seed.osm", str(ctx.exception),
                      "the error must name the path it could not read")

    def test_empty_optional_never_reaches_get(self):
        # Guards the root cause: OptionalModel.get() on an EMPTY optional
        # returns an empty Model rather than raising (Ruby raises), and
        # .get() on other empty Optionals raises SystemError while leaving
        # the C error indicator set — which can segfault a later call.
        import openstudio
        empty = openstudio.model.Model.load(openstudio.path("/nonexistent.osm"))
        self.assertFalse(empty.is_initialized())
        self.assertEqual(0, len(empty.get().getThermalZones()),
                         "documents the trap: .get() yields an EMPTY model, no raise")
