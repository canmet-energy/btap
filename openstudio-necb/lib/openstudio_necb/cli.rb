require 'optparse'
require 'fileutils'
require 'json'

module OpenStudioNECB
  # The command-line face of Compliance.performance_compliance: one .osm in, a
  # verdict + EUIs + a self-contained HTML report out.
  #
  # All logic lives here rather than in exe/necb-compliance so it is testable
  # IN-PROCESS against StringIO — a subprocess test of a 40-minute pipeline is
  # not a test anyone runs. `run` returns an Integer and never calls exit; the
  # shim does that.
  module CLI
    module_function

    # Exit codes are load-bearing: "your building fails the code", "your file is
    # not NECB-tagged" and "EnergyPlus crashed" have three different fixes, and
    # a demo audience hits all three. Collapsing them into 1 would be a lie.
    EXIT = {
      compliant: 0,        # 8.4.1.2 satisfied
      not_compliant: 1,    # a VERDICT, not an error
      usage: 2,            # bad flag, missing file, unresolvable HDD
      preflight: 3,        # the model was rejected before any simulation ran
      simulation: 4,       # EnergyPlus severe/fatal, or no CLI
      internal: 5,         # anything unanticipated
      no_determination: 6  # --quick, --simulate sizing|none, or compliant.nil?
    }.freeze

    QUICK_RUN_PERIOD = { begin_month: 1, begin_day: 1, end_month: 1, end_day: 7 }.freeze

    def run(argv, out: $stdout, err: $stderr)
      opts, early = parse(argv, out, err)
      return early if early

      backend_problem = select_backend(opts)
      if backend_problem
        err.puts("ERROR: #{backend_problem}")
        return EXIT[:usage]
      end

      ticker = Progress.start(opts[:run_dir], out) unless opts[:quiet] || opts[:json]
      begin
        model, kwargs = compliance_kwargs(opts)
        result = OpenStudioNECB.performance_compliance(model, **kwargs)
        Progress.stop(ticker)
        emit(result, opts, out)
        verdict_exit(result)
      rescue PreflightError => e
        Progress.stop(ticker)
        preflight_help(e, opts, err)
        EXIT[:preflight]
      rescue ArgumentError => e
        Progress.stop(ticker)
        err.puts("ERROR: #{e.message}")
        EXIT[:usage]
      rescue StandardError => e
        Progress.stop(ticker)
        # Local#execute already extracts the E+ severe/fatal blocks and names
        # the log; reprint it verbatim rather than paraphrasing it worse.
        simulation = e.message.include?('EnergyPlus') || e.message.include?('openstudio CLI')
        err.puts("ERROR: #{e.message}")
        err.puts(audit_note(opts[:run_dir]))
        simulation ? EXIT[:simulation] : EXIT[:internal]
      end
    ensure
      Progress.stop(ticker) if ticker
    end

    # ---------------------------------------------------------------- parsing

    # @return [[Hash, nil], [nil, Integer]] options, or an early exit code
    def parse(argv, out, err)
      o = { vintage: '2020', simulate: :annual, report_html: true, backend: 'local',
            report_options: {}, necb_loads: {} }
      parser = build_parser(o, out)
      begin
        rest = parser.parse(argv)
      rescue OptionParser::ParseError => e
        err.puts("ERROR: #{e.message}")
        err.puts(parser.help)
        return [nil, EXIT[:usage]]
      end
      return [nil, EXIT[:compliant]] if o[:_printed]

      # Informational, like --help: answering "what weather do I have?" must not
      # require a model the user has not chosen yet.
      if o[:list_cities]
        out.puts(Weather.catalogue_text)
        return [nil, EXIT[:compliant]]
      end

      o[:model] = rest.shift
      unless o[:model]
        err.puts('ERROR: no model given.')
        err.puts(parser.help)
        return [nil, EXIT[:usage]]
      end
      unless rest.empty?
        err.puts("ERROR: unexpected extra argument(s): #{rest.join(' ')}")
        return [nil, EXIT[:usage]]
      end

      problem = Weather.resolve!(o) || validate(o)
      if problem
        err.puts("ERROR: #{problem}")
        return [nil, EXIT[:usage]]
      end
      o[:run_dir] ||= File.join(Dir.pwd, "necb_run_#{File.basename(o[:model], '.osm')}")
      [o, nil]
    end

    def build_parser(o, out)
      OptionParser.new do |p|
        p.banner = "Usage: necb-compliance MODEL.osm --epw FILE [options]\n\n" \
                   "NECB Part 8 performance-path compliance: runs the proposed and reference\n" \
                   "buildings and reports the 8.4.1.2 determination.\n\n"
        p.on('--epw PATH', 'weather file (required unless --simulate none)') { |v| o[:epw] = v }
        p.on('--ddy PATH', 'design-day file (default: the .ddy beside --epw)') { |v| o[:ddy] = v }
        p.on('--hdd N', Float, 'heating degree-days (default: from the EPW site)') { |v| o[:hdd] = v }
        p.on('--city NAME', 'bundled/cached city instead of --epw (--list-cities to see them)') { |v| o[:city] = v }
        p.on('--list-cities', 'list the weather files this install carries') { o[:list_cities] = true }
        p.on('-o', '--out DIR', 'run directory (default: ./necb_run_<model>)') { |v| o[:run_dir] = v }
        p.on('--vintage V', %w[2020 2025], 'NECB vintage: 2020 or 2025 (default 2020)') { |v| o[:vintage] = v }
        p.on('--storeys N', Integer, 'above-ground storey count override') { |v| o[:storeys] = v }
        p.on('--simulate MODE', %w[annual sizing none], 'annual (default), sizing, or none') { |v| o[:simulate] = v.to_sym }
        p.on('--quick', 'one-week run period - NOT a code determination') { o[:quick] = true }
        p.on('--backend B', %w[local remote], 'local (default) or remote') { |v| o[:backend] = v }
        p.on('--no-report', 'skip the HTML report') { o[:report_html] = false }
        p.on('--json', 'machine-readable output on stdout') { o[:json] = true }
        p.on('--quiet', 'no progress ticker') { o[:quiet] = true }

        p.separator("\nSpace types - required when the model is not already NECB-tagged:")
        p.on('--space-type SPEC', '"BuildingType/SpaceType" applied to every floor-area space') { |v| o[:space_type] = v }
        p.on('--space-type-map FILE', 'JSON {"space name": ["BuildingType","SpaceType"]}') { |v| o[:space_type_map] = v }
        p.on('--shw-fuel FUEL', 'service-water fuel, e.g. NaturalGas') { |v| o[:necb_loads][:shw_fuel] = v }
        p.on('--hvac-system NAME', 'proposed HVAC from the catalog') { |v| o[:necb_loads][:hvac_system] = v }

        p.separator("\nCosting - priced tables are not shipped; point at your own:")
        p.on('--costs-csv PATH', 'licensed unit-cost table') { |v| o[:costs_csv] = v }

        p.separator("\nReport header:")
        { project: :project_name, address: :address, permit: :permit_number,
          'prepared-by': :prepared_by, por: :professional_of_record, date: :date }.each do |flag, key|
          p.on("--#{flag} VALUE") { |v| o[:report_options][key] = v }
        end

        p.separator('')
        p.on('-h', '--help') { out.puts(p.help); o[:_printed] = true }
        p.on('--version') { out.puts("necb-compliance #{OpenStudioNECB::VERSION rescue 'dev'}"); o[:_printed] = true }
      end
    end

    # Everything catchable BEFORE the 2-minute model load. attach_weather_and_hdd!
    # raises for a missing epw/ddy too, but only after load_and_validate! has
    # run — a user who fat-fingered a path should not wait for that.
    def validate(o)
      return "model not found: #{o[:model]}" unless File.exist?(o[:model].to_s)
      return nil if o[:simulate] == :none

      return 'no --epw given (required unless --simulate none)' unless o[:epw]
      return "epw not found: #{o[:epw]}" unless File.exist?(o[:epw])

      o[:ddy] ||= o[:epw].sub(/\.epw\z/i, '.ddy')
      unless File.exist?(o[:ddy])
        return "ddy not found: #{o[:ddy]}\n       " \
               'a design-day file is required; pass --ddy explicitly if it is not beside the .epw'
      end
      return "costs csv not found: #{o[:costs_csv]}" if o[:costs_csv] && !File.exist?(o[:costs_csv])
      return "space-type map not found: #{o[:space_type_map]}" if o[:space_type_map] && !File.exist?(o[:space_type_map])

      nil
    end

    # ------------------------------------------------------------- marshalling

    # @return [[String, OpenStudio::Model::Model], Hash] `model` is POSITIONAL on
    #   performance_compliance, so it cannot ride in the kwargs splat.
    def compliance_kwargs(o)
      kw = { vintage: o[:vintage], run_dir: o[:run_dir],
             simulate: o[:simulate], report_html: o[:report_html],
             report_options: default_report_options(o) }
      kw[:weather] = { epw: o[:epw], ddy: o[:ddy] } if o[:epw]
      kw[:hdd] = o[:hdd] if o[:hdd]
      kw[:building] = { storeys: o[:storeys] } if o[:storeys]
      kw[:run_period] = QUICK_RUN_PERIOD if o[:quick]
      kw[:costs_csv] = o[:costs_csv] if o[:costs_csv]
      kw[:costing] = true if o[:costs_csv]
      loads = necb_loads(o)
      kw[:necb_loads] = loads if loads
      [model_argument(o), kw]
    end

    # A path string is enough UNLESS we have to enumerate space names to build
    # the map, in which case load once here and hand over the Model — load_model
    # takes either, and this avoids a second VersionTranslator pass.
    def model_argument(o)
      return o[:model] unless o[:space_type]

      OpenStudio::OSVersion::VersionTranslator.new
                                              .loadModel(OpenStudio::Path.new(o[:model])).get
    end

    def necb_loads(o)
      map = if o[:space_type_map]
              JSON.parse(File.read(o[:space_type_map], encoding: 'UTF-8'))
            elsif o[:space_type]
              bt, st = o[:space_type].split('/', 2)
              raise(ArgumentError, '--space-type must be "BuildingType/SpaceType"') if st.nil? || st.empty?

              # partofTotalFloorArea matches what validate_space_types! checks;
              # mapping plenums would be noise the pre-flight ignores anyway.
              model_argument(o).getSpaces.select(&:partofTotalFloorArea)
                               .to_h { |s| [s.nameString, [bt, st]] }
            end
      return nil if map.nil? && o[:necb_loads].empty?
      return nil if map.nil?

      o[:necb_loads].merge(space_type_map: map)
    end

    def default_report_options(o)
      ro = o[:report_options].dup
      ro[:date] ||= Time.now.strftime('%Y-%m-%d')
      ro[:project_name] ||= File.basename(o[:model], '.osm')
      ro
    end

    # `performance_compliance` takes no backend: the umbrella calls
    # run_energyplus! at ~8 sites, so the selection is a process-wide default
    # set once here rather than a parameter threaded through every phase.
    #
    # @return [String, nil] an error message, or nil on success
    def select_backend(o)
      return nil unless o[:backend] == 'remote'

      remote = OpenStudioSimulation::Remote.new
      unless remote.configured?
        return '--backend remote needs HBIX_SIM_ENDPOINT and HBIX_API_KEY in the environment'
      end

      OpenStudioSimulation::Runner.default_backend = remote
      nil
    end

    # ---------------------------------------------------------------- output

    def verdict_exit(result)
      return EXIT[:no_determination] if result.compliant.nil?
      return EXIT[:no_determination] if result.report['annual'] == false

      result.compliant ? EXIT[:compliant] : EXIT[:not_compliant]
    end

    def emit(result, o, out)
      return out.puts(JSON.pretty_generate(json_payload(result, o))) if o[:json]

      rep = result.report
      out.puts('')
      out.puts(energy_table(rep))
      out.puts(verdict_block(result, rep))
      out.puts(artifact_block(result, o))
    end

    def json_payload(result, o)
      rep = result.report
      { 'compliant' => result.compliant, 'annual' => rep['annual'],
        'determination' => determination(result, rep),
        'vintage' => rep['vintage'], 'hdd' => rep['hdd'],
        'tier' => rep['tier'], 'percent_of_target' => rep['percent_of_target'],
        'proposed' => slice_energy(rep['proposed']), 'reference' => slice_energy(rep['reference']),
        'run_dir' => result.run_dir,
        'report_html' => (File.join(result.run_dir, 'compliance_report.html') if o[:report_html]),
        'warnings' => Array(result.audit&.entries).count { |e| e[:level] == :warning } }
    end

    def slice_energy(section)
      return {} unless section

      section.slice('total_site_kwh', 'eui_kwh_per_m2', 'floor_area_m2',
                    'unmet_occupied_hours', 'clean_run')
    end

    # ASCII only, deliberately: the Windows console is CP437/CP1252 and this
    # tool must not be the thing that breaks. 'kWh/m2', never 'kWh/m2' with a
    # superscript.
    def energy_table(rep)
      p_sec = rep['proposed'] || {}
      r_sec = rep['reference'] || {}
      rule = '-' * 66
      lines = [rule, format('%-12s %14s %14s %12s', '', 'site kWh', 'kWh/m2/yr', 'area m2')]
      lines << row('Proposed', p_sec)
      lines << row('Reference', r_sec) unless r_sec.empty?
      lines << margin_line(p_sec, r_sec, rep)
      lines << unmet_line(p_sec, r_sec)
      (lines.compact << rule).join("\n")
    end

    def row(label, sec)
      format('%-12s %14s %14s %12s', label,
             num(sec['total_site_kwh']), num(sec['eui_kwh_per_m2']), num(sec['floor_area_m2']))
    end

    # 8.4.1.2.(2) is decided on TOTAL SITE ENERGY, not EUI — Compliance.evaluate
    # compares total_site_kwh. Both are printed above, but the margin (the number
    # the verdict rests on) must be the one the code test actually used.
    def margin_line(p_sec, r_sec, rep)
      pk = p_sec['total_site_kwh']
      rk = r_sec['total_site_kwh']
      return nil unless pk && rk && rk.positive?

      pct = (100.0 * (rk - pk) / rk).round(1)
      tier = rep['tier'] ? "   Tier #{rep['tier']}" : ''
      format('%-12s %14s   %s%s', 'Margin', num((rk - pk).round(1)),
             pct >= 0 ? "#{pct}% under target" : "#{pct.abs}% OVER target", tier)
    end

    def unmet_line(p_sec, r_sec)
      ph = p_sec.dig('unmet_occupied_hours', 'heating')
      return nil if ph.nil?

      format('%-12s heating %s / %s h    cooling %s / %s h', 'Unmet hours',
             num(ph), num(r_sec.dig('unmet_occupied_hours', 'heating')),
             num(p_sec.dig('unmet_occupied_hours', 'cooling')),
             num(r_sec.dig('unmet_occupied_hours', 'cooling')))
    end

    def determination(result, rep)
      return 'NO DETERMINATION - run period shortened' if rep['annual'] == false
      return 'NO DETERMINATION - no annual simulation' if result.compliant.nil?

      result.compliant ? 'COMPLIANT' : 'NOT COMPLIANT'
    end

    # A shortened run still returns a boolean from evaluate (it only sets
    # report['annual'] = false and warns), so the CLI must refuse to print a
    # verdict rather than pass a week-long run off as a determination.
    def verdict_block(result, rep)
      rule = '-' * 66
      if rep['annual'] == false
        ['', '  *** NOT A CODE-COMPLIANT DETERMINATION ***',
         '  The run period was shortened (--quick). 8.4.1.2 requires a simulated',
         '  year. The comparison above is arithmetic only.', '',
         '  VERDICT: NO DETERMINATION', rule].join("\n")
      elsif result.compliant.nil?
        ['', "  VERDICT: NO DETERMINATION (simulate: #{rep['simulate']})",
         '  Run with --simulate annual for an 8.4.1.2 determination.', rule].join("\n")
      else
        ['', format('  VERDICT: %s   (NECB %s, Division B, Article 8.4.1.2)',
                    result.compliant ? 'COMPLIANT' : 'NOT COMPLIANT', rep['vintage']),
         rule].join("\n")
      end
    end

    def artifact_block(result, o)
      dir = result.run_dir
      lines = ['']
      lines << "  Report   #{File.join(dir, 'compliance_report.html')}" if o[:report_html]
      lines << "  Audit    #{File.join(dir, 'audit.txt')}"
      lines << "  Data     #{File.join(dir, 'report.json')}"
      warns = Array(result.audit&.entries).count { |e| e[:level] == :warning }
      lines << "  #{warns} warning(s) recorded - see audit.txt" if warns.positive?
      lines.join("\n")
    end

    def preflight_help(err_obj, o, err)
      err.puts('')
      err.puts('ERROR: the model was REJECTED before any simulation ran.')
      err.puts('')
      err.puts(err_obj.message) # already carries per-type did-you-mean suggestions
      unless o[:space_type] || o[:space_type_map]
        err.puts('')
        err.puts('Fix: tag each space type with standardsBuildingType + standardsSpaceType')
        err.puts('from the NECB catalog, or re-run with the on-ramp, e.g.')
        err.puts('  --space-type "Space Function/Office enclosed > 25 m2"')
      end
      err.puts(audit_note(o[:run_dir]))
    end

    # performance_compliance runs flush_on_failure before re-raising, so an
    # audit trail exists even for a crash. Saying so turns a dead end into a
    # next step.
    def audit_note(run_dir)
      return '' unless run_dir && File.exist?(File.join(run_dir.to_s, 'audit.txt'))

      "\nA partial audit trail was written to #{File.join(run_dir, 'audit.txt')}"
    end

    def num(v)
      return '-' if v.nil?
      return v.to_s unless v.is_a?(Numeric)

      whole = v.round.to_s.reverse.scan(/\d{1,3}/).join(',').reverse
      v.is_a?(Float) && v.abs < 1000 ? v.round(1).to_s : whole
    end

    # Weather resolution for --city.
    #
    # A demo that needs the network is a bad demo, so bundled files win and the
    # download is only the long tail. Both the .ddy and the .stat must land
    # BESIDE the .epw: attach_weather! needs the design days, and Climate.hdd18
    # reads the .stat next to the EPW before falling back to Table C-1.
    module Weather
      # Where to look for bundled weather, most authoritative first.
      #
      # The relative depths are NOT interchangeable and both are needed —
      # __dir__ is <root>/openstudio-necb/lib/openstudio_necb, so:
      #   3 up = <root>            -> the source checkout's sibling gem dirs
      #   4 up = <install root>    -> the packaged tree, where the gems sit one
      #                               level deeper under gems/
      # Shipping only the 3-up form made --list-cities report "none" on a real
      # Windows install while every Linux test passed, because in a checkout the
      # openstudio-hvac fixtures path answered instead. Layout-specific paths
      # need a test per LAYOUT, not per platform.
      def self.search
        [ENV.fetch('NECB_HOME', nil)&.then { |h| File.join(h, 'weather') },
         File.expand_path('../../../../weather', __dir__),
         File.expand_path('../../../weather', __dir__),
         File.expand_path('../../../openstudio-hvac/test/fixtures/weather', __dir__)].compact
      end

      def self.dirs = search.select { |d| Dir.exist?(d) }

      # Earlier directories win: NECB_HOME is what the launcher actually set,
      # so it must not be shadowed by a checkout path that happens to exist.
      def self.available
        dirs.reverse.flat_map { |d| Dir.glob(File.join(d, '*.epw')) }
            .to_h { |f| [city_of(f), f] }
      end

      # 'CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw' -> 'toronto'
      def self.city_of(path)
        File.basename(path).split('_')[2].to_s.split('.').first.to_s.downcase
      end

      def self.catalogue_text
        found = available
        return 'No weather files found in this installation.' if found.empty?

        (['Weather files available to --city:'] +
          found.sort.map { |city, path| format('  %-14s %s', city, File.basename(path)) }).join("\n")
      end

      # @return [String, nil] an error message, or nil on success
      def self.resolve!(o)
        return nil unless o[:city]
        return '--city and --epw are mutually exclusive' if o[:epw]

        match = available[o[:city].downcase]
        unless match
          return "unknown city: #{o[:city]}\n       " \
                 "known: #{available.keys.sort.join(', ')}\n       " \
                 'or pass --epw with an explicit path'
        end

        o[:epw] = match
        nil
      end
    end

    # The pipeline has no callback hook and a real run is 40-90 minutes, so a
    # silent terminal reads as a hang. Watch the run dir for the phase
    # directories appearing instead — no API change, and it is what makes the
    # demo watchable.
    module Progress
      PHASES = [['proposed_sizing', 'proposed sizing run'],
                ['proposed_annual', 'proposed annual run'],
                ['reference_sizing', 'reference sizing run'],
                ['reference_annual', 'reference annual run']].freeze

      def self.start(run_dir, out)
        seen = {}
        started = Time.now
        Thread.new do
          loop do
            PHASES.each do |dir, label|
              next if seen[dir] || !Dir.exist?(File.join(run_dir.to_s, dir))

              seen[dir] = true
              out.puts(format('  [%s] %-28s started', stamp(started), label))
            end
            sleep(2)
          end
        end
      end

      def self.stop(thread)
        thread&.kill
      end

      def self.stamp(started)
        secs = (Time.now - started).round
        format('%02d:%02d', secs / 60, secs % 60)
      end
    end
  end
end
