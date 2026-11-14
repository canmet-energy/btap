"""`scripts/sdk_api.py` — the SDK API lookups, and what they must keep answering.

The script exists because three SDK questions were answered by invention or by
probing during #164/#165 when the image already shipped the answer:

- which classes carry a method (`layers()` is on `LayeredConstruction`, not on
  `ConstructionBase`);
- how two classes are related (`Construction` and
  `ConstructionWithInternalSource` are SIBLINGS, so trying one downcast before
  the other preserves nothing — a docstring claimed otherwise);
- which methods return `boost::optional<T>`, and therefore which unguarded
  `.get()` calls can segfault rather than raise (#169).

These tests pin the lookups, not the SDK: a figure that moves with an SDK
version is asserted as a floor or a relationship, never as an exact count.
"""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_PYTHON = Path(__file__).resolve().parent.parent
SCRIPT = REPO_PYTHON / 'scripts' / 'sdk_api.py'
SDK = Path('/usr/local/openstudio-3.11.0')


def needs_sdk_files(test):
    """Skip when the SDK's own files are absent.

    NOT the same as `tests.support.needs_sdk`: this script never imports
    openstudio. It reads the proxy `.py` files and the C++ headers as text, so
    it runs where the wheel is installed but the full SDK tree is not — and
    must skip there rather than fail.
    """
    present = (SDK / 'Python').is_dir() and (
        SDK / 'include/openstudio/model').is_dir()
    if not present and os.environ.get('BTAP_ENGINE_REQUIRED'):
        # The `verify` lane runs on the CI image, which HAS the tree — review
        # of #170 noted that a skip there would be vacuous green if a future
        # base image dropped `include/`. Where the engine is declared
        # required, an absent tree is a failure, not a skip.
        return test
    return unittest.skipUnless(
        present, f'needs the SDK file tree under {SDK}')(test)


def run(*args):
    out = subprocess.run([sys.executable, '-I', str(SCRIPT), *args],
                         capture_output=True, text=True, check=False,
                         timeout=300)
    return out


@needs_sdk_files
class TestClassTree(unittest.TestCase):

    def test_the_sibling_relationship_a_docstring_once_invented(self):
        """`Construction` and `ConstructionWithInternalSource` are siblings.

        `_as_layered` was first written to try `to_ConstructionWithInternalSource`
        before `to_Construction`, documenting a reason the order mattered. It
        did not: both derive from `LayeredConstruction`, so the casts are
        disjoint. This is the lookup that says so.
        """
        out = run('tree', 'LayeredConstruction', '--subclasses')
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn('Construction', out.stdout)
        self.assertIn('ConstructionWithInternalSource', out.stdout)
        self.assertIn('direct subclasses (2)', out.stdout,
                      'exactly two, which is why ONE to_LayeredConstruction '
                      f'cast covers both. Got: {out.stdout}')

    def test_the_ancestry_places_layers_above_ConstructionBase(self):
        out = run('tree', 'Construction')
        self.assertEqual(0, out.returncode, out.stderr)
        chain = [name.strip() for name in out.stdout.split('->')]
        self.assertLess(
            chain.index('LayeredConstruction'), chain.index('ConstructionBase'),
            'LayeredConstruction must sit BETWEEN Construction and '
            f'ConstructionBase — that is why a ConstructionBase has no '
            f'layers(). Got: {out.stdout}')

    def test_an_unknown_name_suggests_rather_than_traces_back(self):
        out = run('tree', 'Constructionn')
        self.assertNotEqual(0, out.returncode)
        self.assertIn('not a class', out.stderr)
        self.assertIn('Did you mean', out.stderr,
                      'a near miss must offer candidates, or the tool is '
                      'harder to use than grepping')


