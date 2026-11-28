"""#256 independent corpus: NREL's OpenStudio-resources simulation tests,
built with the OpenStudio SDK directly (not openstudio-standards, whose
children our catalogue's systems are), each labelled by what it exercises.
The ten `baseline_sysNN` tests are ASHRAE 90.1 Appendix G Systems 1-10 from
the SDK's own `addSystemTypeN`.

1. git clone --depth 1 https://github.com/NREL/OpenStudio-resources.git <dir>
2. build: for each test, in its own directory holding an `in.osw` that names
   a weather file (the scripts read it for design days), run
   `PYTHONPATH=$SDK/Python:<dir>/model/simulationtests python <dir>/model/simulationtests/<test>.py`;
   it saves `in.osm` there
3. PYTHONPATH=$SDK/Python:src:. python scripts/fingerprint_eval/evaluate_openstudio_resources.py \\
       fp.json "<runs>/*/in.osm" detail.json
"""

import collections
import glob
import json
import os
import sys
import warnings

import openstudio

from btap.stock import fingerprint as fpm

warnings.simplefilter("ignore")

rep = {k: [fpm.Component.from_dict(c) for c in v] for k, v in json.load(open(sys.argv[1])).items()}
out = {}
for path in sorted(glob.glob(sys.argv[2])):
    name = os.path.basename(os.path.dirname(path))
    model = openstudio.osversion.VersionTranslator().loadModel(openstudio.toPath(path)).get()
    groups = collections.OrderedDict()
    for zone, comps in fpm.model_components(model):
        groups.setdefault(fpm.signature(comps), [zone, 0, comps])[1] += 1
    rows = []
    for _zone, n, comps in groups.values():
        e = fpm.explain(comps, rep)
        rows.append(
            {
                "zones": n,
                "outcome": e["outcome"],
                "systems": e["systems"][:3],
                "similarity": e.get("similarity"),
                "identity": [sorted(c.identity) for c in comps],
                "uncovered": [u["identity"] for u in e.get("uncovered") or []],
                "diff": e.get("nearest_differences", [])[:3],
                "notes": e.get("notes"),
            }
        )
    out[name] = rows
json.dump(out, open(sys.argv[3], "w"), indent=1)
for name, rows in out.items():
    for r in rows:
        if r["outcome"] != "unserved":
            print(f"{name:30} {r['zones']:2}z {r['outcome']:8} {r['systems'][:2]}")
