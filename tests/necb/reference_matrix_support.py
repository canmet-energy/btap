"""Shared adjudicated inputs for catalog proposed-to-reference tests."""

from __future__ import annotations

from tests.support import FIXTURES

GOLDEN = FIXTURES / 'reference_selection_matrix.json'

CODES = ('necb2020', 'necb2025')

SCENARIOS = {
    'general_2storey': {'storeys': 2, 'type': 'office'},
    'general_3storey': {'storeys': 3, 'type': 'office'},
    'residential': {'storeys': 3, 'type': 'multi-unit residential'},
    'data_processing': {'storeys': 1, 'type': 'data centre'},
}

ASSIGNMENT_KEYS = ('system', 'action', 'energy_type', 'catalog', 'blocks')

MODERN_ROWS = (
    'doas-acb-elec-elecbb-acscrollchiller',
    'doas-pcb-elec-elecbb-acscrollchiller',
    'vav-hw-hwbb-erv-gasboiler-scrollchiller',
    'pvav-hw-hwbb-hrv-gasboiler',
    'ddvav-hw-gasboiler-scrollchiller',
)

# One manually selected row from each distinct four-scenario D-58 assignment
# signature. The five modern rows lead the two signatures they inhabit; seven
# legacy representatives complete the nine-signature set.
SIGNATURE_REPRESENTATIVES = (
    'vav-hw-hwbb-erv-gasboiler-scrollchiller',
    'psz-gas-hwbb-gasboiler',
    'doas-vrf-elec',
    'doas-wshp-elec-gasboiler-tower',
    'cvrh-ashp-elecrh-hwbb-gasboiler',
    'doas-acb-elec-elecbb-acscrollchiller',
    'bb-hwbb-district',
    'bb-elecbb',
    'zone-erv',
)

# The EnergyPlus layer covers all five modern inputs plus one row from every
# remaining D-58 signature. Scenarios span every adjudicated action, including
# copy_proposed through the residential PSZ case. The focused System 2/5
# water-coil sizing gate lives in test_system25_fan_coil_sizing.py.
ENGINE_CASES = (
    ('doas-acb-elec-elecbb-acscrollchiller',
     'general_2storey'),
    ('doas-pcb-elec-elecbb-acscrollchiller',
     'general_3storey'),
    ('vav-hw-hwbb-erv-gasboiler-scrollchiller',
     'general_3storey'),
    ('pvav-hw-hwbb-hrv-gasboiler',
     'general_3storey'),
    ('ddvav-hw-gasboiler-scrollchiller',
     'residential'),
    ('psz-gas-hwbb-gasboiler',
     'residential'),
    ('doas-vrf-elec', 'general_2storey'),
    ('doas-wshp-elec-gasboiler-tower',
     'general_2storey'),
    ('cvrh-ashp-elecrh-hwbb-gasboiler',
     'general_2storey'),
    ('bb-hwbb-district', 'general_2storey'),
    ('bb-elecbb', 'residential'),
    ('zone-erv', 'general_2storey'),
)


def normalize_expected(assignments):
    return [
        {key: assignment.get(key) for key in ASSIGNMENT_KEYS}
        for assignment in (assignments or [])
    ]


def assignment_signature(row, pass_='catalog'):
    return tuple(
        tuple(
            tuple(assignment.get(key) for key in ASSIGNMENT_KEYS)
            for assignment in row[f'{pass_}_{scenario}']
        )
        for scenario in SCENARIOS
    )
