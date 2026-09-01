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

The workflow reads `vars.CI_RUNNER` for `python`, `verify`, and `parity`;
`lint` stays on a bare GitHub-hosted runner. Unset the variable and the other
three jobs revert to `ubuntu-latest`. No workflow edit is needed in either
direction.

## Changing the project's source DETACHES the webhook

`aws codebuild update-project --source …` silently drops the project's
webhook — every subsequent CI job then queues forever, because nothing
delivers `WORKFLOW_JOB_QUEUED` any more (paid for once, at the
openstudio-necb-gems → btap-gems rename; btap-gems → btap (2026-08-30) left CodeBuild's source on the redirecting old URL — fix source + re-create the webhook together). After ANY source change, always:

```bash
aws codebuild create-webhook --project-name necb-ci \
  --filter-groups '[[{"type":"EVENT","pattern":"WORKFLOW_JOB_QUEUED"}]]'
```

and verify the hook is back on the repo (`gh api repos/<owner>/<repo>/hooks`).
A GitHub-side repo RENAME is NOT harmless, and the note that used to sit
here saying so was wrong (paid for at the btap-gems → btap rename,
2026-08-30). The GitHub hook does survive — `gh api repos/<owner>/<repo>/hooks`
still lists it — but CodeBuild matches the incoming event against the
project's SOURCE URL, which still names the old repo, so every job queues
forever with no error anywhere. Symptom: `gh run list` shows runs stuck at
`queued` while `lint` (a bare GitHub runner) passes. After a rename, update
the project source AND re-create the webhook, in that order.

On a PUBLIC repo none of this is needed: GitHub-hosted minutes are free, so
deleting the `CI_RUNNER` variable reverts every job to `ubuntu-latest`
(`gh variable delete CI_RUNNER`) — which is what this repo does since it
went public.

## What runs where afterwards

| job | runner | GitHub minutes |
|---|---|---|
| lint (every PR push) | GitHub bare runner | ~20 s |
| python + verify (main / dispatch) | CodeBuild | **0** |
| parity (dispatch) | CodeBuild | **0** |

AWS cost is per-minute with zero idle — order of $0.25–0.50 per full run on
`BUILD_GENERAL1_LARGE` (verify against current ca-central-1 pricing). The
8-vCPU instance is useful to pytest-xdist in the Python and verify jobs.

## Phase 2 — faster image pulls

`setup.sh` mirrors `nrel/openstudio:3.11.0` into ECR (same region). Point the
workflow's `container:` at the ECR URI it prints to cut the multi-GB Docker Hub
pull to a same-region fetch, and to stop depending on Docker Hub rate limits.
The mirror is optional; CI continues to work directly from Docker Hub without it.
