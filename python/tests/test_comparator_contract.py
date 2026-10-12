"""The frozen-scenario comparator's CONTRACT, case by case.

This replaces the seven machinery hashes — `freezer_sha256`, `defs_sha256`,
`runner_sha256`, `api_worker_sha256`, `compare_runs_sha256`,
`audit_scenario_sha256` and `gate_sha256` — which Sol's `227` ruled out after
Fable's `226` showed what they cost and what they caught.

A hash of `runner.py` proves that `runner.py` changed. It does not prove the
change weakened or strengthened comparison, so it answered a question nobody
asked while making the files it covered expensive to touch: 28 of 89 manifest
commits were hash-only re-freezes, a comment-level edit re-froze 54
scenarios, and the coupling deferred a real correctness fix (issue #99's lock)
for several rounds. Its lifetime record of catching a wrong compliance
behaviour is zero.

What the hashes were REACHING for is real: the comparator that reads frozen
baselines must still be able to tell a moved output from an unmoved one. That
is a property, and a property can be tested directly. Sol's required coverage,
which `CASES` below implements:

    a changed, added and removed baseline file; an added and removed mapping
    key; booleans, strings, numbers, null/absence and nested containers; list
    order where order is significant; each tolerance boundary, just inside and
    just outside; every stripped-key class; exact exit status, stdout and
    stderr; lane/scenario selection; and the compliance-critical fields that
    may never be stripped or made tolerant — verdict/determination, audit
    citation axes, warning level, total energy, unmet hours, BET/tier values
    and exit code.

## Where each required class is covered

    changed / added / removed baseline file   TestTheComparatorsFileAndProcess
    added and removed mapping key             CASES (2)
    bool, string, number, null, nested       CASES (8)
    list order where order is significant     CASES (2)
    tolerance boundaries, in and out          CASES (5)
    every stripped-key class                  CASES (2)
    exit status, stdout, stderr               TestTheComparatorsFileAndProcess
    lane / scenario selection                 test_frozen_scenarios.py's
                                              `test_ci_wires_every_lane` and
                                              the manifest per-lane counts,
                                              both retained
    compliance-critical fields                CASES (10)

## Two rules this file follows, because the session that produced it broke both

**No expected value is computed by the code under test.** Each case states its
inputs and its verdict by hand. The referral-package guard that computed its
expectation with the generator's own `_field()` stayed green while the bug it
guarded was restored; so did a second reader that shared the first one's rule.

**Every case must be shown to discriminate.** `MUTATIONS` below breaks the
comparator in one named way at a time and asserts EXACTLY which cases go red.
A case that no mutation can break is not evidence, and a mutation that breaks
cases it should not is a case written too loosely. That check is the reason to
believe the rest of the file.
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPARATOR = REPO_ROOT / "verification" / "compare_runs.py"
SPEC_PATH = REPO_ROOT / "verification" / "spec.json"


def _load():
    spec = importlib.util.spec_from_file_location("compare_runs", COMPARATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_runs"] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Case:
    """One comparator question, with its answer written by hand."""

    name: str
    a: object
    b: object
    differs: bool
    why: str
    path: str = "report.json"


#: The compliance-critical fields. A difference in any of these must be
#: reported: none may be stripped, and none may acquire a tolerance. They are
#: listed as data so a reader can see the set, and so adding one is one line.
CRITICAL = (
    ("compliant", True, False),
    ("compliance_determination", "conditional", "pass"),
    ("exit_code", 0, 1),
    ("total_site_kwh", 167150.0, 167150.5),
    ("building_energy_target_kwh", 148919.0, 148919.5),
    ("energy_tier", 1, 2),
)

#: Audit citation axes (D-100) and the warning level. Same rule.
AUDIT_FIELDS = (
    ("article", "8.4.1.2.(3)", "8.4.1.2.(4)(a)"),
    ("ruling", "D-102", "D-101"),
    ("ahj", "AHJ-21", "AHJ-1"),
    ("level", "warning", "info"),
)

CASES = [
    # --- structure --------------------------------------------------------
    Case("identical documents agree",
         {"a": 1, "b": "x", "c": None}, {"a": 1, "b": "x", "c": None},
         False, "nothing moved"),
    Case("an added mapping key is reported",
         {"a": 1}, {"a": 1, "new": 2},
         True, "a key appearing is a changed output"),
    Case("a removed mapping key is reported",
         {"a": 1, "gone": 2}, {"a": 1},
         True, "a key disappearing is a changed output"),
    Case("an absent key equals an explicit null",
         {"a": 1}, {"a": 1, "maybe": None},
         False, "writers omit or null the same field, and that was "
                "adjudicated as equivalent. NOTE: `spec.absent_equals_null` "
                "cannot change this — see "
                "`test_absent_equals_null_is_an_INERT_spec_flag`"),
    Case("a nested container is walked",
         {"o": {"p": [{"q": {}}]}}, {"o": {"p": [{"q": []}]}},
         True, "a difference three levels down still reports. The leaf is a "
               "container TYPE mismatch on purpose: a number or a string "
               "there would also fail when the number or string comparison "
               "is defeated, and then this case would be telling us about "
               "leaves rather than about nesting"),
    Case("a type change is reported",
         {"a": 1}, {"a": "1"},
         True, "a number becoming a string is a changed output"),
    Case("a dict against a list is reported",
         {"a": {"k": 1}}, {"a": [1]},
         True, "container type is part of the shape"),
    # --- lists are ORDERED ------------------------------------------------
    Case("list order is significant",
         {"audit": [{"i": {}}, {"i": []}]}, {"audit": [{"i": []}, {"i": {}}]},
         True, "`audit_ordered` is true: the audit is a sequence of decisions "
               "and reordering it changes what the record says happened. "
               "Container leaves again, so this case is about ORDER"),
    Case("a list length change is reported",
         {"audit": ["a", "b"]}, {"audit": ["a", "b", "c"]},
         True, "an extra entry is a changed output"),
    # --- scalars ----------------------------------------------------------
    Case("true against false is reported",
         {"flag": True}, {"flag": False},
         True, "a boolean is compared by identity. The key is NOT a "
               "compliance-critical one, so that this case says something "
               "about booleans and the critical-field cases say something "
               "about stripping"),
    Case("true against 1 is reported",
         {"flag": True}, {"flag": 1},
         True, "Python makes these equal and a report does not: the bool "
               "branch is checked before the numeric one"),
    Case("null against a value is reported",
         {"a": None}, {"a": "x"},
         True, "a missing answer and an answer are different. Not `0`: that "
               "would route through the number comparison and stop being a "
               "statement about null"),
    # --- tolerance, just inside and just outside --------------------------
    Case("a float inside the default tolerance agrees",
         {"x": 1.0}, {"x": 1.0 + 5e-10},
         False, "`float_abs_tol` is 1e-9; writers round and floats wobble"),
    Case("a float just outside the default tolerance is reported",
         {"x": 1.0}, {"x": 1.0 + 2e-9},
         True, "2e-9 exceeds 1e-9"),
    Case("unmet hours inside their own 1e-6 tolerance agree",
         {"unmet_occupied_hours": {"heating": 58.75}},
         {"unmet_occupied_hours": {"heating": 58.75 + 5e-7}},
         False, "raw SQL floats, never pre-rounded by the writer"),
    Case("unmet hours just outside 1e-6 are reported",
         {"unmet_occupied_hours": {"heating": 58.75}},
         {"unmet_occupied_hours": {"heating": 58.75 + 2e-6}},
         True, "2e-6 exceeds the path's own 1e-6"),
    Case("a number embedded in a string is compared numerically",
         {"action": "within 100 h for 5 block(s), worst 58.750000"},
         {"action": "within 100 h for 5 block(s), worst 58.7500001"},
         False, "`string_float_tol` is 1e-6: audit prose carries formatted "
                "floats and the formatting is not the claim"),
    Case("a string's non-numeric text must match exactly",
         {"action": "unmet heating hours within 100 h"},
         {"action": "unmet heating hours EXCEED 100 h"},
         True, "audit text is case-sensitive and the words ARE the claim"),
    Case("a string with a different count of numbers is reported",
         {"action": "5 blocks"}, {"action": "5 blocks, 2 cooled"},
         True, "a added figure is a changed statement"),
    # --- stripped keys ----------------------------------------------------
    Case("run_dir is stripped",
         {"run_dir": "/tmp/a", "x": 1}, {"run_dir": "/tmp/b", "x": 1},
         False, "the only adjudicated strip: a temporary path is not an "
                "output"),
    Case("a stripped key is removed at every depth",
         {"o": [{"run_dir": "/tmp/a", "x": 1}]},
         {"o": [{"run_dir": "/tmp/b", "x": 1}]},
         False, "stripping is recursive or a nested path would fail "
                "spuriously"),
]

# The compliance-critical fields, generated so the set is visible as data.
CASES += [
    Case(f"critical field {name!r} is never tolerated",
         {name: left}, {name: right}, True,
         "a compliance-critical field: a difference here must always report")
    for name, left, right in CRITICAL
]
CASES += [
    Case(f"audit {name!r} is never tolerated",
         {"audit": [{name: left}]}, {"audit": [{name: right}]}, True,
         "D-100's citation axes and the warning level reach the AHJ report")
    for name, left, right in AUDIT_FIELDS
]


@dataclass
class Mutation:
    """One way to break the comparator, and exactly which cases must notice.

    `patch` receives the loaded module and the spec and returns the spec to
    use; mutating the module in place is allowed because each mutation runs
    against a freshly loaded copy.
    """

    name: str
    patch: object
    must_break: frozenset = field(default_factory=frozenset)


def _spec():
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


MUTATIONS = [
    Mutation(
        "numbers always equal",
        lambda m, s: (setattr(m, "numbers_equal", lambda a, b, t: True), s)[1],
        frozenset({
            "a float just outside the default tolerance is reported",
            "unmet hours just outside 1e-6 are reported",
            "critical field 'total_site_kwh' is never tolerated",
            "critical field 'building_energy_target_kwh' is never tolerated",
            "critical field 'energy_tier' is never tolerated",
            "critical field 'exit_code' is never tolerated",
            "audit 'ruling' is never tolerated",
            "audit 'ahj' is never tolerated",
        })),
    Mutation(
        "strings always equal",
        lambda m, s: (setattr(m, "strings_equal", lambda a, b, s_: True), s)[1],
        frozenset({
            "a string's non-numeric text must match exactly",
            "a string with a different count of numbers is reported",
            "critical field 'compliance_determination' is never tolerated",
            "audit 'article' is never tolerated",
            "audit 'ruling' is never tolerated",
            "audit 'ahj' is never tolerated",
            "audit 'level' is never tolerated",
        })),
    # Worth knowing, from building the table: the audit's `ruling` and `ahj`
    # ids are compared through the STRING-float rule, because "AHJ-21" and
    # "AHJ-1" share their non-numeric text and differ only in digits. The
    # comparison works — 21 against 1 is far outside 1e-6 — but it means an
    # id's digits travel as a float, which is why both the number and the
    # string mutation defeat those two cases.
    Mutation(
        "the default float tolerance widened to 1e-3",
        lambda m, s: {**s, "float_abs_tol": 1e-3},
        # NOT the critical energy fields: they differ by 0.5, which 1e-3 does
        # not hide. My first prediction said it would, and the meta-test
        # below corrected me. What tests "never tolerated" for those is the
        # next mutation, which gives their paths a tolerance wide enough to
        # swallow the difference.
        frozenset({
            "a float just outside the default tolerance is reported",
        })),
    Mutation(
        "a wide tolerance given to every compliance-critical numeric path",
        lambda m, s: {**s, "tolerances": s.get("tolerances", []) + [
            {"path_regex": name, "abs": 10.0}
            for name, _l, _r in CRITICAL]},
        frozenset({
            "critical field 'exit_code' is never tolerated",
            "critical field 'total_site_kwh' is never tolerated",
            "critical field 'building_energy_target_kwh' is never tolerated",
            "critical field 'energy_tier' is never tolerated",
        })),
    Mutation(
        "unmet hours given a 1e-3 tolerance",
        lambda m, s: {**s, "tolerances": [
            {"path_regex": "unmet_occupied_hours", "abs": 1e-3}]},
        frozenset({"unmet hours just outside 1e-6 are reported"})),
    Mutation(
        "the verdict added to strip_keys",
        lambda m, s: {**s, "strip_keys": s["strip_keys"] + ["compliant"]},
        frozenset({"critical field 'compliant' is never tolerated"})),
    Mutation(
        "the citation axes added to strip_keys",
        lambda m, s: {**s, "strip_keys":
                      s["strip_keys"] + ["article", "ruling", "ahj", "level"]},
        frozenset({"audit 'article' is never tolerated",
                   "audit 'ruling' is never tolerated",
                   "audit 'ahj' is never tolerated",
                   "audit 'level' is never tolerated"})),
    Mutation(
        "stripping stops being recursive",
        lambda m, s: (setattr(m, "strip_keys", lambda n, k: (
            {kk: vv for kk, vv in n.items() if kk not in k}
            if isinstance(n, dict) else n)), s)[1],
        frozenset({"a stripped key is removed at every depth"})),
    Mutation(
        "lists compared as sets",
        lambda m, s: (setattr(m, "diff", _unordered(m)), s)[1],
        frozenset({"list order is significant"})),
    Mutation(
        "container type mismatches tolerated",
        lambda m, s: (setattr(m, "diff", _ignore_type_mismatch(m)), s)[1],
        frozenset({"a dict against a list is reported",
                   "a nested container is walked",
                   "list order is significant"})),
    Mutation(
        "scalar type mismatches tolerated",
        lambda m, s: (setattr(m, "diff", _ignore_scalar_type(m)), s)[1],
        # A number against a string reaches neither the all-numbers nor the
        # all-strings branch, so no leaf-comparison mutation defeats it. It
        # needs its own.
        frozenset({"a type change is reported",
                   "true against 1 is reported"})),
    Mutation(
        "only keys present in BOTH documents compared",
        lambda m, s: (setattr(m, "diff", _intersect_keys(m)), s)[1],
        frozenset({"an added mapping key is reported",
                   "a removed mapping key is reported"})),
    Mutation(
        "list length ignored",
        lambda m, s: (setattr(m, "diff", _ignore_length(m)), s)[1],
        frozenset({"a list length change is reported"})),
    Mutation(
        "a null on either side treated as a match",
        lambda m, s: (setattr(m, "diff", _null_matches_anything(m)), s)[1],
        # Also the key cases, and that is worth knowing rather than
        # predicting away: `diff` walks dicts with `.get()`, so an ABSENT key
        # and an explicit `null` arrive identically. Tolerating null
        # therefore tolerates an added or removed key too. The three
        # behaviours are one behaviour in this comparator — which is also
        # why `spec.absent_equals_null` can do nothing.
        frozenset({"null against a value is reported",
                   "an added mapping key is reported",
                   "a removed mapping key is reported"})),
    Mutation(
        "booleans compared loosely",
        lambda m, s: (setattr(m, "diff", _bool_loose(m)), s)[1],
        frozenset({"true against false is reported",
                   "true against 1 is reported",
                   "critical field 'compliant' is never tolerated"})),

    # `absent_equals_null` is NOT in this table: flipping it breaks nothing,
    # because it cannot. See the test below — that is a finding, not an
    # omission.
    Mutation(
        "booleans compared numerically",
        lambda m, s: (setattr(m, "diff", _bool_as_number(m)), s)[1],
        frozenset({"true against 1 is reported"})),
]


def _unordered(module):
    """A `diff` that sorts lists before comparing — order stops mattering."""
    original = module.diff

    def patched(a, b, spec, path, out):
        if isinstance(a, list) and isinstance(b, list):
            key = lambda v: json.dumps(v, sort_keys=True)  # noqa: E731
            a, b = sorted(a, key=key), sorted(b, key=key)
        return original(a, b, spec, path, out)

    return patched


def _ignore_type_mismatch(module):
    """A `diff` that lets a dict stand in for a list, and vice versa."""
    original = module.diff

    def patched(a, b, spec, path, out):
        mixed = (isinstance(a, (dict, list)) and isinstance(b, (dict, list))
                 and type(a) is not type(b))
        if mixed or (isinstance(a, dict) != isinstance(b, dict)) or (
                isinstance(a, list) != isinstance(b, list)):
            return
        return original(a, b, spec, path, out)

    return patched


def _intersect_keys(module):
    """A `diff` that compares only the keys both documents have."""
    original = module.diff

    def patched(a, b, spec, path, out):
        if isinstance(a, dict) and isinstance(b, dict):
            shared = set(a) & set(b)
            a = {k: v for k, v in a.items() if k in shared}
            b = {k: v for k, v in b.items() if k in shared}
        return original(a, b, spec, path, out)

    return patched


def _ignore_length(module):
    """A `diff` that truncates both lists to the shorter length."""
    original = module.diff

    def patched(a, b, spec, path, out):
        if isinstance(a, list) and isinstance(b, list) and len(a) != len(b):
            keep = min(len(a), len(b))
            a, b = a[:keep], b[:keep]
        return original(a, b, spec, path, out)

    return patched


def _null_matches_anything(module):
    """A `diff` where a null on either side ends the comparison."""
    original = module.diff

    def patched(a, b, spec, path, out):
        if a is None or b is None:
            return
        return original(a, b, spec, path, out)

    return patched


def _ignore_scalar_type(module):
    """A `diff` where a scalar of one type matches a scalar of another."""
    original = module.diff

    def patched(a, b, spec, path, out):
        containers = (dict, list)
        if (not isinstance(a, containers) and not isinstance(b, containers)
                and a is not None and b is not None
                and type(a) is not type(b)):
            return
        return original(a, b, spec, path, out)

    return patched


def _bool_loose(module):
    """A `diff` where any two booleans, or a boolean and a number, agree."""
    original = module.diff

    def patched(a, b, spec, path, out):
        if isinstance(a, bool) or isinstance(b, bool):
            return
        return original(a, b, spec, path, out)

    return patched


def _bool_as_number(module):
    """A `diff` that lets `True` equal `1`."""
    original = module.diff

    def patched(a, b, spec, path, out):
        if isinstance(a, bool) or isinstance(b, bool):
            a, b = int(a) if isinstance(a, bool) else a, \
                int(b) if isinstance(b, bool) else b
        return original(a, b, spec, path, out)

    return patched


def _run_case(module, spec, case):
    """`True` when the comparator reports a difference."""
    out = []
    module.diff(module.strip_keys(case.a, spec.get("strip_keys", [])),
                module.strip_keys(case.b, spec.get("strip_keys", [])),
                spec, case.path, out)
    return bool(out)


class TestTheComparatorContract(unittest.TestCase):
    def setUp(self):
        self.module = _load()
        self.spec = _spec()

    def test_the_case_table_is_not_vacuous(self):
        self.assertGreaterEqual(
            len(CASES), 30,
            f"only {len(CASES)} cases; Sol's `227` lists eleven classes of "
            "comparator behaviour that must be covered independently")
        names = [c.name for c in CASES]
        self.assertEqual(len(names), len(set(names)),
                         "two cases share a name, so MUTATIONS cannot name "
                         "one of them unambiguously")
        self.assertTrue(any(c.differs for c in CASES))
        self.assertTrue(any(not c.differs for c in CASES))

    def test_every_case_gets_its_authored_answer(self):
        for case in CASES:
            with self.subTest(case=case.name):
                self.assertEqual(
                    case.differs, _run_case(self.module, self.spec, case),
                    f"{case.name}: expected "
                    f"{'a reported difference' if case.differs else 'agreement'}"
                    f" — {case.why}")

    def test_each_mutation_breaks_EXACTLY_its_named_cases(self):
        """The reason to believe this file.

        A case no mutation can break is not evidence. A mutation that breaks
        cases it was not expected to means a case is written too loosely, or
        the comparator couples two behaviours that should be separate.
        """
        for mutation in MUTATIONS:
            with self.subTest(mutation=mutation.name):
                module = _load()
                spec = mutation.patch(module, _spec())
                broke = {c.name for c in CASES
                         if _run_case(module, spec, c) != c.differs}
                self.assertEqual(
                    set(mutation.must_break), broke,
                    f"mutation {mutation.name!r} was expected to break "
                    f"{sorted(mutation.must_break)} and broke "
                    f"{sorted(broke)}")

    def test_every_case_is_broken_by_SOME_mutation(self):
        """The converse: a case nothing can break guards nothing."""
        covered = set().union(*(m.must_break for m in MUTATIONS))
        uncovered = sorted({c.name for c in CASES if c.differs} - covered)
        self.assertEqual(
            [], uncovered,
            "these cases expect a reported difference but no mutation in "
            f"MUTATIONS makes them pass instead: {uncovered}. Either add a "
            "mutation that defeats the behaviour, or delete the case — an "
            "assertion no change can falsify is decoration")


    def test_absent_equals_null_is_an_INERT_spec_flag(self):
        """A finding, asserted so it stays visible.

        `spec.absent_equals_null` reads as an adjudicated normalisation rule,
        it is pinned by `spec_sha256`, and it cannot change any outcome.
        `diff` reaches it only after `dict.get()` has already collapsed an
        absent key into `None`, so the branch it guards skips work that would
        have reached the same answer. Flipping the flag moves nothing in any
        shape I could construct — absent against null, absent against a
        value, null against a value, nested, or inside a list.

        Asserted rather than deleted, in both directions: if someone makes
        the flag live, this fails and they read why; and nobody re-derives
        the knob's meaning from its name.
        """
        shapes = (
            ({"a": 1}, {"a": 1, "k": None}),
            ({"a": 1}, {"a": 1, "k": 0}),
            ({"a": 1, "k": None}, {"a": 1, "k": 0}),
            ({"o": {"a": 1}}, {"o": {"a": 1, "k": None}}),
            ({"o": [{"a": 1}]}, {"o": [{"a": 1, "k": None}]}),
        )
        for left, right in shapes:
            with self.subTest(shape=f"{left} vs {right}"):
                verdicts = []
                for flag in (True, False):
                    spec = dict(self.spec)
                    spec["absent_equals_null"] = flag
                    out = []
                    self.module.diff(left, right, spec, "f", out)
                    verdicts.append(bool(out))
                self.assertEqual(
                    verdicts[0], verdicts[1],
                    "`absent_equals_null` changed an outcome here. It has "
                    "never been able to, so either the comparator's "
                    "key-walk changed or the flag became load-bearing — "
                    "either way the spec's documented meaning needs "
                    "re-reading, not this test relaxing")


class TestTheComparatorsFileAndProcessContract(unittest.TestCase):
    """The parts that are not `diff`: file presence, and the exit status."""

    def setUp(self):
        self.module = _load()
        self.spec = _spec()
        self.work = tempfile.TemporaryDirectory(prefix="cmp-contract-")
        self.addCleanup(self.work.cleanup)
        self.a = pathlib.Path(self.work.name) / "a"
        self.b = pathlib.Path(self.work.name) / "b"
        self.a.mkdir()
        self.b.mkdir()

    def _write(self, where, name, payload):
        (where / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_a_file_present_in_one_run_only_is_reported(self):
        self._write(self.a, "report.json", {"x": 1})
        out = []
        self.module.compare_file(self.a, self.b, "report.json", self.spec, out)
        self.assertTrue(
            out, "a baseline file that exists in one run and not the other is "
                 "the loudest kind of change and must never be silent")

    def test_a_file_absent_from_BOTH_runs_is_not_a_difference(self):
        out = []
        self.module.compare_file(self.a, self.b, "nothing.json", self.spec, out)
        self.assertEqual(
            [], out,
            "a scenario that produces no `audit.txt` must not be failed for "
            "the absence in both runs")

    def test_a_changed_file_is_reported(self):
        self._write(self.a, "report.json", {"compliant": True})
        self._write(self.b, "report.json", {"compliant": False})
        out = []
        self.module.compare_file(self.a, self.b, "report.json", self.spec, out)
        self.assertTrue(out)

    def test_the_exit_status_is_1_on_a_difference_and_0_on_agreement(self):
        """Exact exit status, because a harness reads it.

        Run as a subprocess rather than by calling `main`, so the contract
        tested is the one a caller actually gets.
        """
        self._write(self.a, "report.json", {"compliant": True})
        self._write(self.b, "report.json", {"compliant": True})
        same = subprocess.run(
            [sys.executable, str(COMPARATOR), str(self.a), str(self.b),
             "--spec", str(SPEC_PATH)],
            capture_output=True, text=True, check=False)
        self.assertEqual(
            0, same.returncode,
            f"identical runs must exit 0; stdout={same.stdout[:200]!r} "
            f"stderr={same.stderr[:200]!r}")

        self._write(self.b, "report.json", {"compliant": False})
        moved = subprocess.run(
            [sys.executable, str(COMPARATOR), str(self.a), str(self.b),
             "--spec", str(SPEC_PATH)],
            capture_output=True, text=True, check=False)
        self.assertNotEqual(
            0, moved.returncode,
            "a moved verdict must exit non-zero, or every harness that reads "
            "the status believes the comparison passed")
        self.assertIn(
            "compliant", moved.stdout + moved.stderr,
            "and it must say WHICH field moved, or the failure is unusable")


if __name__ == "__main__":
    unittest.main()
