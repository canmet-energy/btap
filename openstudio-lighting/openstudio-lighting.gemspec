require_relative 'lib/openstudio_lighting/version'

Gem::Specification.new do |spec|
  spec.name = 'openstudio-lighting'
  spec.version = OpenStudioLighting::VERSION
  spec.authors = ['NRCan / openstudio-standards contributors']
  spec.summary = 'NECB Part 4 interior/exterior lighting for OpenStudio models (SDK-only)'
  spec.description = 'Applies NECB lighting power allowances (Tables 4.2.1.5/4.2.1.6), the LED ' \
                     'alternative, atrium rules, occupancy-sensor lighting schedules (Table ' \
                     '4.3.2.10 factors), exterior allowances, and reference-building lighting ' \
                     '(8.4.4.5) — with an audit log and article-coverage accounting.'
  spec.homepage = 'https://github.com/canmet-energy/openstudio-necb-gems'
  spec.metadata = {
    # These gems are not published: the repository is private and the costing
    # data is licence-encumbered. Publishing is a deliberate act — clear this
    # entry consciously, do not let a stray `gem push` make the decision.
    'allowed_push_host' => 'none',
    'source_code_uri' => 'https://github.com/canmet-energy/openstudio-necb-gems',
    'homepage_uri' => 'https://github.com/canmet-energy/openstudio-necb-gems'
  }
  spec.license = 'LGPL-3.0-or-later'
  spec.required_ruby_version = '>= 3.2'

  spec.files = Dir['lib/**/*', 'README.md', 'LICENSE*']
  spec.require_paths = ['lib']

  # openstudio-hvac: costing/database.rb reads the family's single public
  # vendored copy of the PRICED tables (costs.csv, costs_local_factors.csv,
  # locations.csv) from this gem. Undeclared until the gems were extracted,
  # because a side-by-side checkout resolved it by relative path.
  spec.add_dependency 'btap-audit'
  spec.add_dependency 'openstudio-hvac'
  spec.add_dependency 'openstudio-loads'
end