@needs_sdk_files
class TestOptionalFamilies(unittest.TestCase):

    def test_the_crash_family_is_the_larger_half_of_the_surface(self):
        """The fact #169 rests on, asserted as a relationship not a count."""
        out = run('optionals')
        self.assertEqual(0, out.returncode, out.stderr)
        counts = {}
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in ('crash', 'default', 'raise'):
                counts[parts[0]] = int(parts[1])
        self.assertEqual({'crash', 'default', 'raise'}, set(counts),
                         f'all three families must be reported: {out.stdout}')
        self.assertGreater(
            counts['crash'], 500,
            'the crash family is the bulk of the optional surface; if it has '
            'collapsed, either the SDK changed or the header parse broke')
        self.assertLess(
            counts['default'], counts['crash'],
            'the SILENTLY-returning family is the rare one — #164 found 2 of '
            '617 types. If it is now the majority, D-79 needs revisiting')

    def test_a_method_returning_a_model_object_is_crash_family(self):
        out = run('optionals', '--on', 'ThermalZone', '--list')
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn('crash', out.stdout,
                      'optional<ThermalZone> must classify as crash — a model '
                      f'object. Got: {out.stdout[:300]}')
        self.assertNotIn('  raise  ', out.stdout)

    @staticmethod
    def _families(stdout):
        """Parse the tally lines only.

        The first version of this matched loose substrings and caught the
        script's own closing explanation, which contains the word 'crash'. A
        test that reads a tool's prose instead of its output is worthless.
        """
        counts = {}
        for line in stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in ('crash', 'default', 'raise'):
                counts[parts[0]] = int(parts[1])
        return counts

    def test_a_double_only_method_is_raise_and_a_mixed_one_is_its_WORST(self):
        """`--on double` is mostly raise-family, and the exception is correct.

        `getViewFactor()` is declared `optional<ViewFactor>` in one overload
        and `optional<double>` in another, so it classifies as CRASH. That is
        the contract: a method overloaded across families is reported at the
        worst, because that is what a caller must guard against.

        The first version of this test asserted no crash row existed under
        `--on double` and failed on exactly that method. Excluding it would
        have been shaping the assertion around the inconvenient case; the
        property to assert is that every crash row is JUSTIFIED by wrapping
        something that is not a double.
        """
        out = run('optionals', '--on', 'double', '--list')
        self.assertEqual(0, out.returncode, out.stderr)
        counts = self._families(out.stdout)
        self.assertGreater(counts.get('raise', 0), 100,
                           f'optional<double> is the bulk of it: {out.stdout[:200]}')

        rows = re.findall(r'^\s+(crash|raise|default)\s+(\w+)\(\) -> '
                          r'optional<([^>]*)>', out.stdout, re.M)
        self.assertTrue(rows, f'--list must print rows: {out.stdout[:200]}')

        # The POSITIVE half, which this test lacked until review: inverting the
        # worst-case rule so `raise` beat `crash` left all nine tests green,
        # because checking only that crash rows are justified never asserts
        # that a mixed row IS crash. A test rewritten to pass is exactly where
        # to look for that.
        self.assertIn(
            ('crash', 'getViewFactor'), {(f, m) for f, m, _ in rows},
            'getViewFactor() wraps ViewFactor AND double, so the worst-case '
            'rule must classify it crash. If this fails, the rule has been '
            f'inverted or the method renamed. Rows: {out.stdout[:300]}')
        for fam, method, wrapped in rows:
            types = set(wrapped.rstrip('…').split(','))
            self.assertIn('double', types,
                          f'{method} was selected by --on double but does not '
                          f'wrap one: {wrapped}')
            if fam == 'crash':
                self.assertTrue(
                    types - {'double'},
                    f'{method} is classified crash while wrapping only double '
                    f'— the worst-case rule has nothing to justify it')


    @staticmethod
    def _rows(stdout):
        """`[(family, method, wrapped_types)]` from a `--list` listing."""
        rows = []
        for line in stdout.splitlines():
            found = re.match(
                r'\s+(crash|raise|default)\s+(\S+?)\(\) -> optional<(.+)>$',
                line)
            if found:
                rows.append((found.group(1), found.group(2), found.group(3)))
        return rows

    def test_a_namespaced_type_is_reduced_to_its_bare_name(self):
        """`std::string` must classify as raise, not crash.

        `optional_methods()` strips the namespace off a simple T. Dropping
        that strip moves 117 declarations from raise to crash in silence —
        nothing asserted on `--on string`, so the mutation was free.
        """
        out = run('optionals', '--on', 'string')
        self.assertEqual(0, out.returncode, out.stderr)
        counts = self._families(out.stdout)
        self.assertGreater(counts.get('raise', 0), 50,
                           'optional<std::string> is a large raise-family '
                           f'group: {out.stdout}')
        # A name wrapping ONLY string is never crash. The assertion used to
        # be that NO crash row appears at all, which held while the scan
        # covered `model/` alone. With `utilities/**` in it (#175) exactly one
        # name LANDS ON CRASH — `buildingType() ->
        # optional<FSBuildingType,string>` — and reporting it at its worst is
        # the rule working, not the namespace strip failing. This is the same
        # shape as the `--on double` check above: the worst-case rule must
        # have something to justify it.
        #
        # FOUR names are overloaded across families under `--on string`;
        # `fuelType`, `getField` and `units` land on default, so "exactly one
        # overloaded" would be wrong — exactly one lands on CRASH.
        # `FSBuildingType` cannot be measured: no proxy file mentions it and
        # there is no `OptionalFSBuildingType`, so it is unreachable from
        # Python and stays crash by the conservative default (Fable, review
        # of #182).
        for fam, method, wrapped in self._rows(out.stdout):
            if fam != 'crash':
                continue
            types = set(wrapped.rstrip('…').split(','))
            self.assertTrue(
                types - {'string'},
                f'{method} is classified crash while wrapping only string — '
                'so `string` has left RAISES. NOT a namespace-strip failure: '
                'losing that strip makes the wrapped read `std::string`, which '
                "this listing's own `--on string` filter then excludes, so the "
                f'`> 50` assertion above is what reddens: {out.stdout}')


    def test_the_comment_strip_is_load_bearing(self):
        """A ceiling, because the widened match needs the strip.

        Raw text matches 3896 declarations and stripped text 3845: fifty-one
        commented-out declarations would be false positives. Dropping the
        line-comment strip passed every other test, so this asserts a CEILING
        rather than an exact figure — exact counts move with an SDK version,
        while fifty-one phantom declarations would blow straight through it.

        The figures were 3172/3122 while the scan covered `model/` alone;
        `utilities/**` joined it in #175 and the gap between them stayed at
        about fifty, so the ceiling still sits inside it.
        """
        out = run('optionals')
        self.assertEqual(0, out.returncode, out.stderr)
        match = re.search(r'\((\d+) declarations in all\)', out.stdout)
        self.assertIsNotNone(match, f'no declaration count: {out.stdout}')
        count = int(match.group(1))
        self.assertGreater(count, 3000,
                           'the match has collapsed; the header parse broke')
        self.assertLess(count, 3870,
                        f'{count} declarations is above what the headers hold '
                        'once comments are stripped — the strip has been lost '
                        'and commented-out declarations are being counted')

    def test_a_declaration_the_narrow_regex_could_not_reach(self):
        """One of the 41 recovered, so the prefix handling is pinned.

        Dropping the `OS_DEPRECATED`/`static` prefixes — the whole point of
        the widened regex — passed every test until this one. `Component::load`
        is `static`, which the original could not cross.
        """
        out = run('method', 'load')
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn('Component.hpp', out.stdout,
                      'Component::load is a static boost::optional returner; '
                      'if it is missing, the static/OS_DEPRECATED prefixes are '
                      f'no longer matched. Got: {out.stdout[:300]}')


