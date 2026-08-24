require 'tmpdir'
require_relative 'test_helper'

# Proves the execution abstraction / local-vs-cloud seam WITHOUT EnergyPlus:
# the runner prepares the dir, then delegates to an injected backend.
class TestBackends < Minitest::Test
  include FixtureHelper

  Runner = BtapSimulation::Runner
  Backend = BtapSimulation::Backend
  Local = BtapSimulation::Local
  Remote = BtapSimulation::Remote

  # A test backend: asserts the runner prepared the dir, records the call, and
  # lands the two artifacts the contract requires (canned, no E+).
  class FakeBackend < Backend
    attr_reader :called_with

    def initialize(test)
      super()
      @test = test
      @called_with = nil
    end

    def execute(dir)
      # Contract precondition: the runner must have written in.osm + in.osw
      # BEFORE handing the dir to the backend.
      @test.assert File.exist?("#{dir}/in.osm"), 'backend called before in.osm written'
      @test.assert File.exist?("#{dir}/in.osw"), 'backend called before in.osw written'
      @called_with = dir
      FileUtils.mkdir_p("#{dir}/run")
      File.write("#{dir}/run/eplusout.err", "EnergyPlus Completed Successfully\n")
      File.write("#{dir}/run/eplusout.sql", '') # placeholder — no results parsed here
      nil
    end
  end

  def run_dir(name)
    File.join('/tmp/claude-1000/-workspaces-openstudio-standards/14d4ffe0-7e76-41d2-9609-bba51763b608/scratchpad',
              'sim_backends', name)
  end

  def setup
    FileUtils.rm_rf(run_dir(''))
  end

  # Dependency injection: a custom backend is invoked, and only after the runner
  # has written in.osm + in.osw into the prepared dir.
  def test_custom_backend_is_invoked_with_prepared_dir
    model = load_fixture
    dir = run_dir('custom')
    fake = FakeBackend.new(self)

    result = Runner.run_energyplus!(model, dir, sizing_only: true, backend: fake)

    assert_equal dir, fake.called_with, 'backend.execute was not called with the run dir'
    assert File.exist?("#{dir}/in.osm"), 'runner did not write in.osm'
    assert File.exist?("#{dir}/in.osw"), 'runner did not write in.osw'
    assert_equal "#{dir}/run", result
    assert Runner.clean_run?(result), 'clean_run? should read the canned err'
  end

  # The facade uses the injected backend too, and returns a Result.
  def test_facade_uses_injected_backend
    model = load_fixture
    dir = run_dir('facade')
    fake = FakeBackend.new(self)

    result = BtapSimulation.run(model, run_dir: dir, sizing_only: true, backend: fake)

    assert_equal dir, fake.called_with
    assert_instance_of BtapSimulation::Result, result
    assert result.clean?
    assert_nil result.energy, 'sizing_only run has no energy results'
    assert_nil result.unmet_hours, 'sizing_only run has no unmet hours'
  end

  # Local is the DEFAULT backend when none is injected. Stub Local#execute to
  # observe it without needing the CLI.
  def test_local_is_the_default_backend
    model = load_fixture
    dir = run_dir('default')
    called = false
    test = self

    Local.class_eval do
      alias_method :__orig_execute, :execute
      define_method(:execute) do |d|
        called = true
        test.assert File.exist?("#{d}/in.osw"), 'default backend called before in.osw written'
        FileUtils.mkdir_p("#{d}/run")
        File.write("#{d}/run/eplusout.err", "EnergyPlus Completed Successfully\n")
        File.write("#{d}/run/eplusout.sql", '')
        nil
      end
    end
    begin
      Runner.run_energyplus!(model, dir, sizing_only: true) # no backend: arg
    ensure
      Local.class_eval do
        alias_method :execute, :__orig_execute
        remove_method :__orig_execute
      end
    end

    assert called, 'default backend was not an BtapSimulation::Local instance'
  end

  # --- Windows portability, pinned by Linux tests -------------------------
  #
  # There is no Windows CI job, so these are what keep the Windows fixes from
  # rotting. Each one fails against the pre-fix code on Linux too.

  # `openstudio_cli_path` must prefer an explicit override, then ask the SDK for
  # the absolute path of the binary that loaded it. The SDK answer is the only
  # one that works on Windows, where the CLI is not reliably on PATH.
  def test_cli_path_prefers_the_explicit_override
    with_env('OPENSTUDIO_CLI', '/somewhere/openstudio.exe') do
      assert_equal('/somewhere/openstudio.exe', BtapSimulation.openstudio_cli_path)
    end
  end

  def test_cli_path_falls_back_to_the_sdk_absolute_path
    with_env('OPENSTUDIO_CLI', nil) do
      path = BtapSimulation.openstudio_cli_path
      skip('SDK too old to answer getOpenStudioCLI') if path == 'openstudio'
      assert(File.exist?(path), "SDK reported a CLI path that does not exist: #{path}")
      assert(File.absolute_path?(path), 'must be absolute — PATH is not searched on Windows')
    end
  end

  # A blank override must not win over the SDK — an empty env var is how a
  # launcher script spells "unset", and treating it as a path yields the
  # baffling "tried ''" message.
  def test_blank_override_is_ignored
    with_env('OPENSTUDIO_CLI', '') do
      refute_equal('', BtapSimulation.openstudio_cli_path)
    end
  end

  def test_missing_cli_is_reported_with_the_path_it_tried
    with_env('OPENSTUDIO_CLI', '/nonexistent/openstudio') do
      backend = Local.new
      refute(backend.openstudio_cli?)
      e = assert_raises(RuntimeError) { backend.execute(Dir.mktmpdir) }
      assert_match(%r{/nonexistent/openstudio}, e.message, 'must name what it tried')
      assert_match(/OPENSTUDIO_CLI/, e.message, 'must name the escape hatch')
    end
  end

  # THE quoting regression. The old shell string interpolated `dir` unquoted, so
  # `-w /path/with space/in.osw` split into two arguments and `-w` received a
  # truncated path — silently, with the cli.log redirect landing in a stray file
  # named after the first half. Windows paths contain spaces as a matter of
  # course (C:\Program Files\...), so this is the fix that matters most there.
  def test_run_directory_containing_a_space_still_simulates
    skip('openstudio CLI not available') unless Runner.openstudio_cli?

    Dir.mktmpdir do |tmp|
      dir = File.join(tmp, 'a directory with spaces', 'run')
      model = load_fixture
      Runner.attach_weather!(model, epw: EPW, ddy: DDY)
      run_dir = Runner.run_energyplus!(model, dir, sizing_only: true)

      assert(File.exist?(File.join(run_dir, 'eplusout.sql')), 'no SQL — the path split')
      assert(Runner.clean_run?(run_dir))
      assert(File.exist?(File.join(dir, 'cli.log')), 'cli.log landed outside the run dir')
    end
  end

  def with_env(key, value)
    had = ENV.key?(key)
    previous = ENV[key]
    value.nil? ? ENV.delete(key) : ENV[key] = value
    # Both probes memoize, and the memo outlives an env change within a process.
    Runner.instance_variable_set(:@openstudio_cli, nil)
    yield
  ensure
    had ? ENV[key] = previous : ENV.delete(key)
    Runner.instance_variable_set(:@openstudio_cli, nil)
  end

  # The abstraction's base class documents the interface by raising.
  def test_backend_base_execute_raises_not_implemented
    err = assert_raises(NotImplementedError) { Backend.new.execute('/nope') }
    assert_match(/execute/, err.message)
  end

  # Remote is implemented now (see test_remote.rb for the transport-level
  # coverage). Here we only pin the two things the SEAM guarantees: it obeys the
  # same "dir must already be prepared" contract as Local, and it refuses to run
  # unconfigured rather than emitting a confusing network error.
  def test_remote_requires_a_prepared_directory
    remote = Remote.new(endpoint: 'https://example.test', api_key: 'k')
    err = assert_raises(RuntimeError) { remote.execute('/nope') }
    assert_match(/in\.osm is missing/, err.message)
  end

  def test_remote_without_configuration_refuses_before_touching_the_network
    err = assert_raises(RuntimeError) { Remote.new(endpoint: nil, api_key: nil).execute('/nope') }
    assert_match(/not configured/, err.message)
  end

  # Sanity: Local and Remote really are Backends (the seam is polymorphic).
  def test_backends_share_the_interface
    assert Local.new.is_a?(Backend)
    assert Remote.new.is_a?(Backend)
    assert_respond_to Local.new, :execute
    assert_respond_to Remote.new, :execute
  end
end
