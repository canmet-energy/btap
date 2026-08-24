require_relative 'lib/btap_costing/version'

Gem::Specification.new do |spec|
  spec.name = 'btap-costing'
  spec.version = BtapCosting::VERSION
  spec.authors = ['CanmetENERGY']
  spec.summary = 'Capital costing for OpenStudio models (HVAC, envelope, lighting, SHW)'
  spec.description = 'Prices model objects from RS-Means-schema tables. The vendored ' \
                     'CSVs are unpriced placeholders; licensed values are injected at ' \
                     'runtime via costs_csv:/BTAP_COSTING_DIR and never redistributed.'
  spec.homepage = 'https://github.com/canmet-energy/openstudio-necb-gems'
  spec.license = 'LGPL-3.0-or-later'
  spec.required_ruby_version = '>= 3.2.0'
  spec.metadata['homepage_uri'] = spec.homepage
  spec.metadata['source_code_uri'] = spec.homepage
  spec.metadata['allowed_push_host'] = 'none'
  spec.files = Dir['lib/**/*', 'README.md', 'LICENSE*']
  spec.require_paths = ['lib']
  spec.add_dependency 'btap-audit'
  spec.add_dependency 'btap-modeling'
end
