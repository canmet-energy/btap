"""Manifest-driven ventilation & distribution costing (port of btap-costing's
hvac/ventilation.rb — the re-architected legacy "(b)-layer"): instead of
parsing SYS_n from air-loop names, the AHU assembly class comes from the
FAMILY of the gem-built system serving the loop, and coil types are read from
the loop's actual components.

Ledgered domains (tag VENTILATION — line-item parity with the legacy ledger):
- AHU assemblies: every hvac_vent_ahu id_layer x id_quant, scaled by the exact
  legacy get_ahu_mult quantity (L/s buckets, ceil unit count, re-select,
  flow/bucket scale)
- air-loop heating/cooling coil equipment (Coils/ElecHeat/FurnaceGas/ashp +
  DX condensing unit & refrigerant piping, gas-burner AHU adjustment)
- terminal mixing boxes + per-terminal hydronic piping and electrical runs
  sized by the storey-centroid-to-roof-centroid Manhattan distance (legacy
  vav_cost / reheat_coil_costing / vent_box_elec_cost)

Geometry-derived distribution (tag DISTRIBUTION — legacy reports these as
totals only, never ledgered): mech-room-to-roof utility lines, central trunk
duct, floor trunk ducts, per-zone duct distribution.
"""

from __future__ import annotations

import math

from btap._compat import opt, ruby_round, ruby_str, sorted_by_name
from btap.costing.hvac import geometry
from btap.costing.hvac.database import to_f, to_i, to_s
from btap.modeling.hvac.components import coils


