#!/usr/bin/env ruby
# frozen_string_literal: true

# Generates NECB_8_4_COVERAGE.html — how Section 8.4 (Performance Path) is
# covered by the gem family, article by article down to sentence/clause text,
# with links to the source.
#
#   ruby btap-necb/scripts/generate_necb_8_4_coverage.rb          (or: rake necb:coverage_doc)
#
# Inputs, each independent and joined here:
#
#   1. data/necb/necb_8_4_articles_2025.json — every Section 8.4 article's
#      requirement text, parsed into a sentence/clause tree with strict sanity
#      checks (scripts/fetch_necb_8_4_text.rb). This is the DENOMINATOR: all 57
#      articles render, so coverage cannot be overstated by omission.
#   2. openstudio-*/lib/**/data/necb/*_rules_*.json article_coverage manifests
#      (including the umbrella's), vintage-directionally canonicalized to 2025
#      numbering.
#   3. `article:` citations in lib/**/*.rb, classified by the audit call they
#      sit on (warn vs decision/info). A citation proves a LOG LINE mentions
#      the article — nothing more. It is never rendered as "implemented".
#   4. audit.json files from real pipeline runs (env NECB_AUDIT_JSONS,
#      colon-separated run dirs) — articles observed cited AT RUNTIME, the
#      strongest evidence tier available here.
#   5. btap-necb/scripts/necb_8_4_disposition.json — curated engine/modeller/covered_by/
#      gap dispositions for articles nothing declares.
#
# Every article lands in exactly ONE primary state — declared / cited (not
# declared) / dispositioned / unknown — and the states are asserted to sum to
# 57. An article that is dispositioned AND declared/cited is flagged as a
# conflict, never silently resolved.
#
# Prescriptive values (U-values, LPD, efficiencies) are NOT rendered from the
# codes MCP: the gems' own data JSONs are the authoritative source of every
# value the software applies, and the only 8.4-external content permitted here
# is a labelled reference link. A lint below fails the build if the text cache
# contains anything outside Section 8.4.

require 'json'
require 'date'

ROOT = File.expand_path('../..', __dir__)
OUT = File.expand_path('../docs/NECB_8_4_COVERAGE.html', __dir__)
# One text cache PER EDITION. The two editions do not share Section 8.4's
# structure — 2020's 8.4.4 is the reference building and 8.4.5 the part-load
# curves; 2025 inserts the EUI path as 8.4.4 and shifts everything down — so
# each vintage part of this document walks its own edition's articles under its
# own numbers. "Text under a wrong number is worse than no tree."
CACHES = {
  '2020' => File.expand_path('../data/necb/necb_8_4_articles_2020.json', __dir__),
  '2025' => File.expand_path('../data/necb/necb_8_4_articles_2025.json', __dir__)
}.freeze
DISPOSITION = File.expand_path('necb_8_4_disposition.json', __dir__)
# The gems were extracted OUT of the openstudio-standards fork (2026-08-16), so
# source links must resolve against THIS repository — the fork's copies are
# slated for removal and every link into them will 404.
#
# BRANCH is a literal, NOT `git rev-parse HEAD`: this generator's output is
# committed and drift-checked in CI, and deriving the branch made the output
# depend on which branch the regenerating checkout happened to be on (that is
# how 95 links ended up frozen at the pre-rename `phylroy_dnd`). Override for a
# preview build with COVERAGE_BRANCH=my-branch; leave it alone when committing.
REPO = 'https://github.com/canmet-energy/openstudio-necb-gems'
BRANCH = (ENV['COVERAGE_BRANCH'] || 'main').strip
BLOB = "#{REPO}/blob/#{BRANCH}"

SUBSECTIONS = {
  '2020' => {
    '8.4.1' => 'General',
    '8.4.2' => 'Compliance Calculations',
    '8.4.3' => 'Proposed Building',
    '8.4.4' => 'Building Energy Target of the Reference Building',
    '8.4.5' => 'Part-Load Performance Curves'
  },
  '2025' => {
    '8.4.1' => 'General',
    '8.4.2' => 'Compliance Calculations',
    '8.4.3' => 'Proposed Building',
    '8.4.4' => 'Energy Use Intensity (EUI path — new in 2025)',
    '8.4.5' => 'Modeled Reference Building',
    '8.4.6' => 'Part-Load Performance Curves'
  }
}.freeze

STATUS_META = {
  'implemented' => ['Implemented (self-declared)', 'ok'],
  'partial' => ['Partial', 'warn'],
  'not_implemented' => ['Not implemented', 'bad'],
  'satisfied_by_clone' => ['Satisfied by clone', 'clone'],
  'host_scope' => ['Delegated', 'host']
}.freeze

