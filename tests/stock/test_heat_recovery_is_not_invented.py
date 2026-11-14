"""Heat recovery the proposed building does not have must not be built for it.

#214: the identifier chose `PVAV with gas boiler reheat and plate HRV` for the
`multizone_vav` group of `Office_pre-1960`, a loop carrying no air-to-air heat
exchanger at all. The generated model recovered 48.64 GJ/yr of heating that the
source building has no equipment to recover.

The cause was two gaps, and both are covered here:

* `classify` recorded 13 descriptive facts and heat recovery was not one, so
  two catalogue rows differing ONLY by recovery collapsed to one signature and
  the scorer picked between them by tie-break;
* the catalogue's only DX-cooled VAV row carrying hot-water baseboards also
  carried a plate HRV, so a building with baseboards and no exchanger had no
  faithful row: one invented a recovery device, the other dropped baseboards
  the building has.
"""
import unittest

import openstudio

from btap._compat import opt
from btap.modeling.hvac import catalog, classify
from btap.stock.identify import identify_candidates


def _loop_with_outdoor_air(model, *, heat_recovery):
    """An air loop with an OA system, optionally carrying an air-to-air HX."""
    loop = openstudio.model.AirLoopHVAC(model)
    controller = openstudio.model.ControllerOutdoorAir(model)
    oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller)
    oa_system.addToNode(loop.supplyInletNode())
    if heat_recovery:
        exchanger = \
            openstudio.model.HeatExchangerAirToAirSensibleAndLatent(model)
        # The outboard OA node is the outdoor-air stream's inlet; an exchanger
        # sits there, not on the mixed-air node.
        exchanger.addToNode(opt(oa_system.outboardOANode()))
    return loop


def _group_for(loop):
    return classify._air_loop_group(loop, {}, None)


class TestTheFactIsRecorded(unittest.TestCase):
    def test_a_loop_with_no_exchanger_records_False(self):
        model = openstudio.model.Model()
        group = _group_for(_loop_with_outdoor_air(model, heat_recovery=False))
        self.assertIs(group['loop_heat_recovery'], False)

    def test_a_loop_WITH_an_exchanger_records_True(self):
        model = openstudio.model.Model()
        group = _group_for(_loop_with_outdoor_air(model, heat_recovery=True))
        self.assertIs(group['loop_heat_recovery'], True)

    def test_the_exchanger_is_NAMED_in_the_evidence(self):
        model = openstudio.model.Model()
        group = _group_for(_loop_with_outdoor_air(model, heat_recovery=True))
        self.assertTrue(
            any('heat recovery' in line for line in group['evidence']),
            f"evidence does not mention heat recovery: {group['evidence']}")

    def test_it_is_recorded_even_without_demand_controlled_ventilation(self):
        """The regression that the placement guards.

        `_outdoor_air_facts` returns early when DCV is off, which is the common
        case. Reading the exchanger after that return leaves the fact silently
        False on almost every loop — the shape of three guards that shipped
        this session and were never invoked.
        """
        model = openstudio.model.Model()
        loop = _loop_with_outdoor_air(model, heat_recovery=True)
        group = _group_for(loop)
        self.assertFalse(group['dcv'], 'fixture should have DCV off')
        self.assertIs(group['loop_heat_recovery'], True)


class TestTheScorerUsesIt(unittest.TestCase):
    # The fact vocabulary the SCORER reads, verified against
    # `identify.py`'s own `group.get(...)` keys rather than guessed. My first
    # version of this dict supplied `heat_fuels`, `cool_fuels`,
    # `loop_hydronic_heating` and `baseboard_media` — four names nothing
    # reads — so the recovery comparison ran with no fuel or media context at
    # all. It still passed, and the mutations still failed, because both
    # candidate rows lost the same absent credits; the ordering was right for
    # the wrong reason. Caught by an Astra review.
    BASE = {
        'family_guess': 'multizone_vav',
        'heated': True, 'cooled': True,
        'heating_energy_types': ['NaturalGas'],
        'cooling_energy_types': ['Electricity'],
        'loop_dx_cooling': True,
        'supply_heating_media': ['Hot Water'],
        'terminal_type': 'reheat',
        'zonal_units': ['baseboard'],
    }

    def _score(self, system, **overrides):
        facts = dict(self.BASE, **overrides)
        rows = identify_candidates(
            {'resolved': False, 'descriptive': facts}, limit=300)
        hit = next((r for r in rows if r['system'] == system), None)
        self.assertIsNotNone(hit, f'{system!r} was not a candidate')
        return hit

    def test_a_recovery_row_is_marked_DOWN_for_a_loop_with_no_exchanger(self):
        with_hrv = self._score('PVAV with gas boiler reheat and plate HRV',
                               loop_heat_recovery=False)
        without = self._score('PVAV with gas boiler reheat and hot water '
                              'baseboard', loop_heat_recovery=False)
        self.assertGreater(
            without['score'], with_hrv['score'],
            'a row that invents heat recovery must not outscore the row that '
            'does not')

    def test_the_objection_NAMES_the_invented_device(self):
        hit = self._score('PVAV with gas boiler reheat and plate HRV',
                          loop_heat_recovery=False)
        self.assertTrue(
            any('HEAT RECOVERY' in line for line in hit['against']),
            f"nothing names the addition: {hit['against']}")

    def test_a_recovery_row_is_PREFERRED_when_the_loop_does_recover(self):
        with_hrv = self._score('PVAV with gas boiler reheat and plate HRV',
                               loop_heat_recovery=True)
        without = self._score('PVAV with gas boiler reheat and hot water '
                              'baseboard', loop_heat_recovery=True)
        self.assertGreater(
            with_hrv['score'], without['score'],
            'a loop that recovers heat should prefer a row that recovers heat')

    def test_the_winner_for_a_no_exchanger_loop_carries_no_recovery(self):
        rows = identify_candidates(
            {'resolved': False,
             'descriptive': dict(self.BASE, loop_heat_recovery=False)},
            limit=300)
        winner = catalog.resolve(rows[0]['system'])
        self.assertFalse(
            winner.get('needs_erv'),
            f"the winning row {rows[0]['system']!r} builds heat recovery for a "
            'loop that has none')


class TestTheCatalogueCanExpressIt(unittest.TestCase):
    def test_a_DX_cooled_VAV_row_has_baseboards_WITHOUT_recovery(self):
        """The row whose absence caused #214.

        Before it, every DX-cooled `vav_reheat` row carrying hot-water
        baseboards also carried a plate HRV.
        """
        rows = [r for r in catalog.rows()
                if r['family'] == 'vav_reheat'
                and not r.get('needs_chiller')
                and r.get('baseboard_type') == 'Hot Water'
                and not r.get('needs_erv')]
        self.assertTrue(
            rows, 'no DX-cooled VAV row carries hot-water baseboards without '
                  'heat recovery')

    def test_the_new_row_is_not_a_DUPLICATE_of_an_existing_one(self):
        """A chiller-cooled twin WAS a duplicate and had to be withdrawn.

        Six `MZ BU RTU ... and Hot Water Baseboard` rows already covered the
        chiller-cooled case; the added row collided with one of them on its
        canonical name, which is what caught it.
        """
        from btap.modeling.hvac import canonical
        seen = {}
        for row in catalog.rows():
            seen.setdefault(canonical.name(row), []).append(row['name'])
        collisions = {c: names for c, names in seen.items() if len(names) > 1}
        self.assertEqual({}, collisions)


if __name__ == '__main__':
    unittest.main()
