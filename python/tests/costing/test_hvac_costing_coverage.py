"""Port of btap-costing/test/test_hvac_costing_coverage.rb.

C3 coverage gate: every family produces an itemized cost (or explained
warnings) — costing is available to ALL systems and families, not just
NECB/ECM."""

import unittest

import btap.modeling as modeling
from btap.costing.hvac import report as hvac_report
from tests.costing.support import load_fixture, needs_sdk

REPRESENTATIVES = {
    'baseboards': 'Baseboard gas boiler',
    'psz': 'PSZ RTU Gas and DX Coils and Electric Baseboard',
    'vav_reheat': 'MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard',
    'fan_coils': 'FPFC MAU DX Coils with Scroll Chiller',
    'mau_ptac': 'PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC',
    'zone_terminal': 'PTHP',
    'unit_heaters': 'Gas unit heaters',
    'furnace': 'Forced air furnace',
    'evap_cooler': 'Direct evap coolers with no heat',
    'wshp': 'Water source heat pumps',
    'doas': 'DOAS ventilation only',
    'vrf': 'VRF',
    'zone_ervs': 'Zone ERVs',
    'doas_pthp': 'hs11_ashp_pthp',
    'ecm_ashp_baseboard': 'hs12_ashp_baseboard',
    'ecm_doas_vrf': 'hs08_ccashp_vrf',
    'ecm_hp_fancoils': 'hs15_cawhp_fancoils',
}


def hard_size(model):
    for al in model.getAirLoopHVACs():
        al.setDesignSupplyAirFlowRate(2.0)
    for b in model.getBoilerHotWaters():
        b.setNominalCapacity(60_000.0)
    for c in model.getChillerElectricEIRs():
        c.setReferenceCapacity(100_000.0)
    for p in list(model.getPumpConstantSpeeds()) + list(model.getPumpVariableSpeeds()):
        p.setRatedPowerConsumption(1000.0)
    for c in model.getCoilCoolingDXSingleSpeeds():
        c.setRatedTotalCoolingCapacity(20_000.0)
    for c in model.getCoilCoolingDXVariableRefrigerantFlows():
        c.setRatedTotalCoolingCapacity(5_000.0)
    for u in model.getAirConditionerVariableRefrigerantFlows():
        u.setGrossRatedTotalCoolingCapacity(40_000.0)
    for c in model.getCoilHeatingGass():
        c.setNominalCapacity(15_000.0)
    for c in model.getCoilHeatingElectrics():
        c.setNominalCapacity(10_000.0)
    for c in model.getCoilHeatingWaterBaseboards():
        c.setHeatingDesignCapacity(4_000.0)
    for c in model.getCoilCoolingWaterToAirHeatPumpEquationFits():
        c.setRatedTotalCoolingCapacity(6_000.0)
    for h in model.getHeatPumpPlantLoopEIRHeatings():
        h.setReferenceCapacity(80_000.0)
    for h in model.getHeatPumpWaterToWaterEquationFitHeatings():
        h.setRatedHeatingCapacity(80_000.0)
    for e in model.getZoneHVACEnergyRecoveryVentilators():
        e.setSupplyAirFlowRate(0.5)


@needs_sdk
class TestCostingCoverage(unittest.TestCase):
    def test_every_family_produces_an_itemized_cost(self):
        from btap._compat import sorted_by_name

        failures = []
        for family, name in REPRESENTATIVES.items():
            try:
                model = load_fixture()
                zones = sorted_by_name(model.getThermalZones())
                result = modeling.build_system(model, name, zones)
                hard_size(model)
                report = hvac_report.cost(model, systems=[result], city='TORONTO',
                                          province_state='ONTARIO')

                if not report.items:
                    failures.append(f"{family} ({name}): no items")
                if not report.total > 0:
                    failures.append(f"{family} ({name}): zero total")
            except Exception as e:  # noqa: BLE001 — Ruby rescued StandardError
                failures.append(f"{family} ({name}): {type(e).__name__} {e}")
        self.assertEqual([], failures, '\n'.join(failures))


if __name__ == '__main__':
    unittest.main()
