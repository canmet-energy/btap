"""Fixture plumbing shared by the hvac-domain suites (port of btap-necb's
test_helper.rb FixtureHelper, the parts the HVAC tests use).

Domain-scoped on purpose: the Ruby helper is one module every suite includes,
but the Python port slices it per domain so concurrent ports never collide.
"""

from __future__ import annotations

from tests.support import FIXTURE_OSM


def load_raw_fixture():
    """The RAW shared fixture — thermostats, no standardsSpaceType tags, no HVAC."""
    from btap._sdk import load_model
    return load_model(FIXTURE_OSM)


def load_fixture():
    """The shared fixture is ASHRAE-tagged with no standardsSpaceType, which the
    performance-path pre-flight now (correctly) rejects: unresolvable space types
    silently keep the proposed's lighting/loads in the reference. Tag the one space
    type the five floor-area spaces use with a real NECB catalog name — 'Office -
    enclosed' and friends are NOT catalog names (the catalog has 'Office enclosed
    > 25 m2' / '<= 25 m2')."""
    model = load_raw_fixture()
    for st in model.getSpaceTypes():
        if len(st.spaces()):
            st.setStandardsBuildingType('Space Function')
            st.setStandardsSpaceType('Office enclosed > 25 m2')
    return model


def sorted_zones(model):
    from btap._compat import sorted_by_name
    return sorted_by_name(model.getThermalZones())


def proposed_with_hvac(system='Baseboard gas boiler'):
    """A proposed building: the fixture + a package-built HVAC system."""
    import btap.modeling as modeling
    model = load_fixture()
    modeling.build_system(model, system, sorted_zones(model))
    return model


def zone_types(model, type_='Office - enclosed'):
    return {z.nameString(): type_ for z in model.getThermalZones()}


def attach_weather(model):
    import openstudio

    from tests.support import DDY, EPW
    epw = openstudio.EpwFile(openstudio.path(str(EPW)))
    openstudio.model.WeatherFile.setWeatherFile(model, epw)
    ddy = openstudio.energyplus.loadAndTranslateIdf(openstudio.path(str(DDY))).get()
    for dd in ddy.getObjectsByType(openstudio.IddObjectType('SizingPeriod:DesignDay')):
        model.addObject(dd.clone())
    return model
