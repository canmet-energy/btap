"""#256 evaluation: self-match, leave-one-row-out, metamorphic pairs."""
import json, sys, warnings, collections, time
warnings.simplefilter("ignore")
import btap; assert "wt-fp" in btap.__file__, btap.__file__
import openstudio
from btap.modeling import build_system
from btap.modeling.hvac import catalog
from btap.stock import fingerprint as fpm
from tests.necb.hvac_helpers import load_fixture, sorted_zones

def scrub(m):
    for i, l in enumerate(m.getAirLoopHVACs()): l.setName(f'Air System {i+1}')
    for i, l in enumerate(m.getPlantLoops()): l.setName(f'Plant {i+1}')

def built(row, zones=None, config=None, mutate=None):
    m = load_fixture(); zs = sorted_zones(m)
    build_system(m, row, zs if zones is None else zs[:zones], config=config)
    if mutate: mutate(m)
    scrub(m)
    return m

t0 = time.time()
cat, inconsistent, errors = {}, [], {}
for r in catalog.rows():
    try:
        comps = fpm.model_components(built(r['id']))
    except Exception as e:
        errors[r['id']] = f"{type(e).__name__}: {e}"[:160]; continue
    sigs = {fpm.signature(c) for _, c in comps}
    if len(sigs) > 1: inconsistent.append(r['id'])
    cat[r['id']] = comps     # every zone
rep = {k: v[0][1] for k, v in cat.items()}
classes = collections.defaultdict(list)
for rid, comps in rep.items(): classes[fpm.signature(comps)].append(rid)
class_of = {rid: sorted(v) for v in classes.values() for rid in v}

# 1. self: every zone of every row
self_ok = self_bad = 0; self_fail = []
for rid, zones in cat.items():
    for zname, comps in zones:
        e = fpm.explain(comps, rep)
        if e['outcome'] == 'match' and rid in e['systems']: self_ok += 1
        else: self_bad += 1; self_fail.append((rid, zname, e['outcome'], e['systems'][:3]))

# 2. leave-one-row-out
loo = collections.Counter(); loo_bad = []; loo_sims = []; loo_partial = []
for rid in rep:
    rest = {k: v for k, v in rep.items() if k != rid}
    e = fpm.explain(rep[rid], rest)
    siblings = [s for s in class_of[rid] if s != rid]
    if siblings:
        ok = e['outcome'] == 'match' and set(e['systems']) == set(siblings)
        loo['sibling match' if ok else 'sibling WRONG'] += 1
        if not ok: loo_bad.append((rid, e['outcome'], e['systems'][:3]))
    else:
        loo[e['outcome']] += 1
        if e['outcome'] == 'match': loo_bad.append((rid, 'MATCHED A DIFFERENT ROW', e['systems'][:3]))
        if e['outcome'] == 'none': loo_sims.append(e['similarity'])
        if e['outcome'] in ('partial', 'composed'): loo_partial.append((rid, e['outcome'], e['systems'][:3], len(e.get('uncovered') or [])))

# 3. metamorphic
def add_exhaust(m):
    for z in m.getThermalZones():
        openstudio.model.FanZoneExhaust(m).addToThermalZone(z)
def scheduled_spm(m):
    for pl in m.getPlantLoops():
        node = pl.supplyOutletNode()
        for spm in node.setpointManagers():
            if opt_reset(spm):
                spm.remove()
                s = openstudio.model.ScheduleConstant(m); s.setValue(82.0)
                openstudio.model.SetpointManagerScheduled(m, s).addToNode(node)
def opt_reset(spm):
    return spm.to_SetpointManagerOutdoorAirReset().is_initialized()
SAMPLE = ['psz-gas-hwbb-gasboiler', 'vav-hw-hwbb-gasboiler-scrollchiller', 'mau-fc4-gas-gasboiler-scrollchiller',
          'mau-fc2-gas-gasboiler-scrollchiller', 'bb-hwbb-gasboiler', 'uh-hw-gasboiler', 'ptac-hwbb-gasboiler',
          'wshp-gasboiler', 'doas-vrf-elec', 'bb-hwbb-awhp-gasbu', 'doas-acb-elec-elecbb-acscrollchiller',
          'psz-ashp-elecsupp-elecbb']
meta = collections.defaultdict(list)
for rid in SAMPLE:
    for label, kw in (('one zone', dict(zones=1)), ('exhaust fans', dict(mutate=add_exhaust)),
                      ('scheduled plant setpoint', dict(mutate=scheduled_spm))):
        comps = fpm.model_components(built(rid, **kw))[0][1]
        e = fpm.explain(comps, rep)
        meta[label].append((rid, e['outcome'] == 'match' and rid in e['systems'], e['outcome'], e['systems'][:2]))
    # discriminating: the boiler fuel
    cfg = None
    row = catalog.resolve(rid)
    if row.get('needs_boiler') and row.get('hw_source', 'boiler') == 'boiler' and row.get('family') != 'composite':
        try:
            comps = fpm.model_components(built(rid, config={'boiler_fuel': 'Electricity'}))[0][1]
            e = fpm.explain(comps, rep)
            meta['electric boiler (must CHANGE)'].append((rid, not (rid in e['systems'] and e['outcome'] == 'match'), e['outcome'], e['systems'][:2]))
        except Exception as ex:
            meta['electric boiler (must CHANGE)'].append((rid, None, type(ex).__name__, []))

out = {"rows": len(rep), "errors": errors, "rows_whose_zones_differ": inconsistent, "classes": len(classes),
       "multi_member_classes": sorted(sorted(v) for v in classes.values() if len(v) > 1),
       "self": {"ok": self_ok, "bad": self_bad, "first_failures": self_fail[:8]},
       "leave_one_out": dict(loo), "loo_problems": loo_bad[:10],
       "loo_none_similarity": sorted(loo_sims)[-10:] if loo_sims else [], "loo_partial_examples": loo_partial[:6],
       "metamorphic": {k: {"passed": sum(1 for x in v if x[1]), "of": len(v), "failures": [x for x in v if not x[1]]} for k, v in meta.items()},
       "uncast_types": sorted(fpm.UNCAST), "seconds": round(time.time() - t0)}
print(json.dumps(out, indent=1))
json.dump({k: [c.as_dict() for c in v] for k, v in rep.items()}, open(sys.argv[1], "w"))
