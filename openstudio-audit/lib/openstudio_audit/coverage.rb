module OpenStudioAudit
  # Article-coverage emission: the ONE implementation of the completeness
  # accounting every family gem performs at the end of its happy path.
  #
  # Each gem owns an `article_coverage` manifest (implemented / partial /
  # not_implemented / satisfied_by_clone / host_scope) and resolves it its own
  # way — from a pre-resolved ruleset (hvac), from `NECB.rules(vintage)`
  # (envelope, lighting, loads, shw) or from a data file path (the umbrella).
  # What every gem then does with it is identical, and lives here: every
  # declared article lands in the audit with its status and how many decisions
  # cited it this run, so a missed requirement is visible in every log rather
  # than discovered by review.
  #
  # partial/not_implemented WARN — except entries flagged `gap_owner:
  # "modeller"`, whose remaining gaps are wholly the modeller's responsibility:
  # those emit as info scope notes instead, so the AHJ report is not
  # permanently stamped with warnings no model change can clear (project
  # decision D-09, openstudio-necb/docs/necb_decisions.md).
  module Coverage
    module_function

    # @param coverage [Hash, nil] the resolved `article_coverage` block — a
    #   Hash with an 'articles' list of
    #   {article, title, status, how, gaps, gap_owner} records
    # @param audit [OpenStudioAudit::AuditLog] the run's audit log; entries are
    #   appended, and their `article:` tags are what the citation count reads
    # @return [void]
    def emit(coverage, audit)
      return if coverage.nil?

      cited = Hash.new(0)
      audit.entries.each { |e| e[:article].to_s.scan(/\d+\.\d+(?:\.\d+)*\./) { |a| cited[a] += 1 } }
      coverage['articles'].each do |art|
        # Strip ' (slice label)' / '(N)' suffixes, but KEEP the trailing dot: the
        # scan above only ever yields keys ending in '.', so the dot is what stops
        # '8.4.4.1.' from prefix-matching '8.4.4.14.' and '8.4.4.17.' and claiming
        # their citations as its own. (report/checklist.rb#covered? guards the same
        # collision the same way — do not "simplify" the dot away again.)
        applied = cited.select { |a, _| a.start_with?(art['article'].to_s.sub(/\s*\(.*\z/, '')) }.values.sum
        inputs = { status: art['status'], decisions_citing: applied }
        inputs[:gap_owner] = art['gap_owner'] if art['gap_owner']
      # "Where is this dealt with" — path#method refs, linted by
      # test_coverage_code_refs.rb so they cannot rot. Carried into the audit so
      # the AHJ trail answers the question without a trip to the repo.
      inputs[:code] = art['code'] if art['code']
        if %w[implemented satisfied_by_clone host_scope].include?(art['status'])
          audit.info(:coverage, "#{art['title']} — #{art['status'].tr('_', ' ')}#{art['how'] ? ": #{art['how']}" : ''}",
                     inputs: inputs, article: art['article'])
        elsif art['gap_owner'] == 'modeller' # scope note, not a warning (D-09)
          audit.info(:coverage, "#{art['title']} — #{art['status'].tr('_', ' ')}, modeller scope" \
                                "#{art['how'] ? ". Applied: #{art['how']}" : ''}" \
                                "#{art['gaps'] ? ". Modeller's responsibility: #{art['gaps']}" : ''}",
                     inputs: inputs, article: art['article'])
        else # partial / not_implemented
          audit.warn(:coverage, "#{art['title']} — #{art['status'].tr('_', ' ')}" \
                                "#{art['how'] ? ". Applied: #{art['how']}" : ''}" \
                                "#{art['gaps'] ? ". Gaps: #{art['gaps']}" : ''}",
                     inputs: inputs, article: art['article'])
        end
      end
    end
  end
end
