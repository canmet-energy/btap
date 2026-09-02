"""NECB 2020/2025 Article 4.2.2.1., sentences (10)-(15): WHERE automatic
daylight-responsive photocontrols are required.

(10) SIDELIGHTING — in space types whose Table 4.2.1.6 "Automatic Daylight
     Responsive Controls for Sidelighting" column carries an X, the general
     lighting in the primary and secondary sidelighted areas shall be
     separately photocontrolled where
       (a) the combined input power of all general lighting completely or
           partially within the PRIMARY sidelighted areas is >= 150 W, OR
       (b) the combined input power within the PRIMARY AND SECONDARY
           sidelighted areas is >= 300 W.
(12) exceptions to (10): (a) obstruction ratio >= 2, (b) total glazing area
     < 2 m2, (c) retail spaces.
(13) TOPLIGHTING — in space types whose Table 4.2.1.6 toplighting column
     carries an X, the general lighting in the daylighted areas under
     skylights AND roof monitors shall be photocontrolled where that
     combined input power is >= 150 W.
(15) exceptions to (13): (a) adjacent structures/natural objects block
     direct sun > 1 500 h/yr between 8 a.m. and 4 p.m., (b) skylight and
     roof-monitor VT < 0.4, (c) buildings above 55 degN latitude where the
     general-lighting input power within the daylighted areas is < 200 W.

(10) AND (13) ARE INDEPENDENT. Nothing in either sentence conditions one on
the other; a space qualifies under either alone. The NECB 2011 criteria the
legacy port applies (primary sidelighted area > 100 m2 AND under-skylight
area > 400 m2 AND skylight effective aperture > 0.006, all ANDed) make a
window-only space fail on its zero skylight area, which is exactly why the
legacy path places no controls at all on window-only archetypes (L-26).

THE POWER TEST, DERIVED. Sentences (10) and (13) test INPUT POWER inside a
daylighted area, which in general needs per-luminaire placement. It does not
here: this gem applies a single uniform lighting power density per space
(4.2.1.6. allowance, W/m2 over the whole space floor area), so the general
lighting is uniformly distributed by construction and

    input power within a daylighted area = LPD_general x daylighted_area

exactly. No luminaire layout is needed or possible. "General" excludes the
4.2.1.6. specialty/decorative additional allowance, which this gem models as
a separately named "Additional Lights" instance and which (10)/(13) do not
cover.
"""

from __future__ import annotations

import json
import math
import re

from btap._compat import NullAudit, ruby_round
from btap.necb import lighting as _lighting
from btap.necb.lighting import daylighted_areas as DaylightedAreas

PRIMARY_THRESHOLD_W = 150.0         # 4.2.2.1.(10)(a)
COMBINED_THRESHOLD_W = 300.0        # 4.2.2.1.(10)(b)
TOPLIGHTING_THRESHOLD_W = 150.0     # 4.2.2.1.(13)
MIN_GLAZING_AREA_M2 = 2.0           # 4.2.2.1.(12)(b)
OBSTRUCTION_RATIO = 2.0             # 4.2.2.1.(12)(a)
SKYLIGHT_VT_THRESHOLD = 0.4         # 4.2.2.1.(15)(b)
HIGH_LATITUDE_DEG_N = 55.0          # 4.2.2.1.(15)(c)
HIGH_LATITUDE_THRESHOLD_W = 200.0   # 4.2.2.1.(15)(c)

_table_cache = None


