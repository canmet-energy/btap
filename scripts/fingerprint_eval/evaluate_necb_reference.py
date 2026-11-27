"""#256 ground truth: the NECB reference builder records which catalogue row
(and config) it built on each zone. Fingerprint the reference model and check
the fingerprint identifies that row.

    PYTHONPATH=$SDK/Python:src:. python scripts/fingerprint_eval/evaluate_necb_reference.py \
        fp.json "models/*.osm"
"""

import collections
import glob
import json
import os
import sys
import time
import warnings

import openstudio

from btap.codes.necb.hvac.reference import reference_hvac
from btap.modeling import build_system
from btap.stock import fingerprint as fpm
from tests.necb.hvac_helpers import load_fixture, sorted_zones

warnings.simplefilter("ignore")


rep = {k: [fpm.Component.from_dict(c) for c in v] for k, v in json.load(open(sys.argv[1])).items()}
variant_sig = {}


def expected_signature(row, config):
    key = (row, json.dumps(config or {}, sort_keys=True))
    if key not in variant_sig:
        m = load_fixture()
        build_system(m, row, sorted_zones(m), config=config or None)
        variant_sig[key] = fpm.signature(fpm.model_components(m)[0][1])
    return variant_sig[key]


t0 = time.time()
tally = collections.Counter()
failures = []
per_row = collections.Counter()
skipped = []
for path in sorted(glob.glob(sys.argv[2])):
    m = openstudio.osversion.VersionTranslator().loadModel(openstudio.toPath(path)).get()
    try:
        result = reference_hvac(m, code="necb2020")
    except Exception as e:
        skipped.append((os.path.basename(path), f"{type(e).__name__}: {e}"[:140]))
        continue
    ref = result.model
    comps = dict(fpm.model_components(ref))
    for a in result.assignments:
        if not a.catalog_name or (a.action and "copy" in str(a.action)):
            tally["not built by the reference (" + str(a.action) + ")"] += len(a.zones)
            continue
        want = expected_signature(a.catalog_name, a.config)
        for zone in a.zones:
            zc = comps.get(zone)
            if zc is None:
                tally["zone missing"] += 1
                continue
            sig = fpm.signature(zc)
            e = fpm.explain(zc, rep)
            per_row[a.catalog_name] += 1
            if sig == want:
                tally["fingerprint == the built row"] += 1
                if e["outcome"] == "match" and (a.catalog_name in e["systems"] or a.config):
                    tally["  ...and explain names it"] += 1
                else:
                    tally["  ...but explain does NOT name it"] += 1
                    failures.append(
                        (
                            os.path.basename(path)[:30],
                            zone[:24],
                            a.catalog_name,
                            a.config,
                            e["outcome"],
                            e["systems"][:2],
                        )
                    )
            else:
                tally["fingerprint DIFFERS from the built row"] += 1
                extra = sorted(set(map(str, sig)) - set(map(str, want)))
                missing = sorted(set(map(str, want)) - set(map(str, sig)))
                failures.append(
                    (
                        os.path.basename(path)[:30],
                        zone[:24],
                        a.catalog_name,
                        a.config,
                        e["outcome"],
                        e["systems"][:2],
                        "model_has",
                        extra[:2],
                        "row_has",
                        missing[:2],
                    )
                )
print(
    json.dumps(
        {
            "tally": dict(tally),
            "rows_exercised": dict(per_row),
            "skipped_models": skipped,
            "seconds": round(time.time() - t0),
            "failures": failures[:12],
        },
        indent=1,
        default=str,
    )
)