DISPOSITION_META = {
  'engine' => ['EnergyPlus', 'clone'],
  'modeller' => ['Modeller / AHJ', 'host'],
  'covered_by' => ['Covered by (undeclared)', 'warn'],
  'gap' => ['GAP', 'bad']
}.freeze

# Canonicalization is RETIRED from this document: each vintage part shows its
# own edition natively, so nothing is renumbered for display. The only mapping
# left is disposition keys, which are curated in 2025 numbering and translated
# DOWN for the 2020 part (8.4.5.x -> 8.4.4.x, 8.4.6.x -> 8.4.5.x; the 2025-only
# EUI keys 8.4.4.x are dropped — 2020's 8.4.4 is the reference building and
# must not inherit EUI dispositions).
def disposition_key_for(vintage, key)
  return key unless vintage == '2020'
  return nil if key.start_with?('8.4.4.')

  key.sub(/\A8\.4\.([56])\./) { "8.4.#{Regexp.last_match(1).to_i - 1}." }
end

# '8.4.5.5.(1)' -> ['8.4.5.5', 1]; '8.4.1.2.' -> ['8.4.1.2', nil]
def split_ref(ref)
  m = ref.to_s.match(/\A(8\.4\.\d+\.\d+)\.?\s*(?:\((\d+)\))?/)
  m ? [m[1], m[2]&.to_i] : [nil, nil]
end

def esc(text)
  text.to_s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;').gsub('"', '&quot;')
end

# ---------------------------------------------------------------- inputs

