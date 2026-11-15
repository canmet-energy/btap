"""The src-layout move checker must REFUSE everything but a path rename (#229).

It is the review of a diff too large to read, so the tests that matter are the
ones where it must say no. Each builds a real two-commit git repository: a
"before" tree in the old layout, then an "after" that is a pure move plus ONE
defect, and asserts the checker names that defect. The pure move is the
control, so a checker that refused everything would fail it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_path_rename as cpr  # noqa: E402


class TheTextMapping(unittest.TestCase):
    def test_the_three_directories_and_the_readme_move(self):
        self.assertEqual(
            '"src/btap/codes/compliance.py#_evaluate" tests/x.py scripts/y.py src/README.md',
            cpr.map_text('"python/btap/codes/compliance.py#_evaluate" python/tests/x.py '
                         'python/scripts/y.py python/README.md'))

    def test_the_embedded_windows_interpreter_is_NOT_this_directory(self):
        # packaging/windows stages an embedded Python under `python/`; its
        # paths must survive the move untouched or the installer breaks.
        for embedded in ("python/python.exe", "python/Lib/site-packages/btap",
                         "python/python312._pth"):
            self.assertEqual(embedded, cpr.map_text(embedded))

    def test_a_longer_name_is_not_a_match(self):
        for other in ("cpython/btap/x", "my-python/tests/y", "python/btapx",
                      "python/tests_old", ".python/scripts/z"):
            self.assertEqual(other, cpr.map_text(other))

    def test_a_path_at_the_end_of_a_sentence_still_moves(self):
        self.assertEqual("see tests.", cpr.map_text("see python/tests."))

    def test_path_mapping(self):
        self.assertEqual("src/btap/a.py", cpr.map_path("python/btap/a.py"))
        self.assertEqual("tests/t.py", cpr.map_path("python/tests/t.py"))
        self.assertEqual("docs/x.md", cpr.map_path("docs/x.md"))


class TheDiffCheck(unittest.TestCase):
    BEFORE = {
        "python/btap/core.py": "def f():\n    return 1\n",
        "python/tests/test_core.py": "# covers python/btap/core.py\n",
        "python/LICENSE": "GPL\n",
        "LICENSE": "GPL\n",
        "frozen/baseline.json": '{"code": ["python/btap/core.py#f"], "eui": 101.5}\n',
        "pyproject.toml": 'where = ["python"]\n',
        "models/blob.bin": None,  # binary, written below
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._cwd = os.getcwd()
        os.chdir(self.repo)
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@example.invalid")
        self._git("config", "user.name", "t")
        for path, text in self.BEFORE.items():
            self._write(path, text)
        self._commit("before")

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _git(self, *args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    def _write(self, path, text):
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            p.write_bytes(bytes(range(256)) * 4)
        else:
            p.write_text(text, encoding="utf-8")

    def _commit(self, msg):
        self._git("add", "-A")
        self._git("commit", "-q", "-m", msg)

    def _pure_move(self):
        (self.repo / "src").mkdir(exist_ok=True)
        self._git("mv", "python/btap", "src/btap")
        self._git("mv", "python/tests", "tests")
        self._git("rm", "-q", "python/LICENSE")
        for path in ("tests/test_core.py", "frozen/baseline.json"):
            p = self.repo / path
            p.write_text(cpr.map_text(p.read_text(encoding="utf-8")), encoding="utf-8")
        self._write("pyproject.toml", 'where = ["src"]\n')

    def _check(self, hand=("pyproject.toml",)):
        self._commit("after")
        return cpr.check("HEAD~1", "HEAD", set(hand))

    def test_CONTROL_a_pure_move_passes(self):
        self._pure_move()
        problems, counts = self._check()
        self.assertEqual([], problems)
        self.assertEqual(2, counts["renamed"])
        self.assertEqual(1, counts["hand-edited"])

    def _with_a_keep_file(self):
        self._write("python/tests/test_check_path_rename.py", "# feeds python/btap/x in\n")
        self._commit("add a keep file")
        self._pure_move()

    def test_a_KEEP_file_moved_byte_for_byte_passes(self):
        self._with_a_keep_file()
        problems, _ = self._check()
        self.assertEqual([], problems)

    def test_a_KEEP_file_may_not_be_rewritten(self):
        self._with_a_keep_file()
        self._write("tests/test_check_path_rename.py", "# feeds src/btap/x in\n")
        problems, _ = self._check()
        self.assertEqual(["python/tests/test_check_path_rename.py -> "
                          "tests/test_check_path_rename.py: in KEEP_OLD_PATHS, so it "
                          "must move byte-for-byte"], problems)

    def test_a_behaviour_change_smuggled_into_a_moved_file_is_refused(self):
        self._pure_move()
        self._write("src/btap/core.py", "def f():\n    return 2\n")
        problems, _ = self._check()
        self.assertEqual(["python/btap/core.py -> src/btap/core.py: "
                          "content is not a path-only change"], problems)

    def test_a_refrozen_baseline_that_moved_a_NUMBER_is_refused(self):
        self._pure_move()
        p = self.repo / "frozen/baseline.json"
        p.write_text(p.read_text().replace("101.5", "101.6"), encoding="utf-8")
        problems, _ = self._check()
        self.assertEqual(["frozen/baseline.json: content is not a path-only change"],
                         problems)

    def test_a_pointer_left_on_the_OLD_path_is_refused(self):
        self._pure_move()
        self._write("frozen/baseline.json", self.BEFORE["frozen/baseline.json"])
        problems, _ = self._check()
        # Unchanged since BEFORE, so it is not even in the diff: only the
        # leftover scan can see it.
        self.assertEqual(["frozen/baseline.json: still names the old layout 1 time(s)"],
                         problems)

    def test_a_move_to_the_wrong_place_is_refused(self):
        self._pure_move()
        self._git("mv", "tests", "python_tests")
        problems, _ = self._check()
        # Git may report it as a mis-targeted rename or as a delete plus an
        # add, depending on similarity; either way the wrong path is named.
        self.assertTrue(problems)
        self.assertTrue(all("python_tests/" in p or "python/tests/" in p for p in problems),
                        problems)
        self.assertTrue(any("python_tests/test_core.py" in p for p in problems), problems)

    def test_an_unlisted_deletion_is_refused(self):
        self._pure_move()
        self._git("rm", "-q", "LICENSE")
        problems, _ = self._check()
        self.assertIn("LICENSE: deleted, and not in DELETED", problems)

    def test_an_unlisted_addition_is_refused(self):
        self._pure_move()
        self._write("src/btap/new.py", "x = 1\n")
        problems, _ = self._check()
        self.assertIn("src/btap/new.py: added, and not in ADDED or --hand-edited", problems)

    def test_an_unlisted_hand_edit_is_refused(self):
        self._pure_move()
        problems, _ = self._check(hand=())
        self.assertIn("pyproject.toml: content is not a path-only change", problems)

    def test_a_stale_hand_edited_entry_is_refused(self):
        # The list IS the review, so it must not name files the diff never touched.
        self._pure_move()
        problems, _ = self._check(hand=("pyproject.toml", "README.md"))
        self.assertIn("README.md: listed as hand-edited but the diff does not touch it",
                      problems)

    def test_one_flipped_byte_in_a_binary_is_refused(self):
        self._pure_move()
        data = bytearray((self.repo / "models/blob.bin").read_bytes())
        data[10] ^= 1
        (self.repo / "models/blob.bin").write_bytes(bytes(data))
        problems, _ = self._check()
        self.assertEqual(["models/blob.bin: content is not a path-only change"], problems)


if __name__ == "__main__":
    unittest.main()
