"""Pluggable air-loop naming.

'default'        -> human-readable ("PSZ RTU ... | Zone Name")
'necb_pipe_name' -> the machine-parseable NECB convention
                    (e.g. "sys_3|mixed|shr>none|sc>dx|sh>c-g|ssf>cv|zh>b-hw|zc>none|srf>none|"),
                    a faithful port of openstudio-standards assign_base_sys_name token maps,
                    for hosts whose downstream code (ECM, costing, QAQC) parses these names.
"""

from __future__ import annotations

HTG_TOKENS = {
    'none': 'sh>none', 'electric': 'sh>c-e', 'hot water': 'sh>c-hw',
    'gas': 'sh>c-g', 'g': 'sh>c-g', 'naturalgas': 'sh>c-g',
    'dx': 'sh>ashp', 'ashp': 'sh>ashp',
    'ashp>c-g': 'sh>ashp>c-g', 'ashp>c-e': 'sh>ashp>c-e', 'ashp>c-hw': 'sh>ashp>c-hw',
    'ccashp': 'sh>ccashp', 'ccashp>c-g': 'sh>ccashp>c-g',
    'ccashp>c-e': 'sh>ccashp>c-e', 'ccashp>c-hw': 'sh>ccashp>c-hw',
}

CLG_TOKENS = {
    'none': 'sc>none', 'chilled water': 'sc>c-chw', 'hydronic': 'sc>c-chw',
    'dx': 'sc>dx', 'ccashp': 'sc>ccashp', 'ashp': 'sc>ashp',
    'coil_chw': None,  # legacy quirk: unmatched token; the namer pass drops the segment
}

FAN_TOKENS = {'none': 'none', 'cv': 'cv', 'vv': 'vv'}

ZONE_HTG_TOKENS = {
    'none': 'zh>none', 'electric': 'zh>b-e', 'hot water': 'zh>b-hw',
    'tpfc': 'zh>tpfc', 'fpfc': 'zh>fpfc', 'pthp': 'zh>pthp', 'vrf': 'zh>vrf',
    'fancoil_4pipe': 'zh>fancoil_4pipe',  # legacy update_sys_name splices the raw value
}

ZONE_CLG_TOKENS = {
    'none': 'zc>none', 'tpfc': 'zc>tpfc', 'fpfc': 'zc>fpfc',
    'ptac': 'zc>ptac', 'pthp': 'zc>pthp', 'vrf': 'zc>vrf',
    'fancoil_4pipe': 'zc>fancoil_4pipe',
}


def _downcased(value):
    """Ruby's ``value.to_s.downcase`` (nil -> '')."""
    return ('' if value is None else str(value)).lower()


def necb_pipe_name(*, sys_abbr, sys_oa, parts):
    """Build the NECB pipe-name from name parts. Token semantics match
    openstudio-standards assign_base_sys_name exactly, and — like the legacy
    method — tokens are emitted in the PARTS DICT INSERTION ORDER (legacy
    systems differ: sys3/sys4 put sys_clg before sys_htg; sys6 puts sys_htg
    before sys_clg). Callers pass parts in the legacy order.

    :param sys_abbr: e.g. 'sys_3'
    :param sys_oa: 'mixed' or 'doas'
    :param parts: insertion-ordered dict, a subset of the keys
        sys_hr, sys_clg, sys_htg, sys_sf, zone_htg, zone_clg, sys_rf
    :return: str
    """
    sys_htg = parts.get('sys_htg')
    htg = _downcased('none' if sys_htg is None else sys_htg)

    tokens = []
    for key, value in parts.items():
        v = _downcased(value)
        key = str(key)
        if key == 'sys_hr':
            token = 'shr>none'
        elif key == 'sys_clg':
            # Legacy quirk preserved: DX cooling paired with heat-pump heating reads 'sc>ashp'.
            if v == 'dx' and htg in ('dx', 'ashp>c-g', 'ashp>c-e', 'ashp>c-hw'):
                token = 'sc>ashp'
            elif v in CLG_TOKENS:
                token = CLG_TOKENS[v]  # may be None (segment dropped, e.g. 'coil_chw')
            else:
                token = 'sc>none'
        elif key == 'sys_htg':
            token = HTG_TOKENS.get(v, 'sh>none')
        elif key == 'sys_sf':
            token = f"ssf>{FAN_TOKENS.get(v, 'none')}"
        elif key == 'zone_htg':
            token = ZONE_HTG_TOKENS.get(v, 'zh>none')
        elif key == 'zone_clg':
            token = ZONE_CLG_TOKENS.get(v, 'zc>none')
        elif key == 'sys_rf':
            token = f"srf>{FAN_TOKENS.get(v, 'none')}"
        else:
            token = None  # unknown keys fall out, as the Ruby case-with-compact does
        if token is not None:
            tokens.append(token)

    return '|'.join([sys_abbr, sys_oa] + tokens) + '|'


def apply(namer, air_loop, *, system_name, sys_abbr, sys_oa, parts, suffix=None):
    """Apply a name to an air loop per the selected namer.

    :param namer: 'default' or 'necb_pipe_name'
    :param air_loop: openstudio.model.AirLoopHVAC
    :param system_name: the catalog's descriptive name
    :param sys_abbr: str
    :param sys_oa: str
    :param parts: pipe-name parts (see necb_pipe_name)
    :param suffix: disambiguator (e.g. control zone name), or None
    """
    if namer == 'necb_pipe_name':
        air_loop.setName(necb_pipe_name(sys_abbr=sys_abbr, sys_oa=sys_oa, parts=parts))
    else:
        air_loop.setName(' | '.join(p for p in (system_name, suffix) if p is not None))
    return air_loop
