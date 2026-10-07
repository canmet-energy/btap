"""The AHJ register is a RECORD, not a claim that one exists.

phylroy asked (2026-10-07) where AHJ issues were tracked, assuming there was
somewhere. There was not: they lived in `.reviews/` correspondence, which is
gitignored and therefore not a record at all. `docs/NECB_AHJ_QUESTIONS.md` is
that register, and these tests keep it honest in both directions:

  * every id the RUNTIME cites must exist in the file, so a condition cannot
    point at nothing;
  * every entry must say what the tool does meanwhile, so the register cannot
    become a list of questions with no stated interim behaviour.

Without these the register would rot into decoration, which is exactly what
the `.reviews/` trail already did.
"""

from __future__ import annotations

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
REGISTER = REPO_ROOT / "docs" / "NECB_AHJ_QUESTIONS.md"
PRODUCT = REPO_ROOT / "python" / "btap"

ID_RE = re.compile(r"\bAHJ-\d+\b")


def _register_text():
    return REGISTER.read_text(encoding="utf-8")


def _register_ids():
    return set(re.findall(r"^## (AHJ-\d+)", _register_text(), re.M))


def _runtime_ids():
    """Every AHJ id a product source file cites."""
    found = set()
    for path in sorted(PRODUCT.rglob("*.py")):
        found |= set(ID_RE.findall(path.read_text(encoding="utf-8")))
    return found


class TestTheRegisterExists(unittest.TestCase):
    def test_the_file_is_tracked_not_gitignored(self):
        import subprocess

        self.assertTrue(REGISTER.is_file(), f"{REGISTER} is missing")
        out = subprocess.run(
            ["git", "check-ignore", "-q", str(REGISTER)],
            cwd=REPO_ROOT, capture_output=True)
        self.assertNotEqual(
            0, out.returncode,
            "the register must be TRACKED; `.reviews/` is gitignored and that "
            "is why the questions were not a record")

    def test_it_has_entries(self):
        self.assertGreaterEqual(len(_register_ids()), 1)


class TestTheRuntimeCitationsResolve(unittest.TestCase):
    def test_every_id_cited_in_product_source_is_in_the_register(self):
        missing = sorted(_runtime_ids() - _register_ids())
        self.assertEqual(
            [], missing,
            f"product code cites AHJ id(s) with no register entry: {missing}. "
            f"A condition pointing at nothing is worse than no condition.")

    def test_the_conditional_determination_cites_at_least_one(self):
        """The 8.4.x.9.(5) condition is the one that drives a runtime
        verdict, so it must be traceable to an entry."""
        path_py = (PRODUCT / "codes" / "necb" / "path.py").read_text(
            encoding="utf-8")
        self.assertIn('"ahj_ids"', path_py)
        self.assertTrue(ID_RE.search(path_py),
                        "the conditional determination must name its entry")


class TestEveryEntryStatesItsInterimBehaviour(unittest.TestCase):
    def test_each_entry_says_what_the_tool_does_meanwhile(self):
        """An entry without stated interim behaviour lets a gap sit silently,
        which is the failure this whole branch was about."""
        text = _register_text()
        sections = re.split(r"^## (?=AHJ-\d+)", text, flags=re.M)[1:]
        self.assertTrue(sections, "no entries parsed")
        for section in sections:
            ident = section.split(" ", 1)[0].strip()
            lowered = section.lower()
            self.assertTrue(
                # "now" as well as "meanwhile": once a question is RULED and
                # the fix has landed, "meanwhile" is the wrong tense — AHJ-5
                # describes measured present behaviour, not a holding action.
                "what the tool does meanwhile" in lowered
                or "what the tool does now" in lowered
                or "no referral needed" in lowered,
                f"{ident} does not say what the tool does in the meantime")

    def test_each_entry_names_the_article_and_who_established_it(self):
        text = _register_text()
        sections = re.split(r"^## (?=AHJ-\d+)", text, flags=re.M)[1:]
        for section in sections:
            ident = section.split(" ", 1)[0].strip()
            lowered = section.lower()
            self.assertIn("**article", lowered, f"{ident} names no article")
            self.assertTrue(
                "established by" in lowered or "ruled" in lowered,
                f"{ident} does not say who established the ambiguity")


