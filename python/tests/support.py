"""Shared test plumbing for the Python port.

Skip discipline (the family's rule: a skipped gate is a green-but-vacuous
gate): SDK- and engine-dependent tests skip when the dependency is absent,
but ``BTAP_SDK_REQUIRED=1`` / ``BTAP_ENGINE_REQUIRED=1`` turn those skips
into FAILURES — CI sets them wherever the dependency is provisioned, so the
suite can never silently go vacuous there.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "btap-modeling" / "test" / "fixtures"
# The seed model is RUNTIME-owned now (shipped in the package and in the gem
# under lib/); only the weather files remain test fixtures.
FIXTURE_OSM = (REPO_ROOT / "btap-modeling" / "lib" / "btap_modeling" / "hvac"
               / "data" / "5ZoneNoHVAC.osm")
EPW = FIXTURES / "weather" / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"
DDY = FIXTURES / "weather" / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"

try:
    import openstudio  # noqa: F401
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

#: The devcontainer/CI-container EnergyPlus that ships beside the Ruby SDK —
#: the natural BTAP_ENERGYPLUS target where it exists.
CONTAINER_ENERGYPLUS = Path("/usr/local/openstudio-3.11.0/EnergyPlus/energyplus")


def needs_sdk(cls_or_fn):
    if HAVE_SDK:
        return cls_or_fn
    if os.environ.get("BTAP_SDK_REQUIRED") == "1":
        return _hard_fail(cls_or_fn,
                          "BTAP_SDK_REQUIRED=1 but the openstudio wheel is not importable")
    return unittest.skip("needs the openstudio wheel (pip install openstudio~=3.11.0)")(cls_or_fn)


def engine_available() -> bool:
    from btap.simulation import engine
    if os.environ.get("BTAP_ENERGYPLUS", "").strip():
        return True
    if CONTAINER_ENERGYPLUS.is_file():
        os.environ.setdefault("BTAP_ENERGYPLUS", str(CONTAINER_ENERGYPLUS))
        return True
    return engine._binary_in(engine.cache_dir(engine.PINNED_VERSION)) is not None


def needs_engine(cls_or_fn):
    if not HAVE_SDK:
        return needs_sdk(cls_or_fn)
    if engine_available():
        return cls_or_fn
    if os.environ.get("BTAP_ENGINE_REQUIRED") == "1":
        return _hard_fail(cls_or_fn,
                          "BTAP_ENGINE_REQUIRED=1 but no EnergyPlus engine is available")
    return unittest.skip("needs an EnergyPlus engine (set BTAP_ENERGYPLUS, or let the "
                         "provisioner download one)")(cls_or_fn)


def _hard_fail(cls_or_fn, message):
    """Replace the test(s) with a loud failure instead of a silent skip."""
    if isinstance(cls_or_fn, type):
        class Failing(unittest.TestCase):
            def test_required_dependency_missing(self):
                self.fail(message)
        Failing.__name__ = cls_or_fn.__name__
        return Failing

    def failing(self):
        self.fail(message)
    return failing


def load_fixture():

    from btap._sdk import load_model
    return load_model(FIXTURE_OSM)


def tbd_available() -> bool:
    """Is the pinned py-tbd engine importable (and not opted out)?"""
    if os.environ.get("OPENSTUDIO_ENVELOPE_DISABLE_TBD") == "1":
        return False
    try:
        import tbd  # noqa: F401
        return True
    except ImportError:
        return False


def needs_tbd(cls_or_fn):
    """The M7 engine-dependency gate, same discipline as needs_sdk/
    needs_engine: skips name the install, and BTAP_TBD_REQUIRED=1 turns the
    skip into a FAILURE (CI's verify job sets it — a skipped TBD gate is the
    green-but-vacuous failure the Ruby suite already documents)."""
    if not HAVE_SDK:
        return needs_sdk(cls_or_fn)
    if tbd_available():
        return cls_or_fn
    if os.environ.get("BTAP_TBD_REQUIRED") == "1":
        return _hard_fail(cls_or_fn,
                          "BTAP_TBD_REQUIRED=1 but the pinned py-tbd engine is not importable")
    return unittest.skip(
        "needs the pinned py-tbd engine (pip install 'btap[tbd]', or see "
        "docs/DEVELOPERS.md)")(cls_or_fn)