class VentilationQuantifier:
    # family -> legacy AHU Sys_type equivalent (None = no central AHU to cost;
    # fan_coils MAU is skipped exactly as legacy skips sys_type 2 ventilation).
    FAMILY_SYS_TYPE = {
        'mau_ptac': 1, 'doas': 1, 'doas_pthp': 1,
        'ecm_ashp_baseboard': 1, 'ecm_doas_vrf': 1, 'ecm_hp_fancoils': 1,
        'psz': 3, 'furnace': 3,
        'vav_reheat': 6,
        'fan_coils': None,
        # no AHU/media cost data exists (legacy never costed evap);
        # ducts/diffusers still costed
        'evap_cooler': 'distribution_only',
    }

    # single-run supply duct systems (legacy: x1 for sys 1/4 — no return duct)
    SINGLE_RUN_SYS_TYPES = (1, 4)

    RT_ROOF_DIST_FT = 32.8084  # legacy: 10 m allowance per rooftop unit

    def __init__(self, database, ledger, audit=None):
        self._db = database
        self._ledger = ledger
        self._audit = audit
        self.warnings: list[str] = []

    def quantify(self, model, loop_families, mech_room_name=None):
        """:param model: openstudio.model.Model (sized)
        :param loop_families: {air-loop name: gem family} (from build results /
            catalog); loops not in the map produce a warning (foreign
            ventilation)
        :param mech_room_name: pin the mechanical room space explicitly
        """
        roof_cent = geometry.highest_roof_centroid(model)
        mech = geometry.mech_room(model, mech_room_name=mech_room_name)
        if roof_cent is None:
            self.warnings.append(
                'no outdoor roof found — geometry-based ventilation runs not costed')

        heat_line_counts: dict[str, int] = {'Gas': 0, 'HW': 0}
        cool_line_counts: dict[str, int] = {'CHW': 0}
        rooftop_units = 0
        total_flow_m3s = 0.0
        sys_1_4 = True
        hvac_floors: dict[str, dict] = {}

        for air_loop in sorted_by_name(model.getAirLoopHVACs()):
            family = loop_families.get(air_loop.nameString())
            if family is None:
                self.warnings.append(
                    f"air loop '{air_loop.nameString()}' was not built by this gem "
                    "— ventilation not costed (plant/zonal still costed)")
                continue
            sys_type = self.FAMILY_SYS_TYPE.get(family)
            if sys_type is None:
                self.warnings.append(
                    f"family '{family}' ventilation ({air_loop.nameString()}) is not "
                    "AHU-costed (matches legacy sys-2/none handling)")
                continue
            flow = self.flow_m3s(air_loop)
            if flow is None:
                continue

            total_flow_m3s += flow
            if sys_type == 'distribution_only':
                self.warnings.append(
                    f"family '{family}' ({air_loop.nameString()}): no unit-cost data "
                    "for the air handler/media exists (legacy never costed it "
                    "either); distribution costed")
                sys_type_i = 3
            else:
                sys_type_i = sys_type
                units = self.cost_ahu(air_loop, sys_type_i, flow)
                rooftop_units += units
                self.cost_airloop_coils(air_loop, sys_type_i, units, flow)
                htg, clg = self.coil_keys(air_loop)
                if htg == 'Gas':
                    heat_line_counts['Gas'] += 1
                if htg == 'HW':
                    heat_line_counts['HW'] += 1
                if clg == 'CHW':
                    cool_line_counts['CHW'] += 1
            if sys_type_i not in self.SINGLE_RUN_SYS_TYPES:
                sys_1_4 = False
            self.cost_terminals(air_loop, roof_cent)
            self.cost_hrv(air_loop)
            self.collect_hvac_floors(hvac_floors, air_loop, sys_type_i)

        if mech is not None and roof_cent is not None:
            self.cost_mech_to_roof(mech, roof_cent, heat_line_counts,
                                   cool_line_counts, rooftop_units)
        if roof_cent is not None and total_flow_m3s > 0:
            self.cost_trunk_duct(model, total_flow_m3s, roof_cent, sys_1_4)
        if roof_cent is not None:
            self.cost_floor_trunk_ducts(hvac_floors, roof_cent)
        self.cost_zone_distribution(hvac_floors)

    # ---------- shared lookups ----------

    def flow_m3s(self, air_loop):
        flow = air_loop.designSupplyAirFlowRate()
        if not flow.is_initialized():
            flow = air_loop.autosizedDesignSupplyAirFlowRate()
        if not flow.is_initialized():
            self.warnings.append(
                f"no design supply air flow for {air_loop.nameString()} "
                "(model not sized?) — ventilation not costed")
            return None
        return flow.get()

    def coil_keys(self, air_loop):
        """Staged NECB reference systems hide their coils inside an
        AirLoopHVACUnitarySystem — coils.supply_components descends into it. A
        staged coil costs as the same equipment as its single-speed sibling
        (a two-stage furnace is still a furnace); capacity comes from the top
        stage, which is the unit's total."""
        htg = 'none'
        clg = 'none'
        for comp in coils.supply_components(air_loop):
            if comp.to_CoilHeatingGas().is_initialized() or \
                    comp.to_CoilHeatingGasMultiStage().is_initialized():
                htg = 'Gas'
            if comp.to_CoilHeatingElectric().is_initialized() and htg == 'none':
                htg = 'elec'
            if comp.to_CoilHeatingWater().is_initialized():
                htg = 'HW'
            if comp.to_CoilHeatingDXSingleSpeed().is_initialized() or \
                    comp.to_CoilHeatingDXMultiSpeed().is_initialized():
                htg = 'HP-e'
            if comp.to_CoilHeatingDXVariableSpeed().is_initialized():
                htg = 'CCASHP-e'
            if comp.to_CoilCoolingDXSingleSpeed().is_initialized() or \
                    comp.to_CoilCoolingDXTwoSpeed().is_initialized() or \
                    comp.to_CoilCoolingDXMultiSpeed().is_initialized():
                clg = 'DX'
            if comp.to_CoilCoolingWater().is_initialized():
                clg = 'CHW'
            if comp.to_CoilCoolingDXVariableSpeed().is_initialized():
                clg = 'CCASHP'
        return (htg, clg)

    def pick_material(self, lookup, size, context, unit=None, exact_size=False):
        """Case-insensitive materials_hvac selection: prefer exact Size, else
        next-largest, else the largest row. Returns (row, unit_count)
        (count > 1 when size exceeds the largest available — legacy
        get_vent_system_mult behavior) or None with a warning."""
        rows = [r for r in self._db.materials_hvac
                if to_s(r.get('Material')).lower() == str(lookup).lower()]
        if unit is not None:
            rows = [r for r in rows if to_s(r.get('unit')).lower() == str(unit).lower()]
        if not rows:
            self.warnings.append(
                f"no materials_hvac entry '{lookup}' ({context}) — item not costed")
            return None
        if size is None:
            return (rows[0], 1.0)

        exact = [r for r in rows if to_f(r.get('Size')) == to_f(size)]
        if exact:
            return (exact[0], 1.0)
        if exact_size:  # exact requested but absent: first row
            return (rows[0], 1.0)

        candidates = [r for r in rows if to_f(r.get('Size')) >= to_f(size)]
        if candidates:
            return (min(candidates, key=lambda r: to_f(r.get('Size'))), 1.0)

        largest = max(rows, key=lambda r: to_f(r.get('Size')))
        max_size = to_f(largest.get('Size'))
        if max_size == 0.0:
            return (largest, 1.0)

        # legacy get_vent_system_mult: N units of a smaller row that covers size/N
        units = float(math.ceil(to_f(size) / max_size))
        per_unit = to_f(size) / units
        covering = [r for r in rows if to_f(r.get('Size')) >= per_unit]
        row = min(covering, key=lambda r: to_f(r.get('Size'))) if covering else largest
        return (row, units)

    def add_item(self, lookup, size, quantity, tags, context, unit=None, exact_size=False):
        picked = self.pick_material(lookup, size, context, unit=unit, exact_size=exact_size)
        if picked is None:
            return 0.0

        row, units = picked
        self._ledger.add(
            id=row['id'], quantity=units * quantity, tags=tags,
            material_mult=1.0 if to_f(row.get('material_mult')) == 0.0 else to_f(row.get('material_mult')),
            labour_mult=1.0 if to_f(row.get('labour_mult')) == 0.0 else to_f(row.get('labour_mult')),
            note=context)
        if self._audit is not None:
            self._audit.decision(
                'costing_distribution' if 'DISTRIBUTION' in tags else 'costing_ventilation',
                context,
                inputs={'lookup': lookup,
                        'size': ruby_round(size, 2) if isinstance(size, (int, float)) else size},
                value=f"item {row['id']} x {ruby_str(ruby_round(units * quantity, 3))}",
                evidence=to_s(row.get('description'))[0:70])
        return units

    def mech_table(self, name):
        component = next((c for c in self._db.mech_sizing if c.get('component') == name),
                         None)
        return component.get('table') if component is not None else None

    # ---------- AHU assembly ----------

    def cost_ahu(self, air_loop, sys_type, flow_m3s):
        """Exact legacy get_ahu_mult algorithm: number of units =
        ceil(L/s / largest bucket); re-select the smallest bucket >=
        L/s-per-unit; scale layers by flow/bucket. Every id_layer is costed
        with its id_quant (legacy vent_assembly_cost) — the pipe/valve/controls
        layers ARE the AHU hydronic valve-piping items.

        :return: int — the number of rooftop units
        """
        lps = flow_m3s * 1000.0  # Supply_air buckets are L/s
        htg, clg = self.coil_keys(air_loop)
        rows = [r for r in self._db.ahu_assemblies
                if to_i(r.get('Sys_type')) == sys_type
                and r.get('Htg') == htg and r.get('Clg') == clg]
        if not rows:
            self.warnings.append(
                f"no AHU assembly for sys_type {sys_type} htg={htg} clg={clg} "
                f"({air_loop.nameString()}) — AHU not costed")
            return 1
        max_bucket = max(to_f(r.get('Supply_air')) for r in rows)
        ratio = lps / max_bucket
        unit_count = int(ratio) + 1 if ratio > int(ratio) else ruby_round(ratio)
        if unit_count < 1:
            unit_count = 1
        per_unit_lps = lps / unit_count
        covering = [r for r in rows if to_f(r.get('Supply_air')) >= per_unit_lps]
        row = min(covering, key=lambda r: to_f(r.get('Supply_air'))) if covering \
            else max(rows, key=lambda r: to_f(r.get('Supply_air')))
        base_quantity = unit_count * (per_unit_lps / to_f(row.get('Supply_air')))
        if self._audit is not None:
            self._audit.decision(
                'costing_ventilation', 'AHU assembly selected (legacy get_ahu_mult rule)',
                target=air_loop.nameString(),
                inputs={'flow_lps': ruby_round(lps, 1), 'sys_type': sys_type,
                        'htg': htg, 'clg': clg, 'unit_count': unit_count,
                        'bucket_lps': to_f(row.get('Supply_air'))},
                value=(f"assembly scaled to {ruby_str(ruby_round(base_quantity, 3))} "
                       f"({unit_count} unit(s) x {ruby_round(per_unit_lps, 0)}/"
                       f"{to_s(row.get('Supply_air'))} L/s)"),
                article='hvac_vent_ahu (L/s buckets, ceil units, re-select)')

        # id_layers reference materials_hvac material_id -> map to the cost
        # line-item id
        note = (f"AHU {air_loop.nameString()} ({ruby_round(lps * 2.11888)} cfm, "
                f"sys{sys_type} {htg}/{clg})")
        ids = [s.strip() for s in to_s(row.get('id_layers')).split(',')]
        mults = [to_f(m.strip()) for m in
                 to_s(row.get('Id_layers_quantity_multipliers')).split(',')]
        for i, material_id in enumerate(ids):
            mult = mults[i] if i < len(mults) else None  # Ruby zip pads with nil
            material = next((r for r in self._db.materials_hvac
                             if to_s(r.get('material_id')) == material_id), None)
            if material is None:
                self.warnings.append(
                    f"AHU layer material_id {material_id} not in materials_hvac "
                    f"— layer not costed ({note})")
                continue
            self._ledger.add(
                id=material['id'],
                quantity=base_quantity * (1.0 if mult is None else mult),
                tags=['VENTILATION'],
                material_mult=1.0 if to_f(material.get('material_mult')) == 0.0 else to_f(material.get('material_mult')),
                labour_mult=1.0 if to_f(material.get('labour_mult')) == 0.0 else to_f(material.get('labour_mult')),
                note=f"{note} [{to_s(material.get('Material'))}]")
        return unit_count

    # ---------- air-loop heating/cooling coil equipment ----------

    def cost_airloop_coils(self, air_loop, sys_type, units, flow_m3s):
        """Legacy airloop_equipment_costing/cost_heat_cool_equip: each supply
        coil is costed as equipment on a per-air-handler basis
        (capacity / unit count, quantity x units)."""
        found = []
        for comp in coils.supply_components(air_loop):
            c = opt(comp.to_CoilHeatingGasMultiStage())
            if c is not None:
                found.append({'role': 'heat_gas', 'lookup': 'FurnaceGas',
                              'kw': self.staged_kw(c), 'name': c.nameString()})
                continue
            c = opt(comp.to_CoilHeatingDXMultiSpeed())
            if c is not None:
                found.append({'role': 'heat_hp', 'lookup': 'ashp',
                              'kw': self.staged_kw(c), 'name': c.nameString()})
                continue
            c = opt(comp.to_CoilCoolingDXMultiSpeed())
            if c is not None:
                found.append({'role': 'cool_dx', 'lookup': 'coils',
                              'kw': self.staged_kw(c), 'name': c.nameString()})
                continue
            c = opt(comp.to_CoilHeatingWater())
            if c is not None:
                found.append({'role': 'heat', 'lookup': 'Coils',
                              'kw': self.kw_of(c.ratedCapacity(),
                                               c.autosizedRatedCapacity()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilHeatingElectric())
            if c is not None:
                found.append({'role': 'heat_elec', 'lookup': 'ElecHeat',
                              'kw': self.kw_of(c.nominalCapacity(),
                                               c.autosizedNominalCapacity()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilHeatingGas())
            if c is not None:
                found.append({'role': 'heat_gas', 'lookup': 'FurnaceGas',
                              'kw': self.kw_of(c.nominalCapacity(),
                                               c.autosizedNominalCapacity()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilHeatingDXSingleSpeed())
            if c is not None:
                found.append({'role': 'heat_hp', 'lookup': 'ashp',
                              'kw': self.kw_of(c.ratedTotalHeatingCapacity(),
                                               c.autosizedRatedTotalHeatingCapacity()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilHeatingDXVariableSpeed())
            if c is not None:
                ccashp = 'CCASHP' in c.nameString().upper()
                found.append({'role': 'heat_hp',
                              'lookup': 'coils' if ccashp else 'ashp', 'ccashp': ccashp,
                              'kw': self.kw_of(
                                  c.ratedHeatingCapacityAtSelectedNominalSpeedLevel(),
                                  c.autosizedRatedHeatingCapacityAtSelectedNominalSpeedLevel()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilCoolingDXSingleSpeed())
            if c is not None:
                found.append({'role': 'cool_dx', 'lookup': 'coils',
                              'kw': self.kw_of(c.ratedTotalCoolingCapacity(),
                                               c.autosizedRatedTotalCoolingCapacity()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilCoolingDXTwoSpeed())
            if c is not None:
                found.append({'role': 'cool_dx', 'lookup': 'coils',
                              'kw': self.kw_of(
                                  c.ratedHighSpeedTotalCoolingCapacity(),
                                  c.autosizedRatedHighSpeedTotalCoolingCapacity()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilCoolingDXVariableSpeed())
            if c is not None:
                found.append({'role': 'cool_dx', 'lookup': 'coils',
                              'kw': self.kw_of(
                                  c.grossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel(),
                                  c.autosizedGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel()),
                              'name': c.nameString()})
                continue
            c = opt(comp.to_CoilCoolingWater())
            if c is not None:
                found.append({'role': 'cool_chw', 'lookup': 'Coils',
                              'kw': self.kw_of(None, c.autosizedDesignCoilLoad()),
                              'name': c.nameString()})

        # HP merge rule (legacy): the heat pump IS the cooling unit — drop DX
        # cooling items and size the HP by the larger of the two capacities;
        # backup electric heat is costed as a duct heater.
        hp = next((c for c in found if c['role'] == 'heat_hp'), None)
        if hp is not None:
            dx = next((c for c in found if c['role'] == 'cool_dx'), None)
            hp_kw = hp['kw'] if hp['kw'] is not None else 0.0
            dx_kw = (dx['kw'] if dx['kw'] is not None else 0.0) if dx is not None else 0.0
            hp['kw'] = max(hp_kw, dx_kw)
            found = [c for c in found if c['role'] != 'cool_dx']
            for c in found:
                if c['role'] == 'heat_elec':
                    c['lookup'] = 'ElecDuct'

        for coil in found:
            if coil['kw'] is None or coil['kw'] == 0.0:
                coil['kw'] = self.sql_coil_capacity_kw(air_loop.model(), coil['name'])
            if coil['kw'] is None:
                self.warnings.append(
                    f"no capacity for coil {coil['name']} (model not sized?) — not costed")
                continue
            if coil['kw'] <= 0.0:
                continue

            per_unit_kw = coil['kw'] / units
            self.add_item(coil['lookup'], per_unit_kw, float(units), ['VENTILATION'],
                          f"air-loop coil {coil['name']} "
                          f"({ruby_str(ruby_round(per_unit_kw, 1))} kW x {units})")
            if coil['role'] == 'cool_dx':
                self.add_item('CondensingUnit', per_unit_kw, float(units), ['VENTILATION'],
                              f"condensing unit for {coil['name']}")
                # refrigerant piping BOM per condensing unit (legacy
                # cost_heat_cool_equip)
                self.add_item('SteelPipe', 1.25, 32.8 * units, ['VENTILATION'],
                              f"refrigerant piping for {coil['name']}", unit='L.F.')
                self.add_item('PipeInsulationsilica', 1.25, 32.8 * units, ['VENTILATION'],
                              f"refrigerant pipe insulation for {coil['name']}")
                self.add_item('SteelPipeElbow', 1.25, 8.0 * units, ['VENTILATION'],
                              f"refrigerant pipe elbows for {coil['name']}")
            if coil.get('ccashp'):
                self.cost_ccashp_extras(coil, units)

        # gas-burner AHU adjustment (legacy gas_burner_cost): the AHU assembly
        # includes a duct furnace for sys 1/4 — remove it since the gas coil is
        # costed separately.
        gas = next((c for c in found if c['role'] == 'heat_gas'), None)
        if gas is not None and not (sys_type == 3 or sys_type == 6):
            cfm = flow_m3s * 2118.88
            adj_kw = 132 if cfm > 1500 else (88 if cfm >= 1000 else None)
            if adj_kw is not None:
                self.add_item('DuctFurGasExt', adj_kw, -1.0, ['VENTILATION'],
                              f"AHU gas burner adjustment ({air_loop.nameString()})")

    def cost_ccashp_extras(self, coil, units):
        """Legacy cost_ccashp_additional_components: evaporator valve,
        condenser, wiring and the fixed material_id assembly (controller,
        refrigerant tubing, insulation, switch)."""
        per_unit_kw = (coil['kw'] if coil['kw'] is not None else 0.0) / units
        cond_units = self.add_item('EV_valve', per_unit_kw, float(units), ['VENTILATION'],
                                   f"CCASHP EV valve for {coil['name']}")
        # (Ruby's `|| cond_units` fallback is vacuous — add_item never returns
        # nil — kept as a plain assignment.)
        cond_units = self.add_item('ccashp_condensor', per_unit_kw, float(units),
                                   ['VENTILATION'],
                                   f"CCASHP condenser for {coil['name']}")
        cond_mult = max(float(cond_units), 1.0)
        self.add_item('Wiring', 10, 0.2 * units * cond_mult, ['VENTILATION'],
                      f"CCASHP wiring for {coil['name']}", unit='CLF', exact_size=True)
        for material_id, quantity in {'1295': cond_mult, '1662': cond_mult,
                                      '30': cond_mult * 40, '1415': cond_mult}.items():
            material = next((r for r in self._db.materials_hvac
                             if to_s(r.get('material_id')) == material_id), None)
            if material is None:
                self.warnings.append(
                    f"CCASHP extra material_id {material_id} missing — not costed")
                continue

            self._ledger.add(id=material['id'], quantity=quantity * units,
                             tags=['VENTILATION'],
                             note=f"CCASHP extras for {coil['name']} "
                                  f"[{to_s(material.get('Material'))}]")

    def kw_of(self, hard, autosized):
        value = self.optional_f(hard)
        if value is None:
            value = self.optional_f(autosized)
        return None if value is None else value / 1000.0

    def staged_kw(self, coil):
        """A staged coil's TOTAL capacity is its TOP stage (EnergyPlus stages
        are cumulative, not additive), so that is what gets costed."""
        stages = coil.stages()
        stage = stages[-1] if len(stages) > 0 else None
        if stage is None:
            return None

        if hasattr(stage, 'grossRatedTotalCoolingCapacity'):
            return self.kw_of(stage.grossRatedTotalCoolingCapacity(),
                              stage.autosizedGrossRatedTotalCoolingCapacity())
        if hasattr(stage, 'grossRatedHeatingCapacity'):
            return self.kw_of(stage.grossRatedHeatingCapacity(),
                              stage.autosizedGrossRatedHeatingCapacity())
        return self.kw_of(stage.nominalCapacity(), stage.autosizedNominalCapacity())

    def optional_f(self, value):
        if value is None:
            return None
        if not hasattr(value, 'is_initialized'):
            return float(value)
        return float(value.get()) if value.is_initialized() else None

    def sql_coil_capacity_kw(self, model, coil_name):
        """E+ never reports a sized 'Rated Capacity' for hot-water coils, so
        the autosized accessor is empty even on a sized model (the same gap
        makes legacy misclassify hydronic AHUs as heat pumps and skip their
        heating coils — a documented legacy defect this port corrects). Fall
        back to the CoilSizingDetails report."""
        if not model.sqlFile().is_initialized():
            return None

        query = ("SELECT Value FROM TabularDataWithStrings WHERE "
                 "ReportName='CoilSizingDetails' "
                 f"AND RowName='{coil_name.upper()}' "
                 "AND ColumnName='Coil Final Gross Total Capacity'")
        value = opt(model.sqlFile().get().execAndReturnFirstDouble(query))
        return value / 1000.0 if value is not None and value > 0 else None

    # ---------- terminals: mixing boxes + piping/electrical runs ----------

    TERMINAL_TYPES = (
        ('to_AirTerminalSingleDuctVAVReheat', 'VAVFanMixingBoxesHtg'),
        ('to_AirTerminalSingleDuctVAVNoReheat', 'VAVFanMixingBoxesClg'),
        ('to_AirTerminalSingleDuctConstantVolumeReheat', 'CVMixingBoxes'),
    )

    def cost_terminals(self, air_loop, roof_cent):
        """Legacy reheat_recool_cost: per terminal, per storey the zone spans —
        the mixing box (sized by the storey's share of airflow), hydronic
        piping to the roof centroid for hot boxes, an electrical run for every
        box, and the reheat coil for CV boxes."""
        for zone in sorted_by_name(air_loop.thermalZones()):
            tz_mult = float(zone.multiplier())
            for eq in zone.equipment():
                terminal = box = None
                for cast, box_name in self.TERMINAL_TYPES:
                    optional = getattr(eq, cast)()
                    if not optional.is_initialized():
                        continue

                    terminal = optional.get()
                    box = box_name
                    break
                if box is None:
                    continue

                flow = terminal.maximumAirFlowRate()
                if not flow.is_initialized():
                    flow = terminal.autosizedMaximumAirFlowRate()
                if not flow.is_initialized():
                    self.warnings.append(
                        f"no max air flow for terminal {terminal.nameString()} "
                        "— box not costed")
                    continue
                air_m3s = flow.get() / tz_mult

                stories = geometry.zone_story_centroids(zone)
                if not stories:
                    stories = [{'story_name': 'none', 'spaces': list(zone.spaces()),
                                'centroid': None, 'ceiling_area': 1.0}]
                zone_area = float(zone.floorArea())
                for story in stories:
                    frac = ruby_round(sum(float(s.floorArea()) for s in story['spaces'])
                                      / zone_area, 2) if zone_area > 0 else 1.0
                    cfm = frac * air_m3s * 2118.88
                    self.add_item(box, cfm, tz_mult, ['VENTILATION'],
                                  f"terminal box {terminal.nameString()} "
                                  f"({box}, {ruby_round(cfm)} cfm, {story['story_name']})")

                    if box == 'CVMixingBoxes':
                        self.cost_cv_reheat_coil(terminal, frac, tz_mult, air_m3s,
                                                 story, roof_cent)

                    if roof_cent is None or story['centroid'] is None:
                        continue

                    run_ft = geometry.manhattan_xy_m(story['centroid'], roof_cent) * \
                        geometry.M_TO_FT
                    if box == 'VAVFanMixingBoxesHtg':
                        self.cost_terminal_piping(
                            run_ft, frac * air_m3s, tz_mult,
                            f"terminal piping {terminal.nameString()} "
                            f"({story['story_name']})")
                    self.cost_terminal_electrical(
                        run_ft, tz_mult,
                        f"terminal electrical {terminal.nameString()} "
                        f"({story['story_name']})")

    def cost_cv_reheat_coil(self, terminal, frac, tz_mult, air_m3s, story, roof_cent):
        coil = terminal.reheatCoil()
        if coil.to_CoilHeatingWater().is_initialized():
            c = coil.to_CoilHeatingWater().get()
            kw = self.kw_of(c.ratedCapacity(), c.autosizedRatedCapacity())
            if kw is None:
                self.warnings.append(
                    f"no capacity for reheat coil {c.nameString()} — not costed")
                return

            self.add_item('Coils', frac * kw / tz_mult, tz_mult, ['VENTILATION'],
                          f"reheat coil {c.nameString()}")
            if roof_cent is not None and story['centroid'] is not None:
                run_ft = geometry.manhattan_xy_m(story['centroid'], roof_cent) * \
                    geometry.M_TO_FT
                # legacy quirk: CV reheat piping is sized by the FULL terminal
                # airflow
                self.cost_terminal_piping(run_ft, air_m3s, tz_mult,
                                          f"reheat coil piping {c.nameString()}")
        elif coil.to_CoilHeatingElectric().is_initialized():
            c = coil.to_CoilHeatingElectric().get()
            kw = self.kw_of(c.nominalCapacity(), c.autosizedNominalCapacity())
            if kw is None:
                self.warnings.append(
                    f"no capacity for reheat coil {c.nameString()} — not costed")
                return

            self.add_item('ElecDuct', frac * kw / tz_mult, tz_mult, ['VENTILATION'],
                          f"electric duct heater {c.nameString()}")

    def cost_terminal_piping(self, run_ft, air_m3s, quantity, context):
        """Legacy piping_cost: supply+return steel pipe at the heating-valve
        diameter from the mech_sizing piping table (keyed by airflow in L/s),
        2 of each fitting."""
        piping = self.mech_table('piping')
        if piping is None:
            return

        lps = min(air_m3s * 1000.0, 15_000.0)
        row = next((r for r in piping
                    if ruby_round(to_f(r['ahu_airflow_range_Literpers'][0])) < ruby_round(lps)
                    and ruby_round(to_f(r['ahu_airflow_range_Literpers'][1])) >= ruby_round(lps)),
                   None)
        if row is None:
            row = max(piping, key=lambda r: to_f(r['ahu_airflow_range_Literpers'][1]))
        dia = ruby_round(to_f(row['heat_valve_pipe_dia_inch']), 2)

        self.add_item('SteelPipe', dia, 2 * run_ft * quantity, ['VENTILATION'],
                      f'{context} (pipe {ruby_str(dia)}")', unit='L.F.')
        self.add_item('SteelPipeElbow', dia, 2 * quantity, ['VENTILATION'], context)
        self.add_item('SteelPipeTee', dia, 2 * quantity, ['VENTILATION'], context)
        self.add_item('SteelPipeTeeRed', dia, 2 * quantity, ['VENTILATION'], context)
        self.add_item('SteelPipeRed', dia, 2 * quantity, ['VENTILATION'], context)
        self.add_item('SteelPipeUnion', min(dia, 3.0), 2 * quantity, ['VENTILATION'],
                      context)

    def cost_terminal_electrical(self, run_ft, quantity, context):
        """Legacy vent_box_elec_cost: #14 wiring (CLF) + conduit for the run,
        one 4" and one 1" electrical box per mixing box."""
        self.add_item('Wiring', 14, (run_ft / 100.0) * quantity, ['VENTILATION'],
                      context, unit='CLF', exact_size=True)
        self.add_item('Conduit', None, run_ft * quantity, ['VENTILATION'], context,
                      unit='L.F.')
        self.add_item('Box', 4, quantity, ['VENTILATION'], context, exact_size=True)
        self.add_item('Box', 1, quantity, ['VENTILATION'], context, exact_size=True)

    def cost_hrv(self, air_loop):
        """Legacy hrv_cost: the ERV/HRV core (flow-proportionally scaled), a
        duct fitting per served zone, and a dedicated return fan when the loop
        has no return fan of its own."""
        hx = next((c for c in air_loop.oaComponents()
                   if c.to_HeatExchangerAirToAirSensibleAndLatent().is_initialized()),
                  None)
        if hx is None:
            return

        hx = hx.to_HeatExchangerAirToAirSensibleAndLatent().get()
        flow = self.optional_f(hx.nominalSupplyAirFlowRate())
        if flow is None:
            flow = self.optional_f(hx.autosizedNominalSupplyAirFlowRate())
        if flow is None:
            self.warnings.append(
                f"no nominal flow for HRV {hx.nameString()} (model not sized?) "
                "— HRV not costed")
            return
        cfm = flow * 2118.88
        note = f"HRV {hx.nameString()} ({ruby_round(cfm)} cfm)"

        zones = float(sum(z.multiplier() for z in air_loop.thermalZones()))
        self.add_item('Ductwork-Fitting', 8, zones, ['VENTILATION'],
                      f"{note} zone duct fittings")

        # ERV core: legacy scales the row cost by cfm x units / row size
        picked = self.pick_material('ERV', cfm, note)
        if picked is not None:
            row, units = picked
            row_size = to_f(row.get('Size'))
            adj = cfm * units / row_size if row_size > 0 else units
            self._ledger.add(id=row['id'], quantity=adj, tags=['VENTILATION'], note=note)

        if air_loop.returnFan().is_initialized():
            return

        fan_lookup = 'FansDD-LP' if cfm < 800 else 'FansBelt'
        self.add_item(fan_lookup, cfm, 1.0, ['VENTILATION'], f"{note} return fan")

    # ---------- geometry-derived distribution (legacy report-only domains) ----------

    def cost_mech_to_roof(self, mech, roof_cent, heat_line_counts, cool_line_counts,
                          rooftop_units):
        """Legacy mech_to_roof_cost: gas/hot-water/chilled-water lines and the
        electrical run from the mechanical room to the rooftop units."""
        util_ft = geometry.manhattan_xyz_m(mech['centroid'], roof_cent) * geometry.M_TO_FT
        if heat_line_counts['Gas'] > 0:
            self.add_item('GasLine', None,
                          util_ft + self.RT_ROOF_DIST_FT * heat_line_counts['Gas'],
                          ['DISTRIBUTION'], 'gas line mech room -> roof', unit='L.F.')
        for line, count in {'HW': heat_line_counts['HW'],
                            'CHW': cool_line_counts['CHW']}.items():
            if not count > 0:
                continue

            length = 2 * util_ft + 2 * self.RT_ROOF_DIST_FT * count
            self.add_item('SteelPipe', 4, length, ['DISTRIBUTION'],
                          f"{line} line mech room -> roof", unit='L.F.')
            self.add_item('PipeInsulation', 4, length, ['DISTRIBUTION'],
                          f"{line} line insulation")
            self.add_item('PipeJacket', 4, length, ['DISTRIBUTION'],
                          f"{line} line jacket")
        elec_ft = util_ft + rooftop_units * self.RT_ROOF_DIST_FT
        self.add_item('Wiring', 10, elec_ft / 100.0, ['DISTRIBUTION'],
                      'electrical run mech room -> roof', unit='CLF', exact_size=True)
        self.add_item('Conduit', None, elec_ft, ['DISTRIBUTION'],
                      'electrical conduit mech room -> roof', unit='L.F.')

    def cost_trunk_duct(self, model, total_flow_m3s, roof_cent, sys_1_4):
        """Legacy vent_trunk_duct_cost: the vertical trunk from the roof
        centroid down to the lowest conditioned ceiling; x2 runs unless a
        single-run (sys 1/4) building."""
        trunk = self.mech_table('trunk')
        low = geometry.lowest_roof_centroid(model)
        if trunk is None or low is None:
            return

        runs = 1 if sys_1_4 else 2
        flow = total_flow_m3s
        max_row = max(trunk, key=lambda r: to_f(r['max_flow_range_m3pers'][0]))
        if ruby_round(flow, 2) > ruby_round(to_f(max_row['max_flow_range_m3pers'][1]), 2):
            flow = ruby_round(to_f(max_row['max_flow_range_m3pers'][0]), 2)
        row = next((r for r in trunk
                    if ruby_round(to_f(r['max_flow_range_m3pers'][0]), 2) < ruby_round(flow, 2)
                    and ruby_round(to_f(r['max_flow_range_m3pers'][1]), 2) >= ruby_round(flow, 2)),
                   None)
        if row is None:
            row = max_row
        dia = to_f(row['duct_dia_inch'])
        length_ft = abs(roof_cent[2] - low[2]) * geometry.M_TO_FT
        if length_ft <= 0.0:
            return

        self.add_item('Ductwork-S', dia, length_ft * runs, ['DISTRIBUTION'],
                      'central trunk duct', unit='L.F.')
        self.add_item('Ductinsulation', 1.5, (dia / 12.0) * math.pi * length_ft * runs,
                      ['DISTRIBUTION'], 'central trunk duct insulation')

    def collect_hvac_floors(self, hvac_floors, air_loop, sys_type):
        """Legacy gen_hvac_info_by_floor: aggregate terminal airflows per
        storey (return air only for systems other than 1/4)."""
        for zone in sorted_by_name(air_loop.thermalZones()):
            tz_mult = float(zone.multiplier())
            for eq in zone.equipment():
                terminal = None
                for cast, _box in self.TERMINAL_TYPES:
                    optional = getattr(eq, cast)()
                    if optional.is_initialized():
                        terminal = optional.get()
                if terminal is None and \
                        eq.to_AirTerminalSingleDuctConstantVolumeNoReheat().is_initialized():
                    terminal = eq.to_AirTerminalSingleDuctConstantVolumeNoReheat().get()
                if terminal is None:
                    continue

                flow = terminal.maximumAirFlowRate()
                if not flow.is_initialized():
                    flow = terminal.autosizedMaximumAirFlowRate()
                if not flow.is_initialized():
                    continue

                air_m3s = flow.get() / tz_mult
                zone_area = float(zone.floorArea())
                for story in geometry.zone_story_centroids(zone):
                    frac = ruby_round(sum(float(s.floorArea()) for s in story['spaces'])
                                      / zone_area, 2) if zone_area > 0 else 1.0
                    supply = frac * air_m3s
                    if story['story_name'] not in hvac_floors:
                        hvac_floors[story['story_name']] = {
                            'story': opt(story['spaces'][0].buildingStory()),
                            'supply_m3s': 0.0, 'return_m3s': 0.0, 'tz_mult': 0.0,
                            'tz_num': 0, 'sys_types': [], 'zones': []}
                    entry = hvac_floors[story['story_name']]
                    single_run = sys_type in self.SINGLE_RUN_SYS_TYPES
                    entry['supply_m3s'] += supply
                    entry['return_m3s'] += 0.0 if single_run else supply
                    entry['tz_mult'] += tz_mult
                    entry['tz_num'] += 1
                    entry['sys_types'].append(sys_type)
                    entry['zones'].append({'supply_m3s': supply,
                                           'return_m3s': 0.0 if single_run else supply,
                                           'tz_mult': tz_mult})

    def cost_floor_trunk_ducts(self, hvac_floors, roof_cent):
        """Legacy floor_vent_dist_cost/get_floor_trunk_cost: a supply
        (+return) trunk across each storey, sized from the storey airflow at
        the design velocity, run length from the storey outline crossing
        through the roof centroid."""
        vel_prof = self.mech_table('vel_prof')
        for story_name, floor in hvac_floors.items():
            uniq_sys = list(dict.fromkeys(floor['sys_types']))
            if floor['tz_num'] < 2 and uniq_sys == [3]:
                continue
            if floor['story'] is None:
                continue

            line = geometry.story_cent_to_edge(floor['story'], roof_cent,
                                               full_length=True)
            if line is None or line['end_point'] is None:
                continue

            run_ft = line['end_point']['dist'] * geometry.M_TO_FT
            tz_floor_mult = floor['tz_mult'] / floor['tz_num']
            vel_fpm = to_f(vel_prof[-1]['vel_fpm']) if vel_prof is not None else 1500.0
            for flow_m3s, role in ((floor['supply_m3s'], 'supply'),
                                   (floor['return_m3s'], 'return')):
                if not flow_m3s > 0:
                    continue

                cfm = flow_m3s * 2118.88
                dia = 2 * math.sqrt(((cfm / vel_fpm) * 144.0) / math.pi)
                picked = self.pick_material('Ductwork-S', dia,
                                            f"floor trunk duct {story_name}",
                                            unit='L.F.')
                if picked is None:
                    continue

                row = picked[0]
                self._ledger.add(id=row['id'], quantity=run_ft * tz_floor_mult,
                                 tags=['DISTRIBUTION'],
                                 note=f'floor trunk {role} duct {story_name} '
                                      f'({to_s(row.get("Size"))}")')
                area_ft2 = (to_f(row.get('Size')) / 12.0) * math.pi * run_ft
                self.add_item('Ductinsulation', 1.5, area_ft2 * tz_floor_mult,
                              ['DISTRIBUTION'],
                              f"floor trunk {role} duct insulation {story_name}")

    def cost_zone_distribution(self, hvac_floors):
        """Legacy tz_vent_dist_cost: per zone-storey supply (+return)
        distribution from the mech_sizing tz_dist_info table (diffusers,
        ducting lbs, insulation ft2, flex duct)."""
        table = self.mech_table('tz_dist_info')
        flex_table = self.mech_table('flex_duct')
        if table is None:
            return

        for story_name, floor in hvac_floors.items():
            for zone_flows in floor['zones']:
                for flow in (zone_flows['supply_m3s'], zone_flows['return_m3s']):
                    if not flow > 0:
                        continue

                    row = next((r for r in table
                                if flow > to_f(r['airflow_m3ps'][0])
                                and flow <= to_f(r['airflow_m3ps'][1])), None)
                    if row is None:
                        # beyond the largest range: scale the largest row by
                        # diffuser count
                        largest = max(table, key=lambda r: to_f(r['airflow_m3ps'][1]))
                        diffusers = ruby_round(flow / to_f(largest['diffusers']))
                        row = {'diffusers': diffusers,
                               'ducting_lbs': ruby_round(diffusers * to_f(largest['ducting_lbs'])),
                               'duct_insulation_ft2': ruby_round(
                                   diffusers * to_f(largest['duct_insulation_ft2'])),
                               'flex_duct_ft': ruby_round(
                                   diffusers * to_f(largest['flex_duct_ft']))}
                    mult = zone_flows['tz_mult']
                    note = f"zone distribution ({story_name})"
                    self.add_item('Diffusers', 36, to_f(row['diffusers']) * mult,
                                  ['DISTRIBUTION'], note)
                    self.add_item('Ductwork',
                                  199 if to_f(row['ducting_lbs']) < 200 else 200,
                                  to_f(row['ducting_lbs']) * mult, ['DISTRIBUTION'], note)
                    self.add_item('DuctInsulation', 1.5,
                                  to_f(row['duct_insulation_ft2']) * mult,
                                  ['DISTRIBUTION'], note)
                    if flex_table is not None and to_f(row['flex_duct_ft']) > 0:
                        flex = next((f for f in flex_table
                                     if flow > to_f(f['airflow_m3ps'][0])
                                     and flow <= to_f(f['airflow_m3ps'][1])), None)
                        if flex is None:
                            flex = flex_table[-1]
                        self.add_item('Ductwork-M', to_f(flex['diameter_in']),
                                      to_f(row['flex_duct_ft']) * mult, ['DISTRIBUTION'],
                                      f"{note} flex duct", unit='L.F.')
