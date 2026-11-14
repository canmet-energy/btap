"""How often can the suggester recover the row that BUILT a model?

#221. Build each catalogue row on a fixture, scrub the loop and plant NAMES so
the name-recognition path cannot answer, write the recipe, and ask whether the
row that built the model comes back as the top candidate for every one of its
groups. The scrub is the one
`tests/necb/test_hvac_reference_selection_matrix.py` uses, so the scorer is
forced onto the facts.

This is NOT a fidelity requirement. `btap/stock/CLAUDE.md` is explicit that a
generated building is "representative for loads, envelope and equipment
performance, and only approximately for HVAC", and `suggest_systems=` and
`accept_candidates=` are both off by default. A perfect score is neither
expected nor wanted here.

**The property is that the number never silently falls.** The counts are
pinned as floors. A change that improves identification raises them and the
test tells you to re-pin; a change that quietly degrades it fails. Before
this existed, the only evidence about the suggester's accuracy was which
shapes its hand-written tests happened to cover — and measurement showed the
rows it recovered were exactly those shapes.

Written from a harness by a Fable review, 2026-11-06.
"""
import unittest

from btap.modeling import build_system
from btap.modeling.hvac import catalog
from btap.stock.hvac import hvac_section
from btap.stock.identify import identify_candidates
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

# Measured 2026-11-06 on the 110-row catalogue. Floors, not targets: raise
# them when a change earns it.
#
#   before #221's three fact fixes   top-1 18   top-5 40
#   after                            top-1 21   top-5 55
#
# That delta is what the harness is for. The three fixes were each justified
# on their own evidence, and this said whether they helped in aggregate
# instead of leaving it to be assumed.
TOP_1_FLOOR = 21
TOP_5_FLOOR = 55


def _recover(name):
    """Build `name`, scrub the names, and report whether it comes back."""
    model = load_fixture()
    build_system(model, name, sorted_zones(model))
    for i, loop in enumerate(model.getAirLoopHVACs()):
        loop.setName(f'Air System {i + 1}')
    for i, loop in enumerate(model.getPlantLoops()):
        loop.setName(f'Plant {i + 1}')

    groups = hvac_section(model, audit=None)['zone_groups']
    top1 = top5 = True
    for group in groups:
        if group['resolved']:
            # A resolved group names its system outright; that is the
            # name path, not identification, and it must still be right.
            top1 &= group.get('system') == name
            continue
        systems = [c['system'] for c in identify_candidates(group, limit=5)]
        top1 &= bool(systems) and systems[0] == name
        top5 &= name in systems
    return top1, top5


@needs_sdk
class TestSuggesterSelfConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.top1 = []
        cls.top5 = []
        cls.errors = []
        for row in catalog.rows():
            try:
                one, five = _recover(row['name'])
            except Exception as exc:                       # noqa: BLE001
                cls.errors.append(f"{row['name']}: {type(exc).__name__}")
                continue
            if one:
                cls.top1.append(row['name'])
            if five:
                cls.top5.append(row['name'])

    def test_every_row_can_be_built_and_read_back(self):
        """Separate from accuracy: a row that RAISES is a different defect,
        and would otherwise be silently counted as a miss."""
        self.assertEqual([], self.errors)

    def test_top_1_recovery_has_not_regressed(self):
        self.assertGreaterEqual(
            len(self.top1), TOP_1_FLOOR,
            f'top-1 recovery fell to {len(self.top1)} of '
            f'{len(catalog.rows())}; it was {TOP_1_FLOOR}')

    def test_top_5_recovery_has_not_regressed(self):
        self.assertGreaterEqual(
            len(self.top5), TOP_5_FLOOR,
            f'top-5 recovery fell to {len(self.top5)} of '
            f'{len(catalog.rows())}; it was {TOP_5_FLOOR}')

    def test_the_floors_are_not_stale_by_a_wide_margin(self):
        """If recovery improves a lot, re-pin — a floor far below the truth
        stops being a regression test."""
        slack = len(self.top1) - TOP_1_FLOOR
        self.assertLess(
            slack, 15,
            f'top-1 recovery is {len(self.top1)}, {slack} above its floor of '
            f'{TOP_1_FLOOR}. Raise TOP_1_FLOOR.')


if __name__ == '__main__':
    unittest.main()
