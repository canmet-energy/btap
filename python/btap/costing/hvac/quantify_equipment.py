"""Generic equipment quantification (port of btap-costing's
hvac/quantify_equipment.rb — the BTAP costing "(a)-layer"): walks OpenStudio
objects on a SIZED model and adds materials_hvac line items to the ledger.
No name-sniffing: fuel/type come from object fields and the naming contract.
Anything uncostable becomes a warning, never a silent zero."""

from __future__ import annotations

import math
import re

from btap._compat import opt, ruby_round, ruby_str, sorted_by_name
from btap.costing.hvac import geometry
from btap.costing.hvac.database import to_f, to_s


class EquipmentQuantifier:
    def __init__(self, database, ledger, mech_room_name=None, audit=None):
        self._db = database
        self._ledger = ledger
        self._mech_room_name = mech_room_name
        self._audit = audit
        self.warnings: list[str] = []
        # Ruby memoized via `defined?(@geo_model)`; initialize to None instead.
        self._geo_model = None
        self._geo = None

    def pick(self, lookup, size, context):
        """Select the materials_hvac row for a lookup + size using the legacy
        rule: smallest row with Size >= size; if size exceeds the largest, use
        the largest row with quantity = ceil(size / largest). Returns
        (row, unit_count) or None (+warning)."""
        rows = [r for r in self._db.materials_hvac
                if to_s(r.get('Material')).lower() == str(lookup).lower()]
        if not rows:
            self.warnings.append(
                f"no materials_hvac entry '{lookup}' ({context}) — item not costed")
            return None
        if size is None:
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

    def add(self, lookup, size, tags, context, count=1.0):
        picked = self.pick(lookup, size, context)
        if picked is None:
            return None

        row, units = picked
        self._ledger.add(
            id=row['id'], quantity=units * count, tags=tags,
            material_mult=1.0 if to_f(row.get('material_mult')) == 0.0 else to_f(row.get('material_mult')),
            labour_mult=1.0 if to_f(row.get('labour_mult')) == 0.0 else to_f(row.get('labour_mult')),
            note=context)
        if self._audit is not None:
            self._audit.decision(
                'costing_equipment', context,
                inputs={'lookup': lookup,
                        'size': ruby_round(size, 2) if isinstance(size, (int, float)) else size},
                value=f"item {row['id']} x {ruby_str(ruby_round(units * count, 3))}",
                evidence=to_s(row.get('description'))[0:70],
                article='materials_hvac (next-largest-size rule)')
        return units

    def geo(self, model):
        """Building geometry data (legacy getGeometryData), memoized per model."""
        if self._geo_model is not None and self._geo_model == model:
            return self._geo

        self._geo_model = model
        self._geo = geometry.building_data(model, mech_room_name=self._mech_room_name)
        if self._geo is None:
            self.warnings.append(
                'building geometry could not be resolved (no conditioned spaces?) '
                '— utility runs/flues/header piping not costed')
        elif self._audit is not None:
            g = self._geo
            self._audit.decision(
                'costing_geometry', 'building geometry resolved for distance-based items',
                target=g['mech_room']['space'].nameString(),
                inputs={'storeys': g['storeys'],
                        'mech_room_in_basement': g['mech_room_in_basement']},
                value=(f"utility {ruby_str(ruby_round(g['util_dist_ft'], 1))} ft, "
                       f"roof {ruby_str(ruby_round(g['ht_roof_ft'], 1))} ft, "
                       f"horizontal {ruby_str(ruby_round(g['horz_dist_ft'], 1))} ft, "
                       f"floor height {ruby_str(ruby_round(g['flr_height_ft'], 1))} ft"),
                article='legacy getGeometryData port')
        return self._geo

    # ---- capacity helpers (sized model: hard values or autosized accessors) ----

    def optional_f(self, value):
        if value is None:
            return None
        if not hasattr(value, 'is_initialized'):
            return float(value)
        return float(value.get()) if value.is_initialized() else None

    def sql_zone_heating_kw(self, model, zone_name):
        """Zone design heating load from the ZoneSizes SQL table (legacy
        zonalsys_costing capacity source) — fallback when a zonal coil's
        autosized capacity is empty."""
        if not model.sqlFile().is_initialized():
            return None

        query = (f"SELECT UserDesLoad FROM ZoneSizes WHERE "
                 f"ZoneName='{zone_name.upper()}' AND LoadType='Heating'")
        value = opt(model.sqlFile().get().execAndReturnFirstDouble(query))
        return value / 1000.0 if value is not None and value > 0 else None

    def capacity_kw(self, hard, autosized, context):
        kw = self.optional_f(hard)
        if kw is None:
            kw = self.optional_f(autosized)
        if kw is None:
            self.warnings.append(
                f"no capacity available for {context} (model not sized?) — item not costed")
            return None
        return kw / 1000.0

    # ---- plant equipment (tag HEATING_COOLING) ----

    def quantify_plant(self, model):
        for boiler in sorted_by_name(model.getBoilerHotWaters()):
            kw = self.capacity_kw(boiler.nominalCapacity(),
                                  boiler.autosizedNominalCapacity(), boiler.nameString())
            if kw is None:
                continue

            fuel = boiler.fuelType()
            if fuel == 'Electricity':
                bucket = 'ElecBoilers'
            elif fuel in ('FuelOilNo1', 'FuelOilNo2'):
                bucket = 'OilBoilers'
            else:
                bucket = 'CondensingBoilers' if boiler.nominalThermalEfficiency() >= 0.88 \
                    else 'GasBoilers'
            self.add(bucket, kw, ['HEATING_COOLING'],
                     f"boiler {boiler.nameString()} {ruby_str(ruby_round(kw, 1))} kW")

        for chiller in sorted_by_name(model.getChillerElectricEIRs()):
            kw = self.capacity_kw(chiller.referenceCapacity(),
                                  chiller.autosizedReferenceCapacity(), chiller.nameString())
            if kw is None:
                continue

            # chiller compressor type from the naming contract; default Scroll
            kind = next((t for t in ('Scroll', 'Centrifugal', 'Reciprocating', 'Screw')
                         if t in chiller.nameString()), None)
            if kind is None:
                kind = 'Screw' if 'Rotary' in chiller.nameString() else 'Scroll'
            cond = 'Air' if chiller.condenserType() == 'AirCooled' else 'Water'
            self.add(f"ChillerElectricEIR_VSD{kind}{cond}Chiller", kw, ['HEATING_COOLING'],
                     f"chiller {chiller.nameString()} {ruby_str(ruby_round(kw, 1))} kW")

        for tower in sorted_by_name(model.getCoolingTowerSingleSpeeds()):
            # legacy sizes the tower from connected chiller capacity; approximate
            # with the total water-cooled chiller capacity on the model
            # (documented approximation)
            chiller_kw = 0.0
            for c in model.getChillerElectricEIRs():
                if c.condenserType() != 'WaterCooled':
                    continue
                kw = self.capacity_kw(c.referenceCapacity(),
                                      c.autosizedReferenceCapacity(), c.nameString())
                chiller_kw += kw if kw is not None else 0.0
            self.add('ClgTwr', chiller_kw if chiller_kw > 0 else None, ['HEATING_COOLING'],
                     f"cooling tower {tower.nameString()}")

        pumps = list(model.getPumpConstantSpeeds()) + list(model.getPumpVariableSpeeds())
        for pump in sorted_by_name(pumps):
            watts = self.optional_f(pump.ratedPowerConsumption())
            if watts is None:
                watts = self.optional_f(pump.autosizedRatedPowerConsumption())
            if watts is None:
                self.warnings.append(f"no rated power for pump {pump.nameString()} — not costed")
                continue
            self.add('Pumps', watts, ['HEATING_COOLING'],
                     f"pump {pump.nameString()} {ruby_round(watts)} W")
            if pump.to_PumpVariableSpeed().is_initialized():
                self.add('VFD', watts, ['HEATING_COOLING'], f"VFD for {pump.nameString()}")

        for hp in sorted_by_name(model.getHeatPumpPlantLoopEIRHeatings()):
            kw = self.capacity_kw(hp.referenceCapacity(),
                                  hp.autosizedReferenceCapacity(), hp.nameString())
            if kw is not None:
                self.add('Airtowaterhp', kw, ['HEATING_COOLING'],
                         f"air-to-water HP {hp.nameString()}")

        for hp in sorted_by_name(model.getHeatPumpWaterToWaterEquationFitHeatings()):
            kw = self.capacity_kw(hp.ratedHeatingCapacity(),
                                  hp.autosizedRatedHeatingCapacity(), hp.nameString())
            # W2W GSHP unit costed via the ground-source materials; loop piping
            # is distribution
            if kw is not None:
                self.add('gshp_ground_loop', kw, ['HEATING_COOLING'],
                         f"W2W GSHP {hp.nameString()}")

        for district in list(model.getDistrictHeatingWaters()) + list(model.getDistrictCoolings()):
            self.warnings.append(
                f"district energy object {district.nameString()}: connection costs "
                "not modeled (energy purchased, not owned plant)")

        for cooler in model.getEvaporativeFluidCoolerSingleSpeeds():
            self.add('ClgTwr', None, ['HEATING_COOLING'],
                     f"evaporative fluid cooler {cooler.nameString()} (costed as tower class)")

        self.quantify_plant_geometry(model)

    # ---- geometry-derived plant costs (legacy boiler/chiller/tower costing:
    #      flues, fuel lines, electrical runs, piping to pumps, header piping) ----

    def quantify_plant_geometry(self, model):
        data = self.geo(model)
        if data is None:
            return

        for loop in sorted_by_name(model.getPlantLoops()):
            boilers = []
            chillers = []
            towers = []
            pumps = []
            for comp in loop.supplyComponents():
                b = opt(comp.to_BoilerHotWater())
                if b is not None:
                    boilers.append(b)
                c = opt(comp.to_ChillerElectricEIR())
                if c is not None:
                    chillers.append(c)
                t = opt(comp.to_CoolingTowerSingleSpeed())
                if t is not None:
                    towers.append(t)
                p = opt(comp.to_PumpConstantSpeed())
                if p is not None:
                    pumps.append(p)
                p = opt(comp.to_PumpVariableSpeed())
                if p is not None:
                    pumps.append(p)
            if boilers:
                self.cost_boiler_loop_geometry(loop, boilers, pumps, data)
            elif chillers:
                self.cost_chiller_loop_geometry(loop, chillers, pumps, data)
            elif towers:
                self.cost_tower_loop_geometry(loop, towers, pumps, data)

    def cost_boiler_loop_geometry(self, loop, boilers, pumps, data):
        """Legacy boiler_costing geometry items: flue (6" venting up past the
        roof, elbow and top; header when multiple combustion boilers), fuel
        line + electrical run over the mech-room utility distance, piping to
        pumps, and hot-water header distribution."""
        note = f"plant utilities ({loop.nameString()})"
        util = data['util_dist_ft']
        combustion = [b for b in boilers if b.fuelType() != 'Electricity']

        if combustion:
            self.add('Venting', 6, ['HEATING_COOLING'], f"boiler flue {note}",
                     count=data['ht_roof_ft'])
            self.add('VentingElbow', 6, ['HEATING_COOLING'], f"boiler flue elbow {note}")
            self.add('VentingTop', 6, ['HEATING_COOLING'], f"boiler flue top {note}")
            if len(combustion) > 1:  # flue header: 20 ft + an elbow per connected boiler
                self.add('Venting', 6, ['HEATING_COOLING'], f"boiler flue header {note}",
                         count=20.0 * len(combustion))
                self.add('VentingElbow', 6, ['HEATING_COOLING'],
                         f"boiler flue header elbows {note}", count=float(len(combustion)))
            self.gas_line(util, len(combustion), note)
            oil = [b for b in combustion if re.search(r'Oil', str(b.fuelType()), re.IGNORECASE)]
            if oil:
                self.add('OilLine', None, ['HEATING_COOLING'], f"oil filtering system {note}")
                self.add('OilTanks', 2000, ['HEATING_COOLING'], f"oil tank {note}")
        self.electrical_run(util, note)
        self.piping_to_pumps(len(pumps), len(boilers), note)
        self.header_distribution(pumps, data, note)

    def cost_chiller_loop_geometry(self, loop, chillers, pumps, data):
        """Legacy chiller_costing geometry items (electric chillers):
        electrical run, piping to pumps, and chilled-water header
        distribution."""
        note = f"plant utilities ({loop.nameString()})"
        self.electrical_run(data['util_dist_ft'], note)
        self.piping_to_pumps(len(pumps), len(chillers), note)
        self.header_distribution(pumps, data, note)

    def cost_tower_loop_geometry(self, loop, towers, pumps, data):
        """Legacy coolingtower_costing geometry items: electrical run up to
        the roof and the 4" condenser piping riser."""
        note = f"condenser utilities ({loop.nameString()})"
        run = data['ht_roof_ft'] + 20.0
        for _tower in towers:
            self.add('Wiring', 14, ['HEATING_COOLING'], f"tower electrical {note}",
                     count=run / 100.0)
            self.add('Conduit', None, ['HEATING_COOLING'], f"tower conduit {note}", count=run)
        length = data['ht_roof_ft'] * 2 + 10.0 * len(pumps)
        self.add('SteelPipe', 4, ['HEATING_COOLING'], f"condenser riser piping {note}",
                 count=length)
        self.add('PipeInsulation', 4, ['HEATING_COOLING'],
                 f"condenser riser insulation {note}", count=length)
        self.add('SteelPipeTee', 4, ['HEATING_COOLING'], f"condenser piping tees {note}",
                 count=float(len(pumps)))
        self.add('ValvesBFly', 4, ['HEATING_COOLING'], f"condenser butterfly valves {note}",
                 count=float(len(pumps)))

    def gas_line(self, util_dist_ft, unit_count, note):
        self.add('GasLine', None, ['HEATING_COOLING'], f"fuel line {note}",
                 count=util_dist_ft)  # L.F. row
        self.add('GasLine', 4, ['HEATING_COOLING'], f"fuel line fittings {note}",
                 count=float(unit_count))  # 'each' row

    def electrical_run(self, util_dist_ft, note):
        self.add('Wiring', 14, ['HEATING_COOLING'], f"electrical wire {note}",
                 count=util_dist_ft / 100.0)
        self.add('Conduit', None, ['HEATING_COOLING'], f"electrical conduit {note}",
                 count=util_dist_ft)

    def piping_to_pumps(self, pump_count, unit_count, note):
        """Legacy: 10 ft of 1" pipe + insulation, 2 elbows and a gate valve
        per pump, times the number of primary units on the loop."""
        if pump_count == 0 or unit_count == 0:
            return

        factor = pump_count * unit_count
        self.add('SteelPipe', 1, ['HEATING_COOLING'], f"piping to pumps {note}",
                 count=10.0 * factor)
        self.add('PipeInsulation', 1, ['HEATING_COOLING'],
                 f"pump piping insulation {note}", count=10.0 * factor)
        self.add('SteelPipeElbow', 1, ['HEATING_COOLING'], f"pump piping elbows {note}",
                 count=2.0 * factor)
        self.add('ValvesGate', 1, ['HEATING_COOLING'], f"pump gate valves {note}",
                 count=1.0 * factor)

    def header_distribution(self, pumps, data, note):
        """Legacy getHeaderPipingDistributionCost: supply+return header piping
        sized by pump flow (>2 storeys) plus the electrical header
        (conduit/wiring/box per storey)."""
        storeys = data['storeys'] + (1 if data['mech_room_in_basement'] else 0)
        flr = data['flr_height_ft']
        if storeys < 3:
            length = storeys * flr
            dia = 1.25
        else:
            flow = 0.0
            for pump in pumps:
                rate = self.optional_f(pump.ratedFlowRate())
                if rate is None:
                    rate = self.optional_f(pump.autosizedRatedFlowRate())
                flow += rate if rate is not None else 0.0
            if flow <= 0.0001262:
                dia = 0.5
            elif flow <= 0.0002524:
                dia = 0.75
            elif flow <= 0.0005047:
                dia = 1.0
            elif flow <= 0.0010090:
                dia = 1.25
            elif flow <= 0.0015773:
                dia = 1.5
            elif flow <= 0.0031545:
                dia = 2.0
            else:
                dia = 2.5
            length = data['horz_dist_ft'] + flr * storeys
        # supply + return headers (x2)
        self.add('SteelPipe', dia, ['HEATING_COOLING'], f"header piping {note}",
                 count=2.0 * length)
        self.add('PipeInsulation', dia, ['HEATING_COOLING'],
                 f"header pipe insulation {note}", count=2.0 * length)
        self.add('ValvesGate', dia, ['HEATING_COOLING'], f"header gate valves {note}",
                 count=2.0)
        self.add('SteelPipeTee', dia, ['HEATING_COOLING'], f"header tees {note}", count=2.0)
        # electrical header for zonal units
        hdr = storeys * flr
        self.add('Conduit', None, ['HEATING_COOLING'], f"header conduit {note}", count=hdr)
        self.add('Wiring', 10, ['HEATING_COOLING'], f"header wiring {note}",
                 count=hdr / 100.0)
        self.add('Box', 4, ['HEATING_COOLING'], f"header boxes {note}", count=float(storeys))

    # ---- zonal equipment (tag ZONAL) ----

    def quantify_zonal(self, model):
        for zone in sorted_by_name(model.getThermalZones()):
            mult = zone.multiplier()
            for equipment in zone.equipment():
                ptac = opt(equipment.to_ZoneHVACPackagedTerminalAirConditioner())
                if ptac is not None:
                    coil = ptac.coolingCoil().to_CoilCoolingDXSingleSpeed()
                    kw = self.capacity_kw(coil.get().ratedTotalCoolingCapacity(),
                                          coil.get().autosizedRatedTotalCoolingCapacity(),
                                          ptac.nameString()) \
                        if coil.is_initialized() else None
                    units = self.add('PTAC', kw, ['ZONAL'], f"PTAC {ptac.nameString()}",
                                     count=mult)
                    if units is None:
                        units = 1.0
                    # legacy: one electrical junction box per PTAC unit
                    self.add('Box', 1, ['ZONAL'], f"PTAC junction box {ptac.nameString()}",
                             count=units * mult)
                elif equipment.to_ZoneHVACPackagedTerminalHeatPump().is_initialized():
                    pthp = equipment.to_ZoneHVACPackagedTerminalHeatPump().get()
                    coil = pthp.coolingCoil().to_CoilCoolingDXSingleSpeed()
                    kw = self.capacity_kw(coil.get().ratedTotalCoolingCapacity(),
                                          coil.get().autosizedRatedTotalCoolingCapacity(),
                                          pthp.nameString()) \
                        if coil.is_initialized() else None
                    self.add('ashp', kw, ['ZONAL'],
                             f"PTHP {pthp.nameString()} (zone ASHP class)", count=mult)
                elif equipment.to_ZoneHVACFourPipeFanCoil().is_initialized():
                    fc = equipment.to_ZoneHVACFourPipeFanCoil().get()
                    coil = fc.coolingCoil().to_CoilCoolingWater()
                    kw = self.capacity_kw(None, coil.get().autosizedDesignCoilLoad(),
                                          fc.nameString()) \
                        if coil.is_initialized() else None
                    self.add('FanCoil', kw, ['ZONAL'], f"fan coil {fc.nameString()}",
                             count=mult)
                elif equipment.to_ZoneHVACTerminalUnitVariableRefrigerantFlow().is_initialized():
                    term = equipment.to_ZoneHVACTerminalUnitVariableRefrigerantFlow().get()
                    coil = term.coolingCoil()
                    kw = None
                    if coil.is_initialized() and \
                            coil.get().to_CoilCoolingDXVariableRefrigerantFlow().is_initialized():
                        vrf = coil.get().to_CoilCoolingDXVariableRefrigerantFlow().get()
                        kw = self.capacity_kw(vrf.ratedTotalCoolingCapacity(),
                                              vrf.autosizedRatedTotalCoolingCapacity(),
                                              term.nameString())
                    self.add('VRF-CeilingMount', kw, ['ZONAL'],
                             f"VRF terminal {term.nameString()}", count=mult)
                elif equipment.to_ZoneHVACBaseboardConvectiveElectric().is_initialized():
                    bb = equipment.to_ZoneHVACBaseboardConvectiveElectric().get()
                    kw = self.capacity_kw(bb.nominalCapacity(),
                                          bb.autosizedNominalCapacity(),
                                          f"electric baseboard {bb.nameString()}")
                    self.cost_electric_baseboard(model, zone, kw, mult)
                elif equipment.to_ZoneHVACBaseboardConvectiveWater().is_initialized():
                    bb = equipment.to_ZoneHVACBaseboardConvectiveWater().get()
                    coil = bb.heatingCoil().to_CoilHeatingWaterBaseboard().get()
                    kw = self.optional_f(coil.heatingDesignCapacity())
                    if kw is None:
                        kw = self.optional_f(coil.autosizedHeatingDesignCapacity())
                    kw = self.sql_zone_heating_kw(model, zone.nameString()) \
                        if kw is None or kw == 0.0 else kw / 1000.0
                    if kw is None:
                        self.warnings.append(
                            f"no capacity available for hot water baseboard "
                            f"{bb.nameString()} (model not sized?) — item not costed")
                    else:
                        self.cost_hw_baseboard(model, zone, kw, mult)
                elif equipment.to_ZoneHVACUnitHeater().is_initialized():
                    heater = equipment.to_ZoneHVACUnitHeater().get()
                    gas = heater.heatingCoil().to_CoilHeatingGas().is_initialized()
                    kw = self.capacity_kw(
                        heater.heatingCoil().to_CoilHeatingGas().get().nominalCapacity(),
                        heater.heatingCoil().to_CoilHeatingGas().get().autosizedNominalCapacity(),
                        heater.nameString()) if gas else None
                    self.add('GasHeater' if gas else 'ElecUnitHeater', kw, ['ZONAL'],
                             f"unit heater {heater.nameString()}", count=mult)
                elif equipment.to_ZoneHVACWaterToAirHeatPump().is_initialized():
                    wshp = equipment.to_ZoneHVACWaterToAirHeatPump().get()
                    coil = wshp.coolingCoil().to_CoilCoolingWaterToAirHeatPumpEquationFit()
                    kw = self.capacity_kw(coil.get().ratedTotalCoolingCapacity(),
                                          coil.get().autosizedRatedTotalCoolingCapacity(),
                                          wshp.nameString()) \
                        if coil.is_initialized() else None
                    self.add('wshp', kw, ['ZONAL'], f"WSHP {wshp.nameString()}", count=mult)
                elif equipment.to_ZoneHVACEnergyRecoveryVentilator().is_initialized():
                    erv = equipment.to_ZoneHVACEnergyRecoveryVentilator().get()
                    cfm = self.optional_f(erv.supplyAirFlowRate())
                    if cfm is None:
                        cfm = self.optional_f(erv.autosizedSupplyAirFlowRate())
                    # m3/s -> cfm (ERV table sizes are cfm)
                    cfm = cfm * 2118.88 if cfm is not None else None
                    self.add('ERV', cfm, ['ZONAL'], f"zone ERV {erv.nameString()}",
                             count=mult)
                elif equipment.to_FanZoneExhaust().is_initialized():
                    continue  # exhaust fans not costed here

        for unit in sorted_by_name(model.getAirConditionerVariableRefrigerantFlows()):
            kw = self.capacity_kw(unit.grossRatedTotalCoolingCapacity(),
                                  unit.autosizedGrossRatedTotalCoolingCapacity(),
                                  unit.nameString())
            self.add('VRF-HP-Outdoor', kw, ['ZONAL'], f"VRF outdoor unit {unit.nameString()}")

    def legacy_unit_count(self, ratio):
        """Legacy convector-count rule: ratio rounds up only when the
        fractional part exceeds 0.10 (otherwise the fractional count is used
        as-is)."""
        return float(ruby_round(ratio + 0.5)) if (ratio - int(ratio)) > 0.10 else ratio

    def cost_hw_baseboard(self, model, zone, kw, mult):
        """Legacy zonalsys_costing 'Baseboard Convective Water': copper
        convector core at 0.425 kW/ft with an isolation valve, 2 tees and 2
        elbows per 8-ft convector, plus perimeter supply/return distribution
        piping along the exterior wall."""
        if kw is None or kw <= 0.0:
            return

        note = f"hot water baseboard {zone.nameString()}"
        conv_length = float(ruby_round(kw / 0.425))
        convectors = self.legacy_unit_count(conv_length / 8.0)
        self.add('ConvectCopper', 1.25, ['ZONAL'], f"{note} convector",
                 count=conv_length * mult)
        self.add('ValvesGate', 1.25, ['ZONAL'], f"{note} valves", count=convectors * mult)
        self.add('CopperPipeTee', 1.25, ['ZONAL'], f"{note} tees",
                 count=2 * convectors * mult)
        self.add('CopperPipeElbow', 1.25, ['ZONAL'], f"{note} elbows",
                 count=2 * convectors * mult)

        data = self.geo(model)
        if data is None or data['flr_height_ft'] <= 0.0:
            return

        perim_ft = geometry.zone_exterior_wall_area_ft2(zone) / data['flr_height_ft'] * mult
        self.add('SteelPipe', 1.25, ['ZONAL'], f"{note} perimeter piping", count=perim_ft)
        self.add('PipeInsulation', 1.25, ['ZONAL'], f"{note} perimeter pipe insulation",
                 count=perim_ft)

    def cost_electric_baseboard(self, model, zone, kw, mult):
        """Legacy zonalsys_costing 'Baseboard Convective Electric': 0.935 kW
        units, each with a junction box, plus perimeter wiring/conduit along
        the exterior wall."""
        if kw is None or kw <= 0.0:
            return

        note = f"electric baseboard {zone.nameString()}"
        units = self.legacy_unit_count(kw / 0.935)
        self.add('ElectricBaseboard', None, ['ZONAL'], note, count=units * mult)
        self.add('Box', 1, ['ZONAL'], f"{note} junction boxes", count=units * mult)

        data = self.geo(model)
        if data is None or data['flr_height_ft'] <= 0.0:
            return

        perim_ft = geometry.zone_exterior_wall_area_ft2(zone) / data['flr_height_ft'] * mult
        self.add('Conduit', None, ['ZONAL'], f"{note} perimeter conduit", count=perim_ft)
        self.add('Wiring', 10, ['ZONAL'], f"{note} perimeter wiring", count=perim_ft / 100.0)
