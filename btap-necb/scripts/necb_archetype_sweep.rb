#!/usr/bin/env ruby
# frozen_string_literal: true

# Breadth cross-validation sweep: generate legacy NECB2020 archetypes (same
# out-of-process recipe as btap-necb/test/test_legacy_archetype_e2e.rb,
# same cache dir) and run each through the NEW gem pipeline — proving
# preflight, system selection, reference transforms, the sizing run, and the
# post-sizing determinations (ERV 5.2.10.1, pump 8.4.4.14) on real whole
# buildings. SWEEP_MODE=annual adds January-week annual runs for both models
# and reports the 8.4.1.2 verdict + tier (the pipeline flags the shortened
# period as not-annual-compliant by itself). Preflight refusals are reported
# as FINDINGS (the unresolved space types), not crashes.
#
# Buildings are independent, so each runs in its OWN forked process (the
# stages within one building stay sequential by necessity: proposed sizing ->
# reference sizing -> annual runs). Usage:
#   [SWEEP_MODE=annual] [FUEL=NaturalGas] [LOC=edmonton|yellowknife] \
#     ruby btap-necb/scripts/necb_archetype_sweep.rb [types...]
#
# FUEL (default Electricity) is the legacy generator's primary_heating_fuel —
# NaturalGas flips the whole Table 8.4.4.7.-B gas column (boilers, HW
# baseboards, gas coils, boiler staging). LOC picks the EPW/DDY + Table C-1
# HDD — edmonton (zone 7A) / yellowknife (zone 8) exercise the HDD-dependent
# envelope and ERV rows. VINTAGE (2020 default | 2025) picks the PIPELINE
# edition only — the proposed is ALWAYS the legacy NECB2020 archetype (legacy
# has no 2025 generator), so the generated-OSM cache is shared across
# vintages while run dirs and result files fork. ECM (e.g. hs08_ccashp_vrf)
# passes the legacy generator's ecm_system_name — the vehicle for HP-proposed
# buildings (the 8.4.4.13 redirect + D-52 election on real annual data).
# Cache keys include fuel/loc/ecm(/vintage), so variants coexist.

require 'fileutils'
require 'etc'
require 'json'
require 'openstudio'

ROOT = File.expand_path('../..', __dir__)
require File.join(ROOT, 'btap-necb', 'lib', 'btap_necb')

# The routine fleet (phylroy 2026-08-10, D-70): Hospital and Outpatient are
# EXCLUDED from routine sweeps — their capacity-iterated full-annual chains
# (up to 8 runs of 40-60 min each) dominate wall-clock as the least
# sensitive instruments. Run them EXPLICITLY BY NAME when a baseline or
# investigation needs them; week-mode remains cheap enough to include them
# by name too.
FLEET = %w[SmallOffice MediumOffice LargeOffice PrimarySchool SecondarySchool
           RetailStandalone RetailStripmall Warehouse FullServiceRestaurant
           QuickServiceRestaurant HighriseApartment LowriseApartment
           MidriseApartment SmallHotel LargeHotel].freeze
TYPES = if ARGV.empty?
          %w[Warehouse FullServiceRestaurant HighriseApartment PrimarySchool RetailStandalone]
        elsif ARGV == ['fleet']
          FLEET
        else
          ARGV
        end
CACHE_DIR = '/tmp/btap_necb_legacy_archetype_e2e'
FUEL = ENV.fetch('FUEL', 'Electricity')
LOC = ENV.fetch('LOC', 'toronto')
LOCATIONS = {
  # HDD18 from the gem's Table C-1 (table_c1.json) — the same source the pipeline resolves from
  'toronto' => { epw: File.join(ROOT, 'btap-modeling', 'test', 'fixtures', 'weather',
                                'CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw'), hdd: 3890 },
  'edmonton' => { epw: File.join(ROOT, 'data', 'weather', 'CAN_AB_Edmonton.Intl.AP.711230_CWEC2020.epw'), hdd: 5120 },
  'yellowknife' => { epw: File.join(ROOT, 'data', 'weather', 'CAN_NT_Yellowknife.AP.719360_CWEC2020.epw'), hdd: 8170 }
}.freeze
raise(ArgumentError, "unknown LOC '#{LOC}' (#{LOCATIONS.keys.join('/')})") unless LOCATIONS.key?(LOC)

EPW = LOCATIONS[LOC][:epw]
DDY = EPW.sub('.epw', '.ddy')
HDD = LOCATIONS[LOC][:hdd]
VINTAGE = ENV.fetch('VINTAGE', '2020')
raise(ArgumentError, "unknown VINTAGE '#{VINTAGE}' (2020/2025)") unless %w[2020 2025].include?(VINTAGE)

ECM = ENV['ECM'] # legacy ecm_system_name, nil = NECB_Default