@needs_sdk_files
class TestMethodDeclarations(unittest.TestCase):

    def test_it_reports_the_return_type_the_proxy_files_lack(self):
        """The headers' unique contribution.

        Zero of the SWIG proxy files' class-body methods carry a `->`
        annotation, so a return type can only come from the C++ headers. This
        is the lookup that tells a caller `insulation()` needs `opt()`.
        """
        out = run('method', 'insulation')
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn('boost::optional<OpaqueMaterial>', out.stdout)
        self.assertIn('LayeredConstruction.hpp', out.stdout)

    def test_a_method_it_cannot_find_explains_where_else_to_look(self):
        out = run('method', 'thisIsNotAnSdkMethod')
        self.assertNotEqual(0, out.returncode)
        self.assertIn('no declaration', out.stderr)
        self.assertIn('SWIG-synthesized', out.stderr,
                      'the failure must say WHERE else the answer could be, '
                      'since a missing header declaration does not mean the '
                      'method does not exist')


class TestItDegradesWithoutTheSdk(unittest.TestCase):
    """It must fail with a sentence, not a traceback, off-image."""

    def test_a_missing_sdk_root_names_the_problem(self):
        out = run('--sdk', '/nonexistent/openstudio', 'tree', 'Construction')
        self.assertNotEqual(0, out.returncode)
        self.assertIn('sdk_api:', out.stderr)
        self.assertNotIn('Traceback', out.stderr,
                         'an absent SDK is an expected condition on a bare '
                         f'runner, not a crash. Got: {out.stderr[:300]}')


class TestTheMeasuredSetsStaySeparate(unittest.TestCase):
    """`MEASURED_CRASH` must be read by something, or it is a comment.

    It records the four utilities types measured as CRASHING, which `family()`
    reaches by fallthrough anyway — so adding `UUID` to `RETURNS_DEFAULT`
    silently reclassified a measured crash and passed every test. A frozenset
    nothing reads cannot object to being contradicted.
    """

    def test_a_measured_crash_cannot_be_reclassified_as_safe(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('sdk_api', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(module.MEASURED_CRASH, 'the record must not be empty')
        for name in sorted(module.MEASURED_CRASH):
            with self.subTest(wrapped=name):
                self.assertNotIn(
                    name, module.RETURNS_DEFAULT,
                    f'{name} was MEASURED to crash; listing it as returning a '
                    'default would under-report danger')
                self.assertNotIn(name, module.RAISES, f'{name} crashes')
                self.assertEqual(
                    'crash', module.family(name),
                    f'family({name!r}) must agree with the measurement')


if __name__ == '__main__':
    unittest.main()
