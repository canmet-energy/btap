"""btap-energyplus — the pinned EnergyPlus engine as a per-platform wheel.

The companion package of ``btap`` (canmet-energy/btap, decision
D-83): carries the pinned EnergyPlus release as package data so
``pip install btap`` needs no engine thought at all. Built by
``packaging/pypi/energyplus/build_wheel.py`` from the sha256-verified
official NREL release asset, pruned of the PythonPlugin runtime only
(``python_lib``/``pyenergyplus`` — btap drives EnergyPlus purely as a
subprocess); ``PROVENANCE.json`` records the source asset, its verified
digest, and every removed and kept file. Runtime integrity is pip's own
RECORD hashing.

Consumed by ``btap.simulation.engine``'s companion rung — fail-closed:
once this package imports, any defect raises there rather than falling
through to a cache or a download.
"""

import json
import os
import stat
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

with open(_HERE / "PROVENANCE.json", encoding="utf-8") as _handle:
    PROVENANCE = json.load(_handle)

#: The EnergyPlus release this wheel carries (always the full three-part
#: engine version; the DISTRIBUTION version adds a fourth packaging
#: segment — see PROVENANCE["distribution_version"]).
ENERGYPLUS_VERSION = PROVENANCE["energyplus_version"]
BUILD_SHA = PROVENANCE["energyplus_build_sha"]


def binary_path():
    """The bundled energyplus executable, executable-bit guaranteed.

    Wheels are zips and pip's restoration of POSIX mode bits has
    historical sharp edges, so the exec bit is restored here if missing —
    the runtime backstop behind the build-time external_attr setting.
    """
    name = "energyplus.exe" if sys.platform == "win32" else "energyplus"
    binary = _HERE / "payload" / name
    if not binary.is_file():
        raise FileNotFoundError(
            f"btap-energyplus payload is missing {binary} — the install is "
            "corrupted; reinstall with pip install --force-reinstall "
            "btap-energyplus")
    if sys.platform != "win32" and not os.access(binary, os.X_OK):
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                     | stat.S_IXOTH)
    return binary