# The proposed-OSM cache is vintage-independent (always the legacy NECB2020
# archetype); run dirs and result files carry the vintage.
#
# LEGACY_SHA keys the cache to the legacy library that GENERATES the
# archetypes: any commit touching lib/openstudio-standards invalidates every
# cached OSM automatically. Before this key existed, the nrcan merge of
# 2026-08-10 (upstream #2119: SHW tank sizing + daylighting-control fixes,
# both of which change generated archetypes) would have silently reused
# stale pre-merge OSMs — existence was the only check.
LEGACY_SHA = `git -C #{ROOT} rev-parse --short HEAD:lib/openstudio-standards`.strip
raise('cannot resolve the legacy-subtree SHA for cache keying') if LEGACY_SHA.empty?

GEN_VARIANT = [FUEL == 'Electricity' ? nil : FUEL.downcase, LOC == 'toronto' ? nil : LOC,
               ECM&.downcase, LEGACY_SHA].compact.join('_')
SUFFIX = GEN_VARIANT.empty? ? '' : "_#{GEN_VARIANT}"
RUN_VARIANT = [GEN_VARIANT.empty? ? nil : GEN_VARIANT, VINTAGE == '2020' ? nil : "v#{VINTAGE}"].compact.join('_')
RUN_SUFFIX = RUN_VARIANT.empty? ? '' : "_#{RUN_VARIANT}"
FileUtils.mkdir_p(CACHE_DIR)

def generate!(type)
  osm = File.join(CACHE_DIR, "sweep_necb2020_#{type.downcase}#{SUFFIX}.osm")
  return osm if File.exist?(osm)

  gen = File.join(CACHE_DIR, "gen_#{type}#{SUFFIX}.rb")
  File.write(gen, <<~RUBY)
    require File.join('#{ROOT}', 'lib', 'openstudio-standards')
    std = Standard.build('NECB2020')
    model = std.model_create_prototype_model(
      template: 'NECB2020', building_type: '#{type}',
      primary_heating_fuel: '#{FUEL}',
      ecm_system_name: '#{ECM || 'NECB_Default'}',
      epw_file: '#{File.basename(EPW)}',
      sizing_run_dir: File.join('#{CACHE_DIR}', 'gen_sizing_#{type}#{SUFFIX}'))
    (warn('GENERATION FAILED'); exit 1) if model.nil? || model.is_a?(FalseClass)
    model.save(OpenStudio::Path.new('#{osm}'), true)
    puts 'OK'
  RUBY
  ok = system('bundle', 'exec', 'ruby', gen, chdir: ROOT, out: File.join(CACHE_DIR, "gen_#{type}#{SUFFIX}.log"),
                                              err: File.join(CACHE_DIR, "gen_#{type}#{SUFFIX}.err"))
  ok && File.exist?(osm) ? osm : nil
end

def sweep_one(type)
  osm = generate!(type)
  return { type: type, verdict: 'GEN-FAIL', detail: "see #{CACHE_DIR}/gen_#{type}.err" } if osm.nil?

  # SWEEP_MODE: 'sizing' (default) | 'annual' (January-week shortcut — fast,
  # flagged not-code-compliant by the pipeline) | 'full' (true 8760 h annual —
  # the code-compliant 8.4.1.2 determination). Full mode keeps its own run
  # dirs/result files so week-run artifacts survive side by side.
  mode = ENV.fetch('SWEEP_MODE', 'sizing')
  annual = %w[annual full].include?(mode)
  run_dir = File.join(CACHE_DIR, "sweep_run#{mode == 'full' ? '_full' : ''}_#{type.downcase}#{RUN_SUFFIX}")
  FileUtils.rm_rf(run_dir)
  FileUtils.mkdir_p(run_dir)
  result = BtapNECB.performance_compliance(
    osm, vintage: VINTAGE, simulate: annual ? :annual : :sizing, hdd: HDD,
    weather: { epw: EPW, ddy: DDY }, run_dir: run_dir,
    run_period: mode == 'annual' ? { begin_month: 1, begin_day: 1, end_month: 1, end_day: 7 } : nil)
  ref = result.reference_model
  detail = "zones=#{ref.getThermalZones.size} air_loops=#{ref.getAirLoopHVACs.size} " \
           "plant_loops=#{ref.getPlantLoops.size} ervs=#{ref.getHeatExchangerAirToAirSensibleAndLatents.size} " \
           "warnings=#{result.audit.warnings.size}"
  if annual
    rep = result.report
    detail += format(' | proposed=%.0f ref=%.0f kWh wk compliant=%s tier=%s (%.0f%% of target)',
                     rep.dig('proposed', 'total_site_kwh').to_f, rep.dig('reference', 'total_site_kwh').to_f,
                     rep['compliant'].inspect, rep['tier'].inspect, rep['percent_of_target'].to_f)
  end
  { type: type, verdict: 'PASS', detail: detail }
# PreflightError subclasses ArgumentError, so it must be rescued FIRST — a
# leading `rescue ArgumentError` would swallow it. This used to match on the
# message text ('pre-flight'), which broke the moment the wording moved.
rescue BtapNECB::PreflightError => e
  { type: type, verdict: 'PREFLIGHT-REFUSAL', detail: e.message.lines.first(4).join(' ').strip[0, 300] }