def table():
    """Table 4.2.1.6.'s two daylight-control columns, mapped to the NECB
    space-function catalog names. Five states per column:
      required       — the column carries 'X'
      not_required   — the column carries a dash (the two editions agree)
      not_applicable — the table refers the space type to a DIFFERENT article
                       (4.2.2.2. storage garages, 4.2.2.6.(2) guest rooms)
      not_listed     — the space type has no row at all, and (10)/(13) reach
                       only spaces requiring the control "in accordance with
                       Table 4.2.1.6." (dwelling units)
      unknown        — the space type has NO ROW in Table 4.2.1.6, so neither
                       column can be read for it. Never decided silently
    'unknown' is STRUCTURAL, not an extraction defect. The table's nine control
    columns were re-read 2026-07-30 after the upstream extraction fix and agree
    exactly between the 2020 and 2025 editions (0 differing cells of 909), so
    the earlier conflict machinery — 2025 primary, 2020 corroborating — is gone
    from the data file. What remains unknown is three catalog entries that the
    printed table genuinely does not list: the '- undefined -' sentinel, the
    legacy-only convention-centre seating type, and WholeBuilding (whose LPD
    comes from the building-type method of Table 4.2.1.5)."""
    global _table_cache
    if _table_cache is None:
        path = _lighting.DATA_DIR / 'daylighting_controls_4_2_1_6.json'
        _table_cache = json.loads(path.read_text(encoding='utf-8'))
    return _table_cache


def residue():
    return table()['residue']


def requirement(standards_space_type):
    """:return: the Table 4.2.1.6. row for a standards space-type name
    (schedule-letter suffixes stripped), or None when the name is not in the
    catalog at all"""
    if standards_space_type is None:
        return None

    return table()['space_types'].get(_base_name(standards_space_type))


def _base_name(standards_space_type):
    return re.sub(r'-sch-[A-Z]\Z', '', str(standards_space_type))


def evaluate(space, audit=None, unknown_default='required', shading_surfaces=None, seen=None):
    """Evaluate 4.2.2.1.(10)-(15) for one space.

    :param space: openstudio.model.Space
    :param unknown_default: 'required' or 'not_required' — what to do when
        Table 4.2.1.6. cannot be read for this space type. Default 'required' —
        photocontrols in the REFERENCE building lower the reference's lighting
        energy and therefore TIGHTEN the target the proposed building must beat,
        so assuming "required" cannot hand a non-conforming building a pass.
        Every use of the default WARNS.
    :param seen: a caller-owned dedupe map so a 122-space apartment run logs
        each unresolved (space type, column) ONCE rather than 122 times
    :return: 'required' (bool), 'sidelighting' / 'toplighting' (sub-dicts with
        'required', 'reason', 'power_w'), 'areas', 'lpd_w_per_m2'
    """
    audit = audit if audit is not None else NullAudit()
    standards_type = _standards_space_type(space)
    row = requirement(standards_type)
    lpd = _general_lighting_lpd(space)
    areas = DaylightedAreas.areas(space, audit=audit)

    if row is None:
        if seen is None or seen.get(f"absent|{standards_type}") is None:
            if seen is not None:
                seen[f"absent|{standards_type}"] = True
            audit.warn('daylighting',
                       f"SPACE TYPE {_inspect(standards_type)} IS NOT IN THE VENDORED TABLE 4.2.1.6. CONTROL "
                       f"MATRIX — its 4.2.2.1.(10)/(13) columns cannot be read (first seen on space "
                       f"'{space.nameString()}'), so the conservative default ({unknown_default}) is applied to "
                       'BOTH sidelighting and toplighting',
                       target=space.nameString(), article='4.2.1.6.; 4.2.2.1.(10); 4.2.2.1.(13)',
                       ruling='D-57')
        row = {'sidelighting': 'unknown', 'toplighting': 'unknown',
               'table_row': standards_type,
               'evidence': 'space type absent from the vendored matrix'}

    side = _evaluate_sidelighting(space, row, lpd, areas, audit, unknown_default,
                                  shading_surfaces, standards_type, seen)
    top = _evaluate_toplighting(space, row, lpd, areas, audit, unknown_default,
                                standards_type, seen)

    return {'required': side['required'] or top['required'],
            'sidelighting': side, 'toplighting': top, 'areas': areas,
            'lpd_w_per_m2': lpd, 'space_type': standards_type,
            'table_row': row.get('table_row')}


def _inspect(value):
    """Ruby ``String#inspect`` / ``nil.inspect``."""
    return 'nil' if value is None else f'"{value}"'


