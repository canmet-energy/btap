require 'minitest/autorun'
require 'json'

# Every `code` reference in every gem's article_coverage manifest must resolve:
# the file exists and defines the named symbol. Without this, the per-sentence
# "where is this dealt with" pointers rot silently on the next rename — and a
# stale pointer in an AHJ-facing document is worse than none.
#
# Pure JSON + file reads: no SDK, no gem requires. Runs on the bare lint runner.
class TestCoverageCodeRefs < Minitest::Test
  ROOT = File.expand_path('../..', __dir__)

  def manifests
    Dir.glob(File.join(ROOT, '*/lib/**/*_rules_*.json')).sort.filter_map do |path|
      data = JSON.parse(File.read(path, encoding: 'UTF-8'))
      arts = data.dig('article_coverage', 'articles')
      [path.sub("#{ROOT}/", ''), arts] if arts
    end
  end

  def test_every_code_ref_resolves_to_a_real_symbol
    checked = 0
    manifests.each do |manifest, arts|
      arts.each do |art|
        Array(art['code']).each do |ref|
          path, symbol = ref.split('#', 2)
          file = File.join(ROOT, path.to_s)
          assert(File.file?(file), "#{manifest} #{art['article']}: no such file #{path}")
          refute(symbol.to_s.empty?, "#{manifest} #{art['article']}: ref #{ref} has no #symbol")
          source = File.read(file, encoding: 'UTF-8')
          assert(source.match?(/def (self\.)?#{Regexp.escape(symbol)}[\s(=]/) ||
                 source.match?(/def (self\.)?#{Regexp.escape(symbol)}$/),
                 "#{manifest} #{art['article']}: #{path} does not define ##{symbol}")
          checked += 1
        end
      end
    end
    assert_operator(checked, :>, 60, 'the code refs exist and were actually checked')
  end

  # The refs answer "where is this sentence dealt with", so a sentence that IS
  # dealt with must say where. not_implemented and modeller-scope entries have
  # no site by definition; sizing-time partials may legitimately have none.
  def test_every_implemented_sentence_entry_names_its_code
    manifests.each do |manifest, arts|
      arts.each do |art|
        next unless art['article'] =~ /\(\d+\)\z/     # per-sentence entries only
        next unless art['status'] == 'implemented'

        refute_empty(Array(art['code']),
                     "#{manifest} #{art['article']}: implemented per-sentence entries must name " \
                     'the code that implements them')
      end
    end
  end
end
