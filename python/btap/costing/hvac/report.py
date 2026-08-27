"""The HVAC costing facade (port of btap-costing's hvac/report.rb).

Requires a SIZED model (capacities/flows are read from the objects' hard or
autosized values)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from btap._compat import ruby_round
from btap.audit import AuditLog
from btap.costing.hvac.database import Database
from btap.costing.hvac.ledger import Ledger
from btap.costing.hvac.quantify_equipment import EquipmentQuantifier
from btap.costing.hvac.ventilation import VentilationQuantifier
from btap.modeling.hvac import catalog, classify


@dataclass
class Report:
    """Ruby Struct.new(..., keyword_init: true) — constructed by keyword."""
    total: float = None
    by_category: dict = None
    items: list = field(default=None)
    warnings: list = field(default=None)
    city: str = None
    province_state: str = None
    audit: object = None


def _array(x):
    """Ruby Array(): Array(nil) == [], Array([a]) == [a], Array(x) == [x]."""
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def cost(model, systems=None, city=None, province_state=None, costs_csv=None,
         mech_room_name=None, audit=None):
    """:param model: openstudio.model.Model
    :param systems: builder Result list — the highest-fidelity mapping of air
        loops to families for AHU/distribution costing. OPTIONAL: any loop not
        covered (or any general OSM with systems omitted) is classified
        automatically — exactly when its name is recognizable (gem catalog /
        legacy sys_N pipe names), structurally otherwise (guess reported as a
        warning).
    :param city: cost location; None => nearest city to the model's weather site
    :param province_state: like city
    :param costs_csv: inject licensed cost values (see data/costing/README.md)
    :param mech_room_name: pin the mechanical-room space by name for the
        geometry-derived items (utility runs, flues, header piping); None =>
        legacy election (Electrical/Mechanical space type, else lowest storey
        closest to centre)
    :return: Report
    """
    audit = audit if audit is not None else AuditLog()
    database = Database(costs_csv=costs_csv)
    ledger = Ledger()

    if city is None or province_state is None:
        site = model.getSite()
        location = database.closest_location(site.latitude(), site.longitude())
        if city is None:
            city = location['city']
        if province_state is None:
            province_state = location['province_state']
        audit.decision('costing', 'cost location resolved from site coordinates',
                       inputs={'latitude': ruby_round(site.latitude(), 3),
                               'longitude': ruby_round(site.longitude(), 3)},
                       value=f"{city}, {province_state}")

    equipment = EquipmentQuantifier(database, ledger, mech_room_name=mech_room_name,
                                    audit=audit)
    equipment.quantify_plant(model)
    equipment.quantify_zonal(model)

    loop_families = {}
    for result in _array(systems):
        family = catalog.resolve(result.system_name)['family'] \
            if hasattr(result, 'system_name') else None
        for air_loop in _array(getattr(result, 'air_loops', None)):
            loop_families[air_loop.nameString()] = family
            audit.decision('costing_classification', 'air loop family from build result',
                           target=air_loop.nameString(), value=family)
    classifier_warnings = classify_unmapped_loops(model, loop_families, audit)

    ventilation = VentilationQuantifier(database, ledger, audit=audit)
    ventilation.quantify(model, loop_families, mech_room_name=mech_room_name)

    priced = ledger.price(database, province_state=province_state, city=city)
    warnings = list(dict.fromkeys(database.warnings + equipment.warnings +
                                  classifier_warnings + ventilation.warnings))
    for w in warnings:
        audit.warn('costing', w)
    audit.info('costing', 'costing complete',
               inputs={'items': len(priced['items']), 'city': city},
               value=', '.join(f"{k}={ruby_round(v)}"
                               for k, v in priced['by_category'].items()))
    return Report(total=priced['total'],
                  by_category=priced['by_category'],
                  items=priced['items'],
                  warnings=warnings,
                  city=city, province_state=province_state, audit=audit)


# Structural-guess -> costing family (AHU assembly class). Exact recognition
# (gem catalog names, legacy sys_N pipe names) already yields a real family.
STRUCTURAL_FAMILY = {
    'multizone_vav': 'vav_reheat',       # central VAV -> sys6 assembly class
    'multizone_cv': 'psz',               # central CV w/ reheat -> packaged class
    'packaged_single_zone': 'psz',       # single-zone packaged -> sys3/4 class
    'central_doas_or_cv': 'doas',        # multi-zone CV ventilation -> sys1 class
}


def classify_unmapped_loops(model, loop_families, audit=None):
    """Costing works on ANY OSM: air loops not covered by build results are
    classified (exactly by recognized names, else structurally) so their
    AHU/distribution can be costed. Guessed families are reported as warnings
    — approximations are never silent. Loops the classifier cannot place
    remain uncosted with the standard foreign-loop warning from the
    ventilation quantifier.

    Port note: Ruby told legacy-pipe-name mappings (String) apart from
    structural guesses (Symbol) by class; the Python classify port emits str
    for both, so the discriminator is membership in STRUCTURAL_FAMILY (the
    two value sets are disjoint).
    """
    unmapped = [al for al in model.getAirLoopHVACs()
                if al.nameString() not in loop_families]
    if not unmapped:
        return []

    warnings = []
    facts = classify.characterize(model)
    for group in facts['zone_groups']:
        name = group['air_loop']
        if name is None or name in loop_families:
            continue

        guess = group['family_guess']
        if group['family'] is not None:
            loop_families[name] = group['family']
            if audit is not None:
                audit.decision('costing_classification',
                               'air loop family recognized from catalog name',
                               target=name, value=group['family'],
                               evidence=next((e for e in group['evidence']
                                              if re.search(r'catalog', e)), None))
        elif isinstance(guess, str) and guess not in STRUCTURAL_FAMILY:
            # exact mapping (legacy sys_N pipe names) — a real family, not a guess
            loop_families[name] = guess
            if audit is not None:
                audit.decision('costing_classification',
                               'air loop family mapped from legacy NECB pipe name',
                               target=name, value=guess)
        elif (family := STRUCTURAL_FAMILY.get(guess)) is not None:
            loop_families[name] = family
            if audit is not None:
                audit.decision('costing_classification',
                               'air loop family guessed structurally (approximation)',
                               target=name, inputs={'structural_guess': guess},
                               value=family,
                               evidence='; '.join(group['evidence'][-2:]))
            warnings.append(f"air loop '{name}': family '{family}' guessed structurally "
                            f"({guess}) — AHU assembly class is an approximation")
    return warnings