rescue ArgumentError => e
  { type: type, verdict: 'ERROR', detail: "#{e.class}: #{e.message[0, 200]}" }
rescue StandardError => e
  { type: type, verdict: 'ERROR', detail: "#{e.class}: #{e.message[0, 200]}" }
end

RESULT_TAG = ENV.fetch('SWEEP_MODE', 'sizing') == 'full' ? "_full#{RUN_SUFFIX}" : RUN_SUFFIX

# Forking ALL the buildings at once does not make them finish sooner: each
# EnergyPlus run is single-threaded, so N processes on M cores just timeshare,
# and the whole fleet lands at the same wall-clock while every run competes for
# RAM. A full-annual archetype needs on the order of a gigabyte; 15 at once on
# a 16 GB runner is how a sweep gets OOM-killed at hour three, after the
# expensive part is done. Bound the pool instead: same wall-clock when the
# fleet exceeds the cores, far less risk, and the AWS 8-vCPU gain becomes
# predictable rather than accidental.
#
# Bounded on BOTH axes, because they bind on different machines: a CI runner is
# core-poor (4 cores / 16 GB) while a dev box can be core-rich and memory-poor
# (48 cores / 31 GB), where a core-only bound would start 48 EnergyPlus runs on
# 31 GB. MEM_PER_WORKER_GB is a deliberately conservative allowance for a
# full-annual archetype, not a measurement — SWEEP_WORKERS overrides both.
MEM_PER_WORKER_GB = 1.5

def detected_memory_gb
  kb = File.read('/proc/meminfo')[/MemTotal:\s+(\d+)/, 1]
  kb ? kb.to_i / 1_048_576.0 : nil
rescue StandardError
  nil
end

WORKERS = if ENV['SWEEP_WORKERS']
            [ENV['SWEEP_WORKERS'].to_i, 1].max
          else
            mem = detected_memory_gb
            by_memory = mem ? (mem / MEM_PER_WORKER_GB).floor : Etc.nprocessors
            [[Etc.nprocessors, by_memory].min, 1].max
          end

# Longest FIRST, so the tail of the sweep is not one Hospital finishing alone
# while every other core idles. A scheduling hint only — it can never change a
# result, and an unlisted type simply sorts last. Ranks follow the D-70 note
# above: the capacity-iterated chains dominate, then the large archetypes.
COST_HINT = {
  'Hospital' => 100, 'Outpatient' => 90,
  'LargeHotel' => 60, 'LargeOffice' => 55, 'SecondarySchool' => 50,
  'PrimarySchool' => 40, 'MediumOffice' => 35, 'HighriseApartment' => 30,
  'MidriseApartment' => 25, 'SmallHotel' => 25, 'LowriseApartment' => 20,
  'RetailStripmall' => 15, 'RetailStandalone' => 12, 'SmallOffice' => 10,
  'FullServiceRestaurant' => 8, 'QuickServiceRestaurant' => 6, 'Warehouse' => 5
}.freeze

queue = TYPES.sort_by { |type| [-COST_HINT.fetch(type, 0), type] }
mem_gb = detected_memory_gb
puts format('running %<n>d building(s) %<w>d at a time (%<c>d cores, %<m>s; SWEEP_WORKERS overrides)',
            n: TYPES.size, w: WORKERS, c: Etc.nprocessors,
            m: mem_gb ? format('%.0f GB RAM, %.1f GB budgeted per run', mem_gb, MEM_PER_WORKER_GB) : 'memory unknown')
running = {}
until queue.empty? && running.empty?
  while running.size < WORKERS && !queue.empty?
    type = queue.shift
    pid = Process.fork do
      result = sweep_one(type)
      File.write(File.join(CACHE_DIR, "result_#{type}#{RESULT_TAG}.json"), JSON.generate(result))
      exit!(result[:verdict] == 'PASS' ? 0 : 1)
    end
    running[pid] = type
    puts "  started #{type} (#{running.size}/#{WORKERS} busy, #{queue.size} queued)"
  end
  pid, _status = Process.wait2
  finished = running.delete(pid)
  puts "  finished #{finished}" if finished
end
results = TYPES.map { |t| JSON.parse(File.read(File.join(CACHE_DIR, "result_#{t}#{RESULT_TAG}.json")), symbolize_names: true) }

puts
mode_label = { 'annual' => 'annual/week-run', 'full' => 'FULL ANNUAL (8760 h)' }.fetch(ENV.fetch('SWEEP_MODE', 'sizing'), 'sizing')
puts "necb_archetype_sweep results (#{mode_label} mode, vintage=#{VINTAGE}, fuel=#{FUEL}, loc=#{LOC}, #{TYPES.size} parallel):"
results.each { |r| puts format('  %-22s %-18s %s', r[:type], r[:verdict], r[:detail]) }
exit(results.all? { |r| r[:verdict] == 'PASS' } ? 0 : 1)
