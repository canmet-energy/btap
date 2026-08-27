"""Shared costing-test plumbing (the ported slice of btap-costing's
test_helper.rb the Python suites need).

Deliberately thin: fixture paths, model loading and the skip discipline come
straight from tests.support — this module only adds the costing-suite
constants. The Ruby helper's ``tagged_model`` (NECB space-type tagging) and
the EnergyPlus runners wait on the btap.necb milestone; suites that need a
tagged or prescriptive-applied model must adapt or skip until then.
"""

from __future__ import annotations

from tests.support import (  # noqa: F401  (re-exported for the costing suites)
    DDY,
    EPW,
    FIXTURE_OSM,
    FIXTURES,
    HAVE_SDK,
    load_fixture,
    needs_sdk,
)

# fixture space-type tag used by the lighting/shw suites (offices carry SHW
# peak flows) — Ruby FixtureHelper::OFFICE
OFFICE = ("Space Function", "Office enclosed > 25 m2")
