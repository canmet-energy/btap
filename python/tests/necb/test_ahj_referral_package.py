"""The referral package must be current, and must carry only what needs an authority.

`docs/NECB_AHJ_REFERRALS.md` is generated from the authored register so that
the questions blocked on someone outside the project can be handed over once
rather than rediscovered one at a time. It is a SECOND view of register
content, which is exactly the shape that drifted eight times in D-102 — so it
is generated, and these tests pin the two properties that make generation
worth it: it is current, and it includes neither `ruled` nor `tool-gap`.
"""
import json
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "python" / "scripts" / "generate_ahj_referrals.py"
OUTPUT = ROOT / "docs" / "NECB_AHJ_REFERRALS.md"
REGISTER = ROOT / "docs" / "NECB_AHJ_QUESTIONS.md"
PROJECTION = ROOT / "python" / "btap" / "codes" / "data" / "ahj.json"


def entries():
    data = json.loads(PROJECTION.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else (data.get("entries") or [])
    return list(rows.values()) if isinstance(rows, dict) else rows


def _generator():
    """The generator module, imported from `python/scripts/`.

    The package's correctness is a relationship between the authored register
    and the published document, and the generator owns the one parser that
    defines it. Re-implementing `_field` here would test a copy.
    """
    import importlib.util

    path_ = (pathlib.Path(__file__).resolve().parents[2]
             / "scripts" / "generate_ahj_referrals.py")
    spec = importlib.util.spec_from_file_location("_ahj_referrals", path_)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _register_body(register, ident):
    """One entry's body out of the authored register."""
    start = register.index(f"## {ident} — ")
    nxt = register.find("\n## ", start + 4)
    return register[start:nxt if nxt != -1 else len(register)]


def _read_field(body, heads):
    """A field's whole text, LINE BY LINE — a second implementation.

    Deliberately not the generator's regex: a field runs from the line
    opening `**Label...**` to the next line that opens a bold label or a
    sub-heading. Written differently on purpose, so a change to the
    generator's reader cannot carry this test's expectation along with it.
    """
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if not any(line.startswith(f"**{head}") for head in heads):
            continue
        collected = [line.split("**", 2)[-1].lstrip()]
        for later in lines[index + 1:]:
            if later.startswith("**") and later.find("**", 2) != -1:
                break
            if later.startswith("#"):
                break
            collected.append(later)
        return "\n".join(collected).strip()
    return ""


class TestTheReferralPackage(unittest.TestCase):

    def test_the_committed_document_is_current(self):
        if not SCRIPT.is_file():
            self.skipTest(f"{SCRIPT} is not present in this layout")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            capture_output=True, text=True)
        self.assertEqual(
            0, result.returncode,
            "the referral package is stale — run "
            f"generate_ahj_referrals.py\n{result.stderr}")

    def test_it_carries_every_entry_needing_an_authority_and_no_others(self):
        """`ruled` needs nobody and `tool-gap` is ours to close.

        Including either would launder a defect as a question for someone
        else, which is the distinction the register's four statuses exist to
        draw. Excluding a `referral` would hide a question that blocks a
        determination.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        for row in entries():
            ident, status = row["id"], row.get("status")
            heading = f"### {ident} — "
            with self.subTest(entry=ident, status=status):
                if status in ("referral", "alternative-solution"):
                    self.assertIn(
                        heading, text,
                        f"{ident} is `{status}` and needs an authority, so the "
                        "package must carry it")
                else:
                    self.assertNotIn(
                        heading, text,
                        f"{ident} is `{status}` — it needs no authority, and "
                        "listing it here would present our own defect as "
                        "someone else's question")

    def test_every_entry_carries_each_field_exactly_ONCE(self):
        """The structure: one labelled block per field, per entry.

        Content is checked by comparing it with the register
        (`test_no_field_is_TRUNCATED_against_the_register`), which subsumes
        the length floors this used to carry. Those floors were the wrong
        instrument twice over: one value of 40 characters failed AHJ-12, whose
        attribution "Sol `122`." is complete and correct, and no floor could
        see AHJ-7 publishing a plausible 246-character sentence in place of
        1150 characters with a table in them.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        self.assertEqual(
            len(wanted), len(re.findall(r"(?m)^### AHJ-\d+ — ", text)),
            "one section per entry needing an authority")
        for ident in wanted:
            start = text.index(f"### {ident} — ")
            nxt = text.find("\n### ", start + 4)
            section = text[start:nxt if nxt != -1 else len(text)]
            for label in ("Editions", "Article", "Makes a run conditional"):
                with self.subTest(entry=ident, bullet=label):
                    lines = [ln for ln in section.split("\n")
                             if ln.startswith(f"- **{label}:**")]
                    self.assertEqual(1, len(lines),
                                     f"{ident}: one {label} bullet")
                    value = lines[0].split("**", 2)[-1].lstrip(": ").strip()
                    self.assertTrue(value, f"{ident}: {label} is EMPTY")
                    self.assertNotIn("absent", value.lower(),
                                     f"{ident}: {label} is a placeholder")
            for label in ("The question", "Established by",
                          "What the tool does meanwhile"):
                with self.subTest(entry=ident, field=label):
                    self.assertEqual(
                        1, section.count(f"**{label}.** "),
                        f"{ident}: exactly one {label} block")

    def test_the_two_ALTERNATIVE_SOLUTIONS_are_named_explicitly(self):
        """AHJ-1 and AHJ-7 by id, not by count.

        Both shipped with no requirement text at all and the counts still
        matched, because eight referrals satisfied every aggregate assertion.
        The two entries where the Code DOES decide and this tool does not meet
        it are the ones an authority most needs (Sol, `213`).
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        by_status = {r["id"]: r.get("status") for r in entries()}
        alternatives = sorted(
            (i for i, s in by_status.items() if s == "alternative-solution"),
            key=lambda v: int(v.split("-")[1]))
        self.assertEqual(
            ["AHJ-1", "AHJ-7"], alternatives,
            "the register's alternative solutions have changed — this test "
            "names them deliberately, so update it with the register")
        for ident in alternatives:
            with self.subTest(entry=ident):
                start = text.index(f"### {ident} — ")
                nxt = text.find("\n### ", start + 4)
                section = text[start:nxt if nxt != -1 else len(text)]
                self.assertEqual(
                    1, section.count("**The question.** "),
                    f"{ident} is an alternative solution: the requirement it "
                    "does not meet IS what an authority is being asked to "
                    "accept, and it must be in the package")

    def test_no_field_is_TRUNCATED_against_the_register(self):
        """Every field, whole — read INDEPENDENTLY of the generator.

        `_field` stopped at the first blank line, so AHJ-7's requirement
        published 246 of its 1150 characters and ended on the colon
        introducing the coefficient table it dropped: the authority was asked
        to accept a non-conforming substitution and shown neither the three
        wrong published rows nor the paragraph headed "Why an authority must
        weigh in". AHJ-1 lost 842 characters and AHJ-10 357 (Sol, `216`;
        Fable, `214`).

        The first version of this test called the generator's own `_field` to
        say what the package SHOULD contain, so restoring the blank-line stop
        truncated both sides equally and all five tests stayed green. A check
        that defines its expectation with the code under test cannot fail.

        So the field is read here by a second, deliberately different
        implementation — line-based rather than regex-based, same rule. Two
        implementations of one simple rule is the point; if they disagree, one
        of them is wrong.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        register = REGISTER.read_text(encoding="utf-8")
        published = " ".join(OUTPUT.read_text(encoding="utf-8").split())
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        labels = {"article": ("Article",),
                  "question": ("The ambiguity", "The question",
                               "The requirement"),
                  "established": ("Established by",),
                  "meanwhile": ("What the tool does meanwhile",
                                "What the tool does now")}
        for ident in wanted:
            body = _register_body(register, ident)
            for key, heads in labels.items():
                with self.subTest(entry=ident, field=key):
                    text = _read_field(body, heads)
                    self.assertTrue(
                        text, f"{ident}: the register states no {key}")
                    normalised = " ".join(text.split())
                    self.assertIn(
                        normalised, published,
                        f"{ident}.{key}: {len(normalised)} characters in the "
                        "register are not all in the package. A field "
                        "truncated in the middle still reads as prose, which "
                        "is why this compares the TEXT and not its length")

    def test_the_READER_itself_sees_more_than_one_paragraph(self):
        """The control for the test above.

        If this file's own reader stopped at a blank line too, the comparison
        would pass against a truncated package and prove nothing. AHJ-7's
        requirement is the case: four material parts under one heading,
        including the table of wrong coefficients.
        """
        register = REGISTER.read_text(encoding="utf-8")
        text = _read_field(_register_body(register, "AHJ-7"),
                           ("The requirement", "The question"))
        self.assertGreater(
            len(text), 900,
            "AHJ-7's requirement is a multi-paragraph field with a table; a "
            f"reader returning {len(text)} characters has stopped early, and "
            "this file's other assertions are then vacuous")
        self.assertIn(
            "|", text,
            "the coefficient table is part of the requirement — it names the "
            "three wrong published rows an authority is asked about")
