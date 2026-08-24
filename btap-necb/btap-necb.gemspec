require_relative 'lib/btap_necb/version'

Gem::Specification.new do |spec|
  spec.name = 'btap-necb'
  spec.version = BtapNECB::VERSION
  spec.authors = ['NRCan / openstudio-standards contributors']
  spec.summary = 'NECB performance-path compliance pipeline composing the btap gem family'
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

  spec.files = Dir['lib/**/*', 'exe/**/*', 'README.md', 'LICENSE*']
  spec.require_paths = ['lib']

  spec.add_dependency 'btap-audit', '~> 0.2'
  spec.add_dependency 'btap-costing', '~> 0.2'
  spec.add_dependency 'tbd'
  spec.add_dependency 'btap-modeling', '~> 0.2'
  spec.add_dependency 'btap-simulation', '~> 0.2'
end
