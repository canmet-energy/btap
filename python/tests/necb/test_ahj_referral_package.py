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


def _published_field(section, label, all_labels):
    """One field's text out of the PUBLISHED section.

    Ends at the next published label or at the section's `---` rule,
    whichever comes first.
    """
    opener = f"**{label}.** "
    tail = section[section.index(opener) + len(opener):]
    stops = [tail.index(f"**{other}.** ") for other in all_labels
             if other != label and f"**{other}.** " in tail]
    if "\n---" in tail:
        stops.append(tail.index("\n---"))
    return tail[:min(stops)] if stops else tail


def _read_field(body, heads, boundaries):
    """A field's whole text, LINE BY LINE — a second implementation.

    Deliberately not the generator's regex, but it takes the same RECOGNISED
    HEADINGS, because that is the register's grammar and two copies of a
    grammar is worse than one. The first version of this reader invented its
    own typographic rule — "stop at a bold run that opens and closes on one
    line" — identical to the generator's, so both cut AHJ-7's requirement at
    its `**Why an authority must weigh in.**` sub-paragraph and both ran
    AHJ-16's interim behaviour through 50 lines of review-loop history
    (Fable, `217`). Sharing a WRONG rule is what made the comparison useless;
    sharing the authored grammar is the point of having one.

    What makes this test able to fail is therefore not this reader. It is
    `test_fields_are_IDENTICAL_to_the_register` comparing for equality rather
    than containment — so over-reading fails too — and the two content
    assertions below, which name text that must and must not appear and are
    independent of any parsing rule at all.
    """
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if not any(line.startswith(f"**{head}") for head in heads):
            continue
        collected = [line.split("**", 2)[-1].lstrip()]
        for later in lines[index + 1:]:
            if any(later.startswith(f"**{name}{tail}")
                   for name in boundaries
                   for tail in (".", ":", ",", "**")):
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

    def test_the_ALTERNATIVE_SOLUTIONS_are_named_explicitly(self):
        """AHJ-1, AHJ-7 and AHJ-22 by id, not by count.

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
            ["AHJ-1", "AHJ-7", "AHJ-22"], alternatives,
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

    def test_no_field_SWALLOWS_another(self):
        """PLACEMENT, and independent of the grammar on either side.

        Every content assertion in this file asks whether some text is
        SOMEWHERE in a section, and all of them passed while seven of the ten
        Article bullets had swallowed the status line and everything after
        it — AHJ-7's went from 59 characters to 2050, with the coefficient
        table flattened onto one line (Fable, `223`). The text was all
        present; it was in the wrong field.

        `test_fields_are_IDENTICAL_to_the_register` does catch that, but only
        while the generator's grammar and this file's reader disagree. Edit
        both and it goes quiet again, which is the shared-grammar problem
        that has now bitten twice. These assertions use neither: a bullet is
        one short line, and no field may contain a DIFFERENT field's heading.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        labels = ("The question", "Established by",
                  "What the tool does meanwhile")
        # Spelled out here rather than imported, so a change to the
        # generator's tuple cannot move this expectation with it.
        headings = ("Article", "Status", "The ambiguity", "The question",
                    "The requirement", "The gap", "What is missing",
                    "Why it matters", "Established by",
                    "What the tool does meanwhile", "What the tool does now",
                    "Where a reader meets it")
        for ident in wanted:
            start = text.index(f"### {ident} — ")
            nxt = text.find("\n### ", start + 4)
            section = text[start:nxt if nxt != -1 else len(text)]

            for bullet in ("Editions", "Article", "Makes a run conditional"):
                with self.subTest(entry=ident, bullet=bullet):
                    line = [ln for ln in section.split("\n")
                            if ln.startswith(f"- **{bullet}:**")][0]
                    self.assertLess(
                        len(line), 300,
                        f"{ident}: the {bullet} bullet is {len(line)} "
                        "characters. A bullet carries one short value, so "
                        "this one has absorbed what follows it")
                    value = line[len(f"- **{bullet}:**"):]
                    for name in headings:
                        self.assertNotIn(
                            f"**{name}", value,
                            f"{ident}: the {bullet} bullet's VALUE contains "
                            f"the heading '{name}', so it ran past its end")

            for label in labels:
                with self.subTest(entry=ident, field=label):
                    body = _published_field(section, label, list(labels))
                    for name in headings:
                        if label.startswith(name) or name.startswith(label):
                            continue
                        for tail in (".", ":", ","):
                            self.assertNotIn(
                                f"\n**{name}{tail}", body,
                                f"{ident}: the {label} field swallowed the "
                                f"'{name}' heading")

    def test_fields_are_IDENTICAL_to_the_register(self):
        """Equality, not containment — so OVER-reading fails too.

        Containment could only ever catch a field that lost text. An
        over-reading generator passes it trivially, and that is the state the
        package shipped in: AHJ-16's interim behaviour ran on through 50 lines
        of review-loop history, 68 lines against 16-29 for the other
        referrals, and nothing failed (Fable, `217`).
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        generator = _generator()
        register = REGISTER.read_text(encoding="utf-8")
        text = OUTPUT.read_text(encoding="utf-8")
        wanted = [r["id"] for r in entries()
                  if r.get("status") in ("referral", "alternative-solution")]
        labels = (("The question", generator.FIELDS["question"]),
                  ("Established by", generator.FIELDS["established"]),
                  ("What the tool does meanwhile", generator.FIELDS["meanwhile"]))
        for ident in wanted:
            body = _register_body(register, ident)
            start_ = text.index(f"### {ident} — ")
            nxt_ = text.find("\n### ", start_ + 4)
            section = text[start_:nxt_ if nxt_ != -1 else len(text)]
            for label, heads in labels:
                with self.subTest(entry=ident, field=label):
                    want = _read_field(body, heads,
                                       generator.FIELD_HEADINGS)
                    got = _published_field(section, label,
                                           [o for o, _ in labels])
                    self.assertEqual(
                        " ".join(want.split()), " ".join(got.split()),
                        f"{ident}.{label}: the package and the register must "
                        "carry the SAME text — equality, because containment "
                        "cannot see the package carrying MORE")

    def test_AHJ_7_publishes_the_paragraph_that_states_the_CHOICE(self):
        """A content fact, independent of any parsing rule.

        AHJ-7's requirement ends with `**Why an authority must weigh in.**`:
        complying literally with the printed coefficient is absurd, the
        corrected one departs from the published text, and "a project relying
        on either needs its authority to accept which reading applies". That
        sentence IS the referral. The typographic field-end rule dropped it
        because the heading happens to fit on one line (Fable, `217`; Sol's
        `216` named it).
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        start_ = text.index("### AHJ-7 — ")
        nxt_ = text.find("\n### ", start_ + 4)
        section = text[start_:nxt_ if nxt_ != -1 else len(text)]
        self.assertIn(
            "Why an authority must weigh in", section,
            "AHJ-7 is an alternative solution and this is the paragraph "
            "saying what an authority is being asked to accept")
        self.assertIn(
            "needs its authority to accept which reading applies", section,
            "and the sentence that states the choice must survive")
        self.assertIn(
            "|", section,
            "as must the table of the three wrong published rows")
        # And the Phase E runtime disposition, which the grammar cannot
        # protect: a declared grammar removes guessing but does not make the
        # content checkable, so pin the substantive closure.
        self.assertIn(
            "Runtime disclosure closed in Phase E", section,
            "AHJ-7 must say that affected curves now reach the report")
        self.assertIn(
            "conditional on acceptance of the corrected coefficient", section,
            "including the consequence of the alternative solution")

    def test_AHJ_16_does_NOT_publish_the_review_loop_history(self):
        """The other direction, also by content.

        AHJ-16's register entry carries a Guard-7 history of how its frozen
        artifact was obtained — a real record, and not what an authority is
        being asked. It reached the package because the field-end rule missed
        a heading that WRAPPED.
        """
        if not OUTPUT.is_file():
            self.skipTest(f"{OUTPUT} is not present in this layout")
        text = OUTPUT.read_text(encoding="utf-8")
        start_ = text.index("### AHJ-16 — ")
        nxt_ = text.find("\n### ", start_ + 4)
        section = text[start_:nxt_ if nxt_ != -1 else len(text)]
        for leaked in ("Guard 7 is MET", "refused as a baseline",
                       "before D-101"):
            with self.subTest(phrase=leaked):
                self.assertNotIn(
                    leaked, section,
                    f"{leaked!r} is this project's review history, not a "
                    "question for an authority")

    def test_the_READER_itself_sees_more_than_one_paragraph(self):
        """The control: if this file's reader stopped early too, the equality
        above would hold against a truncated package."""
        register = REGISTER.read_text(encoding="utf-8")
        generator = _generator()
        text = _read_field(_register_body(register, "AHJ-7"),
                           ("The requirement", "The question"),
                           generator.FIELD_HEADINGS)
        self.assertGreater(
            len(text), 1400,
            "AHJ-7's requirement spans its table AND its closing paragraph; "
            f"a reader returning {len(text)} characters has stopped early")
        self.assertIn("Why an authority must weigh in", text)
        self.assertIn("|", text)
