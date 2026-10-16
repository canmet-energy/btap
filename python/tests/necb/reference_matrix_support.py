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
    'DOAS with active chilled beams and electric baseboards',
    'DOAS with passive chilled beams and electric baseboards',
    'VAV chiller with gas boiler reheat and rotary ERV',
    'PVAV with gas boiler reheat and plate HRV',
    'Dual-duct VAV with gas boiler and water-cooled chiller',
)

# One manually selected row from each distinct four-scenario D-58 assignment
# signature. The five modern rows lead the two signatures they inhabit; seven
# legacy representatives complete the nine-signature set.
SIGNATURE_REPRESENTATIVES = (
    'VAV chiller with gas boiler reheat and rotary ERV',
    'PSZ RTU Gas and DX Coils and Hot Water Baseboard',
    'DOAS with VRF',
    'DOAS with water source heat pumps cooling tower with boiler',
    'PSZ RTU ASHP with Electric and ASHP Coils and Hot Water Baseboard with Electric Reheat',
    'DOAS with active chilled beams and electric baseboards',
    'Baseboard district hot water',
    'Baseboard electric',
    'Zone ERVs',
)

# The EnergyPlus layer covers all five modern inputs plus one row from every
# remaining D-58 signature. Scenarios span every adjudicated action, including
# copy_proposed through the residential PSZ case. The data-processing System
# 2/5 water-coil UA failure remains tracked separately in #113.
ENGINE_CASES = (
    ('DOAS with active chilled beams and electric baseboards',
     'general_2storey'),
    ('DOAS with passive chilled beams and electric baseboards',
     'general_3storey'),
    ('VAV chiller with gas boiler reheat and rotary ERV',
     'general_3storey'),
    ('PVAV with gas boiler reheat and plate HRV',
     'general_3storey'),
    ('Dual-duct VAV with gas boiler and water-cooled chiller',
     'residential'),
    ('PSZ RTU Gas and DX Coils and Hot Water Baseboard',
     'residential'),
    ('DOAS with VRF', 'general_2storey'),
    ('DOAS with water source heat pumps cooling tower with boiler',
     'general_2storey'),
    ('PSZ RTU ASHP with Electric and ASHP Coils and Hot Water Baseboard with Electric Reheat',
     'general_2storey'),
    ('Baseboard district hot water', 'general_2storey'),
    ('Baseboard electric', 'residential'),
    ('Zone ERVs', 'general_2storey'),
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