def _evaluate_sidelighting(space, row, lpd, areas, audit, unknown_default, shading_surfaces,
                           standards_type=None, seen=None):
    state = _column_state(row.get('sidelighting'), unknown_default, space, 'sidelighting', row,
                          audit, standards_type, seen)
    primary_w = lpd * areas['primary_sidelighted_m2']
    combined_w = lpd * (areas['primary_sidelighted_m2'] + areas['secondary_sidelighted_m2'])
    result = {'primary_power_w': ruby_round(primary_w, 1),
              'combined_power_w': ruby_round(combined_w, 1),
              'table': row.get('sidelighting')}

    if not state:
        return _merge(result, required=False,
                      reason='Table 4.2.1.6. does not require sidelighting photocontrols for '
                             'this space type')

    # (12)(c) retail
    if row.get('retail'):
        audit.info('daylighting', 'sidelighting photocontrols not required: retail space',
                   target=space.nameString(), article='4.2.2.1.(12)(c)',
                   ruling='D-57')
        return _merge(result, required=False, reason='4.2.2.1.(12)(c) exception: retail space')

    # (12)(b) total glazing < 2 m2
    if areas['window_area_m2'] < MIN_GLAZING_AREA_M2:
        return _merge(result, required=False,
                      reason='4.2.2.1.(12)(b) exception: total glazing '
                             f"{areas['window_area_m2']:.2f} m2 < 2 m2")

    # (12)(a) obstruction ratio >= 2
    ratio = _obstruction_ratio(space, shading_surfaces)
    if ratio is not None and ratio >= OBSTRUCTION_RATIO:
        audit.info('daylighting',
                   'sidelighting photocontrols not required: adjacent-structure obstruction ratio >= 2',
                   target=space.nameString(), inputs={'obstruction_ratio': ruby_round(ratio, 2)},
                   article='4.2.2.1.(12)(a)',
                   ruling='D-57')
        return _merge(result, required=False,
                      reason=f"4.2.2.1.(12)(a) exception: obstruction ratio {ratio:.2f} >= 2")

    if primary_w >= PRIMARY_THRESHOLD_W:
        return _merge(result, required=True,
                      reason=f"4.2.2.1.(10)(a): {primary_w:.0f} W of general lighting in "
                             f"{areas['primary_sidelighted_m2']:.1f} m2 of primary "
                             'sidelighted area >= 150 W')
    if combined_w >= COMBINED_THRESHOLD_W:
        combined_m2 = areas['primary_sidelighted_m2'] + areas['secondary_sidelighted_m2']
        return _merge(result, required=True,
                      reason=f"4.2.2.1.(10)(b): {combined_w:.0f} W of general lighting in "
                             f"{combined_m2:.1f} m2 of primary + "
                             'secondary sidelighted area >= 300 W')
    return _merge(result, required=False,
                  reason=f"below both 4.2.2.1.(10) thresholds: {primary_w:.0f} W primary (< 150 W) and "
                         f"{combined_w:.0f} W primary + secondary (< 300 W)")


