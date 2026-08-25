#!/usr/bin/env ruby
# frozen_string_literal: true

# Fetches every NECB Section 8.4 article from the building-codes MCP for ONE
# edition (EDITION=2025 default, EDITION=2020 supported),
# parses each into a sentence/clause tree with STRICT sanity checks, and caches
# the result to data/necb_8_4_articles_2025.json for the coverage-document
# generator (which must run in CI without MCP access).
#
#   ruby scripts/fetch_necb_8_4_text.rb
#
# Auth: X-API-Key from $HBIX_API_KEY, else read at runtime from .mcp.json
# (which is never committed with a live key). The key is never printed and
# never written into the cache.
#
# Parsing is deliberately conservative: an article whose text fails ANY sanity
# check is cached with parse_ok: false and its raw text — the generator then
# renders "structure unverified" with the raw text in a <details>, never a
# guessed tree. Requirement text under the wrong article number is the worst
# outcome available in a compliance document; a patchy tree is not.

require 'json'
require 'net/http'
require 'uri'
require 'date'
require 'fileutils'

ROOT = File.expand_path('../..', __dir__)
# The two editions do not share Section 8.4's structure: 2020's 8.4.4 is the
# reference building (20 articles) and 8.4.5 the part-load curves; 2025 inserts
# the EUI path as 8.4.4 and shifts everything down. One article list per
# edition, not a renumbering of one list.
EDITION = ENV.fetch('EDITION', '2025')
abort("unsupported EDITION #{EDITION} (2020|2025)") unless %w[2020 2025].include?(EDITION)
OUT = File.expand_path("../data/necb_8_4_articles_#{EDITION}.json", __dir__)

ARTICLES = if EDITION == '2020'
             [
               *(1..4).map { |i| "8.4.1.#{i}" },
               *(1..10).map { |i| "8.4.2.#{i}" },
               *(1..9).map { |i| "8.4.3.#{i}" },
               *(1..20).map { |i| "8.4.4.#{i}" },
               *(1..9).map { |i| "8.4.5.#{i}" }
             ].freeze
           else
             [
               *(1..5).map { |i| "8.4.1.#{i}" },
               *(1..12).map { |i| "8.4.2.#{i}" },
               *(1..9).map { |i| "8.4.3.#{i}" },
               *(1..2).map { |i| "8.4.4.#{i}" },
               *(1..20).map { |i| "8.4.5.#{i}" },
               *(1..9).map { |i| "8.4.6.#{i}" }
             ].freeze
           end

# .mcp.json is gitignored (it carries live keys) and is simply absent in a fresh
# clone or on CI. Read it defensively: an unguarded File.read raised
# Errno::ENOENT instead of the intended abort message, which read as a crash
# rather than "you have not configured this yet".
SERVER = 'codes'

def mcp_config
  return @mcp_config if defined?(@mcp_config)

  path = File.join(ROOT, '.mcp.json')
  @mcp_config = File.exist?(path) ? (JSON.parse(File.read(path)).dig('mcpServers', SERVER) || {}) : {}
rescue JSON::ParserError => e
  abort("#{path} is not valid JSON: #{e.message}")
end

# ONE key for all six servers, under one name — the same one canmet-energy/bluesky
# uses, so a .env copied between the repos works in both. There is deliberately no
# per-server alias: the servers do not take different keys, so a second name would
# only raise the question of which one to set. The .mcp.json fallback is LAST and
# skipped when it holds a ${VAR} placeholder that cannot be resolved — see expand.
def api_key
  @api_key ||= ENV['HBIX_API_KEY'] ||
               expand(mcp_config.dig('headers', 'X-API-Key')) ||
               abort('no codes API key: set HBIX_API_KEY (see .env.example)')
end

# .mcp.json holds ${VAR} and ${VAR:-default} placeholders that Claude Code
# expands but this script does not, so expand them here from ENV. nil when a
# placeholder has neither a value nor a default — the caller then falls through
# to its abort instead of sending the literal string and getting a bare 403.
def expand(value)
  return nil if value.nil?

  out = value.gsub(/\$\{(\w+)(?::-([^}]*))?\}/) { ENV[Regexp.last_match(1)] || Regexp.last_match(2) || "\0" }
  out unless out.include?("\0")