class TestTheStatusTaxonomyIsHonoured(unittest.TestCase):
    """Sol's `122` blocker 4: the register stated a one-status contract that
    two of its own six entries broke — AHJ-4 is settled and AHJ-6 is
    tool-fixable, neither a referral. Four statuses now exist, and these tests
    keep each entry honest about which one it claims."""

    STATUSES = {"referral", "alternative-solution", "ruled", "tool-gap"}

    def _rows(self):
        """The status table's rows, as (id, status)."""
        out = {}
        for line in _register_text().splitlines():
            m = re.match(r"\|\s*(AHJ-\d+)\s*\|[^|]*\|\s*([a-z-]+)\s*\|", line)
            if m:
                out[m.group(1)] = m.group(2)
        return out

    def _editions(self):
        """The `editions` column, as (id, value)."""
        out = {}
        for line in _register_text().splitlines():
            m = re.match(
                r"\|\s*(AHJ-\d+)\s*\|[^|]*\|[^|]*\|\s*([a-z0-9, ]+?)\s*\|", line)
            if m:
                out[m.group(1)] = m.group(2).strip()
        return out

    def test_every_entry_has_a_row_with_a_known_status(self):
        rows = self._rows()
        self.assertEqual(_register_ids(), set(rows),
                         "every entry needs a status-table row and vice versa")
        unknown = {i: s for i, s in rows.items() if s not in self.STATUSES}
        self.assertEqual({}, unknown, f"unknown status(es): {unknown}")

    def test_the_taxonomy_itself_is_documented(self):
        text = _register_text()
        for status in self.STATUSES:
            self.assertIn(f"`{status}`", text,
                          f"{status} is used but never defined")

    def test_a_tool_gap_or_ruled_entry_does_not_set_a_run_conditional(self):
        """The whole point of the taxonomy: a defect must not be dressed as an
        interpretation that blocks a verdict.

        REWRITTEN for Sol's `127`. This used to scan `path.py` for ids and
        demand every one be approval-required, which assumed CITED meant
        CONDITIONAL. That is now exactly the distinction the design draws: a
        rule site cites every applicable disposition, including `ruled` and
        `tool-gap`, because a reader wants to know AHJ-5 is why a WSHP group
        entered multi-energy scope. Only the resolved STATUS decides the
        verdict, and nothing but the generated register may say what a status
        is.

        So the property is now about the collector, not about which ids appear
        in a source file.
        """
        from btap.codes import ahj as registry

        self.assertEqual(
            ("referral", "alternative-solution"),
            registry.approval_required_statuses(),
            "only these two may require approval")
        rows = self._rows()
        for ident, status in sorted(rows.items()):
            record = registry.by_id().get(ident)
            self.assertIsNotNone(
                record, f"{ident} is in the register but not the projection")
            self.assertEqual(
                status, record["status"],
                f"{ident}: the authored register and the generated projection "
                f"disagree")

    def test_every_cited_id_RESOLVES_in_the_generated_projection(self):
        """A citation that resolves to nothing would turn a missing disclosure
        into a clean non-conditional success — AHJ-5's defect, one layer up."""
        from btap.codes import ahj as registry

        sources = [PRODUCT / "codes" / "necb" / "path.py",
                   PRODUCT / "codes" / "necb" / "hvac" / "reference.py"]
        table = registry.by_id()
        found = set()
        for source in sources:
            for ident in ID_RE.findall(source.read_text(encoding="utf-8")):
                found.add(ident)
                self.assertIn(
                    ident, table,
                    f"{ident} is cited in {source.name} but is not in the "
                    f"generated register")
        self.assertTrue(found, "no citations found — the scan is vacuous")


class TestEveryEntrySaysWhichEditionsItAffects(unittest.TestCase):
    """phylroy asked whether the register should carry the affected edition.
    It must: a decision taken against one edition's text otherwise reads as
    applying to both, and NECB 2025 already differs in at least one way that
    matters (its 8.4.2.12 exceptional-calculation route has no 2020
    equivalent).

    The vocabulary is `code`/`edition`. `vintage` is retired everywhere in
    this repository, so the register must not reintroduce it.
    """

    @staticmethod
    def _registered_codes():
        """The code ids that actually exist, discovered rather than listed, so
        adding an edition does not leave this gate stale."""
        data = PRODUCT / "codes" / "necb" / "data"
        return {p.parent.name for p in data.glob("*/manifest.json")}

    def test_every_entry_lists_REAL_code_ids_or_is_unverified(self):
        """phylroy: an authority must know WHICH code is affected, and a
        collective noun does not scale past two editions. So the column holds
        code ids, validated against the editions that exist."""
        codes = self._registered_codes()
        self.assertTrue(codes, "no registered editions discovered")
        eds = TestTheStatusTaxonomyIsHonoured()._editions()
        self.assertEqual(_register_ids(), set(eds),
                         "every entry needs an editions value")
        for ident, value in sorted(eds.items()):
            if value == "unverified":
                continue
            listed = {v.strip() for v in value.split(",") if v.strip()}
            self.assertTrue(
                listed, f"{ident}: empty editions value")
            unknown = listed - codes
            self.assertEqual(
                set(), unknown,
                f"{ident} lists code id(s) that are not registered: "
                f"{sorted(unknown)}; registered are {sorted(codes)}")

    def test_no_entry_uses_a_COLLECTIVE_noun_for_the_editions(self):
        """"both" was the first version of this column and it does not scale:
        a third edition would make every such row claim coverage nobody
        checked."""
        eds = TestTheStatusTaxonomyIsHonoured()._editions()
        for ident, value in sorted(eds.items()):
            for banned in ("both", "all", "any", "every"):
                self.assertNotEqual(
                    banned, value.strip().lower(),
                    f"{ident} says {value!r}; list the code ids instead")

    def test_the_register_does_not_USE_the_retired_word_as_a_concept(self):
        """`vintage` is retired as a field and a concept; `code`/`edition` is
        the vocabulary. The register may NAME it to warn against it, and may
        cite the `vintage-match` verification by its actual name — what it
        must not do is use it as the label for an edition.

        The gate's first version failed on this file's own warning sentence,
        which is the difference between forbidding a word and forbidding a
        usage."""
        for line in _register_text().lower().splitlines():
            if "vintage" not in line:
                continue
            allowed = ("vintage-match" in line or "vintage_match" in line
                       or "retired" in line)
            self.assertTrue(
                allowed,
                f"register uses 'vintage' as an edition label: "
                f"{line.strip()[:90]}")


