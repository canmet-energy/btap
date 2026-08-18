require_relative 'lib/openstudio_necb/version'

Gem::Specification.new do |spec|
  spec.name = 'openstudio-necb'
  spec.version = OpenStudioNECB::VERSION
  spec.authors = ['NRCan / openstudio-standards contributors']
  spec.summary = 'NECB performance-path compliance pipeline composing openstudio-hvac and openstudio-envelope'
  spec.description = 'Umbrella gem: proposed -> reference building generation (HVAC + envelope, one ' \
                     'clone, one audit), SDK+CLI sizing/annual simulation, NECB 8.4.1.2 building-energy-target ' \
                     'comparison, and unified compliance + costing reporting.'
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

  spec.add_dependency 'openstudio-audit'
  spec.add_dependency 'openstudio-envelope'
  spec.add_dependency 'openstudio-geometry'
  spec.add_dependency 'openstudio-hvac'
  spec.add_dependency 'openstudio-lighting'
  spec.add_dependency 'openstudio-loads'
  spec.add_dependency 'openstudio-shw'
  spec.add_dependency 'openstudio-simulation'
end
