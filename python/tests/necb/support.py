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
    from btap.necb import loads

    model = load_raw_fixture()
    map_ = {s.nameString(): list(OFFICE) for s in model.getSpaces()}
    loads.assign_space_types(model, map_, vintage="2020")
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
