"""Negative tests for the D-80 recursive inventory validator
(verification/oracle/inventory.py) — the layer whose FALSE-GREEN paths
matter most, so each hazard Sol's post-merge review identified gets a test
that proves the validator refuses it. The Ruby twin
(btap-necb/test/test_oracle_inventory.rb) covers inventory.rb."""

import sys
import unittest

from tests.support import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "verification" / "oracle"))
from inventory import build_skeleton, validate  # noqa: E402

RULES = {(): ("keyed", ["id"])}
GOLDEN = [{"id": "a", "v": 1.0}, {"id": "b", "v": 2.0}]


class TestKeyedListValidation(unittest.TestCase):
    def setUp(self):
        self.skeleton = build_skeleton(GOLDEN, RULES)

    def test_clean_data_validates(self):
        self.assertEqual([], validate(GOLDEN, self.skeleton))

    def test_duplicate_keys_are_refused_not_collapsed(self):
        # The post-merge High: dict construction silently overwrote one
        # duplicate with the other and returned ZERO errors.
        malformed = [{"id": "a", "v": 1.0}, {"id": "a", "v": 99.0},
                     {"id": "b", "v": 2.0}]
        errors = validate(malformed, self.skeleton)
        self.assertTrue(any("duplicate item 'a'" in e for e in errors),
                        f"duplicate key collapsed silently: {errors}")

    def test_missing_and_extra_items_are_named(self):
        errors = validate([{"id": "a", "v": 1.0}], self.skeleton)
        self.assertTrue(any("missing item 'b'" in e for e in errors))
        errors = validate(GOLDEN + [{"id": "c", "v": 3.0}], self.skeleton)
        self.assertTrue(any("unexpected item 'c'" in e for e in errors))

    def test_build_refuses_duplicate_keys_in_the_golden_itself(self):
        with self.assertRaises(ValueError):
            build_skeleton([{"id": "a"}, {"id": "a"}], RULES)


class TestNestedShrinkage(unittest.TestCase):
    def test_nested_key_loss_is_named_by_path(self):
        golden = {"outer": {"inner": [1.0, 2.0]}}
        skeleton = build_skeleton(golden)
        errors = validate({"outer": {"inner": [1.0]}}, skeleton)
        self.assertTrue(any("length 1 != 2" in e for e in errors), errors)
        errors = validate({"outer": {}}, skeleton)
        self.assertTrue(any("missing key 'inner'" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
