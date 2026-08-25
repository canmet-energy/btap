#!/usr/bin/env ruby
# frozen_string_literal: true

# Regenerates NECB_GEM_COVERAGE.md — the family-wide rollup of every domain
# gem's NECB article_coverage manifest. Deterministic: sorted by gem then
# article, 2020/2025 rows that differ only by the 8.4.4<->8.4.5 renumbering are
# merged into one row citing both vintages.
#
#   ruby scripts/generate_necb_gem_coverage.rb
#
# Run from the repo root. Reads {openstudio,btap}-*/lib/**/data/*_rules_*.json.

require 'json'

ROOT = File.expand_path('../..', __dir__)
# btap-necb (the umbrella) declares the pipeline-level articles no domain
# gem can: the 8.4.1.2 determination itself, calculation methods, the 2025 EUI
# path. It emits them at runtime exactly as the domain gems do — D-09 chose
# runtime emission over declaration-only; Compliance#emit_article_coverage runs
# from finalize!, which is the shared epilogue of BOTH the reference and the
# 8.4.4 EUI path.
# Manifests are discovered by glob (the canary's convention) and attributed
# by DOMAIN from the basename — the migration moves them between gem dirs,
# and a hard-coded dir list is exactly the fail-open trap C1 retired.
MANIFEST_DOMAINS = { 'reference' => 'hvac', 'necb' => 'necb' }.freeze
def manifest_domain(path)
  prefix = File.basename(path)[/\A([a-z]+)_rules_/, 1]
  MANIFEST_DOMAINS.fetch(prefix, prefix)
end

STATUS_GROUPS = [
  ['implemented',        'Implemented'],
  ['partial',            'Partial (warns every run)'],
  ['not_implemented',    'Not implemented (warns every run)'],
  ['satisfied_by_clone', 'Satisfied by construction (clone)'],
  ['host_scope',         'Host / other-gem scope']
].freeze

# VINTAGE-DIRECTIONAL renumbering into canonical 2025 numbering.
#
# 2020's 8.4.4 (Reference Building) became 2025's 8.4.5; 2025's 8.4.4 is the
# NEW Energy Use Intensity subsection with no 2020 equivalent. So only refs
# originating in a 2020 manifest are translated (8.4.4.x -> 8.4.5.x); 2025
# refs pass through untouched. The previous blind bidirectional collapse
# (8.4.[45]. -> 8.4.N.) merged reference-building declarations INTO the 2025
# EUI subsection — wrong content on the one subsection that is genuinely new.
def canonical(article, vintage)
  a = article.to_s
  return a unless vintage.to_s == '2020'

  # ONE-SHOT map (2020 -> 2025): 8.4.4 (Reference Building) -> 8.4.5, and
  # 8.4.5 (Part-Load Curves in 2020 numbering) -> 8.4.6. Sequential subs
  # would cascade 8.4.4 -> 8.4.5 -> 8.4.6.
  a.sub(/\A8\.4\.([45])\./) { "8.4.#{Regexp.last_match(1).to_i + 1}." }
end

def article_sort_key(article)
  article.to_s.scan(/\d+/).map(&:to_i)
end

# Bidirectional prefix match on CANONICAL refs (trailing '.' guards 8.4.5.2.
# from matching 8.4.5.20.): '8.4.5.20.' matches '8.4.5.20.(1)'.
def canonicals_match?(na, nb)
  na.start_with?(nb) || nb.start_with?(na)
end

