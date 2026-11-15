"""The envelope section of a recipe: one aggregate per assembly class."""

from __future__ import annotations

from btap._compat import opt, sorted_by_name
from btap.modeling.envelope.constructions import film_r

# Only these outside boundary conditions are ENVELOPE. 'Surface' and
# 'Adiabatic' are interior partitions, and there are a lot of them: the
# pre-1960 Hangar has 310 interior walls against 76 exterior ones, so
# including them would dominate the average and describe nothing.
ENVELOPE_BOUNDARIES = (
    'Outdoors',
    'Ground',
    'GroundFCfactorMethod',
    'GroundSlabPreprocessorAverage',
    'GroundSlabPreprocessorCore',
    'GroundSlabPreprocessorPerimeter',
    'GroundBasementPreprocessorAverageWall',
    'GroundBasementPreprocessorAverageFloor',
    'GroundBasementPreprocessorUpperWall',
    'GroundBasementPreprocessorLowerWall',
)

# Above this, one number is a poor summary of the set and the section says so
# rather than leaving it to be noticed.
SPREAD_WARNING_RATIO = 1.5

# `constructions.film_r` keys on the surface CLASSES its own package touches —
# 'wall', 'window', 'door', 'roofceiling', 'skylight', 'floor' — and returns
# 0.0 for anything else. OpenStudio's `subSurfaceType()` returns none of those
# spellings for glazing: measured, the eight valid values are FixedWindow,
# OperableWindow, Door, GlassDoor, OverheadDoor, Skylight,
# TubularDaylightDome and TubularDaylightDiffuser. So
# `film_r('fixedwindow', 'outdoors')` is 0.0, and passing the raw type added
# NO film resistance to any window.
#
# That was invisible until a mutation test caught nothing: adding films to a
# SimpleGlazing U-factor — which would be wrong — broke no test, because the
# films were zero either way. Only 'Door' worked, and only by coincidence of
# spelling.
_SUBSURFACE_FILM_CLASS = {
    'FixedWindow': 'window',
    'OperableWindow': 'window',
    'GlassDoor': 'door',
    'Door': 'door',
    'OverheadDoor': 'door',
    'Skylight': 'skylight',
    'TubularDaylightDome': 'skylight',
    'TubularDaylightDiffuser': 'skylight',
}


def film_class(surface_type):
    """The `film_r` surface class for an OpenStudio surface or sub-surface type."""
    return _SUBSURFACE_FILM_CLASS.get(surface_type, surface_type).lower()


def _layered(surface):
    construction = opt(surface.construction())
    if construction is None:
        return None
    return opt(construction.to_LayeredConstruction())


def _simple_glazing(layered):
    for layer in layered.layers():
        simple = opt(layer.to_SimpleGlazing())
        if simple is not None:
            return simple
    return None


def _u_overall(layered, surface_type, boundary):
    """Overall U including air films, or None — by TWO different routes.

    **A SimpleGlazing construction carries its U-factor directly and has no
    readable conductance.** Measured on 3.11: `Vintage 4 Window R1.6` is one
    `SimpleGlazing` layer with `uFactor() == 3.55`, and its
    `thermalConductance()` returns None. The first version of this reader
    computed from conductance only, so it dropped EVERY window — 30 of them on
    `Office_pre-1960`, which is the whole fenestration section — and reported
    them as unreadable rather than wrong, which is how the hole was visible at
    all.

    A SimpleGlazing U-factor is already the OVERALL U, films included (that is
    the definition of `WindowMaterial:SimpleGlazingSystem`'s U-Factor field),
    so films must NOT be added to it. Adding them would report a window better
    than it is.

    For everything else the films matter in the other direction: a
    construction's `thermalConductance()` EXCLUDES them, and NECB's
    prescriptive maxima are overall U values that include them. Measured on
    the pre-1960 Hangar's exterior walls, R 1.498 without films against
    R 1.65 with — 10%, enough to make a recipe wrong.
    """
    simple = _simple_glazing(layered)
    if simple is not None:
        return simple.uFactor()

    # A single-layer StandardGlazing has its own `thermalConductance()` — a
    # plain double on the MATERIAL — while the layered CONSTRUCTION's returns
    # None for glazing. Measured: the campus archetypes carry
    # `Customized Fenestration: cond=0.280 tvis=0.210 tsol=0.500`, one
    # StandardGlazing layer, and reading only the construction's conductance
    # dropped 19 of those windows. This is a conductance, not a U-factor, so
    # the films DO apply here, unlike the SimpleGlazing route above.
    glazing_layers = [opt(layer.to_StandardGlazing())
                      for layer in layered.layers()]
    glazing_layers = [g for g in glazing_layers if g is not None]
    if len(glazing_layers) == 1 and len(layered.layers()) == 1:
        films = film_r(film_class(surface_type), boundary.lower())
        return 1.0 / (1.0 / glazing_layers[0].thermalConductance() + films)

    try:
        conductance = layered.thermalConductance()
    except Exception:
        return None
    conductance = (opt(conductance) if hasattr(conductance, 'is_initialized')
                   else conductance)
    if not conductance:
        return None
    films = film_r(film_class(surface_type), boundary.lower())
    return 1.0 / (1.0 / conductance + films)


def _shgc(layered):
    """SHGC, or None when it cannot be read.

    Deliberately NOT `constructions.fenestration_solar_transmittance`, which
    returns 0.60 when it finds neither a SimpleGlazing nor a StandardGlazing.
    That default is correct when APPLYING a construction and a fabrication
    when reading one: this writer must not report an assumed number as a
    measured one.
    """
    simple = _simple_glazing(layered)
    if simple is not None:
        return simple.solarHeatGainCoefficient()
    for layer in layered.layers():
        standard = opt(layer.to_StandardGlazing())
        if standard is not None:
            return opt(standard.solarTransmittanceatNormalIncidence())
    return None


