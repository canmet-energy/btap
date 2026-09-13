"""Engine regression for D-89's part-load tables: what EnergyPlus DOES with
them, measured, not read off the source. Skips without a provisioned engine.

Three facts the decision rests on, each one probe:
1. a positive boiler-curve output is used UNCLAMPED (a constant 0.005 curve
   burns exactly 1/(eta x 0.005) per unit heat) — there is no 0.01 floor;
2. the shipped BOILER-PLF-NONCONDENSING table gives fuel = heat / (eta x
   PLF(PLR)) at an ordinary part load, i.e. the Code's Fuel_design x FHeatPLC;
3. at a load far below the old first node (PLR 0.00005) the zero node keeps
   the engine on the Code equation: fuel/heat matches FHeatPLC(p)/(eta x p).
"""

from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

import openstudio

from btap.codes.necb.hvac import efficiency
from btap.simulation import engine
from tests.support import EPW, needs_engine

ETA = 0.9
CAPACITY_W = 100_000.0


def fheatplc(coefficients, plr):
    return sum(c * plr ** i for i, c in enumerate(coefficients))


def boiler_model(load_w, curve_factory, capacity_w=CAPACITY_W):
    """One hot-water loop: a boiler at CAPACITY_W and a LoadProfile:Plant at a
    fixed load, so the boiler runs at a known part-load ratio all day."""
    m = openstudio.model.Model()
    always = openstudio.model.ScheduleConstant(m)
    always.setValue(1.0)
    load = openstudio.model.ScheduleConstant(m)
    load.setValue(load_w)
    loop = openstudio.model.PlantLoop(m)
    loop.setName('Probe HW Loop')
    sizing = loop.sizingPlant()
    sizing.setLoopType('Heating')
    sizing.setDesignLoopExitTemperature(82.0)
    sizing.setLoopDesignTemperatureDifference(16.0)
    boiler = openstudio.model.BoilerHotWater(m)
    boiler.setName('Probe Boiler')
    boiler.setFuelType('NaturalGas')
    boiler.setNominalCapacity(capacity_w)
    boiler.setNominalThermalEfficiency(ETA)
    boiler.setDesignWaterFlowRate(0.002)
    boiler.setMinimumPartLoadRatio(0.0)
    boiler.setMaximumPartLoadRatio(1.0)
    boiler.setBoilerFlowMode('ConstantFlow')
    boiler.setEfficiencyCurveTemperatureEvaluationVariable('EnteringBoiler')
    boiler.setNormalizedBoilerEfficiencyCurve(curve_factory(m))
    loop.addSupplyBranchForComponent(boiler)
    pump = openstudio.model.PumpConstantSpeed(m)
    pump.setRatedFlowRate(0.002)
    pump.setRatedPumpHead(1000.0)
    pump.addToNode(loop.supplyInletNode())
    setpoint = openstudio.model.ScheduleConstant(m)
    setpoint.setValue(82.0)
    spm = openstudio.model.SetpointManagerScheduled(m, setpoint)
    spm.addToNode(loop.supplyOutletNode())
    profile = openstudio.model.LoadProfilePlant(m)
    profile.setLoadSchedule(load)
    profile.setPeakFlowRate(0.002)
    profile.setFlowRateFractionSchedule(always)
    loop.addDemandBranchForComponent(profile)
    for name in ('Boiler NaturalGas Energy', 'Boiler Heating Energy'):
        ov = openstudio.model.OutputVariable(name, m)
        ov.setReportingFrequency('RunPeriod')
    return m, boiler


def constant_curve(value):
    def factory(m):
        k = openstudio.model.CurveQuadratic(m)
        k.setName('CONST')
        k.setCoefficient1Constant(value)
        k.setCoefficient2x(0.0)
        k.setCoefficient3xPOW2(0.0)
        k.setMinimumValueofx(0.0)
        k.setMaximumValueofx(1.0)
        return k
    return factory


def shipped_table(name='BOILER-PLF-NONCONDENSING', edition='2020'):
    def factory(m):
        return efficiency.curve(m, efficiency.data(edition), name)
    return factory


def run_period_totals(out_dir):
    sql = sqlite3.connect(str(Path(out_dir) / 'eplusout.sql'))
    env = sql.execute("select EnvironmentPeriodIndex from EnvironmentPeriods "
                      "where EnvironmentType=3").fetchone()[0]

    def total(name):
        idx = sql.execute("select ReportDataDictionaryIndex from ReportDataDictionary "
                          "where Name=?", (name,)).fetchone()[0]
        return sql.execute("select sum(d.Value) from ReportData d join Time t on "
                           "d.TimeIndex=t.TimeIndex where d.ReportDataDictionaryIndex=? "
                           "and t.EnvironmentPeriodIndex=?", (idx, env)).fetchone()[0]
    return total('Boiler Heating Energy'), total('Boiler NaturalGas Energy')


