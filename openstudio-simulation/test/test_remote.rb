require 'tmpdir'
require_relative 'test_helper'

# The whole Remote backend, exercised OFFLINE through an injected transport.
# Nothing here touches the network, so it runs in CI like any other test.
class TestRemote < Minitest::Test
  include FixtureHelper

  Remote = OpenStudioSimulation::Remote

  # Records every call and replays canned responses. Deliberately not a mock
  # library — the seam is four methods wide.
  class FakeTransport
    attr_reader :calls

    def initialize(status: 'completed', fail_times: 0, files: nil)
      @calls = []
      @status = status
      @fail_times = fail_times
      @files = files
    end

    def post_json(url, body)
      @calls << [:post, url, body]
      if url.end_with?('/models')
        raise('503 Service Unavailable') if (@fail_times -= 1) >= 0

        { 'model_id' => 'm-1', 'upload_url' => 'https://s3.test/put', 's3_key' => 'k' }
      else
        { 'job_id' => 'j-1', 'status' => 'submitted' }
      end
    end

    def get_json(url)
      @calls << [:get, url]
      return { 'status' => @status, 'phases' => [{ 'errors' => ['boom'] }] } unless url.end_with?('/results')

      { 'files' => @files || { 'eplusout.sql' => 'https://s3.test/sql',
                               'eplusout.err' => 'https://s3.test/err' } }
    end

    def put_bytes(url, bytes)
      @calls << [:put, url, bytes.bytesize]
    end

    def get_bytes(url)
      @calls << [:getb, url]
      url.end_with?('sql') ? 'SQLITE-BYTES' : 'EnergyPlus Completed Successfully'
    end
  end

  def prepared_dir(tmp)
    dir = File.join(tmp, 'run')
    FileUtils.mkdir_p(dir)
    model = load_fixture
    model.save(OpenStudio::Path.new(File.join(dir, 'in.osm')), true)
    dir
  end

  def test_unconfigured_backend_names_both_variables
    e = assert_raises(RuntimeError) { Remote.new.execute('/tmp') }
    assert_match(/HBIX_SIM_ENDPOINT/, e.message)
    assert_match(/HBIX_API_KEY/, e.message)
  end

  def test_happy_path_lands_both_artifacts_locally
    Dir.mktmpdir do |tmp|
      dir = prepared_dir(tmp)
      t = FakeTransport.new
      Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t,
                 weather_station_id: 'CAN_ON_Toronto', poll_seconds: 0).execute(dir)

      assert_equal('SQLITE-BYTES', File.read(File.join(dir, 'run', 'eplusout.sql')))
      assert_match(/Completed Successfully/, File.read(File.join(dir, 'run', 'eplusout.err')))
    end
  end

  # The default workflow translates in-process and uploads an IDF, so the
  # remote only has to match our EnergyPlus, not our OpenStudio.
  def test_default_workflow_uploads_a_translated_idf
    Dir.mktmpdir do |tmp|
      dir = prepared_dir(tmp)
      t = FakeTransport.new
      Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t, poll_seconds: 0).execute(dir)

      register = t.calls.find { |c| c[0] == :post && c[1].end_with?('/models') }
      assert_equal('in.idf', register[2][:filename])
      assert(File.exist?(File.join(dir, 'in.idf')), 'the IDF should be left beside in.osm')

      submit = t.calls.find { |c| c[0] == :post && c[1].end_with?('/simulations') }
      assert_equal('energyplus', submit[2][:workflow_type])
    end
  end

  def test_openstudio_workflow_uploads_the_osm_instead
    Dir.mktmpdir do |tmp|
      dir = prepared_dir(tmp)
      t = FakeTransport.new
      Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t,
                 workflow_type: 'openstudio', poll_seconds: 0).execute(dir)

      assert_equal('in.osm', t.calls.find { |c| c[0] == :post && c[1].end_with?('/models') }[2][:filename])
    end
  end

  # engine_version must be sent explicitly; relying on the platform default is
  # how a 25.2 model ends up on a 3.9 runner and dies opaquely.
  def test_engine_version_is_always_sent_and_defaults_to_the_local_energyplus
    Dir.mktmpdir do |tmp|
      t = FakeTransport.new
      Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t, poll_seconds: 0)
            .execute(prepared_dir(tmp))
      submitted = t.calls.find { |c| c[0] == :post && c[1].end_with?('/simulations') }[2][:engine_version]
      refute_nil(submitted)
      assert_equal(OpenStudio.energyPlusVersion.to_s.split('.').first(2).join('.'), submitted)
    end
  end

  # Translation is forward-only. Asking for an older engine must fail in
  # milliseconds, not 20 minutes into a queued run.
  def test_requesting_an_older_engine_is_refused_before_upload
    Dir.mktmpdir do |tmp|
      t = FakeTransport.new
      e = assert_raises(RuntimeError) do
        Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t,
                   engine_version: '9.1', poll_seconds: 0).execute(prepared_dir(tmp))
      end
      assert_match(/forward-only/, e.message)
      assert(t.calls.none? { |c| c[0] == :put }, 'must refuse BEFORE uploading anything')
    end
  end

  def test_transient_503_on_submit_is_retried
    Dir.mktmpdir do |tmp|
      t = FakeTransport.new(fail_times: 2)
      Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t, poll_seconds: 0)
            .execute(prepared_dir(tmp))
      assert_operator(t.calls.count { |c| c[0] == :post && c[1].end_with?('/models') }, :>=, 3)
    end
  end

  def test_failed_status_raises_with_the_phase_errors
    Dir.mktmpdir do |tmp|
      t = FakeTransport.new(status: 'failed')
      e = assert_raises(RuntimeError) do
        Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t, poll_seconds: 0)
              .execute(prepared_dir(tmp))
      end
      assert_match(/remote run failed/, e.message)
      assert_match(/boom/, e.message, 'the phase errors are the diagnostic')
    end
  end

  def test_missing_sql_in_the_result_bundle_raises
    Dir.mktmpdir do |tmp|
      t = FakeTransport.new(files: { 'eplusout.err' => 'https://s3.test/err' })
      e = assert_raises(RuntimeError) do
        Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t, poll_seconds: 0)
              .execute(prepared_dir(tmp))
      end
      assert_match(/no eplusout\.sql/, e.message)
    end
  end

  def test_timeout_is_bounded
    Dir.mktmpdir do |tmp|
      t = FakeTransport.new(status: 'running')
      e = assert_raises(RuntimeError) do
        Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: t,
                   poll_seconds: 0, timeout_seconds: -1).execute(prepared_dir(tmp))
      end
      assert_match(/did not finish within/, e.message)
    end
  end

  # The credential must never reach a message a user can paste into a ticket.
  def test_api_key_never_appears_in_an_error_message
    Dir.mktmpdir do |tmp|
      secret = 'super-secret-key-do-not-leak'
      t = FakeTransport.new(status: 'failed')
      e = assert_raises(RuntimeError) do
        Remote.new(endpoint: 'https://svc.test', api_key: secret, transport: t, poll_seconds: 0)
              .execute(prepared_dir(tmp))
      end
      refute_match(/#{secret}/, e.message)
    end
  end

  def test_missing_in_osm_is_reported_as_a_contract_violation
    Dir.mktmpdir do |tmp|
      e = assert_raises(RuntimeError) do
        Remote.new(endpoint: 'https://svc.test', api_key: 'k', transport: FakeTransport.new).execute(tmp)
      end
      assert_match(/in\.osm is missing/, e.message)
    end
  end
end
