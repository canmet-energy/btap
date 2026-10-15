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
    'DOAS with hydronic radiant floors, gas boiler and air-cooled chiller',
    'VAV chiller with gas boiler reheat and rotary ERV',
    'PVAV with gas boiler reheat and plate HRV',
    'Dual-duct VAV with gas boiler and water-cooled chiller',
)

# One manually selected row from each distinct four-scenario D-58 assignment
# signature. Modern systems lead the three signatures they inhabit so the
# broad reference gate also exercises their new teardown paths.
SIGNATURE_REPRESENTATIVES = (
    'DOAS with hydronic radiant floors, gas boiler and air-cooled chiller',
    'VAV chiller with gas boiler reheat and rotary ERV',
    'DOAS with VRF',
    'DOAS with water source heat pumps cooling tower with boiler',
    'PSZ RTU ASHP with Electric and ASHP Coils and Hot Water Baseboard with Electric Reheat',
    'DOAS with active chilled beams and electric baseboards',
    'Baseboard district hot water',
    'Baseboard electric',
    'Zone ERVs',
)

# The EnergyPlus layer covers all six modern inputs plus one row from every
# remaining D-58 signature. Scenarios are chosen to span every construction
# action: System 1 build, through-the-wall, System 3, System 6, heat-pump
# redirect, residential copy, and the unconditioned no-assignment case.
ENGINE_CASES = (
    ('DOAS with active chilled beams and electric baseboards',
     'general_2storey'),
    ('DOAS with passive chilled beams and electric baseboards',
     'general_3storey'),
    ('DOAS with hydronic radiant floors, gas boiler and air-cooled chiller',
     'residential'),
    ('VAV chiller with gas boiler reheat and rotary ERV',
     'general_3storey'),
    ('PVAV with gas boiler reheat and plate HRV',
     'data_processing'),
    ('Dual-duct VAV with gas boiler and water-cooled chiller',
     'residential'),
    ('DOAS with VRF', 'general_2storey'),
    ('DOAS with water source heat pumps cooling tower with boiler',
     'data_processing'),
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