def _evaluate_toplighting(space, row, lpd, areas, audit, unknown_default,
                          standards_type=None, seen=None):
    state = _column_state(row.get('toplighting'), unknown_default, space, 'toplighting', row,
                          audit, standards_type, seen)
    power_w = lpd * areas['toplighted_m2']
    result = {'power_w': ruby_round(power_w, 1), 'table': row.get('toplighting')}

    if not state:
        return _merge(result, required=False,
                      reason='Table 4.2.1.6. does not require toplighting photocontrols for '
                             'this space type')

    # (15)(b) skylight VT < 0.4
    vt = areas['skylight_vt_max']
    if vt is not None and vt < SKYLIGHT_VT_THRESHOLD:
        return _merge(result, required=False,
                      reason=f"4.2.2.1.(15)(b) exception: highest skylight VT {vt:.3f} < 0.4")

    # (15)(c) above 55 degN with < 200 W
    latitude = _site_latitude(space.model())
    if (latitude is not None and latitude > HIGH_LATITUDE_DEG_N
            and power_w < HIGH_LATITUDE_THRESHOLD_W):
        audit.info('daylighting',
                   'toplighting photocontrols not required: above 55 degN with < 200 W of general lighting '
                   'in the daylighted areas',
                   target=space.nameString(),
                   inputs={'latitude_deg_n': ruby_round(latitude, 2),
                           'power_w': ruby_round(power_w, 1)},
                   article='4.2.2.1.(15)(c)',
                   ruling='D-57')
        return _merge(result, required=False,
                      reason=f"4.2.2.1.(15)(c) exception: latitude {latitude:.2f} degN > 55 degN and "
                             f"{power_w:.0f} W < 200 W")

    if power_w >= TOPLIGHTING_THRESHOLD_W:
        return _merge(result, required=True,
                      reason=f"4.2.2.1.(13): {power_w:.0f} W of general lighting in "
                             f"{areas['toplighted_m2']:.1f} m2 of daylighted area "
                             'under skylights >= 150 W')
    return _merge(result, required=False,
                  reason=f"below the 4.2.2.1.(13) threshold: {power_w:.0f} W in "
                         f"{areas['toplighted_m2']:.1f} m2 of daylighted area "
                         'under skylights (< 150 W)')


def _merge(result, **kwargs):
    """Ruby ``Hash#merge`` — a NEW hash, so the caller's `result` is untouched."""
    merged = dict(result)
    merged.update(kwargs)
    return merged


def _column_state(value, unknown_default, space, column, row, audit,
                  standards_type=None, seen=None):
    """Is the Table 4.2.1.6. column gate open? 'not_listed' and 'not_applicable'
    are DETERMINATIONS read from the code text and are logged once as such;
    only 'unknown' falls back on the caller's documented default, LOUDLY."""
    sentence = 10 if column == 'sidelighting' else 13
    label = standards_type or row.get('table_row') or '(untagged space type)'
    if value == 'required':
        return True
    if value in ('not_required', 'not_applicable'):
        return False
    if value == 'not_listed':
        if seen is None or seen.get(f"not_listed|{label}|{column}") is None:
            if seen is not None:
                seen[f"not_listed|{label}|{column}"] = True
            note = row.get('note')
            audit.info('daylighting',
                       f"space type '{label}' has NO Table 4.2.1.6. row, and 4.2.2.1.({sentence}) reaches "
                       'only spaces requiring the control "in accordance with Table 4.2.1.6." (4.2.2.1.(2) '
                       f"ties the requirement to that table's space-by-space types) — so {column} "
                       f"photocontrols are not required for it. {'' if note is None else note}",
                       target=space.nameString(),
                       article=f"4.2.1.6.; 4.2.2.1.({sentence}); 4.2.2.1.(2)",
                       ruling='D-57')
        return False

    if seen is None or seen.get(f"unknown|{label}|{column}") is None:
        if seen is not None:
            seen[f"unknown|{label}|{column}"] = True
        evidence = row.get(f"evidence_{column}") or row.get('evidence')
        audit.warn('daylighting',
                   f"TABLE 4.2.1.6. {column.upper()} COLUMN IS UNRESOLVED for space type "
                   f"'{label}' (row {_inspect(row.get('table_row'))}) — "
                   f"{'' if evidence is None else evidence}. Every space of this type therefore "
                   f"takes the documented conservative default ({unknown_default}); photocontrols in the "
                   'REFERENCE lower its lighting energy and so tighten the target, which cannot grant an '
                   f"undeserved pass. First seen on '{space.nameString()}'",
                   target=space.nameString(), article=f"4.2.1.6.; 4.2.2.1.({sentence})",
                   ruling='D-57')
    return unknown_default == 'required'


# --- inputs ---------------------------------------------------------------

def _standards_space_type(space):
    space_type = space.spaceType()
    if not space_type.is_initialized():
        return None

    standards = space_type.get().standardsSpaceType()
    return standards.get() if standards.is_initialized() else None