class TestEveryEntryDeclaresItsOwnStatus(unittest.TestCase):
    """An entry must state its status in its OWN body, not only in the table.

    AHJ-7 carried a published-table referral and a missing-curve tool gap under
    one `referral` row, and nothing caught it, because nine of seventeen
    bodies named no status at all — a reader of the entry could not see which
    of the four it claimed to be. The table is still the contract; this makes
    each entry able to contradict it visibly.
    """

    def setUp(self):
        self.text = REGISTER.read_text(encoding="utf-8")
        self.rows = dict(re.findall(
            r"^\| (AHJ-\d+) \|[^|]*\| ([a-z-]+) \|", self.text, re.M))
        parts = re.split(r"^## (AHJ-\d+)", self.text, flags=re.M)
        self.bodies = {parts[i]: parts[i + 1]
                       for i in range(1, len(parts), 2)}

    def test_the_table_and_the_entries_name_the_same_ids(self):
        self.assertEqual(set(self.rows), set(self.bodies))
        self.assertTrue(self.rows, "the status table did not parse at all")

    def test_each_body_declares_the_status_its_row_declares(self):
        for ident, status in sorted(self.rows.items()):
            with self.subTest(ident):
                found = re.search(r"\*\*Status[:*\s]*`?([a-z-]+)`?",
                                  self.bodies[ident])
                self.assertIsNotNone(
                    found, "{} states no status in its own body".format(ident))
                self.assertEqual(
                    status, found.group(1),
                    "{}: the table says {!r} and the entry says {!r}".format(
                        ident, status, found.group(1)))

    def test_a_status_the_taxonomy_does_not_define_is_refused(self):
        """The four are not decorative: only `referral` and
        `alternative-solution` may set a run conditional."""
        for status in self.rows.values():
            self.assertIn(status, {"referral", "alternative-solution",
                                   "ruled", "tool-gap"})


class TestTheREADMEMatchesTheRegister(unittest.TestCase):
    """The README's claim about how many entries change a run must be the
    register's own answer.

    The first version said "If your building hits one, the run says so", which
    AHJ-5 contradicts — nothing fires for its shape. Correcting that to "for
    most of them" replaced one false claim with a different one: TWO of
    seventeen set a run conditional. A prose hedge cannot be checked, so the
    README names the ids and this test holds them to the table.
    """

    def setUp(self):
        self.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        text = REGISTER.read_text(encoding="utf-8")
        self.conditional = {
            ident for ident, sets in re.findall(
                r"^\| (AHJ-\d+) \|(?:[^|]*\|){3}([^|]*)\|", text, re.M)
            if sets.strip().lower().startswith("yes")}

    def test_the_register_still_marks_some_entry_as_conditional(self):
        """Guards the parse: an empty set would make the next test vacuous."""
        self.assertTrue(
            self.conditional,
            "no row sets a run conditional — either the table changed shape "
            "or the conditional determination was withdrawn")

    def test_the_README_names_exactly_those_ids(self):
        named = {m for m in re.findall(r"AHJ-\d+", self._claim_sentence())}
        self.assertEqual(
            self.conditional, named,
            "the README says {} change a run; the register says {}".format(
                sorted(named), sorted(self.conditional)))

    def test_the_README_does_not_hedge_with_a_quantity_word(self):
        sentence = self._claim_sentence().lower()
        for hedge in ("most of them", "all of them", "each of them"):
            self.assertNotIn(
                hedge, sentence,
                "a quantity word cannot be checked against the register; "
                "name the ids instead")

    def _claim_sentence(self):
        match = re.search(r"\*\*([^*]*change what a run reports[^*]*)\*\*",
                          self.readme)
        self.assertIsNotNone(
            match, "the README no longer states which entries change a run")
        return match.group(1)


