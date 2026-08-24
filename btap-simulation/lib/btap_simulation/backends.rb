require 'net/http'
require 'uri'
require 'json'
require 'fileutils'

module BtapSimulation
  module_function

  # Absolute path of the `openstudio` CLI, resolved in this order:
  #
  #   1. ENV['OPENSTUDIO_CLI'] — the explicit escape hatch.
  #   2. OpenStudio.getOpenStudioCLI — the SDK knows the absolute path of the
  #      binary that loaded it. Correct on every platform, immune to PATH, and
  #      the only thing that works on Windows, where the installer does not
  #      reliably put itself on PATH (and where a bundled private copy is not
  #      on PATH by design).
  #   3. the bare name, off PATH — the historical behaviour, kept as a fallback
  #      for an SDK too old to answer.
  #
  # @return [String]
  def openstudio_cli_path
    explicit = ENV.fetch('OPENSTUDIO_CLI', nil)
    return explicit unless explicit.nil? || explicit.empty?

    if defined?(OpenStudio) && OpenStudio.respond_to?(:getOpenStudioCLI)
      path = OpenStudio.getOpenStudioCLI.to_s
      return path if !path.empty? && File.exist?(path)
    end
    'openstudio'
  end

  # Execution backends — the seam between "prepare a run directory" (the
  # backend-agnostic Runner) and "actually run EnergyPlus" (here).
  #
  # The Runner writes `dir/in.osm` + `dir/in.osw` into a run directory, then
  # hands that directory to a Backend. A backend's job is narrow and precise:
  # execute the simulation so that, on return, BOTH
  #   * `dir/run/eplusout.sql`  (results — parsed by Runner.energy_results)
  #   * `dir/run/eplusout.err`  (E+ log — parsed by Runner.clean_run?)
  # exist. On any failure the backend must raise.
  #
  # This is the local-vs-cloud seam: swap `Local` (the `openstudio` CLI on this
  # machine) for `Remote` (a remote/AWS EnergyPlus service) without the Runner,
  # the facade, or any consumer changing.
  class Backend
    # Execute the simulation for a prepared run directory.
    #
    # @param dir [String] a run directory already containing `in.osm` + `in.osw`
    # @return [void] — must leave `dir/run/eplusout.sql` and
    #   `dir/run/eplusout.err` in place; must raise on failure.
    def execute(_dir)
      raise(NotImplementedError, "#{self.class}#execute(dir) must run EnergyPlus and " \
                                 'produce dir/run/eplusout.sql + dir/run/eplusout.err')
    end
  end

  # Local execution via the `openstudio` CLI on this machine — exactly the
  # command the runner has always used. This is the default backend.
  class Local < Backend
    # @return [Boolean] is the `openstudio` CLI runnable?
    #
    # ARGV form, not a shell string: `> /dev/null` is a POSIX-ism that Windows
    # cmd cannot resolve, so the old probe reported "no CLI" on Windows even
    # when the CLI was right there. File::NULL is the portable spelling.
    def openstudio_cli?
      if @openstudio_cli.nil?
        @openstudio_cli = system(BtapSimulation.openstudio_cli_path, 'openstudio_version',
                                 out: File::NULL, err: File::NULL)
      end
      @openstudio_cli
    end

    def execute(dir)
      cli = BtapSimulation.openstudio_cli_path
      raise("openstudio CLI not available (tried #{cli}) — set OPENSTUDIO_CLI to its full path") unless openstudio_cli?

      # ARGV form again, and for a second reason: the old shell string
      # interpolated `dir` UNQUOTED, so any path containing a space — which on
      # Windows is the norm (C:\Program Files\..., C:\Users\Jane Smith\...) —
      # split into multiple arguments. No shell means no quoting to get wrong,
      # no metacharacter surface, and no redirection syntax to be portable about.
      ok = system(cli, 'run', '-w', File.join(dir, 'in.osw'),
                  out: File.join(dir, 'cli.log'), err: [:child, :out])
      err_path = "#{dir}/run/eplusout.err"
      raise("EnergyPlus run failed in #{dir} and wrote no eplusout.err — see #{dir}/cli.log") unless File.exist?(err_path)
      return nil if ok

      # The Fatal line is usually the useless 'final processing' one — the
      # SEVERE lines above it carry the cause. Surface both, plus the path.
      err = File.read(err_path)
      severes = err.scan(/^\s*\*\* Severe {2}\*\*.*(?:\n\s*\*\* {3}~~~ {3}\*\*.*)*/)
      fatal = err[/^.*Fatal.*$/]
      detail = (severes.first(5) + [fatal]).compact.join("\n").strip
      detail = err[-800..] || err if detail.empty?
      raise("EnergyPlus run failed in #{dir}:\n#{detail}\n(full log: #{err_path})")
    end
  end

  # Remote/cloud execution — a DOCUMENTED STUB awaiting a real endpoint spec.
  #
  # This is the intended extension point for running EnergyPlus against a
  # provided remote service (e.g. an AWS API) instead of the local CLI. The
  # contract is identical to every other backend: given a `dir` that already
  # contains `in.osm` + `in.osw`, run the simulation remotely and land
  # `dir/run/eplusout.sql` and `dir/run/eplusout.err` back on the local disk.
  #
  # The skeleton below is modelled on a REAL service observed this session — an
  # AWS-Batch EnergyPlus/OpenStudio runner (the "hbix" simulation API, region
  # ca-central-1) whose flow is:
  #
  #   upload_model(filename)      -> { model_id, upload_url (presigned S3 PUT), s3_key }
  #   PUT the model bytes to upload_url                       (direct to S3)
  #   submit_simulation(model_id, weather_station_id,         -> { job_id, status, phases }
  #                     weather_format, workflow_type,
  #                     engine_version, queue)
  #   get_simulation_status(job_id) / get_simulation_progress(job_id)
  #                                                           (poll: pending|running|failed|completed)
  #   get_simulation_results(job_id)                          -> presigned download URLs (~15 min TTL)
  #
  # HARD-WON NOTES from validating that service live:
  #   * ENGINE VERSION MUST MATCH THE MODEL. Neither OpenStudio nor EnergyPlus
  #     translates *backward*. A model saved by OpenStudio 3.11 / EnergyPlus 25.2
  #     fails instantly ("Essential container exited (exit code 1)") on the
  #     platform-default OpenStudio 3.9 runner. Submit an IDF/OSM whose version
  #     an available remote engine can open — pass `engine_version:` explicitly
  #     (e.g. '25.2') rather than relying on the platform "latest" default.
  #   * The `openstudio` workflow is 2-phase (measures 3.x -> energyplus 24/25.x);
  #     the `energyplus` workflow is 1-phase and takes a translated IDF directly.
  #   * The service is async on AWS Batch — expect a cold-start before the phase
  #     leaves `submitted`; poll on a backoff, don't tight-loop.
  #
  # We deliberately do NOT ship a working client: the MCP that surfaced this API
  # is agent-facing, so the raw REST endpoints + auth headers behind it are not
  # ours to hardcode. Supply `endpoint:`/`api_key:` for the service's HTTP API
  # and fill in the transport.
  class Remote < Backend
    # @param endpoint [String, nil] base URL of the remote simulation service
    # @param api_key [String, nil] credential for the service
    # @param opts [Hash] transport options — e.g. weather_station_id:,
    #   weather_format:, workflow_type: ('energyplus'|'openstudio'),
    #   engine_version: (MUST match the model — see class notes), queue:,
    #   poll_seconds:, region:
    def initialize(endpoint: nil, api_key: nil, **opts)
      super()
      @endpoint = endpoint
      @api_key = api_key
      @opts = opts
    end

    # @param endpoint [String, nil] base URL of the remote simulation service
    #   (falls back to HBIX_SIM_ENDPOINT, then OS_SIM_REMOTE_ENDPOINT)
    # @param api_key [String, nil] credential (falls back to HBIX_API_KEY, then
    #   OS_SIM_REMOTE_API_KEY). NEVER logged, echoed, or put in a raised message.
    # @param transport [#post_json, #get_json, #put_bytes, #get_bytes, nil] the
    #   HTTP seam. Injected by the tests so the whole backend is exercisable
    #   offline; nil builds the real Net::HTTP one.
    # @param opts [Hash] weather_station_id:, weather_format:, workflow_type:
    #   ('energyplus' default, or 'openstudio'), engine_version: (MUST match the
    #   model — see the class notes), queue:, poll_seconds:, timeout_seconds:,
    #   station_map: {epw basename => station id}
    def initialize(endpoint: nil, api_key: nil, transport: nil, **opts)
      super()
      @endpoint = (endpoint || ENV['HBIX_SIM_ENDPOINT'] || ENV.fetch('OS_SIM_REMOTE_ENDPOINT', nil))&.chomp('/')
      @api_key = api_key || ENV['HBIX_API_KEY'] || ENV.fetch('OS_SIM_REMOTE_API_KEY', nil)
      @opts = opts
      @transport = transport || Http.new(@api_key)
    end

    # @return [Boolean] is this backend configured enough to try?
    def configured?
      !(@endpoint.nil? || @endpoint.empty? || @api_key.nil? || @api_key.empty?)
    end

    def execute(dir)
      unless configured?
        raise('remote backend is not configured: set HBIX_SIM_ENDPOINT and HBIX_API_KEY ' \
              '(or pass endpoint:/api_key:)')
      end

      payload, filename = prepare_payload(dir)
      guard_engine_version!
      model_id = upload(payload, filename)
      job_id = submit(model_id)
      poll(job_id)
      download(job_id, dir)
      nil
    end

    private

    # The 1-phase `energyplus` workflow is the default: translate in-process
    # with the SDK's ForwardTranslator and upload an IDF. That sidesteps the
    # OSM-version wall entirely — the remote only has to match our EnergyPlus,
    # not our OpenStudio. `workflow_type: 'openstudio'` uploads the OSM instead
    # and leans on the remote's 2-phase workflow.
    def prepare_payload(dir)
      osm = File.join(dir, 'in.osm')
      raise("remote backend: #{osm} is missing — the runner did not prepare this dir") unless File.exist?(osm)
      return [File.binread(osm), 'in.osm'] if workflow_type == 'openstudio'

      model = OpenStudio::Model::Model.load(OpenStudio::Path.new(osm))
      raise("remote backend: cannot load #{osm}") if model.empty?

      idf = OpenStudio::EnergyPlus::ForwardTranslator.new.translateModel(model.get)
      path = File.join(dir, 'in.idf')
      idf.save(OpenStudio::Path.new(path), true)
      [File.binread(path), 'in.idf']
    end

    # Neither OpenStudio nor EnergyPlus translates BACKWARD. Submitting a 25.2
    # model to a 24.x runner dies instantly with an opaque container error, ~20
    # minutes of queue time after you stop watching. Catch it here, in
    # milliseconds, with an explanation.
    def guard_engine_version!
      requested = engine_version
      local = OpenStudio.energyPlusVersion.to_s
      return if requested.nil? || local.empty?

      want = requested.split('.').first(2).map(&:to_i)
      have = local.split('.').first(2).map(&:to_i)
      return unless (want <=> have) == -1

      raise("remote engine_version #{requested} is OLDER than the EnergyPlus that wrote this model " \
            "(#{local}). Translation is forward-only — the run would fail on the runner. " \
            'Request an engine that matches, or generate the model with the older SDK.')
    end

    def upload(bytes, filename)
      reg = with_retry('upload') { @transport.post_json("#{@endpoint}/models", { filename: filename }) }
      url = reg['upload_url'] || reg[:upload_url]
      id = reg['model_id'] || reg[:model_id]
      raise("remote upload registration returned no upload_url (host #{host})") if url.nil?

      with_retry('upload-put') { @transport.put_bytes(url, bytes) }
      id
    end

    def submit(model_id)
      body = { model_id: model_id,
               weather_station_id: station_id,
               weather_format: @opts.fetch(:weather_format, 'CWEC2020'),
               workflow_type: workflow_type,
               engine_version: engine_version,
               queue: @opts.fetch(:queue, 'auto') }.compact
      job = with_retry('submit') { @transport.post_json("#{@endpoint}/simulations", body) }
      id = job['job_id'] || job[:job_id]
      raise("remote submit returned no job_id (host #{host})") if id.nil?

      id
    end

    # Async on AWS Batch: a cold start before the phase leaves `submitted` is
    # normal. Poll on a fixed interval with a hard deadline, and tolerate a
    # transient read error rather than abandoning a running job.
    def poll(job_id)
      deadline = Time.now + @opts.fetch(:timeout_seconds, 3600)
      interval = @opts.fetch(:poll_seconds, 15)
      loop do
        raise("remote job #{job_id} did not finish within #{@opts.fetch(:timeout_seconds, 3600)}s") if Time.now > deadline

        status = begin
          @transport.get_json("#{@endpoint}/simulations/#{job_id}")
        rescue StandardError
          nil # transient — the job is still out there; try again next tick
        end
        state = (status && (status['status'] || status[:status])).to_s
        raise("remote run failed: #{phase_errors(status)}") if state == 'failed'
        return if state == 'completed'

        sleep(interval)
      end
    end

    # Presigned result URLs carry a ~15-minute TTL, so fetch both artifacts
    # immediately rather than stashing the URLs.
    def download(job_id, dir)
      res = with_retry('results') { @transport.get_json("#{@endpoint}/simulations/#{job_id}/results") }
      files = res['files'] || res[:files] || {}
      FileUtils.mkdir_p(File.join(dir, 'run'))
      %w[eplusout.sql eplusout.err].each do |name|
        url = files[name] || files[name.to_sym]
        next if url.nil?

        File.binwrite(File.join(dir, 'run', name), @transport.get_bytes(url))
      end
      sql = File.join(dir, 'run', 'eplusout.sql')
      return if File.size?(sql)

      raise("remote run #{job_id} produced no eplusout.sql — the contract needs it for results parsing")
    end

    # Submits transiently 503 after a service deploy or an idle period; that is
    # not "the service is down". Exponential backoff, then give up loudly.
    def with_retry(what, attempts: 5)
      delay = 1
      begin
        yield
      rescue StandardError => e
        attempts -= 1
        raise("remote #{what} failed against #{host}: #{e.message}") if attempts <= 0

        sleep(delay)
        delay *= 2
        retry
      end
    end

    def phase_errors(status)
      Array(status && (status['phases'] || status[:phases]))
        .flat_map { |p| Array(p['errors'] || p[:errors]) }.compact.first(5).join('; ')
    end

    def workflow_type = @opts.fetch(:workflow_type, 'energyplus')
    def engine_version = @opts[:engine_version] || OpenStudio.energyPlusVersion.to_s.split('.').first(2).join('.')

    # The service resolves weather from its own library by station id; arbitrary
    # local EPWs are not uploadable on this path (documented, out of scope).
    def station_id
      @opts[:weather_station_id] || @opts.dig(:station_map, :default)
    end

    # Never put @api_key in a message — errors name the host only.
    def host
      URI(@endpoint.to_s).host || @endpoint.to_s
    rescue StandardError
      'the configured endpoint'
    end

    # The default transport. Isolated so tests never touch the network.
    class Http
      def initialize(api_key) = @api_key = api_key

      def post_json(url, body) = json(request(:post, url, body: JSON.generate(body), json: true))
      def get_json(url) = json(request(:get, url))
      def get_bytes(url) = request(:get, url, auth: false).body
      def put_bytes(url, bytes) = request(:put, url, body: bytes, auth: false)

      private

      def json(response) = JSON.parse(response.body.to_s)

      def request(method, url, body: nil, json: false, auth: true)
        uri = URI(url)
        klass = { get: Net::HTTP::Get, post: Net::HTTP::Post, put: Net::HTTP::Put }.fetch(method)
        req = klass.new(uri)
        req['X-API-Key'] = @api_key if auth && @api_key
        req['Content-Type'] = 'application/json' if json
        req.body = body if body
        res = Net::HTTP.start(uri.hostname, uri.port, use_ssl: uri.scheme == 'https') { |http| http.request(req) }
        raise("HTTP #{res.code}") unless res.is_a?(Net::HTTPSuccess)

        res
      end
    end
  end
end