def _general_lighting_lpd(space):
    """W/m2 of GENERAL lighting for a space: every Lights instance reaching the
    space except the 4.2.1.6. specialty/decorative "Additional Lights"
    allowance, which 4.2.2.1.(10)/(13) do not cover."""
    floor_area = space.floorArea()
    instances = list(space.lights())
    if space.spaceType().is_initialized():
        instances += list(space.spaceType().get().lights())
    total = 0.0
    for instance in instances:
        if re.search(r'additional', instance.nameString(), re.IGNORECASE):
            continue

        definition = instance.lightsDefinition()
        multiplier = instance.multiplier()
        method = definition.designLevelCalculationMethod()
        if method == 'Watts/Area':
            watts = definition.wattsperSpaceFloorArea()
            total += watts.get() * multiplier if watts.is_initialized() else 0.0
        elif method == 'LightingLevel':
            level = definition.lightingLevel()
            if not level.is_initialized() or floor_area <= 0.0:
                continue
            total += level.get() * multiplier / floor_area
        elif method == 'Watts/Person':
            watts = definition.wattsperPerson()
            if not watts.is_initialized() or floor_area <= 0.0:
                continue
            total += watts.get() * multiplier * space.numberOfPeople() / floor_area
    return total


def _site_latitude(model):
    try:
        site = model.getSite()
        latitude = site.latitude()
        return None if latitude == 0 else latitude
    except Exception:
        return None


def shading_polygons(model):
    """World-coordinate shading surfaces, computed once per model.

    :return: list of point lists"""
    polygons = []
    for group in model.getShadingSurfaceGroups():
        transformation = group.transformation()
        for surface in group.shadingSurfaces():
            polygons.append(list(transformation * surface.vertices()))
    return polygons


def _obstruction_ratio(space, shading_surfaces=None):
    """4.2.2.1.(12)(a): "the vertical projected distance from the top of the
    windows to the top of any adjacent structure divided by the horizontal
    distance from the window to the adjacent structure". Adjacent structures
    in an OpenStudio model are ShadingSurfaces; the ratio is taken per window
    against every shading surface and the LARGEST governs (the sentence says
    "any adjacent structure").

    :return: None when the model carries no shading surfaces, in which case the
        exception has nothing to apply to"""
    polygons = shading_surfaces if shading_surfaces is not None else shading_polygons(space.model())
    if not polygons:
        return None

    transformation = space.transformation()
    best = None
    for surface in space.surfaces():
        if not (surface.outsideBoundaryCondition() == 'Outdoors'
                and surface.surfaceType() == 'Wall'):
            continue

        for sub in surface.subSurfaces():
            if sub.subSurfaceType() not in DaylightedAreas.WINDOW_TYPES:
                continue

            world = list(transformation * sub.vertices())
            head_z = max(v.z() for v in world)
            centre_x = sum(v.x() for v in world) / len(world)
            centre_y = sum(v.y() for v in world) / len(world)
            for polygon in polygons:
                rise = max(v.z() for v in polygon) - head_z
                if not rise > 0:
                    continue

                run = _plan_distance(centre_x, centre_y, polygon)
                if not run > 0:
                    continue

                ratio = rise / run
                if best is None or ratio > best:
                    best = ratio
    return best


def _plan_distance(point_x, point_y, polygon):
    """Shortest distance in PLAN from a point to a polygon's boundary — measured
    to the edges, not only the vertices, so a broad wall 5 m away reads 5 m
    (a vertex-only measure would read the diagonal and understate the ratio)."""
    return min(_segment_distance(point_x, point_y, vertex.x(), vertex.y(),
                                 polygon[(index + 1) % len(polygon)].x(),
                                 polygon[(index + 1) % len(polygon)].y())
               for index, vertex in enumerate(polygon))


def _segment_distance(point_x, point_y, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    length_squared = (dx * dx) + (dy * dy)
    t = 0.0 if length_squared == 0 else (((point_x - ax) * dx) + ((point_y - ay) * dy)) / length_squared
    t = min(max(t, 0.0), 1.0)
    return math.sqrt(((point_x - (ax + (t * dx))) ** 2) + ((point_y - (ay + (t * dy))) ** 2))
