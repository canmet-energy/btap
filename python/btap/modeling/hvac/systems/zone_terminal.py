"""Self-ventilating per-zone terminal units (port of the generic prototype
model_add_ptac / model_add_pthp / model_add_window_ac topologies used by CBECS).
Unlike the NECB MAU+PTAC pattern, these units provide their own outdoor air —
there is no central ventilation loop.

config 'unit_type':
- 'ptac'      : PTAC, single-speed DX cooling, heating per 'heating_type'
                (None/'None' = always-off zero-capacity electric section — the CBECS
                "PTAC with baseboard X" pattern where baseboards do the heating),
                'Electric', or 'Water' (hw_loop)
- 'pthp'      : PTHP, DX heat + DX cool + electric supplemental
- 'window_ac' : cooling-only PTAC at EER 8.5 with a zero-capacity heat section
config 'baseboard_type': adds zone baseboards ('Electric'/'Hot Water'/'None')
"""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac.systems import baseboards
from btap.modeling.hvac.systems.base_system import BaseSystem

WINDOW_AC_EER = 8.5  # Btu/W-h (generic model_add_window_ac default)


class ZoneTerminal(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        """:return: list of openstudio.model.AirLoopHVAC — empty (no central air system)"""
        unit_type = self.config.get('unit_type', 'ptac')
        heating_type = self.config.get('heating_type', 'None')
        baseboard_type = self.config.get('baseboard_type', 'None')

        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)
            sz = zone.sizingZone()
            # 0.008 kg/kg design supply humidity ratios: legacy parity with the prototype
            # zone-terminal creators — model_add_ptac (Prototype.hvac_systems.rb:4067-4068)
            # and model_add_pthp (:4179-4180) set the same pair (also the common E+ sizing
            # default neighbourhood; legacy carries it bare).
            sz.setZoneCoolingDesignSupplyAirHumidityRatio(0.008)
            sz.setZoneHeatingDesignSupplyAirHumidityRatio(0.008)

            if unit_type == 'ptac':
                self._add_ptac(model, zone, heating_type, hw_loop)
            elif unit_type == 'pthp':
                self._add_pthp(model, zone)
            elif unit_type == 'window_ac':
                self._add_window_ac(model, zone)
            else:
                raise ValueError(f"unknown zone terminal unit_type '{unit_type}'")

            baseboards.add(model, zone, baseboard_type, hw_loop=hw_loop)
        return []

    def _no_heat_coil(self, model, zone):
        coil = openstudio.model.CoilHeatingElectric(model, model.alwaysOffDiscreteSchedule())
        coil.setName(f"{zone.nameString()} PTAC No Heat")
        coil.setNominalCapacity(0.0)
        return coil

    def _cycling_fan(self, model, zone, label):
        fan = openstudio.model.FanOnOff(model)
        fan.setName(f"{zone.nameString()} {label} Fan")
        fan.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule())
        return fan

    def _add_ptac(self, model, zone, heating_type, hw_loop):
        always_on = model.alwaysOnDiscreteSchedule()
        if heating_type in ('None', None):
            htg_coil = self._no_heat_coil(model, zone)
        elif heating_type in ('Electric', 'Electricity'):
            htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
            htg_coil.setName(f"{zone.nameString()} PTAC Electric Htg Coil")
        elif heating_type in ('Water', 'Hot Water'):
            if hw_loop is None:
                raise ValueError('a hot water loop is required for a Water PTAC coil')

            htg_coil = openstudio.model.CoilHeatingWater(model, always_on)
            htg_coil.setName(f"{zone.nameString()} PTAC Water Htg Coil")
            hw_loop.addDemandBranchForComponent(htg_coil)
        else:
            raise ValueError(f"'{heating_type}' is not a valid PTAC heating type")

        clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        clg_coil.setName(f"{zone.nameString()} PTAC 1spd DX AC Clg Coil")

        ptac = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
            model, always_on, self._cycling_fan(model, zone, 'PTAC'), htg_coil, clg_coil)
        ptac.setName(f"{zone.nameString()} PTAC")
        ptac.addToThermalZone(zone)   # ventilation: default OA (self-ventilating)
        return ptac

    def _add_pthp(self, model, zone):
        always_on = model.alwaysOnDiscreteSchedule()
        htg_coil = openstudio.model.CoilHeatingDXSingleSpeed(model)
        htg_coil.setName(f"{zone.nameString()} PTHP Htg Coil")
        clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        clg_coil.setName(f"{zone.nameString()} PTHP Clg Coil")
        supp_coil = openstudio.model.CoilHeatingElectric(model, always_on)
        supp_coil.setName(f"{zone.nameString()} PTHP Supp Htg Coil")

        pthp = openstudio.model.ZoneHVACPackagedTerminalHeatPump(
            model, always_on, self._cycling_fan(model, zone, 'PTHP'),
            htg_coil, clg_coil, supp_coil)
        pthp.setName(f"{zone.nameString()} PTHP")
        pthp.addToThermalZone(zone)
        return pthp

    def _add_window_ac(self, model, zone):
        always_on = model.alwaysOnDiscreteSchedule()
        clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        clg_coil.setName(f"{zone.nameString()} Window AC Clg Coil")
        clg_coil.setRatedCOP(openstudio.convert(WINDOW_AC_EER, 'Btu/h', 'W').get())

        ac = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
            model, always_on, self._cycling_fan(model, zone, 'Window AC'),
            self._no_heat_coil(model, zone), clg_coil)
        ac.setName(f"{zone.nameString()} Window AC")
        ac.addToThermalZone(zone)
        return ac
