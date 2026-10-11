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