end

# One knob, matching the key: HBIX_MCP_BASE_URL moves every server at once, and
# the per-server path is ours to append rather than yours to retype. It is
# checked BEFORE .mcp.json so a staging base wins over an installed template,
# and it keeps "no .mcp.json" a supported configuration without hardcoding a
# host here (see the auth paragraph under D-71..D-75).
def endpoint
  @endpoint ||= URI(
    (ENV['HBIX_MCP_BASE_URL'] && "#{ENV['HBIX_MCP_BASE_URL'].chomp('/')}/#{SERVER}/mcp") ||
    expand(mcp_config['url']) ||
    abort("no #{SERVER} MCP url: set HBIX_MCP_BASE_URL (see .env.example) or install .mcp.json")
  )
end

# One stateless JSON-RPC tools/call. The server replies as a single SSE
# "data:" frame wrapping the tool result, whose content[0].text is itself JSON.
def get_section(number)
  req = Net::HTTP::Post.new(endpoint)
  req['X-API-Key'] = api_key
  req['Content-Type'] = 'application/json'
  req['Accept'] = 'application/json, text/event-stream'
  req.body = { jsonrpc: '2.0', id: 1, method: 'tools/call',
               params: { name: 'get_section',
                         arguments: { code: 'necb', edition: EDITION, division: 'B',
                                      section_number: number, include_sentences: false } } }.to_json
  res = Net::HTTP.start(endpoint.host, endpoint.port, use_ssl: true, read_timeout: 60) { |h| h.request(req) }
  raise "HTTP #{res.code} for #{number}" unless res.code == '200'

  data_line = res.body.lines.find { |l| l.start_with?('data: ') } or raise "no SSE data frame for #{number}"
  payload = JSON.parse(data_line.delete_prefix('data: '))
  raise "RPC error for #{number}: #{payload['error']}" if payload['error']

  JSON.parse(payload.dig('result', 'content', 0, 'text'))['result'] ||
    JSON.parse(payload.dig('result', 'content', 0, 'text'))
end

# ---------------------------------------------------------------- parsing

FURNITURE = [
  /\ANational Energy Code of Canada for Buildings #{EDITION}\z/,
  /\ADivision B(\s+8-\d+)?\z/,
  /\A8-\d+\s+Division B\z/,
  /\A©\s*His Majesty.*\z/,
  /\A\d{1,3}\z/ # bare page number
].freeze

ARTICLE_TOKEN = /\A8\.4\.\d+\.(\d+\.)?\z/
SENTENCE = /\A(\d+)\)\s+(.*)\z/
CLAUSE = /\A([a-z])\)\s+(.*)\z/
ROMAN = /\A(i{1,3}|iv|vi{0,3}|ix)\)\s+(.*)\z/

# Reject if a DIFFERENT article demonstrably starts inside this body: its
# token followed within 3 lines by a sentence "1)". A bare token with no such
# follow-up is a page running header and is stripped, not rejected — 8.4.6.4's
# correct body legitimately contains "8.4.6.5." as a running header.
def embedded_article_start?(lines, own)
  lines.each_with_index do |line, i|
    next unless line.strip.match?(ARTICLE_TOKEN)
    next if line.strip.delete_suffix('.') == own

    return line.strip if lines[(i + 1)..(i + 3)].to_a.any? { |l| l.strip.match?(/\A1\)\s/) }
  end
  nil
end

