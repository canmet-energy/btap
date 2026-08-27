"""The re-costable item ledger (port of btap-costing's hvac/ledger.rb —
itself a port of the legacy btap_items / cost_list_items model).

Quantification produces line items {id, quantity, mults, tags}; pricing
applies the cost database + regional factors. The same ledger can be
re-priced for any city or custom cost database.
"""

from __future__ import annotations

from btap._compat import ruby_round
from btap.costing.hvac.database import to_f


def _array(x):
    """Ruby Array(): Array(nil) == [], Array([a]) == [a], Array(x) == [x]."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


class Ledger:
    CATEGORIES = ('HEATING_COOLING', 'ZONAL', 'VENTILATION', 'DISTRIBUTION')

    def __init__(self):
        self.items: list[dict] = []

    def add(self, *, id, quantity, tags, material_mult=1.0, labour_mult=1.0,
            equipment_mult=1.0, note=None):
        """:param id: cost line-item id (str or int)
        :param quantity: numeric
        :param tags: category tags (see CATEGORIES) + free-form context tags
        """
        if to_f(quantity) == 0.0:
            return

        item = {'id': str(id), 'quantity': to_f(quantity),
                'material_mult': to_f(material_mult), 'labour_mult': to_f(labour_mult),
                'equipment_mult': to_f(equipment_mult),
                'tags': [str(t) for t in _array(tags)], 'note': note}
        # Ruby's .compact drops the nil-valued note
        self.items.append({k: v for k, v in item.items() if v is not None})

    def add_assembly(self, *, id_layers, layer_multipliers, base_quantity, tags, note=None):
        """Add every layer of an assembly row (hvac_vent_ahu-style id_layers x
        multipliers), scaled by a base quantity."""
        ids = [s.strip() for s in ('' if id_layers is None else str(id_layers)).split(',')]
        mults = [to_f(m.strip()) for m in
                 ('' if layer_multipliers is None else str(layer_multipliers)).split(',')]
        for i, id_ in enumerate(ids):
            mult = mults[i] if i < len(mults) else None  # Ruby zip pads with nil
            self.add(id=id_, quantity=to_f(base_quantity) * (1.0 if mult is None else mult),
                     tags=tags, note=note)

    def price(self, database, *, province_state, city):
        """Price the ledger for a location (port of cost_list_items):
        item_cost = (mat*matf/100*mat_mult + lab*instf/100*lab_mult +
        eq*eqf/100*eq_mult) * qty

        :return: {'total':, 'by_category': {cat: cost}, 'items': priced items}
        """
        by_category: dict[str, float] = {}
        priced = []
        for item in self.items:
            record = database.cost_record(item['id'])
            mat_f, inst_f, eq_f = database.regional_factors(province_state, city, item['id'])
            cost = (record['materialOpCost'] * (mat_f / 100.0) * item['material_mult'] +
                    record['laborOpCost'] * (inst_f / 100.0) * item['labour_mult'] +
                    record['equipmentOpCost'] * (eq_f / 100.0) * item['equipment_mult']) * \
                item['quantity']
            for tag in item['tags']:
                if tag in self.CATEGORIES:
                    by_category[tag] = by_category.get(tag, 0.0) + cost
            priced.append({**item, 'cost': ruby_round(cost, 2)})
        return {'province_state': province_state, 'city': city,
                'total': ruby_round(sum(i['cost'] for i in priced), 2),
                'by_category': {k: ruby_round(v, 2) for k, v in by_category.items()},
                'items': priced}
