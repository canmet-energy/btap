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