def parse_article(number, record)
  raw = record['full_text'].to_s
  lines = raw.split("\n").map(&:rstrip)

  if (foreign = embedded_article_start?(lines, number))
    return { 'parse_ok' => false, 'reason' => "embedded start of article #{foreign}" }
  end

  lines = lines.reject do |l|
    s = l.strip
    FURNITURE.any? { |re| s.match?(re) } || s.match?(ARTICLE_TOKEN) || s.empty?
  end

  sentences = []
  preamble_notes = []
  preamble_dropped = []
  current = nil     # innermost text sink: sentence, clause, or subclause hash
  expected_letter = nil

  lines.each do |line|
    s = line.strip
    if (m = s.match(SENTENCE))
      sentences << { 'num' => m[1].to_i, 'text' => m[2], 'clauses' => [] }
      current = sentences.last
      expected_letter = 'a'
    elsif sentences.any? && (m = s.match(CLAUSE)) &&
          # "i)" is a clause letter only when it is the alphabetically expected
          # next letter; otherwise it is a roman numeral under the open clause
          # (e.g. 8.4.5.13.(2)(g)(i)).
          !(m[1].match?(/\A(i|v|x)\z/) && m[1] != expected_letter)
      clause = { 'id' => m[1], 'text' => m[2], 'subclauses' => [] }
      sentences.last['clauses'] << clause
      current = clause
      expected_letter = m[1].next
    elsif sentences.any? && (m = s.match(ROMAN)) && sentences.last['clauses'].any?
      sub = { 'id' => m[1], 'text' => m[2] }
      sentences.last['clauses'].last['subclauses'] << sub
      current = sub
    elsif sentences.empty?
      # Before sentence 1): keep code notes, log anything else (e.g. the
      # wrapped-title fragment "and Set-Point Temperature") for transparency.
      s.match?(/\A\(See\s/) ? preamble_notes << s : preamble_dropped << s
    else
      current['text'] = "#{current['text']} #{s}".strip
    end
  end

  # Trailing next-subsection heading bleed ("Interior Lighting", "Boiler"):
  # a short heading-like tail glued onto the last text sink is dropped.
  if current && (m = current['text'].match(/\A(.*[.)])\s+([A-Z][A-Za-z ,\/-]{2,40})\z/))
    current['text'] = m[1]
  end

  nums = sentences.map { |x| x['num'] }
  reason = if sentences.empty? then 'no sentences found'
           elsif nums.first != 1 then "first sentence is #{nums.first}), not 1)"
           elsif nums != (1..nums.size).to_a then "sentence numbering not contiguous: #{nums.join(',')}"
           end
  return { 'parse_ok' => false, 'reason' => reason } if reason

  { 'parse_ok' => true, 'sentences' => sentences,
    'preamble_notes' => preamble_notes, 'preamble_dropped' => preamble_dropped }
end

# ---------------------------------------------------------------- main

return unless __FILE__ == $PROGRAM_NAME # requirable for tests (necb:coverage_doc lint)

cache = {
  'provenance' => {
    'code' => 'necb', 'edition' => EDITION, 'division' => 'B',
    'retrieved' => Date.today.iso8601,
    'source' => 'building-codes MCP (get_section, JSON-RPC), Crown copyright — reproduction authorized (GoC work)',
    'note' => 'Regenerate with: ruby scripts/fetch_necb_8_4_text.rb. The 2020->2025 renumbering (8.4.4->8.4.5) makes stale text actively misleading; check `retrieved` before trusting.'
  },
  'articles' => {}
}

ok = 0
ARTICLES.each do |number|
  record = get_section(number)
  parsed = parse_article(number, record)
  ok += 1 if parsed['parse_ok']
  cache['articles'][number] = {
    'title' => record['title'].to_s,
    'pages' => [record['page_start'], record['page_end']],
    'equations' => Array(record['equations']).map { |e| e['text'] || e['raw_text'] }.compact,
    'raw' => record['full_text'].to_s
  }.merge(parsed)
  status = parsed['parse_ok'] ? 'ok        ' : "UNVERIFIED (#{parsed['reason']})"
  puts format('%-10s %s %s', number, status, record['title'].to_s[0, 50])
rescue StandardError => e
  cache['articles'][number] = { 'parse_ok' => false, 'reason' => "fetch failed: #{e.message}", 'raw' => '' }
  puts format('%-10s FETCH FAILED %s', number, e.message)
end

FileUtils.mkdir_p(File.dirname(OUT))
File.write(OUT, JSON.pretty_generate(cache))
puts "\n#{ok}/#{ARTICLES.size} parsed clean -> #{OUT.sub("#{ROOT}/", '')}"