@needs_engine
class TestPartLoadTablesInTheEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _gas_per_heat(self, tag, load_w, factory, capacity_w=CAPACITY_W):
        """(gas/heat, actual PLR). The PLR is taken from the heat the boiler
        actually delivered (the pump adds ~2 W to the loop, which at a 100 W
        load is 2 % of the part-load ratio), not from the nominal load."""
        """Forward-translate and run the engine directly, sizing off: nothing
        here is autosized and a zone-less loop has no design environments for
        the plant-sizing pass btap.simulation.runner always requests."""
        model, _ = boiler_model(load_w, factory, capacity_w)
        control = model.getSimulationControl()
        control.setDoZoneSizingCalculation(False)
        control.setDoSystemSizingCalculation(False)
        control.setDoPlantSizingCalculation(False)
        control.setRunSimulationforSizingPeriods(False)
        control.setRunSimulationforWeatherFileRunPeriods(True)
        period = model.getRunPeriod()
        period.setBeginMonth(1)
        period.setBeginDayOfMonth(1)
        period.setEndMonth(1)
        period.setEndDayOfMonth(2)
        run_dir = Path(self.tmp.name) / tag
        run_dir.mkdir(parents=True)
        idf = run_dir / 'in.idf'
        idf.write_text(str(openstudio.energyplus.ForwardTranslator().translateModel(model)),
                       encoding='utf-8')
        out = run_dir / 'out'
        proc = subprocess.run([str(engine.ensure_energyplus()), '-w', str(EPW), '-d', str(out),
                               str(idf)], capture_output=True, text=True, check=False)
        err = (out / 'eplusout.err').read_text(encoding='utf-8', errors='replace') \
            if (out / 'eplusout.err').exists() else proc.stdout + proc.stderr
        self.assertEqual(0, proc.returncode, f'{tag}: EnergyPlus failed\n{err[-2000:]}')
        self.assertNotIn('** Severe', err, f'{tag}: severe errors\n{err[-2000:]}')
        heat, gas = run_period_totals(out)
        self.assertGreater(heat, 0, f'{tag}: the boiler delivered no heat')
        seconds = 2 * 24 * 3600  # the two-day run period
        return gas / heat, heat / (capacity_w * seconds)

    def test_a_positive_curve_output_is_used_unclamped(self):
        ratio, _ = self._gas_per_heat('const005', 20_000.0, constant_curve(0.005))
        self.assertAlmostEqual(1.0 / (ETA * 0.005), ratio, delta=0.01 * ratio,
                               msg='a 0.005 multiplier is applied as 0.005, not floored to 0.01')

    def test_the_shipped_table_is_the_code_equation_at_part_load(self):
        coefficients = next(e for e in efficiency.data('2020')['part_load_fheatplc']
                            if e['equipment'] == 'boiler' and e['class'] == 'non_condensing'
                            )['coefficients']
        ratio, plr = self._gas_per_heat('plr020', 0.20 * CAPACITY_W, shipped_table())
        self.assertAlmostEqual(0.20, plr, delta=0.01)
        expected = fheatplc(coefficients, plr) / (ETA * plr)  # Fuel_design x FHeatPLC / heat
        self.assertAlmostEqual(expected, ratio, delta=0.01 * expected)

    def test_the_zero_node_keeps_the_engine_on_the_equation_at_a_tiny_load(self):
        coefficients = next(e for e in efficiency.data('2020')['part_load_fheatplc']
                            if e['equipment'] == 'boiler' and e['class'] == 'non_condensing'
                            )['coefficients']
        # a 2 MW boiler at 100 W: PLR 0.00005, below the 0.0001 first node of
        # the previous freeze (a 5 W load on a 100 kW boiler never registers
        # as a plant load, so the ratio is reached through capacity)
        capacity = 2_000_000.0
        ratio, plr = self._gas_per_heat('plr00005', 0.00005 * capacity, shipped_table(), capacity)
        self.assertLess(plr, 0.0001, 'the case sits below the previous first node')
        self.assertGreater(plr, 0.00002)
        expected = fheatplc(coefficients, plr) / (ETA * plr)
        self.assertAlmostEqual(expected, ratio, delta=0.02 * expected,
                               msg='the standby term a x Fuel_design is charged at a load '
                                   'of 0.005 % of capacity')
