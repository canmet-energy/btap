require 'minitest/autorun'
require 'fileutils'
require_relative '../lib/btap_costing'

module FixtureHelper
  # Fixtures shared from btap-modeling (monorepo incubation).
  FIXTURE = File.expand_path('../../btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm', __dir__)
  EPW = File.expand_path('../../btap-modeling/test/fixtures/weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw', __dir__)
  DDY = File.expand_path('../../btap-modeling/test/fixtures/weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy', __dir__)

  OFFICE = ['Space Function', 'Office enclosed > 25 m2'].freeze

  def load_fixture
    OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get
  end

  # fixture tagged office everywhere (offices carry SHW peak flows)
  def tagged_model
    model = load_fixture
    map = model.getSpaces.to_h { |s| [s.nameString, OFFICE] }
    BtapNECB::Loads.assign_space_types(model, map, vintage: '2020')
    model
  end

  def openstudio_cli?
    @openstudio_cli = system('openstudio openstudio_version > /dev/null 2>&1') if @openstudio_cli.nil?
    @openstudio_cli
  end

  def attach_weather!(model)
    epw = OpenStudio::EpwFile.new(OpenStudio::Path.new(EPW))
    OpenStudio::Model::WeatherFile.setWeatherFile(model, epw)
    ddy = OpenStudio::EnergyPlus.loadAndTranslateIdf(DDY).get
    ddy.getDesignDays.each { |dd| model.addObject(dd.clone) }
    model
  end

  def run_energyplus!(model, dir, sizing_only: true)
    FileUtils.mkdir_p(dir)
    sim = model.getSimulationControl
    sim.setDoZoneSizingCalculation(true)
    sim.setDoSystemSizingCalculation(true)
    sim.setDoPlantSizingCalculation(true)
    sim.setRunSimulationforSizingPeriods(true)
    sim.setRunSimulationforWeatherFileRunPeriods(!sizing_only)
    unless sizing_only
      run_period = model.getRunPeriod
      run_period.setBeginMonth(1)
      run_period.setBeginDayOfMonth(1)
      run_period.setEndMonth(1)
      run_period.setEndDayOfMonth(7)
    end
    model.save("#{dir}/in.osm", true)
    osw = OpenStudio::WorkflowJSON.new
    osw.setSeedFile("#{dir}/in.osm")
    osw.saveAs("#{dir}/in.osw")
    ok = system("openstudio run -w #{dir}/in.osw > #{dir}/cli.log 2>&1")
    err = File.exist?("#{dir}/run/eplusout.err") ? File.read("#{dir}/run/eplusout.err") : '(no eplusout.err)'
    raise("E+ run failed in #{dir}:\n#{err[/^.*Fatal.*$/] || err[-800..] || err}") unless ok

    model.setSqlFile(OpenStudio::SqlFile.new(OpenStudio::Path.new("#{dir}/run/eplusout.sql")))
    "#{dir}/run"
  end

  def assert_clean_energyplus_run(run_dir, context)
    err = File.read("#{run_dir}/eplusout.err")
    refute_match(/\*\*\s*Fatal\s*\*\*/, err, "#{context}: E+ fatal error")
    severe = err.scan(/\*\* Severe  \*\*(.*)$/).flatten
    assert_empty severe, "#{context}: E+ severe errors:\n#{severe.join("\n")}"
    assert_match(/EnergyPlus Completed Successfully/, err, "#{context}: E+ did not complete")
  end
end

# The e2e costing tests drive costing THROUGH the host-gem facades (hvac,
# envelope, shw, loads). Those gems still exist as siblings until their
# remainders fold into btap-necb; these requires (and the tests' facade
# tokens) get rewritten by that fold.
[
  '../../btap-necb/lib/btap_necb',
].each { |rel| require File.expand_path(rel, __dir__) }
