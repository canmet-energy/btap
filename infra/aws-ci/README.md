# CI on AWS (CodeBuild-hosted Actions runners)

GitHub bills Actions minutes **only for GitHub-hosted runners**. Jobs on
CodeBuild-hosted runners consume zero GitHub minutes while keeping the Actions
UI, checks and PR gating — the workflow does not move, only its compute does.

## Turn it on

```bash
aws login                       # the account that holds the HBIX stack
bash infra/aws-ci/setup.sh      # idempotent; ca-central-1
```

Then set one repository variable (Settings → Secrets and variables → Actions):

    CI_RUNNER = necb-ci

The PROJECT NAME only. The workflow composes the per-run label
`codebuild-necb-ci-<runId>-<runAttempt>` itself with `format()` — expressions
stored inside a variable are never re-expanded by GitHub, so a variable
holding `${{ github.run_id }}` delivers that literal text and CodeBuild 400s
every queued job.

The workflow reads `vars.CI_RUNNER` for the container matrix, `verify` and
`parity`; unset it and everything reverts to `ubuntu-latest`. No workflow edit
in either direction.

## Changing the project's source DETACHES the webhook

`aws codebuild update-project --source …` silently drops the project's
webhook — every subsequent CI job then queues forever, because nothing
delivers `WORKFLOW_JOB_QUEUED` any more (paid for once, at the
openstudio-necb-gems → btap-gems rename). After ANY source change, always:

```bash
aws codebuild create-webhook --project-name necb-ci \
  --filter-groups '[[{"type":"EVENT","pattern":"WORKFLOW_JOB_QUEUED"}]]'
```

and verify the hook is back on the repo (`gh api repos/<owner>/<repo>/hooks`).
A GitHub-side repo RENAME alone is harmless — the hook lives on the repo and
survives; it is the CodeBuild-side source update that kills it.

## What runs where afterwards

| job | runner | GitHub minutes |
|---|---|---|
| lint (every PR push) | GitHub bare runner | ~20 s |
| test matrix + verify (main / dispatch) | CodeBuild | **0** |
| parity (dispatch) | CodeBuild | **0** |

AWS cost is per-minute with zero idle — order of $0.25–0.50 per full run on
`BUILD_GENERAL1_LARGE` (verify against current ca-central-1 pricing). The
8-vCPU instance actually exploits `rake test:gem`'s file-parallelism, which
GitHub's 2-core runners never could.

## Phase 2 — faster image pulls

`setup.sh` mirrors `nrel/openstudio:3.11.0` into ECR (same region). Point the
workflow's `container:` at the ECR URI it prints to cut the multi-GB Docker Hub
pull to a same-region fetch, and to stop depending on Docker Hub rate limits.

## Also worth doing on this account

An on-demand **Windows EC2 instance** is the missing piece for validating the
Windows installer on real Windows — the thing Wine cannot do (the embedded Ruby
dies on `unexpected ucrtbase.dll`). One `t3.large` Windows box, started for the
checklist in `packaging/windows/README.md`, stopped after.
