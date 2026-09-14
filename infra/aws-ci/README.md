# CI on AWS (CodeBuild-hosted Actions runners)

The `python`, `verify`, `parity` and `parity-scenarios` jobs in
`.github/workflows/test.yml` run on a CodeBuild-hosted Actions runner when the
repository variable `CI_RUNNER` names the CodeBuild project, and on
`ubuntu-latest` when it is unset. The workflow does not move, only its compute
does: the Actions UI, checks and PR gating stay on GitHub.

**Why it is on (2026-09-14): speed.** The repository is public, so
GitHub-hosted minutes are free, but a standard public runner has 4 vCPUs. The
project runs on `BUILD_GENERAL1_XLARGE` (36 vCPUs, 72 GiB), and the
pytest-xdist suites in `python` and `verify` spread across all of it. GitHub
bills nothing for jobs on CodeBuild-hosted runners; the build minutes land on
the AWS account (`btap-dev`, ca-central-1) instead.

## Turn it on

```bash
aws sso login --sso-session <session>   # the account that holds the HBIX stack
bash infra/aws-ci/setup.sh               # idempotent; ca-central-1
gh variable set CI_RUNNER --body necb-ci
```

The variable holds the PROJECT NAME only. The workflow composes the per-run
label `codebuild-necb-ci-<runId>-<runAttempt>` itself with `format()` —
expressions stored inside a variable are never re-expanded by GitHub, so a
variable holding `${{ github.run_id }}` delivers that literal text and
CodeBuild 400s every queued job.

**Turn it off:** `gh variable delete CI_RUNNER`. Every job reverts to
`ubuntu-latest` with no workflow edit; the container jobs still run in the CI
image below.

## Changing the project's source can DETACH the webhook

`aws codebuild update-project --source …` with a new source LOCATION silently
dropped the project's webhook (2026-09-14: after repointing btap-gems → btap,
the project showed `webhook: null`) — every subsequent CI job then queues
forever, because nothing delivers `WORKFLOW_JOB_QUEUED` any more. The same
call with the location unchanged and only the inline buildspec added kept the
webhook (`create-webhook` then answered "Webhook already exists"). After ANY
source change, check `aws codebuild batch-get-projects --names necb-ci
--query 'projects[0].webhook.url'` and, if it is null, run:

```bash
aws codebuild create-webhook --project-name necb-ci \
  --filter-groups '[[{"type":"EVENT","pattern":"WORKFLOW_JOB_QUEUED"}]]'
```

and verify the hook is on the repo (`gh api repos/<owner>/<repo>/hooks`).

A GitHub-side repo RENAME is NOT harmless. The GitHub hook survives, but
CodeBuild matches the incoming event against the project's SOURCE URL, which
still names the old repo, so every job queues forever with no error anywhere.
Symptom: `gh run list` shows runs stuck at `queued` while `lint` (a bare GitHub
runner) passes. After a rename, update the project source AND re-create the
webhook, in that order. Paid for at the openstudio-necb-gems → btap-gems and
btap-gems → btap (2026-08-30) renames; the second was only repaired on
2026-09-14, when the source was repointed to `canmet-energy/btap` and the
webhook was re-created. (Changing only the compute type does not detach the
webhook.)

## What runs where

| job | when | runner with `CI_RUNNER=necb-ci` | environment |
|---|---|---|---|
| lint | every push and PR | GitHub-hosted | bare |
| python | every push and PR | CodeBuild XLARGE | bare (installs the wheel) |
| verify | main/develop push, dispatch | CodeBuild XLARGE | CI image |
| parity | dispatch | CodeBuild XLARGE | CI image |
| parity-scenarios | dispatch | CodeBuild XLARGE | CI image |

AWS cost is per build-minute with zero idle; each job is one build, billed
from submission (queue time included). Check current ca-central-1 pricing.
A reserved-capacity fleet would remove the queue wait but is billed while
idle, so it is deliberately not used.

## Why XLARGE, not 2XLARGE

Measured on 2026-09-14 with the same commit, dispatching the whole workflow:

| size | provisioning per build | CodeBuild queue per build | wall clock | verify suite |
|---|---|---|---|---|
| `BUILD_GENERAL1_2XLARGE` (72 vCPU) | 175–176 s | 90–149 s | 12 min 11 s | 320 s |
| `BUILD_GENERAL1_XLARGE` (36 vCPU) | 8–9 s | 0–150 s | 10 min 24 s | 345 s |

The 2XLARGE image is not in CodeBuild's cache (its compute-type table marks
cached images for SMALL through XLARGE only), so every build pulls it before
the runner starts. The extra 36 cores save 25 s of verify's suite, which is
bounded by a few long serial tests, not by core count. What remains is
CodeBuild's own queue, which varies from run to run.

## The CI image

`infra/ci-image/Dockerfile` is `nrel/openstudio:3.11.0` plus what the container
jobs used to install on every run (apt `python3-venv librsvg2-bin`, a verify
venv with pytest, pytest-xdist and the thermal-bridging stack, and a plain
pytest venv for parity). `.github/workflows/ci-image.yml` publishes it to
`ghcr.io/canmet-energy/btap-ci:<openstudio>-<sha256(Dockerfile)[:12]>` on a
GitHub-hosted runner whenever the Dockerfile changes on any branch, and never
overwrites a tag. `test.yml` pins that exact tag, and
`python/tests/test_ci_image_pin.py` fails when the two disagree — so edit the
Dockerfile, push, wait for `ci-image`, then move the tag in `test.yml`.

**Where each runner pulls it from.** Pulling ~1 GB from GHCR cost ~50 s per
container job on CodeBuild, so the image is mirrored into ECR in the runners'
own region:

- `ci-image.yml`'s `mirror-to-ecr` job runs on a CodeBuild runner, after the
  GHCR publish, and copies the exact GHCR image to
  `765017559068.dkr.ecr.ca-central-1.amazonaws.com/btap-ci:<same tag>`.
  The repository has immutable tags. The service role holds the
  `ecr-push-btap-ci` inline policy, scoped to that repository.
- With `CI_RUNNER` set, the container jobs name the ECR image. The project's
  inline buildspec logs Docker in to ECR in `PRE_BUILD`, which runs only
  because every CodeBuild job's `runs-on` carries `buildspec-override:true`.
  The Actions runner does no registry login when a job supplies no
  credentials, so its pull uses that login.
- Without `CI_RUNNER`, they name the GHCR image. On GitHub-hosted runners the
  Actions runner logs in to `ghcr.io` with the job's `GITHUB_TOKEN`
  (`packages: read`); the package is private.

Every CodeBuild job in a workflow run uses the same two labels, so GitHub
cannot hand a job to a runner created for another (CodeBuild's
unique-label caveat applies only when label counts differ). The older ECR
mirror `setup.sh` creates (`nrel-openstudio:3.11.0`) predates the CI image
and is not used by the workflow.
