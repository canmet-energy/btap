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

  # The refs answer "where is this dealt with", so an entry that claims a rule
  # IS dealt with must say where — at every depth, not only per sentence:
  #
  #   implemented / satisfied_by_clone   always (the claim is a code claim)
  #   host_scope                         must point at the DELEGATE's code —
  #                                      "delegated to gem X" without a pointer
  #                                      was the reader complaint that produced
  #                                      this field — unless the delegate is the
  #                                      modeller, who has no code
  #   partial                            unless the applied half is EnergyPlus
  #                                      sizing-time behaviour with no gem site
  #   not_implemented / modeller scope   no site exists by definition
  def test_every_covering_entry_names_its_code
    sizing_time = /sizing[- ]time|autosiz|not explicitly enforced|not individually evaluated/i
    manifests.each do |manifest, arts|
      arts.each do |art|
        next if art['gap_owner'] == 'modeller'

        needed = case art['status']
                 when 'implemented', 'satisfied_by_clone' then true
                 when 'host_scope' then !"#{art['how']} #{art['gaps']}".match?(/modeller/i)
                 when 'partial' then !art['gaps'].to_s.match?(sizing_time)
                 else false
                 end
        next unless needed

        refute_empty(Array(art['code']),
                     "#{manifest} #{art['article']} (#{art['status']}): must name the code where " \
                     'this is dealt with')
      end
    end
  end
end
