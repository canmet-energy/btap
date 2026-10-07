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
                "what the tool does meanwhile" in lowered
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
        interpretation that blocks a verdict."""
        rows = self._rows()
        product = (PRODUCT / "codes" / "necb" / "path.py").read_text(
            encoding="utf-8")
        cited = set(ID_RE.findall(product))
        for ident in cited:
            self.assertIn(
                rows.get(ident), {"referral", "alternative-solution"},
                f"{ident} is cited by the conditional determination but its "
                f"status is {rows.get(ident)!r}; only a referral or an "
                f"alternative solution may set a run conditional")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
