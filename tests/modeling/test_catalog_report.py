"""Full-coverage render: builds all 108 catalog systems on the fixture, extracts
their real topology, and asserts the self-contained HTML catalog contains every
system, draws most of them, and makes NO external requests. Building 108 models
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

    def test_contains_every_id_display_and_legacy_name(self):
        from btap.modeling.hvac import taxonomy
        html = self.html()
        for key in ('id', 'legacy_name'):
            missing = [r[key] for r in self.rows() if self.esc(r[key]) not in html]
            self.assertEqual([], missing, f'{key}s missing from catalog HTML: {missing!r}')
        missing = [r['id'] for r in self.rows() if self.esc(taxonomy.display(r)) not in html]
        self.assertEqual([], missing, f'display names missing for: {missing!r}')

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

    def test_the_tree_is_category_then_type(self):
        from btap.modeling.hvac import taxonomy
        html = self.html()
        tree = taxonomy.tree()
        self.assertEqual(len(tree), html.count('<section class="nav-cat">'))
        # A type with several variants is a collapsible group; a type with ONE
        # variant is that single entry, so the tree does not repeat itself.
        sizes = [len(rows) for types in tree.values() for rows in types.values()]
        self.assertEqual(sum(1 for n in sizes if n > 1), html.count('<details class="nav-type"'))
        self.assertEqual(sum(1 for n in sizes if n == 1), html.count('class="nav-type nav-single"'))
        self.assertEqual(len(self.rows()), html.count('class="nav-item"'))

    def test_variant_labels_are_terse_and_unique_within_their_type(self):
        """phylroy (2026-11-26): the tree repeated itself going down. A variant
        is labelled by what its siblings do NOT share; the full name stays in
        its tooltip and the detail pane."""
        from btap.modeling.hvac import catalog_report, taxonomy
        tree = taxonomy.tree()
        for types in tree.values():
            for system_type, rows in types.items():
                if len(rows) < 2:
                    continue
                cards = [{'row': r} for r in rows]
                shared, entries = catalog_report._tree_labels(cards)
                paths = [(sub, label) for sub, _, label in entries]
                with self.subTest(system_type=system_type):
                    self.assertEqual(len(paths), len(set(paths)), paths)
                    for (sub, sub_shared, label), row in zip(entries, rows):
                        self.assertLess(len(label), len(taxonomy.display(row)))
                        for phrase in shared + sub_shared + ([sub] if sub else []):
                            self.assertNotIn(phrase, label.split(', '))
                    if len(rows) > catalog_report.SUBGROUP_ABOVE:
                        self.assertTrue(any(sub for sub, _, _ in entries),
                                        f'{system_type}: a large type gets a second level')

    def test_the_tree_path_loses_no_equipment(self):
        """phylroy (2026-11-26): 'Window air conditioner' alone hid the unit's
        electric baseboards. Every phrase of a system's full name must be
        shown somewhere on its tree path: the type's 'all:' line, its
        subgroup and that line, or its own label."""
        from btap.modeling.hvac import catalog_report, taxonomy
        for types in taxonomy.tree().values():
            for rows in types.values():
                shared, entries = catalog_report._tree_labels([{'row': r} for r in rows])
                for row, (sub, sub_shared, label) in zip(rows, entries):
                    _, body, plant = taxonomy.display_parts(row)
                    wanted = {catalog_report._tree_phrase(p) for p in body + plant}
                    shown = (set(shared) | set(sub_shared) | ({sub} if sub else set())
                             | set(label.split(', ')))
                    with self.subTest(id=row['id']):
                        self.assertEqual(set(), wanted - shown)
                        self.assertNotEqual('base configuration', label)

    def test_a_single_variant_entry_shows_its_equipment(self):
        html = self.html()
        self.assertIn('Window air conditioner (Window AC)<span class="nav-detail">'
                      'window AC units that ventilate, electric baseboards</span>', html)

    def test_the_tree_is_sorted_below_the_categories(self):
        """phylroy (2026-11-26): the outdoor-air section was not sorted.
        Categories keep their deliberate order; each level below is
        alphabetical (case-insensitive)."""
        import html as html_mod
        import re
        page = self.html()
        nav = page[page.index('<nav class="nav-list">'):page.index('</nav>')]
        for section in re.findall(r'<section class="nav-cat">(.*?)</section>', nav, re.S):
            singles = [html_mod.unescape(h) for h in re.findall(
                r'<div class="nav-type nav-single"><button[^>]*>([^<]*)<span', section)]
            types = [html_mod.unescape(h) for h in re.findall(
                r'<details class="nav-type" open><summary>([^<]*?) <span', section)]
            ordered = re.findall(r'<details class="nav-type" open><summary>([^<]*?) <span'
                                 r'|<div class="nav-type nav-single"><button[^>]*>([^<]*)<span', section)
            names = [html_mod.unescape(a or b) for a, b in ordered]
            self.assertEqual(sorted(names, key=str.casefold), names)
            self.assertEqual(len(names), len(types) + len(singles))
        for group in re.findall(r'<details class="nav-sub">(.*?)</details>', nav, re.S):
            labels = [html_mod.unescape(x) for x in re.findall(r'class="nav-item"[^>]*>([^<]*)</button>', group)]
            self.assertEqual(sorted(labels, key=str.casefold), labels)

    def test_a_variant_says_what_it_lacks(self):
        """Fable (naming review): 'without hot water baseboards, HRV' read as
        'with HRV'. A variant lacking what a sibling has says "no ..."."""
        from btap.modeling.hvac import catalog, catalog_report, taxonomy
        pvav = [r for r in catalog.rows() if taxonomy.facets(r)['system_type'] == 'pvav']
        _, entries = catalog_report._tree_labels([{'row': r} for r in pvav])
        plain = dict(zip([r['id'] for r in pvav], [e[2] for e in entries]))['pvav-hw-gasboiler']
        self.assertEqual('no baseboards, no heat recovery', plain)
        self.assertNotIn('without', ' '.join(e[2] for e in entries))

    def test_the_system_list_is_resizable(self):
        html = self.html()
        self.assertIn('id="splitter" role="separator"', html)
        self.assertIn('--sidebar-w', html)
        # every filter chip is a labelled checkbox with a unique id
        ids = re.findall(r'<input type="checkbox" id="(f-[^"]+)"', html)
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))

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
        self.assertRegex(html, r'class="[^"]*\bnav-type\b', 'type-grouped nav present')
        self.assertRegex(html, r'class="filters"', 'facet filters present')

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
            self.assertIn(self.esc(r['id']), written,
                          "written file contains id {}".format(r['id']))


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

    # The SDK behaviour that makes the contract above necessary — that
    # unwrapping an empty OptionalModel yields an EMPTY model rather than
    # raising, so an unreadable seed must be refused explicitly — is not a
    # contract of this module and is not asserted here. It lives in
    # tests/test_sdk_invariants.py, which probes it in a SUBPROCESS.
    #
    # It WAS asserted here, in-process, until issue #141. The cause was not
    # what that issue and `opt()` both assumed (a stale C error indicator left
    # by a predecessor): it is that the first unwrap of an empty
    # default-constructible optional returns a default object and every later
    # one raises, per class and per process. So this probe's result depended on
    # whether a predecessor in its xdist worker had constructed a `Model()` —
    # which nearly every SDK test does — and the worker layout shifts whenever
    # tests are added anywhere. An in-process probe cannot observe a
    # first-call behaviour; only the isolated copy can.


if __name__ == '__main__':
    unittest.main()
