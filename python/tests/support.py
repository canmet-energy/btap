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
from importlib import resources
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: PYTHON-OWNED fixtures (D-80 R2.1). The Python verification stack no longer
#: reaches into the gem tree for its test data: these are copies, and
#: ``tests/test_fixture_drift.py`` pins them byte-for-byte to the Ruby
#: originals until the gems retire at R6 (after which the Python copies are
#: authoritative and that cross-tree assertion goes away).
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# The seed model is RUNTIME-owned (package data, shipped in the wheel and in
# the gem under lib/), so it resolves out of the INSTALLED package rather than
# either tree; only the weather files and the JSON goldens are test fixtures.
FIXTURE_OSM = Path(str(resources.files("btap.modeling.hvac") / "data"
                       / "5ZoneNoHVAC.osm"))
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
    # The canmet-energyplus companion (R5, D-83): delegate to the engine's
    # own fail-closed probe. A BROKEN installed companion returns True —
    # available-but-corrupted must surface as the loud EngineError in the
    # actual test, never hide behind the cache probe below.
    try:
        if engine._companion_binary(engine.PINNED_VERSION) is not None:
            return True
    except engine.EngineError:
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


def oracle_goldens_dir():
    """The Leg-C goldens directory, with STRICT override semantics (D-80 R1):

    - ``BTAP_ORACLE_GOLDENS`` unset -> the COMMITTED goldens
      (verification/oracle/goldens — the frozen fast path).
    - set and valid -> exactly that directory (live-Leg-C mode: a fresh
      export from the pinned oracle).
    - set and INVALID -> raise at import/collection time, never fall back:
      a misspelled live-export path must not quietly test the frozen path.

    ``BTAP_GOLDENS_REQUIRED=1`` additionally makes a missing/unreadable
    committed directory a hard failure (the LEGACY_PIN_REQUIRED
    discipline) — used by the live orchestrator so the required run can
    never silently skip.
    """
    override = os.environ.get("BTAP_ORACLE_GOLDENS")
    if override:
        path = Path(override)
        if not (path.is_dir() and (path / "manifest.json").is_file()):
            raise RuntimeError(
                f"BTAP_ORACLE_GOLDENS={override} is not a goldens directory "
                "(missing dir or manifest.json) — refusing to fall back to "
                "the committed goldens; fix the path or unset the override")
        return path

    committed = REPO_ROOT / "verification" / "oracle" / "goldens"
    if os.environ.get("BTAP_GOLDENS_REQUIRED") == "1" and not (
            committed.is_dir() and (committed / "manifest.json").is_file()):
        raise RuntimeError(
            f"BTAP_GOLDENS_REQUIRED=1 but {committed} is missing or has no "
            "manifest.json — run verification/oracle/export_goldens.rb (or "
            "the goldens dispatch) to produce them")
    return committed