def _visible_transmittance(layered):
    simple = _simple_glazing(layered)
    if simple is not None:
        return opt(simple.visibleTransmittance())
    for layer in layered.layers():
        standard = opt(layer.to_StandardGlazing())
        if standard is not None:
            return opt(standard.visibleTransmittanceatNormalIncidence())
    return None


def _aggregate(rows, extras=()):
    """Area-weighted aggregate of (area, u, *extra) rows, with its spread.

    Weighted on U, never on R. Heat flow is the sum of U*A*dT, so the
    effective U of an assembly set is sum(U*A)/sum(A); averaging R by area
    overweights the well-insulated surfaces and reports an envelope better
    than the one that exists. R is then DERIVED as 1/U_eff, so the two can
    never disagree.
    """
    area = sum(row[0] for row in rows)
    if area <= 0:
        return None
    u_eff = sum(row[1] * row[0] for row in rows) / area
    us = sorted(row[1] for row in rows)
    out = {
        'u_si': round(u_eff, 4),
        'r_si': round(1.0 / u_eff, 3),
        'from': {
            'surfaces': len(rows),
            'area_m2': round(area, 1),
            'u_min': round(us[0], 4),
            'u_max': round(us[-1], 4),
            'u_spread_ratio': round(us[-1] / us[0], 2) if us[0] else None,
        },
    }
    for index, name in enumerate(extras, start=2):
        present = [(row[0], row[index]) for row in rows
                   if row[index] is not None]
        if not present:
            continue
        sub_area = sum(a for a, _v in present)
        out[name] = round(sum(v * a for a, v in present) / sub_area, 4)
        out['from'][f'{name}_from_surfaces'] = len(present)

    ratio = out['from']['u_spread_ratio']
    if ratio is not None and ratio > SPREAD_WARNING_RATIO:
        out['from']['spread_warning'] = (
            f'these {len(rows)} surfaces span {ratio}x in U, so one value is '
            'a lossy summary of the set')
    return out


def envelope_section(model, audit=None):
    """The recipe's envelope section: one aggregate per assembly class.

    Keys are ``'<SurfaceType>:<OutsideBoundaryCondition>'`` for opaque
    assemblies and ``'<SubSurfaceType>:<boundary>'`` for glazed ones, so a
    reader can tell an exterior wall from a ground-contact one without
    inferring it from the number.

    :returns: ``{'opaque': {...}, 'fenestration': {...}, 'unreadable': [...]}``
    """
    opaque_rows, glazed_rows, unreadable = {}, {}, []

    for surface in sorted_by_name(model.getSurfaces()):
        boundary = surface.outsideBoundaryCondition()
        if boundary not in ENVELOPE_BOUNDARIES:
            continue
        surface_type = surface.surfaceType()
        layered = _layered(surface)
        u = (_u_overall(layered, surface_type, boundary)
             if layered is not None else None)
        if u is None:
            unreadable.append({'surface': surface.nameString(),
                               'why': 'no layered construction, or its '
                                      'conductance is not resolvable'})
            continue
        opaque_rows.setdefault(f'{surface_type}:{boundary}', []).append(
            (surface.grossArea(), u))

        for sub in sorted_by_name(surface.subSurfaces()):
            sub_layered = _layered(sub)
            sub_u = (_u_overall(sub_layered, sub.subSurfaceType(), boundary)
                     if sub_layered is not None else None)
            if sub_u is None:
                unreadable.append({'surface': sub.nameString(),
                                   'why': 'no layered construction, or its '
                                          'conductance is not resolvable'})
                continue
            # Bucket by whether the CONSTRUCTION is opaque, NOT by
            # `subSurfaceType`. An exterior `Door` is a sub-surface with an
            # opaque assembly — 'V4 Door R4', a single `Material` layer,
            # `isOpaque() == True` — while a `GlassDoor` carries
            # `WindowMaterial:SimpleGlazingSystem`.
            #
            # Filing every sub-surface as fenestration made the reader hand an
            # opaque door a GLAZING construction, and the ForwardTranslator
            # then reclassified it: all 29 exterior doors in
            # `Office_pre-1960` came out of a round trip as `GlassDoor` in the
            # IDF, gaining solar heat the real doors do not admit. The OSM
            # still reported `subSurfaceType() == 'Door'`, so the defect was
            # invisible until the translated IDF was read.
            #
            # The writer already had the signal and did not use it: it records
            # `shgc=None` for these, because `_shgc` finds no glazing to read.
            if sub_layered.isOpaque():
                opaque_rows.setdefault(
                    f'{sub.subSurfaceType()}:{boundary}', []).append(
                        (sub.grossArea(), sub_u))
            else:
                glazed_rows.setdefault(
                    f'{sub.subSurfaceType()}:{boundary}', []).append(
                        (sub.grossArea(), sub_u, _shgc(sub_layered),
                         _visible_transmittance(sub_layered)))

    section = {
        'opaque': {key: _aggregate(rows)
                   for key, rows in sorted(opaque_rows.items())},
        'fenestration': {
            key: _aggregate(rows, extras=('shgc', 'visible_transmittance'))
            for key, rows in sorted(glazed_rows.items())},
        'unreadable': unreadable,
    }
    if audit is not None and unreadable:
        audit.warn('recipe',
                   f'{len(unreadable)} envelope surface(s) could not be read '
                   'and are OMITTED from the recipe rather than defaulted',
                   inputs={'surfaces': [u['surface'] for u in unreadable][:20]})
    return section