class TestTheREADMEQuotesRealOutput(unittest.TestCase):
    """Every line the README shows as CLI output must be a line the CLI emits.

    The README quoted a verdict block saying the authority must accept "the
    interpretation". That word was removed from the CLI two commits earlier,
    because AHJ-1 is an alternative solution and the clause DOES decide the
    requirement. Nothing noticed: the README is prose to every test that
    existed, so a hand-maintained copy of program output drifted silently.
    This is the same failure as the withdrawn claim surviving on the HTML
    surface, one document further out.
    """

    def setUp(self):
        from btap.codes import cli

        from .support import CARDINALITY_CONDITION, MULTI_ENERGY_CONDITION, real_conditional_report

        # The SAME builder and the SAME conditions the README block was
        # rendered from, so the two cannot drift apart by construction. The
        # earlier version hand-built its own report, so this test could fail
        # while the README matched the CLI perfectly — or pass while it did
        # not.
        report = real_conditional_report(
            [MULTI_ENERGY_CONDITION, CARDINALITY_CONDITION])

        class Result:
            compliant = True
            report = {"annual": True}

        self.rendered = cli.verdict_block(Result(), report)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        marker = "*** NOT A CODE-COMPLIANT DETERMINATION ***"
        start = readme.index(marker)
        self.quoted = readme[start:readme.index("```", start)]

    def test_the_quoted_block_is_not_empty(self):
        """Guards the parse, so the next test cannot pass vacuously."""
        lines = [ln for ln in self.quoted.splitlines() if ln.strip()]
        self.assertGreater(len(lines), 8, self.quoted)

    def test_every_quoted_line_is_a_line_the_CLI_emits(self):
        emitted = {ln.strip() for ln in self.rendered.splitlines()}
        for line in self.quoted.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            with self.subTest(stripped[:60]):
                self.assertIn(
                    stripped, emitted,
                    "the README shows a line the CLI does not emit; "
                    "re-render the block rather than editing it")


class TestTheREADMECountsMatchTheRegistry(unittest.TestCase):
    """The README states how many decisions exist and how many are runtime.
    Both were stale the moment D-99 landed — 98/49 against a generated 99/50
    (Sol, `125`.5).

    A number in prose is a claim, and the only way to keep one true is to
    check it against the thing it counts.
    """

    def setUp(self):
        import json

        self.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        raw = json.loads(
            (REPO_ROOT / "python" / "btap" / "codes" / "data"
             / "decisions.json").read_text(encoding="utf-8"))
        self.rows = (raw if isinstance(raw, list)
                     else raw.get("decisions") or list(raw.values()))

    def test_the_registry_parsed(self):
        """Guards the parse so the comparisons cannot pass vacuously."""
        self.assertGreater(len(self.rows), 50)

    def test_the_total_matches(self):
        total = len(self.rows)
        self.assertIn(
            "**{} decisions**".format(total), self.readme,
            "the README's decision total disagrees with the generated "
            "registry, which has {}".format(total))
        self.assertIn("not all {}.".format(total), self.readme)

    def test_the_runtime_count_matches(self):
        runtime = sum(1 for r in self.rows if r.get("kind") == "runtime")
        self.assertIn(
            "{} of them".format(runtime), self.readme,
            "the README's runtime count disagrees with the generated "
            "registry, which has {}".format(runtime))


class TestNonReferralEntriesAreNotCalledAmbiguities(unittest.TestCase):
    """Only a `referral` entry describes an ambiguity.

    AHJ-1 is an alternative solution — the text DECIDES the requirement and
    this tool does not meet it — and AHJ-6, AHJ-8 and AHJ-17 are tool gaps.
    All four introduced their text as "**The ambiguity.**", recreating the
    classification error the surrounding documents were corrected to avoid
    (Sol, `125`.5).
    """

    def setUp(self):
        text = REGISTER.read_text(encoding="utf-8")
        parts = re.split(r"^## (AHJ-\d+)", text, flags=re.M)
        self.bodies = {parts[i]: parts[i + 1]
                       for i in range(1, len(parts), 2)}

    def test_entries_were_found(self):
        self.assertGreater(len(self.bodies), 10)

    def test_only_a_referral_may_call_its_subject_an_ambiguity(self):
        for ident, body in sorted(self.bodies.items()):
            found = re.search(r"\*\*Status[:*\s]*`?([a-z-]+)`?", body)
            status = found.group(1) if found else "referral"
            if status == "referral":
                continue
            with self.subTest(ident, status=status):
                self.assertNotIn(
                    "**The ambiguity.**", body,
                    "{} is {!r}, so its subject is not an ambiguity".format(
                        ident, status))


if __name__ == "__main__":
    unittest.main(verbosity=2)
