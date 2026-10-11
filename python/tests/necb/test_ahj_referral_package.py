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
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "python" / "scripts" / "generate_ahj_referrals.py"
OUTPUT = ROOT / "docs" / "NECB_AHJ_REFERRALS.md"
PROJECTION = ROOT / "python" / "btap" / "codes" / "data" / "ahj.json"


def entries():
    data = json.loads(PROJECTION.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else (data.get("entries") or [])
    return list(rows.values()) if isinstance(rows, dict) else rows


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

    def test_every_listed_entry_states_the_QUESTION_itself(self):
        """The thing the authority is being asked, present for every entry.

        Both `alternative-solution` entries shipped without it and nothing
        noticed: AHJ-1 and AHJ-7 head their requirement "The requirement, and
        why we do not meet it.", the extractor matched "The requirement."
        exactly, and a truthiness check dropped the field — so the two entries
        where the Code DOES decide and this tool does not meet it went to a
        reader whose whole job is to judge that, with no statement of the
        requirement (Fable, `212`).

        Emptying the extractor's heading tuple altogether left all three of
        the other tests green, which is why this one counts BLOCKS rather than
        trusting the renderer.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        self.assertEqual(
            len(wanted), text.count("**The question.** "),
            f"{len(wanted)} entries need an authority, so the package must "
            f"carry {len(wanted)} question blocks and carries "
            f"{text.count('**The question.** ')}")
        for ident in wanted:
            with self.subTest(entry=ident):
                start = text.index(f"### {ident} — ")
                nxt = text.find("### ", start + 4)
                section = text[start:nxt if nxt != -1 else len(text)]
                m = [ln for ln in section.split("\n")
                     if ln.startswith("**The question.** ")]
                self.assertEqual(
                    1, len(m),
                    f"{ident}: exactly one question block")
                self.assertGreater(
                    len(m[0]), 80,
                    f"{ident}: the question is a sentence, not a stub — "
                    f"got {len(m[0])} characters")

    def test_every_section_carries_all_five_fields_NON_EMPTY(self):
        """Parsed out of the rendered document, field by field.

        The earlier tests checked that a LABEL occurred somewhere in a
        section, which an empty value satisfies: Sol (`213`) blanked AHJ-2's
        conditional cell, regenerated, and all three tests passed on the empty
        value. A placeholder is not an authority package, so each field is
        read and required to carry content.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        bullets = ("Editions", "Article", "Makes a run conditional")
        # The minimum length is per FIELD, because the fields do different
        # jobs. A question and an interim behaviour have to EXPLAIN something,
        # so a 20-character value is a stub. An attribution does not: AHJ-12's
        # is "Sol `122`." and that is the complete, correct answer. Holding
        # every field to one threshold would have meant either accepting
        # stubs everywhere or excluding AHJ-12 from the check, and an
        # exclusion in a test filter is a confession.
        paragraphs = (("The question", 40), ("Established by", 8),
                      ("What the tool does meanwhile", 40))
        for ident in wanted:
            start = text.index(f"### {ident} — ")
            nxt = text.find("### ", start + 4)
            section = text[start:nxt if nxt != -1 else len(text)]
            for label in bullets:
                with self.subTest(entry=ident, field=label):
                    line = [ln for ln in section.split("\n")
                            if ln.startswith(f"- **{label}:**")]
                    self.assertEqual(1, len(line), f"{ident}: one {label}")
                    value = line[0].split("**", 2)[-1].lstrip(": ").strip()
                    self.assertTrue(
                        value, f"{ident}: {label} is EMPTY — a blank cell "
                        "tells an authority nothing and reads as if it had "
                        "been considered")
                    self.assertNotIn(
                        "absent", value.lower(),
                        f"{ident}: {label} rendered a placeholder")
            for label, floor in paragraphs:
                with self.subTest(entry=ident, field=label):
                    line = [ln for ln in section.split("\n")
                            if ln.startswith(f"**{label}.** ")]
                    self.assertEqual(1, len(line), f"{ident}: one {label}")
                    value = line[0][len(label) + 7:].strip()
                    self.assertGreater(
                        len(value), floor,
                        f"{ident}: {label} is a stub ({len(value)} chars, "
                        f"floor {floor}): {value!r}")

    def test_the_two_ALTERNATIVE_SOLUTIONS_are_named_explicitly(self):
        """AHJ-1 and AHJ-7 by id, not by count.

        Both shipped with no requirement text at all and the counts still
        matched, because eight referrals satisfied every aggregate assertion.
        The two entries where the Code DOES decide and this tool does not meet
        it are the ones an authority most needs, so they are pinned by name
        (Sol, `213`).
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
                nxt = text.find("### ", start + 4)
                section = text[start:nxt if nxt != -1 else len(text)]
                question = [ln for ln in section.split("\n")
                            if ln.startswith("**The question.** ")]
                self.assertEqual(
                    1, len(question),
                    f"{ident} is an alternative solution: the requirement it "
                    "does not meet IS the thing an authority is being asked "
                    "to accept, and it must be in the package")
                self.assertGreater(len(question[0]), 120,
                                   f"{ident}: not a stub")

    def test_every_listed_entry_states_what_the_tool_does_meanwhile(self):
        """A question with no stated interim behaviour tells a reader what is
        being asked and not what hangs on the answer."""
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        for ident in wanted:
            with self.subTest(entry=ident):
                start = text.index(f"### {ident} — ")
                nxt = text.find("### ", start + 4)
                section = text[start:nxt if nxt != -1 else len(text)]
                self.assertIn(
                    "What the tool does meanwhile.", section,
                    f"{ident}: the package must say what happens until the "
                    "question is answered")
                self.assertIn(
                    "Makes a run conditional:", section,
                    f"{ident}: and whether it makes a run conditional, which "
                    "is the register's own status-table column")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
