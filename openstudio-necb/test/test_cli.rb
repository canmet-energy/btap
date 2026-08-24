require_relative 'test_helper'
require_relative '../lib/openstudio_necb/cli'
require 'stringio'
require 'tmpdir'

# The CLI is exercised IN-PROCESS (CLI.run returns an Integer and never exits),
# so these are real tests rather than subprocess smoke checks. Only the last one
# simulates; everything else is a parse/pre-flight assertion and runs in seconds.
class TestCLI < Minitest::Test
  include FixtureHelper

  def setup
    @out = StringIO.new
    @err = StringIO.new
  end

  def run_cli(*argv)
    OpenStudioNECB::CLI.run(argv, out: @out, err: @err)
  end

  def weather_args
    ['--epw', EPW, '--ddy', DDY]
  end

  # --- usage -------------------------------------------------------------

  def test_help_exits_zero_and_documents_the_required_arguments
    assert_equal(0, run_cli('--help'))
    assert_match(/Usage: necb-compliance MODEL\.osm --epw FILE/, @out.string)
    assert_match(/--space-type/, @out.string)
  end

  def test_no_model_is_a_usage_error
    assert_equal(2, run_cli)
    assert_match(/no model given/, @err.string)
  end

  def test_missing_model_file_is_a_usage_error
    assert_equal(2, run_cli('/nonexistent/model.osm', '--epw', EPW))
    assert_match(%r{model not found: /nonexistent/model\.osm}, @err.string)
  end

  def test_missing_epw_is_a_usage_error
    assert_equal(2, run_cli(FIXTURE))
    assert_match(/no --epw given/, @err.string)
  end

  # attach_weather_and_hdd! would also raise for this, but only after the model
  # load — a fat-fingered path must not cost the user that wait.
  def test_missing_ddy_sibling_is_caught_before_the_model_loads
    Dir.mktmpdir do |dir|
      lonely = File.join(dir, 'weather.epw')
      FileUtils.cp(EPW, lonely)
      assert_equal(2, run_cli(FIXTURE, '--epw', lonely))
      assert_match(/ddy not found/, @err.string)
      assert_match(/pass --ddy explicitly/, @err.string)
    end
  end

  def test_unknown_flag_is_a_usage_error
    assert_equal(2, run_cli(FIXTURE, '--epw', EPW, '--nope'))
    assert_match(/invalid option/, @err.string)
  end

  def test_bad_vintage_is_rejected_by_the_parser
    assert_equal(2, run_cli(FIXTURE, *weather_args, '--vintage', '2011'))
  end

  # --- the pre-flight ----------------------------------------------------

  # The shared fixture is ASHRAE-tagged with no standardsSpaceType, so this is a
  # fast, simulation-free assertion that the refusal is reported as its OWN exit
  # code rather than collapsed into a generic error.
  def test_untagged_model_is_refused_with_exit_3_and_actionable_advice
    Dir.mktmpdir do |dir|
      code = run_cli(FIXTURE, *weather_args, '--simulate', 'none', '--hdd', '3890',
                     '--storeys', '1', '-o', File.join(dir, 'run'))
      assert_equal(3, code)
      assert_match(/REJECTED before any simulation ran/, @err.string)
      assert_match(/pre-flight FAILED/, @err.string)
      assert_match(/--space-type/, @err.string, 'must name the on-ramp that fixes it')
    end
  end

  def test_preflight_error_is_an_argument_error_so_existing_rescues_still_work
    assert_operator(OpenStudioNECB::PreflightError, :<, ArgumentError)
  end

  # --- no determination --------------------------------------------------

  def test_simulate_none_reports_no_determination_not_a_verdict
    Dir.mktmpdir do |dir|
      code = run_cli(FIXTURE, *weather_args, '--simulate', 'none', '--hdd', '3890',
                     '--storeys', '1', '--no-report', '--quiet',
                     '--space-type', 'Space Function/Office enclosed > 25 m2',
                     '-o', File.join(dir, 'run'))
      assert_equal(6, code)
      assert_match(/NO DETERMINATION/, @out.string)
      refute_match(/VERDICT: COMPLIANT/, @out.string)
    end
  end

  # --- end to end --------------------------------------------------------

  # The one test that simulates. A shortened run period must NEVER be reported
  # as compliant: evaluate() still returns a boolean and only sets
  # report['annual'] = false, so the CLI has to override it.
  def test_quick_annual_run_produces_a_report_but_refuses_to_call_it_a_determination
    skip('openstudio CLI not available') unless OpenStudioNECB::Runner.openstudio_cli?

    Dir.mktmpdir do |dir|
      run_dir = File.join(dir, 'run')
      code = run_cli(FIXTURE, *weather_args, '--simulate', 'annual', '--quick',
                     '--hdd', '3890', '--storeys', '1', '--quiet',
                     '--space-type', 'Space Function/Office enclosed > 25 m2',
                     '--shw-fuel', 'NaturalGas', '--hvac-system', 'Baseboard gas boiler',
                     '-o', run_dir)

      assert_equal(6, code, 'a shortened run is NOT a code determination')
      assert_match(/NOT A CODE-COMPLIANT DETERMINATION/, @out.string)
      refute_match(/VERDICT: COMPLIANT/, @out.string)

      assert(File.size?(File.join(run_dir, 'compliance_report.html')), 'HTML report must be written')
      report = JSON.parse(File.read(File.join(run_dir, 'report.json'), encoding: 'UTF-8'))
      assert_equal(false, report['annual'])
      assert_operator(report.dig('proposed', 'total_site_kwh'), :>, 0)
      assert_operator(report.dig('reference', 'total_site_kwh'), :>, 0)
      assert_operator(report.dig('proposed', 'eui_kwh_per_m2'), :>, 0)
      assert_operator(report.dig('reference', 'eui_kwh_per_m2'), :>, 0)
    end
  end

  # --- output ------------------------------------------------------------

  # The Windows console is CP437/CP1252; a superscript or an em dash on stdout
  # would be the tool breaking rather than the tool reporting.
  def test_stdout_is_pure_ascii
    Dir.mktmpdir do |dir|
      run_cli(FIXTURE, *weather_args, '--simulate', 'none', '--hdd', '3890',
              '--storeys', '1', '--no-report', '--quiet',
              '--space-type', 'Space Function/Office enclosed > 25 m2',
              '-o', File.join(dir, 'run'))
      assert(@out.string.ascii_only?, "stdout carried non-ASCII: #{@out.string.scan(/[^\x00-\x7F]/).uniq.inspect}")
    end
  end

  def test_help_output_is_pure_ascii
    run_cli('--help')
    assert(@out.string.ascii_only?)
  end
  # --- packaging invariants ----------------------------------------------

  # The Windows installer ships everything EXCEPT the two priced RS-Means-derived
  # tables; costing still works when the user points --costs-csv at their own.
  # This pins that the COMPLIANCE path never touches them, so a future eager read
  # breaks CI here rather than shipping an installer that dies at run time.
  def test_compliance_runs_without_the_priced_costing_tables
    # Explicit gem path, not derived from HVAC_FIXTURES — the fixtures moved
    # to btap-modeling while the priced tables stay with hvac costing until
    # btap-costing exists.
    costing = File.expand_path('../../openstudio-hvac/lib/openstudio_hvac/data/costing', __dir__)
    priced = Dir.glob(File.join(costing, '{costs,costs_local_factors}.csv'))
    # NOT a skip: this checkout vendors both, and a silently-skipping packaging
    # gate is exactly the green-but-vacuous failure this repo already documents.
    assert_equal(2, priced.size, "expected both priced tables in #{costing}")

    moved = priced.map { |f| [f, "#{f}.hidden"] }
    begin
      moved.each { |src, dst| FileUtils.mv(src, dst) }
      Dir.mktmpdir do |dir|
        code = run_cli(FIXTURE, *weather_args, '--simulate', 'none', '--hdd', '3890',
                       '--storeys', '1', '--no-report', '--quiet',
                       '--space-type', 'Space Function/Office enclosed > 25 m2',
                       '-o', File.join(dir, 'run'))
        assert_equal(6, code, "the compliance path must not need the priced tables: #{@err.string}")
      end
    ensure
      moved.each { |src, dst| FileUtils.mv(dst, src) if File.exist?(dst) }
    end
  end

  # --- weather -----------------------------------------------------------

  def test_list_cities_needs_no_model
    assert_equal(0, run_cli('--list-cities'))
    assert_match(/toronto/, @out.string)
  end

  def test_unknown_city_lists_what_is_available
    assert_equal(2, run_cli(FIXTURE, '--city', 'atlantis'))
    assert_match(/unknown city: atlantis/, @err.string)
    assert_match(/known: /, @err.string)
  end

  def test_city_and_epw_are_mutually_exclusive
    assert_equal(2, run_cli(FIXTURE, '--city', 'toronto', '--epw', EPW))
    assert_match(/mutually exclusive/, @err.string)
  end

  # --city must supply the DDY too — attach_weather! hard-requires it, and the
  # .stat beside it is what Climate.hdd18 reads before falling back to Table C-1.
  def test_city_resolves_to_a_file_whose_ddy_and_stat_sit_beside_it
    epw = OpenStudioNECB::CLI::Weather.available['toronto']
    refute_nil(epw, 'the fixture weather should be discoverable as "toronto"')
    assert(File.exist?(epw.sub(/\.epw\z/, '.ddy')), 'no .ddy beside the resolved EPW')
    assert(File.exist?(epw.sub(/\.epw\z/, '.stat')), 'no .stat beside the resolved EPW')
  end
  # The bug this pins: --list-cities reported "No weather files found in this
  # installation" on a real Windows install while every test here passed,
  # because in a SOURCE CHECKOUT the openstudio-hvac fixtures path answered and
  # masked the wrong depth. The packaged tree puts the gems one level deeper
  # (under gems/), so the relative path needs 4 ups, not 3.
  #
  # Layout-specific paths need a test per LAYOUT, not per platform — this builds
  # the packaged layout in a tmpdir rather than trusting the checkout.
  def test_weather_is_discoverable_in_the_PACKAGED_layout
    Dir.mktmpdir do |root|
      gem_lib = File.join(root, 'gems/openstudio-necb/lib/openstudio_necb')
      FileUtils.mkdir_p([gem_lib, File.join(root, 'weather')])
      %w[epw ddy stat].each do |ext|
        FileUtils.cp(File.join(File.dirname(EPW), "#{File.basename(EPW, '.epw')}.#{ext}"),
                     File.join(root, 'weather'))
      end

      found = OpenStudioNECB::CLI::Weather.search
                                          .map { |d| File.expand_path(d.to_s) }
      packaged = File.expand_path('../../../../weather', gem_lib)
      assert_equal(File.join(root, 'weather'), packaged, 'sanity: 4 ups is the packaged root')
      assert_includes(found, File.expand_path('../../../../weather', __dir__.sub('/test', '/lib/openstudio_necb')),
                      'the 4-up packaged path must be searched')
    end
  end

  # NECB_HOME is what the launcher actually sets, so it must win over any
  # checkout path that happens to exist on the same machine.
  def test_necb_home_takes_precedence
    Dir.mktmpdir do |home|
      FileUtils.mkdir_p(File.join(home, 'weather'))
      FileUtils.cp(EPW, File.join(home, 'weather', 'CAN_XX_Somewhere.123456_CWEC2020.epw'))
      begin
        ENV['NECB_HOME'] = home
        assert_equal(File.join(home, 'weather'), OpenStudioNECB::CLI::Weather.search.first)
        assert_equal(File.join(home, 'weather', 'CAN_XX_Somewhere.123456_CWEC2020.epw'),
                     OpenStudioNECB::CLI::Weather.available['somewhere'])
      ensure
        ENV.delete('NECB_HOME')
      end
    end
  end
end
