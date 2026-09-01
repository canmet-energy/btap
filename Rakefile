# Repository tasks for the Python canmet-btap product and pinned Ruby oracle.

PYTHON = ENV.fetch('BTAP_PYTHON', 'python3')

namespace :legacy do
  desc 'What changed in the legacy fork since the pin (BRANCH=nrcan, LEGACY_FORK=/path)'
  task :whatsnew do
    abort('legacy:whatsnew failed') unless system(PYTHON, 'python/scripts/legacy_whatsnew.py')
  end

  desc 'Show the pinned oracle revision'
  task :pin do
    ref = File.read('legacy_pin/REF').strip
    puts "legacy_pin/REF = #{ref}"
    puts 'fork           = https://github.com/NatLabRockies/openstudio-standards'
    puts 'bump workflow  = legacy_pin/README.md'
  end
end

namespace :necb do
  desc 'Lint: every top-level NECB rule key is consumed by Python source'
  task :orphan_keys do
    abort('necb:orphan_keys failed') unless system(PYTHON, 'python/scripts/necb_orphan_keys.py')
  end

  desc 'Regenerate the committed NECB coverage documents from Python inputs'
  task :coverage_doc do
    abort('necb:coverage_doc failed') unless
      system(PYTHON, 'python/scripts/generate_necb_gem_coverage.py') &&
      system(PYTHON, 'python/scripts/generate_necb_8_4_coverage.py')
  end

  desc 'Verify as-applied part-load curves against NECB 2025 Subsection 8.4.6'
  task :curves do
    abort('necb:curves failed') unless
      system(PYTHON, 'python/scripts/necb_8_4_6_curve_probe.py')
  end

  desc 'Run all Python NECB rule-verification checks and report every outcome'
  task :verify do
    results = {
      'orphan_keys' => system(PYTHON, 'python/scripts/necb_orphan_keys.py'),
      'curves_8_4_6' => system(PYTHON, 'python/scripts/necb_8_4_6_curve_probe.py'),
      'hostile' => system(PYTHON, '-m', 'pytest', '-q',
                          'python/tests/necb/test_envelope_necb_hostile_reference.py',
                          'python/tests/necb/test_lighting_necb_hostile_reference.py')
    }
    puts "\n#{'=' * 70}\nnecb:verify summary"
    results.each { |name, ok| puts format('  %-14s %s', name, ok ? 'OK' : 'WORK REQUIRED') }
    puts '=' * 70
    abort('necb:verify: see failures above') unless results.values.all?
  end
end