# ---- collect every manifest entry ----------------------------------------
records = []
manifests = Dir.glob(File.join(ROOT, '{openstudio,btap}-*', 'lib', '**', 'data', '*_rules_*.json')).sort
abort('no coverage manifests found — the glob went stale') if manifests.empty?
manifests.each do |path|
  begin
    gem = manifest_domain(path)
    data = JSON.parse(File.read(path))
    coverage = data.dig('article_coverage', 'articles')
    next if coverage.nil?

    vintage = File.basename(path)[/(\d{4})\.json\z/, 1] || data.dig('provenance', 'edition') || '?'
    coverage.each do |art|
      records << { gem: gem, vintage: vintage, article: art['article'].to_s,
                   canonical: canonical(art['article'], vintage),
                   title: art['title'].to_s, status: art['status'].to_s,
                   how: art['how'], gaps: art['gaps'], gap_owner: art['gap_owner'],
                   code: art['code'] }
    end
  end
end

# ---- merge cross-vintage duplicates (differ only by renumbering) ----------
merged = {}
records.each do |r|
  key = [r[:gem], r[:canonical], r[:title], r[:status], r[:how], r[:gaps]]
  if merged.key?(key)
    merged[key][:vintages] << r[:vintage]
    merged[key][:articles] << r[:article]
  else
    merged[key] = r.merge(vintages: [r[:vintage]], articles: [r[:article]])
  end
end
rows = merged.values

def vintage_label(vintages)
  vintages.uniq.sort.join(', ')
end

# One article label per merged row: if both vintages, show both numbers.
def article_label(row)
  row[:articles].uniq.sort.join(' / ')
end

def notes(row)
  parts = []
  parts << row[:how] if row[:how] && !row[:how].empty?
  parts << "Gaps: #{row[:gaps]}" if row[:gaps] && !row[:gaps].empty?
  # The "where is this dealt with" pointers (linted by test_coverage_code_refs).
  # Method anchors, not line numbers — lines rot with every edit above them.
  if row[:code] && !Array(row[:code]).empty?
    refs = Array(row[:code]).map { |r| "`#{r.split('/').last}`" }.join(', ')
    parts << "Code: #{refs}"
  end
  parts.join(' — ').tr('|', '/') # '|' would break the Markdown table
end

# ---- render ----------------------------------------------------------------
# One collapsible section PER VINTAGE, each self-contained in its own article
# numbering. The previous layout merged vintages into single rows ("8.4.4.3. /
# 8.4.5.3.", vintage column "2020, 2025") and left unmergeable rows interleaved
# beside them — one table mixing two numbering schemes, which read as noise.
# Now a reader opens the vintage they are reviewing and sees only that code's
# numbers. Identical text appearing in both sections is the deliberate cost of
# a generated document; nothing is hand-maintained here.
out = []
out << '<!-- Generated by scripts/generate_necb_gem_coverage.rb — do not edit by hand.'
out << '     Regenerate: ruby scripts/generate_necb_gem_coverage.rb -->'
out << ''
out << '# NECB coverage across the openstudio-* gem family'
out << ''
out << 'Rollup of every gem\'s NECB `article_coverage` manifest, one collapsible'
out << 'section per vintage, each in that code edition\'s own article numbering.'
out << 'Statuses: **implemented** / **partial** (warns every run) /'
out << '**not_implemented** (warns every run) / **satisfied_by_clone** /'
out << '**host_scope** (delegated to the umbrella or a sibling gem); entries with'
out << '`gap_owner: "modeller"` are field/document-verified scope notes and do'
out << 'not warn (D-09, D-76). Each gem emits its section of this accounting into'
out << 'the shared AuditLog on every run — including the umbrella, whose manifest'
out << 'is emitted by `Compliance#emit_article_coverage` from the epilogue both'
out << 'compliance paths share — so nothing is silently missed.'
out << ''

FIELD_VERIFIED_HEADING = 'Field / document verification (modeller scope, does not warn)'.freeze
VINTAGES = %w[2020 2025].freeze

