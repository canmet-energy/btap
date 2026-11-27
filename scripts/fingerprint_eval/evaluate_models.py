import json, sys, warnings, glob, os, collections
warnings.simplefilter("ignore")
import btap; assert "wt-fp" in btap.__file__
import openstudio
from btap.stock import fingerprint as fpm
from btap.stock.hvac import hvac_section
from btap.stock.identify import identify_candidates
rep = {k: [fpm.Component.from_dict(c) for c in v] for k, v in json.load(open(sys.argv[1])).items()}
by_sig = {}
for path in sorted(glob.glob(sys.argv[2])):
    m = openstudio.osversion.VersionTranslator().loadModel(openstudio.toPath(path))
    if not m.is_initialized(): continue
    m = m.get()
    for i, l in enumerate(m.getAirLoopHVACs()): l.setName(f'Air System {i+1}')
    for i, l in enumerate(m.getPlantLoops()): l.setName(f'Plant {i+1}')
    old = {}
    for g in hvac_section(m, audit=None)['zone_groups']:
        c = identify_candidates(g, limit=1)
        for z in g.get('zones') or []: old[z] = c[0]['system'] if c else None
    for zname, comps in fpm.model_components(m):
        sig = fpm.signature(comps)
        d = by_sig.setdefault(sig, {"zones": 0, "models": set(), "old": collections.Counter(), "comps": comps})
        d["zones"] += 1; d["models"].add(os.path.basename(path)[:-4]); d["old"][old.get(zname)] += 1
out = collections.Counter(); outz = collections.Counter(); detail = []
for sig, d in by_sig.items():
    e = fpm.explain(d["comps"], rep)
    out[e["outcome"]] += 1; outz[e["outcome"]] += d["zones"]
    detail.append({"zones": d["zones"], "models": len(d["models"]), "outcome": e["outcome"], "systems": e["systems"][:3],
                   "similarity": e.get("similarity"), "uncovered": e.get("uncovered"), "old_top": d["old"].most_common(1)[0][0],
                   "nearest_differences": e.get("nearest_differences", [])[:3],
                   "control_differences": e.get("control_differences")})
detail.sort(key=lambda r: -r["zones"])
print(json.dumps({"distinct_signatures": len(by_sig), "outcomes_by_signature": dict(out), "outcomes_by_zone": dict(outz),
                  "uncast": sorted(fpm.UNCAST)}, indent=1))
json.dump(detail, open(sys.argv[3], "w"), indent=1, default=list)
