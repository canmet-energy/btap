"""Shared NECB-suite plumbing — the ported slice of btap-necb's
test_helper.rb ``FixtureHelper`` the Python domain suites need.

Deliberately thin: fixture paths, model loading and the skip discipline come
straight from tests.support; this module adds the NECB-specific fixture
shapes. ``tests.support.load_fixture()`` is Ruby's ``load_raw_fixture`` (the
untagged shared .osm); ``tagged_model()`` is the office-everywhere model the
shw/lighting suites are written against (offices carry SHW peak flows).
"""

from __future__ import annotations

from tests.support import (  # noqa: F401  (re-exported for the necb suites)
    DDY,
    EPW,
    FIXTURE_OSM,
    FIXTURES,
    HAVE_SDK,
    load_fixture,
    needs_engine,
    needs_sdk,
)

#: Ruby FixtureHelper::OFFICE
OFFICE = ["Space Function", "Office enclosed > 25 m2"]


def load_raw_fixture():
    """The RAW shared fixture — thermostats, no standardsSpaceType tags, no
    HVAC (Ruby ``load_raw_fixture``)."""
    return load_fixture()


def tagged_model():
    """The raw fixture tagged office everywhere (Ruby ``tagged_model``)."""
    from btap.codes.necb import loads

    model = load_raw_fixture()
    map_ = {s.nameString(): list(OFFICE) for s in model.getSpaces()}
    loads.assign_space_types(model, map_, code="necb2020")
    return model


#: Ruby FixtureHelper::STAT — the third of the weather trio.
STAT = EPW.with_suffix(".stat")


def compliance_fixture():
    """Ruby FixtureHelper#load_fixture (the compliance suites' shape): the
    shared fixture is ASHRAE-tagged with no standardsSpaceType, which the
    performance-path pre-flight (correctly) rejects — tag the one space type
    the five floor-area spaces use with a real NECB catalog name."""
    model = load_raw_fixture()
    for st in model.getSpaceTypes():
        if st.spaces():
            st.setStandardsBuildingType("Space Function")
            st.setStandardsSpaceType("Office enclosed > 25 m2")
    return model


def proposed_with_hvac(system="Baseboard gas boiler"):
    """A proposed building: the tagged fixture + a package-built HVAC
    system."""
    import btap.modeling as modeling
    from btap._compat import sorted_by_name

    model = compliance_fixture()
    modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
    return model


def zone_types_for(model):
    return {z.nameString(): "Office - enclosed"
            for z in model.getThermalZones()}


def real_conditional_report(conditions, *, code_label="NECB 2020",
                            compliant=True, annual=True):
    """A report built by the REAL `_set_conditional`, not by hand.

    The renderer fixtures used to hand-write `ahj_must_approve`, so they could
    not carry what the builder actually appends — and a hand-written fixture
    that mirrors the builder's assumptions hides exactly the shape bugs these
    tests exist to catch. The builder is cheap and pure; use it.
    """
    from btap.audit import AuditLog
    from btap.codes.necb import path as necb_path

    class _Run:
        pass

    run = _Run()
    run.report = {"compliant": compliant, "annual": annual,
                  "code_label": code_label,
                  "compliance_determination": "conditional"}
    required = sorted({c["id"] for c in conditions},
                      key=lambda i: int(i.split("-")[1]))
    necb_path._set_conditional(run, AuditLog(), required, conditions,
                               ("referral", "alternative-solution"))
    return run.report


#: One alternative-solution condition, the multi-energy case.
MULTI_ENERGY_CONDITION = {
    "id": "AHJ-1", "status": "alternative-solution",
    "title": "a single-fuel reference is a NON-CONFORMING substitution",
    "article": "8.4.4.9.(5)", "target": "Hot Water Loop",
    "detail": ("what the reference's final heating equipment carries is NOT "
               "established by this tool"),
    "entry_index": 0,
}

#: The (6) cardinality question, AHJ-3, which rides with AHJ-1 where one
#: hydronic plant carries the group's fuels.
CARDINALITY_CONDITION = {
    "id": "AHJ-3", "status": "referral",
    "title": "whether 8.4.4.9.(6)(d) permits more than one boiler",
    "article": "8.4.4.9.(5); 8.4.4.9.(6)", "target": "Hot Water Loop",
    "detail": ("whether that conflicts with the boiler-count sentence is NOT "
               "established here"),
    "entry_index": 1,
}

#: A referral that has NOTHING to do with multi-energy heating. Sol's `127`
#: requires the renderers to show this truthfully rather than in
#: capacity-ratio language.
SYSTEM_5_CONDITION = {
    "id": "AHJ-11", "status": "referral",
    "title": "heating in a two-pipe System 5 reference",
    "article": "8.4.4.1.(5)", "target": "Thermal Zone 7",
    "detail": ("the tool retains heating although the table's cell for this "
               "system says None"),
    "entry_index": 0,
}