# The at-a-glance comparison, visible without expanding either section.
out << '## At a glance'
out << ''
out << '| | NECB 2020 | NECB 2025 |'
out << '|---|---|---|'
summary_rows = STATUS_GROUPS.map { |st, heading| [heading, ->(r) { r[:status] == st && r[:gap_owner].to_s != 'modeller' }] }
summary_rows << [FIELD_VERIFIED_HEADING, ->(r) { r[:gap_owner].to_s == 'modeller' }]
summary_rows.each do |heading, filter|
  counts = VINTAGES.map { |v| records.count { |r| r[:vintage] == v && filter.call(r) } }
  next if counts.sum.zero?

  out << "| #{heading} | #{counts[0]} | #{counts[1]} |"
end
out << "| **Total entries** | **#{records.count { |r| r[:vintage] == '2020' }}** | **#{records.count { |r| r[:vintage] == '2025' }}** |"
out << ''

VINTAGES.each do |vintage|
  vrows = records.select { |r| r[:vintage] == vintage }
  out << '<details>'
  out << "<summary><b>NECB #{vintage}</b> — #{vrows.size} entries (click to expand)</summary>"
  out << ''

  field_verified = vrows.select { |r| r[:gap_owner].to_s == 'modeller' }
                        .sort_by { |r| [r[:gem], article_sort_key(r[:canonical])] }

  STATUS_GROUPS.each do |status, heading|
    group = vrows.select { |r| r[:status] == status && r[:gap_owner].to_s != 'modeller' }
                 .sort_by { |r| [r[:gem], article_sort_key(r[:canonical])] }
    next if group.empty?

    out << "### #{heading} (#{group.size})"
    out << ''
    out << '| Gem | Article | Title | Notes |'
    out << '|---|---|---|---|'
    group.each { |r| out << "| #{r[:gem]} | #{r[:article]} | #{r[:title]} | #{notes(r)} |" }
    out << ''
  end

  unless field_verified.empty?
    out << "### #{FIELD_VERIFIED_HEADING} (#{field_verified.size})"
    out << ''
    out << 'Requirements the code imposes on the BUILDING that no energy model can'
    out << 'answer — a blower-door test, an installed control device, a pipe'
    out << 'insulation thickness. Declared so a reviewer sees them accounted for;'
    out << 'verified from drawings, submittals or on site.'
    out << ''
    out << '| Gem | Article | Title | Notes |'
    out << '|---|---|---|---|'
    field_verified.each { |r| out << "| #{r[:gem]} | #{r[:article]} | #{r[:title]} | #{notes(r)} |" }
    out << ''
  end

  covering = vrows.reject { |r| r[:status] == 'host_scope' }
  host = vrows.select { |r| r[:status] == 'host_scope' }
              .sort_by { |r| [r[:gem], article_sort_key(r[:canonical])] }
  unless host.empty?
    out << "### Cross-gem delegations (#{host.size})"
    out << ''
    out << 'Each `host_scope` article and the sibling-gem entry that actually'
    out << 'covers it. "(none in family)" means the umbrella/modeller owns it — a'
    out << 'genuine open item to watch on a real run.'
    out << ''
    out << '| host_scope in | Article | Covered by |'
    out << '|---|---|---|'
    host.each do |h|
      matches = covering.select { |c| c[:gem] != h[:gem] && canonicals_match?(c[:canonical], h[:canonical]) }
                        .map { |c| "#{c[:gem]} #{c[:article]} (#{c[:status]})" }
                        .uniq.sort
      covered = matches.empty? ? '(none in family — host/modeller scope)' : matches.join('; ')
      out << "| #{h[:gem]} | #{h[:article]} | #{covered} |"
    end
    out << ''
  end

  out << '</details>'
  out << ''
end

domains = records.map { |r| r[:gem] }.uniq.size
out << "_#{records.size} coverage entries across #{domains} domains (#{records.count { |r| r[:vintage] == '2020' }} × 2020, #{records.count { |r| r[:vintage] == '2025' }} × 2025)._"
out << ''

File.write(File.expand_path('../docs/NECB_GEM_COVERAGE.md', __dir__), out.join("\n"))
puts "wrote NECB_GEM_COVERAGE.md — #{records.size} entries in two vintage sections"
