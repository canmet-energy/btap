"""P3 E2E gate: a model with the full prescriptive envelope applied (U-values
+ FDWR windows + SRR skylights) must run in EnergyPlus with no Fatal/Severe.

Port of btap-necb/test/test_envelope_e2e_run.rb. The Ruby test drove the
openstudio CLI through FixtureHelper#run_energyplus!; here the same sizing run
goes through btap.simulation's Local backend, whose ``is_clean()`` is the
ported ``assert_clean_energyplus_run`` (completed, no Fatal, no Severe).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.necb.support import DDY, EPW, load_raw_fixture
from tests.support import needs_engine


def attach_weather(model):
    """Ruby FixtureHelper#attach_weather! — EPW only; btap.simulation.run
    attaches the EPW/DDY pair itself via its ``weather=`` argument, so this
    exists purely so HDD resolves from the model before the run."""
    import openstudio

    epw = openstudio.EpwFile(openstudio.path(str(EPW)))
    openstudio.model.WeatherFile.setWeatherFile(model, epw)
    return model


@needs_engine
class TestE2ERun(unittest.TestCase):
    def test_prescriptive_envelope_sizes_cleanly(self):
        from btap.necb import envelope
        from btap.simulation import run

        model = attach_weather(load_raw_fixture())
        audit = envelope.apply_prescriptive(model, vintage='2020',
                                            apply_fdwr=True, apply_srr=True)
        self.assertTrue(audit.entries)

        # ideal-air so the run exercises envelope only
        for z in model.getThermalZones():
            z.setUseIdealAirLoads(True)
        with tempfile.TemporaryDirectory(prefix='osenv-e2e-') as tmp:
            result = run(model, run_dir=str(Path(tmp) / 'prescriptive'),
                         weather={'epw': str(EPW), 'ddy': str(DDY)}, sizing_only=True)
            self.assertTrue(result.is_clean(),
                            'prescriptive envelope (U + FDWR + SRR)')


if __name__ == '__main__':
    unittest.main()