# The source scan happens ONCE; classification per vintage. The one ambiguous
# token family is 8.4.4.x — the umbrella writes it meaning the 2025 EUI path,
# the domain gems write it meaning the reference building (2020 numbering, and
# runtime-renumbered to 8.4.5 on 2025 runs). Verified against the tree: no
# 8.4.5.x or 8.4.6.x literals exist anywhere, so this is the only fork.
# A citation's evidentiary weight depends on the call it sits on: a warning
# often announces the rule is NOT applied. Look back a few lines for the call.
def classify_call(lines, idx)
  idx.downto([idx - 6, 0].max) do |j|
    return :warn  if lines[j].match?(/(?:audit&?\.|\.)\s*warn\s*\(/)
    return :cited if lines[j].match?(/(?:audit&?\.|\.)\s*(?:decision|info)\s*\(/)
  end
  :cited
end


# Attribution is by DOMAIN, not gem directory: the by-nature refactor is
# folding the domain gems into btap-necb, where the subdirectory (or the
# manifest basename) carries the domain. Both spellings resolve here so every
# commit of the migration stays truthful. Fail-loud: an unattributable path
# aborts rather than silently losing its citations.
DOMAIN_SUBDIRS = %w[hvac envelope loads lighting shw].freeze
def domain_for(rel)
  seg = rel.split('/').first
  case seg
  when /\Aopenstudio-([a-z]+)\z/ then Regexp.last_match(1)
  when 'btap-necb' then rel[%r{btap_necb/(#{DOMAIN_SUBDIRS.join('|')})/}, 1] || 'necb'
  when /\Abtap-([a-z]+)\z/ then Regexp.last_match(1)
  else abort("cannot attribute #{rel} to a domain — teach domain_for")
  end
end

# Manifest basenames carry the domain (envelope_rules_2020.json => envelope);
# two historical names need mapping.
MANIFEST_DOMAINS = { 'reference' => 'hvac', 'necb' => 'necb' }.freeze
def manifest_domain(path)
  prefix = File.basename(path)[/\A([a-z]+)_rules_/, 1]
  MANIFEST_DOMAINS.fetch(prefix, prefix)
end

RAW_CITATIONS = [].tap do |acc|
  Dir.glob(File.join(ROOT, '{openstudio,btap}-*/lib/**/*.rb')).sort.each do |path|
    rel = path.sub("#{ROOT}/", '')
    gem_name = domain_for(rel)
    lines = File.readlines(path, encoding: 'UTF-8', invalid: :replace, undef: :replace)
    lines.each_with_index do |line, i|
      raw = line[/article:\s*["']([^"']+)["']/, 1] or next
      kind = classify_call(lines, i)
      tokens = raw.gsub('#{prefix}', 'PREFIX').scan(/(?:PREFIX|8\.4)(?:\.\d+)*\.?(?:\(\d+\))?/)
      acc << { gem: gem_name, file: rel, line: i + 1, kind: kind, tokens: tokens } unless tokens.empty?
    end
  end
end
# Fail LOUD: an empty scan means the gem glob went stale (directory rename),
# and the doc would regenerate 'cleanly' with every citation gone.
abort('RAW_CITATIONS is empty — the openstudio-*/lib glob went stale') if RAW_CITATIONS.empty?

def citations_for(vintage, articles)
  reference_prefix = vintage == '2020' ? '8.4.4' : '8.4.5'
  citations = Hash.new { |h, k| h[k] = [] }
  RAW_CITATIONS.each do |c|
    # An umbrella line citing ANY 8.4.4.x token is EUI-path code (the umbrella's
    # 8.4.4 is the 2025-only EUI subsection), so the WHOLE line is 2025-only —
    # including companion tokens like the 8.4.3.6.(1)(a) it applies rates from.
    # Without this, multi-article literals leak their non-EUI half into 2020.
    if vintage == '2020' && c[:gem] == 'necb' &&
       c[:tokens].any? { |t| t.start_with?('8.4.4.') }
      next
    end
    c[:tokens].each do |tok|
      ref = tok.sub('PREFIX', reference_prefix)
      if ref.start_with?('8.4.4.')
        if c[:gem] == 'necb'
          # umbrella 8.4.4.x = the 2025 EUI path; it has no 2020 counterpart
          next if vintage == '2020'
        elsif vintage == '2025'
          ref = ref.sub(/\A8\.4\.4\./, '8.4.5.') # domain gems: reference numbering
        end
      end
      art, = split_ref(ref)
      next unless art && articles.key?(art)

      citations[art] << { file: c[:file], line: c[:line], kind: c[:kind] }
    end
  end
  citations.each_value { |v| v.uniq! { |x| [x[:file], x[:line], x[:kind]] } }
  citations
end

def declarations_for(vintage)
  declarations = Hash.new { |h, k| h[k] = [] }
  Dir.glob(File.join(ROOT, "{openstudio,btap}-*/lib/**/data/necb/*_rules_#{vintage}.json")).sort.each do |path|
    data = JSON.parse(File.read(path))
    entries = data.dig('article_coverage', 'articles') or next
    gem_name = manifest_domain(path)
    entries.each do |e|
      next unless e['article'].to_s.start_with?('8.4')

      art, sentence = split_ref(e['article'])
      next unless art

      declarations[art] << e.merge('gem' => gem_name, 'vintage' => vintage, 'sentence' => sentence)
    end
  end
  # Same fail-loud rationale as RAW_CITATIONS: silence here means the manifest
  # glob went stale, not that nothing is declared.
  abort("no 8.4 declarations found for #{vintage} — the manifest glob went stale") if declarations.empty?
  declarations
end

# Runtime evidence, native per vintage: a 2020 run's audit cites 8.4.4.x and
# belongs to the 2020 part; it is not renumbered into the other edition.
RUNS = (ENV['NECB_AUDIT_JSONS'] || '').split(':').map(&:strip).reject(&:empty?)
def executed_for(vintage)
  executed = Hash.new { |h, k| h[k] = [] }
  RUNS.each do |dir|
    audit_path = File.join(dir, 'audit.json')
    next unless File.exist?(audit_path)

    run_vintage = begin
      JSON.parse(File.read(File.join(dir, 'report.json')))['vintage'].to_s
    rescue StandardError
      ''
    end
    next unless run_vintage == vintage

    levels = Hash.new { |h, k| h[k] = Hash.new(0) }
    JSON.parse(File.read(audit_path)).each do |entry|
      ref = entry['article'].to_s
      next unless ref.start_with?('8.4')

      art, = split_ref(ref)
      levels[art][entry['level'].to_s] += 1 if art
    end
    levels.each { |art, counts| executed[art] << { run: File.basename(dir), vintage: run_vintage, levels: counts } }
  end
  executed
end

DISPOSITIONS_2025 = JSON.parse(File.read(DISPOSITION))['dispositions']
def dispositions_for(vintage, articles)
  DISPOSITIONS_2025.each_with_object({}) do |(key, val), out|
    mapped = disposition_key_for(vintage, key)
    out[mapped] = val if mapped && articles.key?(mapped)
  end
end

def states_for(articles, declarations, citations, dispositions)
  states = {}
  conflicts = []
  articles.each_key do |art|
    primary = if declarations.key?(art) then :declared
              elsif citations.key?(art) then :cited
              elsif dispositions.key?(art) then :dispositioned
              else :unknown
              end
    states[art] = primary
    conflicts << art if dispositions.key?(art) && primary != :dispositioned
  end
  [states, conflicts]
end

# ---------------------------------------------------------------- rendering

def link(cit)
  short = "#{cit[:file].split('/').last}:#{cit[:line]}"
  badge = cit[:kind] == :warn ? ' <span class="pill bad" title="this citation sits on an audit WARNING — often announcing the rule is NOT applied">warning</span>' : ''
  %(<a href="#{BLOB}/#{cit[:file]}#L#{cit[:line]}" title="#{esc(cit[:file])}:#{cit[:line]}">#{esc(short)}</a>#{badge})
end

def executed_badge(obs)
  return '' if obs.empty?

  substantive = obs.any? { |o| (o[:levels].keys - ['warning']).any? }
  label = substantive ? 'observed in run' : 'observed in run (warnings only)'
  css = substantive ? 'ok' : 'warn'
  detail = obs.map { |o| "#{o[:run]} (#{o[:vintage]}): #{o[:levels].map { |l, n| "#{n} #{l}" }.join(', ')}" }.join(' | ')
  %(<span class="pill #{css}" title="#{esc(detail)}">#{label}</span>)
end

# Resolve a manifest code ref ("path#method") to its CURRENT line number.
#
# The manifests deliberately store method anchors, not line numbers — a line
# number rots with every edit above it. The DOCUMENT shows real line numbers
# anyway, because it is regenerated (and CI-gated) on every source change, so
# the resolution below is always fresh. Same contract as the "Cited at" links.
CODE_LINES = {}
def code_ref_link(ref)
  path, sym = ref.to_s.split('#', 2)
  return esc(ref) if path.nil? || sym.nil?

  CODE_LINES[ref] ||= begin
    file = File.join(ROOT, path)
    line = nil
    if File.file?(file)
      File.readlines(file, encoding: 'UTF-8', invalid: :replace, undef: :replace).each_with_index do |l, i|
        if l.match?(/def (self\.)?#{Regexp.escape(sym)}[\s(=]/) || l.match?(/def (self\.)?#{Regexp.escape(sym)}$/)
          line = i + 1
          break
        end
      end
    end
    line
  end
  line = CODE_LINES[ref]
  text = "#{File.basename(path)}##{sym}#{line ? ":#{line}" : ''}"
  %(<a href="#{BLOB}/#{esc(path)}#{line ? "#L#{line}" : ''}" title="#{esc(ref)}">#{esc(text)}</a>)
end

def code_cell(entry)
  refs = Array(entry['code'])
  return '' if refs.empty?

  %(<div class="coderefs">#{refs.map { |r| code_ref_link(r) }.join(' · ')}</div>)
end

# Plain per-article declaration table. Each vintage part shows only its own
# edition's declarations, so no inner vintage split is needed any more.
def declaration_rows(decls, art_executed)
  # A host_scope row beside the row that actually implements the article is
  # bookkeeping, not information: it exists so an hvac-only RUN still audits
  # "this is envelope's job", but a reader looking at 8.4.4.3 does not need
  # "openstudio-hvac: Delegated" as a peer of the envelope implementation. When
  # an implementing declaration is present, delegations collapse to a footnote;
  # they render as rows only in the "(none in family)" case, where the
  # delegation IS the open item.
  implementing = decls.reject { |d| d['status'] == 'host_scope' }
  delegations = decls.select { |d| d['status'] == 'host_scope' }
  shown = implementing.any? ? implementing : delegations

  rows = shown.group_by { |d| [d['gem'], d['article'], d['status'], d['how'].to_s, d['gaps'].to_s] }
              .map do |(gem_name, article, status, how, gaps), group|
    label, css = STATUS_META.fetch(status, [status, 'none'])
    <<~ROW
      <tr>
        <td class="ref">#{esc(article)}</td>
        <td>#{esc(gem_name)}</td>
        <td><span class="pill #{css}">#{esc(label)}</span> #{art_executed}</td>
        <td class="how">#{esc(how)}#{gaps.empty? ? '' : %(<div class="gaps"><b>Gaps:</b> #{esc(gaps)}</div>)}#{code_cell(group.first)}</td>
      </tr>
    ROW
  end.join
  table = %(<table class="inner"><thead><tr><th>Declared at</th><th>Gem</th><th>Status</th><th>How / gaps · code</th></tr></thead><tbody>#{rows}</tbody></table>)
  if implementing.any? && delegations.any?
    note = delegations.map { |d| d['gem'] }.uniq.sort.join(', ')
    table += %(<div class="dim delegnote">Also declared <code>host_scope</code> by #{esc(note)} — runtime bookkeeping so a partial-composition run still names the owner; reconciled against the row#{implementing.size == 1 ? '' : 's'} above.</div>)
  end
  table
end

def citation_cell(cits)
  return '' if cits.to_a.empty?

  links = cits.first(8).map { |c| link(c) }
  links << "<span class=\"dim\">+#{cits.size - 8} more</span>" if cits.size > 8
  <<~HTML
    <div class="citerow"><b>Cited at</b> <span class="dim">(a citation proves a log line mentions the
    article — it is not, by itself, evidence the rule is applied):</span> #{links.join(' · ')}</div>
  HTML
end

def disposition_block(art, dispo, conflict)
  label, css = DISPOSITION_META.fetch(dispo['category'], [dispo['category'], 'none'])
  target = Array(dispo['covered_by']).join(', ')
  <<~HTML
    <div class="dispo#{conflict ? ' conflict' : ''}">
      #{conflict ? '<span class="pill bad">⚑ CONFLICT</span> this article is dispositioned AND declared/cited — resolve, do not trust either alone.' : ''}
      <span class="pill #{css}">#{esc(label)}#{target.empty? ? '' : ": #{esc(target)}"}</span>
      #{dispo['draft'] ? '<span class="pill warn" title="not yet reviewed by a human">DRAFT</span>' : ''}
      <span class="how">#{esc(dispo['rationale'])}</span>
      <div class="dim">Reviewer: #{esc(dispo['reviewer'])}</div>
    </div>
  HTML
end

def clause_tree(art, record, decls)
  unless record['parse_ok']
    return <<~HTML
      <details><summary>Requirement text — <b>structure unverified</b> (#{esc(record['reason'])})</summary>
      <p class="dim">The parser could not verify this article's sentence structure, so the raw text is shown
      rather than a guessed tree (text under a wrong number is worse than no tree).</p>
      <pre>#{esc(record['raw'])}</pre></details>
    HTML
  end

  sentence_decls = decls.group_by { |d| d['sentence'] }
  depth_note = if sentence_decls.keys.compact.any?
                 'coverage below is declared per-sentence where marked'
               elsif decls.any?
                 'coverage is declared at ARTICLE level — per-sentence marks would be fabrication'
               else
                 'no coverage declared at any depth'
               end
  items = record['sentences'].map do |s|
    # Dedupe across vintages: hvac declares the same sentence in 2020 and 2025
    # numbering, and two identical pills per sentence read as stutter. One pill,
    # vintages named in the tooltip; a vintage-specific difference in status or
    # text still gets its own pill because it hashes differently.
    marks = (sentence_decls[s['num']] || [])
            .group_by { |d| [d['gem'], d['status'], d['how'].to_s, Array(d['code'])] }
            .map do |(_gem, _status, _how, _code), same|
      d = same.first
      vintages = same.map { |x| x['vintage'] }.uniq.sort.join(', ')
      label, css = STATUS_META.fetch(d['status'], [d['status'], 'none'])
      # "Where is this dealt with": the manifest's path#method refs, linted by
      # test_coverage_code_refs.rb, rendered as file deep links (method in the
      # link text — GitHub cannot anchor a method, and line numbers rot).
      code = Array(d['code']).map { |ref| code_ref_link(ref) }.join(' · ')
      pill = %(<span class="pill #{css}" title="#{esc(d['gem'])} (#{esc(vintages)}): #{esc(d['how'].to_s[0, 160])}">#{esc(d['gem'])}: #{esc(label)}</span>)
      code.empty? ? pill : "#{pill} <span class=\"dim\">[#{code}]</span>"
    end.join(' ')
    clauses = s['clauses'].map do |c|
      subs = c['subclauses'].map { |sc| %(<li class="sub"><span class="cid">(#{esc(sc['id'])})</span> #{esc(sc['text'])}</li>) }.join
      %(<li><span class="cid">(#{esc(c['id'])})</span> #{esc(c['text'])}#{subs.empty? ? '' : "<ul>#{subs}</ul>"}</li>)
    end.join
    %(<li><span class="cid">(#{s['num']})</span> #{esc(s['text'])} #{marks}#{clauses.empty? ? '' : "<ul>#{clauses}</ul>"}</li>)
  end.join
  eqs = Array(record['equations']).first(6)
  eq_html = eqs.empty? ? '' : %(<div class="eqs"><b>Formulas (reference rendering):</b><pre>#{esc(eqs.join("\n\n"))}</pre></div>)
  <<~HTML
    <details><summary>Requirement text (#{record['sentences'].size} sentences) — <span class="dim">#{depth_note}</span></summary>
    <ul class="clauses">#{items}</ul>#{eq_html}</details>
  HTML
end

STATE_META = { declared: ['Declared', 'ok'], cited: ['Cited in code, not declared', 'warn'],
               dispositioned: ['Dispositioned', 'host'], unknown: ['Unknown', 'bad'] }.freeze

# One vintage part: the full subsection walk for that edition, natively
# numbered, preceded by its own summary cards. Anchors are vintage-prefixed so
# 8.4.4.9 (2020, Heating System) and 8.4.4.2 (2025, EUI schedules) cannot
# collide.
def vintage_part(vintage)
  articles = JSON.parse(File.read(CACHES.fetch(vintage)))['articles']
  outside = articles.keys.reject { |k| k.start_with?('8.4.') }
  abort("LINT: non-8.4 content in the #{vintage} text cache: #{outside.join(', ')}") unless outside.empty?

  declarations = declarations_for(vintage)
  citations = citations_for(vintage, articles)
  executed = executed_for(vintage)
  dispositions = dispositions_for(vintage, articles)
  states, conflicts = states_for(articles, declarations, citations, dispositions)
  counts = states.values.tally
  total = counts.values.sum
  abort("SELF-CHECK FAILED (#{vintage}): states sum to #{total}, not #{articles.size}") unless total == articles.size

  sections_html = SUBSECTIONS.fetch(vintage).map do |prefix, sub_title|
    rows = articles.keys.select { |a| a.start_with?("#{prefix}.") }
                   .sort_by { |a| a.scan(/\d+/).map(&:to_i) }.map do |art|
      record = articles[art]
      decls = declarations[art]
      state = states[art]
      label, css = STATE_META[state]
      conflict = conflicts.include?(art)
      exec_badge = executed_badge(executed[art])

      body = +''
      if decls.any?
        body << declaration_rows(decls, exec_badge)
      elsif state == :cited
        body << %(<div class="dispo"><span class="pill warn">cited in code, not declared</span> <span class="how">No
          manifest entry exists, but source citations reference this article (see below). This is a manifest
          gap to close — it is NOT a claim of implementation.</span> #{exec_badge}</div>)
      elsif state == :unknown
        body << %(<div class="dispo"><span class="pill bad">unknown</span> <span class="how">No declaration, no
          citation, no disposition. Nothing is known about how this article is satisfied.</span></div>)
      end
      body << disposition_block(art, dispositions[art], conflict) if dispositions.key?(art)
      body << citation_cell(citations[art])
      body << clause_tree(art, record, decls)

      <<~ROW
        <tr class="article" id="v#{vintage}-a#{art.tr('.', '-')}">
          <td class="ref">#{esc(art)}.</td>
          <td><b>#{esc(record['title'].to_s.empty? ? '(untitled)' : record['title'])}</b>
              <span class="pill #{css}">#{label}</span>#{conflict ? ' <span class="pill bad">⚑</span>' : ''}
              <span class="dim">pp. #{record['pages']&.join('–')}</span></td>
        </tr>
        <tr class="nested"><td colspan="2">#{body}</td></tr>
      ROW
    end.join
    <<~SECTION
      <section><h2>#{esc(prefix)}. #{esc(sub_title)}</h2>
      <table class="outer"><tbody>#{rows}</tbody></table></section>
    SECTION
  end.join

  cards = STATE_META.map do |state, (label, css)|
    %(<div class="card #{css}"><b>#{counts[state] || 0}</b><span>#{label}</span></div>)
  end.join + %(<div class="card bad"><b>#{conflicts.size}</b><span>⚑ Conflicts</span></div>)

  { articles: articles, counts: counts, conflicts: conflicts,
    html: <<~PART }
      <details class="vintage-part" open id="v#{vintage}">
      <summary><b>NECB #{vintage}</b> — #{articles.size} articles <span class="dim">(click to collapse)</span></summary>
      <div class="cards">#{cards}</div>
      <div class="scroll">#{sections_html}</div>
      </details>
    PART
end

parts = { '2020' => vintage_part('2020'), '2025' => vintage_part('2025') }

run_note = if RUNS.empty?
             'No run evidence supplied (set NECB_AUDIT_JSONS to one or more run directories containing audit.json + report.json) — the "observed in run" tier is absent from this build.'
           else
             "Run evidence: #{RUNS.map { |r| File.basename(r) }.join(', ')} — articles cited at runtime in those runs carry an \"observed in run\" badge (the strongest evidence tier here: it proves the citing code executed in at least one real scenario)."
           end

html = <<~HTML
  <!doctype html>
  <html lang="en"><head><meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NECB Section 8.4 — Performance Path coverage</title>
  <style>
    :root { color-scheme: light dark;
      --bg:#fff; --fg:#1a1a1a; --dim:#666; --line:#e3e3e3; --panel:#fafafa;
      --ok:#1a7f37; --warn:#9a6700; --bad:#b32424; --clone:#0969da; --host:#6639ba; --none:#767676; }
    @media (prefers-color-scheme: dark) { :root {
      --bg:#0d1117; --fg:#e6edf3; --dim:#9198a1; --line:#30363d; --panel:#161b22;
      --ok:#3fb950; --warn:#d29922; --bad:#f85149; --clone:#58a6ff; --host:#bc8cff; --none:#8b949e; } }
    :root[data-theme="dark"] { --bg:#0d1117; --fg:#e6edf3; --dim:#9198a1; --line:#30363d; --panel:#161b22;
      --ok:#3fb950; --warn:#d29922; --bad:#f85149; --clone:#58a6ff; --host:#bc8cff; --none:#8b949e; }
    :root[data-theme="light"] { --bg:#fff; --fg:#1a1a1a; --dim:#666; --line:#e3e3e3; --panel:#fafafa;
      --ok:#1a7f37; --warn:#9a6700; --bad:#b32424; --clone:#0969da; --host:#6639ba; --none:#767676; }
    body { background:var(--bg); color:var(--fg); margin:0 auto; padding:2rem 1.25rem; max-width:76rem;
      font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
    h1 { font-size:1.55rem; margin:0 0 .3rem; } h2 { font-size:1.12rem; margin:2rem 0 .5rem; }
    .lede { color:var(--dim); max-width:58rem; }
    .caveat { border-left:3px solid var(--warn); background:var(--panel); padding:.8rem 1rem; margin:1.1rem 0; border-radius:0 4px 4px 0; }
    .cards { display:flex; flex-wrap:wrap; gap:.5rem; margin:1.1rem 0; }
    .card { border:1px solid var(--line); border-radius:6px; padding:.5rem .85rem; background:var(--panel); min-width:8rem; }
    .card b { display:block; font-size:1.3rem; } .card span { color:var(--dim); font-size:.78rem; }
    .card.ok b{color:var(--ok)} .card.warn b{color:var(--warn)} .card.bad b{color:var(--bad)} .card.host b{color:var(--host)}
    .scroll { overflow-x:auto; }
    table { border-collapse:collapse; width:100%; }
    tr.article > td { border-top:1px solid var(--line); padding:.55rem .5rem; background:var(--panel); vertical-align:top; }
    tr.nested > td { padding:.15rem 0 .8rem 1.4rem; border:0; }
    table.inner { font-size:.87rem; margin:.3rem 0; }
    table.inner th { text-align:left; font-weight:500; font-size:.72rem; text-transform:uppercase; color:var(--dim);
      padding:.25rem .5rem; border-bottom:1px solid var(--line); }
    table.inner td { padding:.4rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }
    .ref { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; white-space:nowrap; }
    .orig { color:var(--dim); font-size:.72rem; }
    .dim { color:var(--dim); font-size:.82em; }
    .how { max-width:44rem; display:inline; } .gaps { margin-top:.3rem; color:var(--warn); }
    .pill { display:inline-block; padding:.05rem .5rem; border-radius:10px; font-size:.74rem; white-space:nowrap; border:1px solid currentColor; }
    .pill.ok{color:var(--ok)} .pill.warn{color:var(--warn)} .pill.bad{color:var(--bad)}
    .pill.clone{color:var(--clone)} .pill.host{color:var(--host)} .pill.none{color:var(--none)}
    .citerow { font-size:.83rem; margin:.35rem 0; }
    .citerow a { color:var(--clone); text-decoration:none; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em; }
    .citerow a:hover { text-decoration:underline; }
    .dispo { font-size:.87rem; margin:.35rem 0; padding:.45rem .6rem; background:var(--panel); border:1px solid var(--line); border-radius:5px; }
    .dispo.conflict { border-color:var(--bad); }
    details { margin:.4rem 0; font-size:.88rem; }
    summary { cursor:pointer; color:var(--dim); }
    ul.clauses { margin:.5rem 0 .3rem; padding-left:1.2rem; list-style:none; }
    ul.clauses ul { list-style:none; padding-left:1.4rem; }
    ul.clauses li { margin:.3rem 0; }
    .cid { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--host); }
    .eqs pre, details pre { background:var(--panel); border:1px solid var(--line); border-radius:5px;
      padding:.6rem; overflow-x:auto; font-size:.8rem; white-space:pre-wrap; }
    footer { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line); color:var(--dim); font-size:.82rem; }
    code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.9em; }
    .coderefs { margin-top:.25rem; font-size:.8rem; }
    .coderefs a { color:var(--clone); text-decoration:none; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
    .coderefs a:hover { text-decoration:underline; }
    .delegnote { margin:.2rem 0 .4rem; font-size:.78rem; }
    details.vintage-part { margin:1.4rem 0; border:1px solid var(--line); border-radius:8px; padding:.2rem .9rem .6rem; }
    details.vintage-part > summary { cursor:pointer; font-size:1.25rem; padding:.55rem 0; color:var(--fg); }
    details.vintage-part[open] > summary { border-bottom:1px solid var(--line); margin-bottom:.6rem; }
</style></head><body>

  <h1>NECB Section 8.4 — Performance Path coverage</h1>
  <p class="lede">How the <code>openstudio-*</code> gem family covers Section 8.4 of the National Energy Code of
  Canada for Buildings — one collapsible part per edition, each walking its own subsections under its own
  article numbers. Every article of both editions renders with its full requirement text, so coverage cannot
  be overstated by omission. #{esc(run_note)}</p>

  <div class="caveat"><b>How to read the evidence — weakest to strongest.</b>
  <ul>
    <li><b>Disposition</b> — a curated claim of <i>responsibility</i> (engine / modeller / named gem / gap), not
        of correctness. Draft dispositions are unreviewed.</li>
    <li><b>"Cited at" links</b> — the article number appears on an audit log call in that source line. A citation
        proves the log line exists, <em>nothing more</em>; citations sitting on <em>warnings</em> often announce
        the rule is <em>not</em> applied and are badged accordingly. Absence of a citation is not evidence of
        non-implementation either.</li>
    <li><b>Manifest status</b> — the gem's self-declared <code>article_coverage</code>. "Implemented" here means
        the gem <i>asserts</i> it applies the rule; two real defects have been found inside articles declared
        implemented. Independent behavioural verification is <code>rake necb:verify</code>
        (see <code>btap-necb/docs/necb_rule_verification.md</code>).</li>
    <li><b>"Observed in run"</b> — the article was cited at runtime in a named real pipeline run: the citing code
        demonstrably executed in at least one scenario. Still not proof of correct values.</li>
  </ul>
  <b>Prescriptive values</b> (U-values, LPDs, efficiencies) are governed by each gem's own data JSON — the number
  the software actually applies and the thing to audit: <code>openstudio-envelope .../envelope_rules_*.json</code>,
  <code>openstudio-loads .../space_types_*.json</code>, <code>openstudio-shw .../shw_rules_*.json</code>,
  <code>openstudio-hvac .../efficiencies_*.json</code>. The official code wording is available through the
  building-codes MCP (<code>get_section</code>/<code>get_table</code>) as a human reference only.</div>

  <p class="lede"><b>Jump to:</b> <a href="#v2020">NECB 2020</a> (#{parts['2020'][:articles].size} articles,
  8.4.1–8.4.5) · <a href="#v2025">NECB 2025</a> (#{parts['2025'][:articles].size} articles, 8.4.1–8.4.6).
  Each edition is a collapsible part in its OWN article numbering — 2020's 8.4.4 is the reference building
  where 2025's 8.4.4 is the EUI path, so nothing is renumbered across editions here.</p>

  #{parts['2020'][:html]}
  #{parts['2025'][:html]}

  <footer>Generated by <code>btap-necb/scripts/generate_necb_8_4_coverage.rb</code> — do not edit by hand
  (<code>rake necb:coverage_doc</code> to regenerate).
  Requirement text: NECB 2020 and 2025 Division B via the building-codes MCP
  (2020 retrieved #{esc(JSON.parse(File.read(CACHES['2020'])).dig('provenance', 'retrieved'))},
  2025 retrieved #{esc(JSON.parse(File.read(CACHES['2025'])).dig('provenance', 'retrieved'))})
  (Crown copyright — reproduction authorized as Government of Canada work); parse safety checks in
  <code>scripts/fetch_necb_8_4_text.rb</code>. Source links resolve against <code>#{esc(BRANCH)}</code> of #{esc(REPO)}.</footer>
  </body></html>
HTML

File.write(OUT, html)
puts "wrote #{OUT.sub("#{ROOT}/", '')}"
parts.each do |vintage, part|
  puts format('  %s: %s  (sum %d/%d)  conflicts: %s',
              vintage, part[:counts].map { |k, v| "#{k}=#{v}" }.join(' '),
              part[:counts].values.sum, part[:articles].size, part[:conflicts].join(', '))
  parse_fail = part[:articles].reject { |_, r| r['parse_ok'] }.keys
  puts "  #{vintage} clause-tree fallbacks: #{parse_fail.empty? ? 'none' : parse_fail.join(', ')}"
end
