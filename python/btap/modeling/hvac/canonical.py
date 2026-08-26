"""ONE consolidated naming grammar, GENERATED from each catalog row's structured config
(never hand-written, so it cannot drift or go inconsistent). The legacy names — CBECS's
fuel-first ("Baseboard gas boiler"), NECB's medium-first ("... Hot Water Baseboard"),
ECM ids ("hs11_ashp_pthp") — remain the stable catalog keys, byte-matched to their
upstream vocabularies; the canonical name is an equally valid resolver key and the
recommended one for new code and tool/MCP surfaces.

Grammar:  <primary system>[ + <zone equipment>][ (<plant>)]
Example:  'Baseboard gas boiler'  ->  'hot water baseboards (gas boiler)'
          'PSZ RTU Gas and DX Coils and Hot Water Baseboard'
               -> 'packaged single-zone DX with gas heat + hot water baseboards (gas boiler)'
"""

from __future__ import annotations

FUEL_WORDS = {
    'NaturalGas': 'gas', 'Gas': 'gas', 'Electricity': 'electric', 'Electric': 'electric',
    # 'DX' is the LEGACY spelling of the reference-ASHP marker (now `heat_source: 'ashp'`);
    # kept so an out-of-tree row still written that way reads as ASHP rather than as 'dx'.
    'Hot Water': 'hot water', 'HotWater': 'hot water', 'DX': 'ASHP', 'None': None, None: None,
}


def fuel(value):
    if value in FUEL_WORDS:
        return FUEL_WORDS[value]
    return ('' if value is None else str(value)).lower()


def name(row):
    """:param row: a catalog row (dict, string keys). Composites recurse via catalog.
    :return: the canonical name (str)"""
    primary = primary_part(row)
    zone = zone_part(row)
    plant = plant_part(row)
    out = primary
    if zone:
        out += f" + {zone}"
    if plant:
        out += f" ({plant})"
    return out


def primary_part(row):
    family = row.get('family')
    if family == 'baseboards':
        return 'hot water baseboards' if row.get('baseboard_type') == 'Hot Water' else 'electric baseboards'
    if family == 'psz':
        # Reference-ASHP marker: `heat_source: 'ashp'`, with the legacy
        # `heating_coil_type: 'DX'` spelling accepted as an alias (see data/README.md).
        ashp = row.get('heat_source') == 'ashp' or row.get('heating_coil_type') == 'DX'
        if ashp:
            heat = f"ASHP heat with {fuel(row.get('supp_htg_fuel'))} backup"
        else:
            heat = f"{fuel(row.get('heating_coil_type'))} heat"
        base = f"packaged single-zone DX with {heat}"
        if row.get('per_zone'):
            base += ', one unit per zone'
        if row.get('sys_abbr') == 'sys_4':
            base += ', with exhaust'
        return base
    if family == 'vav_reheat':
        cool = 'DX' if row.get('cooling_type') == 'dx' else 'chilled water'
        return f"built-up VAV with {fuel(row.get('heating_coil_type'))} reheat and {cool} cooling"
    if family == 'fan_coils':
        pipes = 'two-pipe' if row.get('fan_coil_type') == 'TPFC' else 'four-pipe'
        if row.get('mau', True):
            mau = f" + {'DX' if row.get('mau_cooling_type') == 'DX' else 'hydronic'} make-up air"
        else:
            mau = ''
        return f"{pipes} fan coils{mau}"
    if family == 'mau_ptac':
        if row.get('reference_hp'):
            return f"100% OA make-up air ASHP + CAV {fuel(row.get('supp_htg_fuel'))} reheat"
        return f"100% OA make-up air ({fuel(row.get('mau_heating_coil_type'))} heat) + zone PTAC cooling"
    if family == 'zone_terminal':
        unit_type = row.get('unit_type')
        if unit_type == 'pthp':
            return 'zone PTHPs'
        if unit_type == 'window_ac':
            return 'window AC units'
        return 'zone PTAC cooling'
    if family == 'unit_heaters':
        return f"{fuel(row.get('heating_type'))} unit heaters"
    if family == 'furnace':
        h = row.get('heating', True)
        c = row.get('cooling', False)
        if h and c:
            return 'per-zone furnace with DX cooling'
        return 'per-zone gas furnace' if h else 'per-zone central AC'
    if family == 'evap_cooler':
        return 'per-zone direct evaporative coolers'
    if family == 'wshp':
        rej = {'cooling_tower': 'cooling tower', 'ground': 'ground'}.get(
            row.get('heat_rejection', 'fluid_cooler'), 'fluid cooler')
        return f"water-source heat pumps on a {rej} loop"
    if family == 'doas':
        return 'DOAS ventilation'
    if family == 'vrf':
        return 'VRF heat recovery system'
    if family == 'doas_pthp':
        return 'DOAS ASHP + zone PTHPs'
    if family == 'ecm_ashp_baseboard':
        hp = 'cold-climate ASHP' if row.get('air_eqpt') == 'ccashp' else 'ASHP'
        return f"DOAS {hp} + zone PTAC cooling"
    if family == 'ecm_doas_vrf':
        hp = 'cold-climate ASHP' if row.get('air_eqpt') == 'ccashp' else 'ASHP'
        return f"DOAS {hp} + VRF"
    if family == 'ecm_hp_fancoils':
        plant = ('ground-source heat pump plant' if row.get('plant_type') == 'gshp'
                 else 'air-to-water heat pump plant')
        air = ' with ASHP DOAS' if row.get('air_eqpt') == 'ashp' else ''
        return f"four-pipe fan coils on a {plant}{air}"
    if family == 'zone_ervs':
        return 'zone energy recovery ventilators'
    if family == 'composite':
        from btap.modeling.hvac import catalog  # composites recurse through the registry
        parts = []
        for part in row['parts']:
            merged = {**catalog.resolve(part['name']),
                      **{str(k): v for k, v in (part.get('config') or {}).items()}}
            parts.append(name(merged))
        return ' + '.join(parts)
    return ('' if row.get('name') is None else str(row['name'])).lower()


def zone_part(row):
    if row.get('family') == 'baseboards':
        return None  # baseboards ARE the primary there

    baseboard_type = row.get('baseboard_type')
    if baseboard_type == 'Hot Water':
        return 'hot water baseboards'
    if baseboard_type == 'Electric':
        return 'electric baseboards'
    return None


def plant_part(row):
    bits = []
    if row.get('needs_boiler'):
        if row.get('hw_source') == 'district':
            bits.append('district heating')
        else:
            bits.append(f"{fuel(row.get('boiler_fuel', 'NaturalGas'))} boiler")
    if row.get('needs_chiller'):
        chw_source = row.get('chw_source')
        if chw_source == 'air_cooled':
            bits.append(f"air-cooled {row.get('chiller_type', 'scroll').lower()} chiller")
        elif chw_source == 'district':
            bits.append('district cooling')
        else:
            bits.append(f"{row.get('chiller_type', 'Scroll').lower()} chiller")
    return None if not bits else ', '.join(bits)
