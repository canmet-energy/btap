#!/usr/bin/env bash
# One-shot AWS-side setup for CodeBuild-hosted GitHub Actions runners.
#
# Run this AUTHENTICATED (aws login / SSO) in the account that holds the HBIX
# stack, region ca-central-1. It is idempotent — safe to re-run.
#
# Why this exists: GitHub bills Actions minutes only for GITHUB-hosted runners.
# Jobs on CodeBuild-hosted runners consume zero GitHub minutes while keeping
# the Actions UI, checks and PR gating. The org allowance stops being spent;
# the pennies land on the AWS account instead.
set -euo pipefail

REGION="${AWS_REGION:-ca-central-1}"
PROJECT="necb-ci"
REPO_URL="https://github.com/canmet-energy/btap-gems"
ECR_REPO="nrel-openstudio"
IMAGE_TAG="3.11.0"

echo "== 1/4  ECR mirror of nrel/openstudio:${IMAGE_TAG} (same-region pulls in seconds) =="
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1 ||
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" >/dev/null
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
if ! aws ecr describe-images --repository-name "$ECR_REPO" --image-ids imageTag="$IMAGE_TAG" --region "$REGION" >/dev/null 2>&1; then
  echo "   mirroring docker.io/nrel/openstudio:${IMAGE_TAG} -> ${ECR_URI}:${IMAGE_TAG}"
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
    docker pull "nrel/openstudio:${IMAGE_TAG}"
    docker tag "nrel/openstudio:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
    docker push "${ECR_URI}:${IMAGE_TAG}"
  else
    # No docker daemon (e.g. inside the devcontainer): crane copies
    # registry-to-registry without one.
    command -v crane >/dev/null || {
      echo "   no docker and no crane — install crane (go-containerregistry releases) or run where docker exists" >&2
      exit 1
    }
    aws ecr get-login-password --region "$REGION" | crane auth login "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com" -u AWS --password-stdin
    crane copy "docker.io/nrel/openstudio:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
  fi
else
  echo "   already mirrored"
fi

echo "== 2/4  service role for the CodeBuild project =="
ROLE="codebuild-${PROJECT}-role"
aws iam get-role --role-name "$ROLE" >/dev/null 2>&1 || {
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "codebuild.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }' >/dev/null
  aws iam put-role-policy --role-name "$ROLE" --policy-name inline --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {"Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "*"},
      {"Effect": "Allow", "Action": ["ecr:GetAuthorizationToken","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:BatchCheckLayerAvailability"], "Resource": "*"}
    ]
  }'
  echo "   created $ROLE"
}

echo "== 3/4  GitHub connection =="
echo "   CodeBuild needs a one-time OAuth/App connection to GitHub. If none exists:"
echo "     Console -> CodeBuild -> Settings -> Connections -> Connect to GitHub"
echo "   (this is the only step the CLI cannot fully automate)"

echo "== 4/4  CodeBuild project wired as an Actions runner =="
aws codebuild batch-get-projects --names "$PROJECT" --region "$REGION" --query 'projects[0].name' --output text 2>/dev/null | grep -q "$PROJECT" || {
  aws codebuild create-project --region "$REGION" \
    --name "$PROJECT" \
    --source "type=GITHUB,location=${REPO_URL}" \
    --artifacts "type=NO_ARTIFACTS" \
    --environment "type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_LARGE,privilegedMode=true" \
    --service-role "arn:aws:iam::${ACCOUNT}:role/${ROLE}" >/dev/null
  aws codebuild create-webhook --region "$REGION" --project-name "$PROJECT" \
    --filter-groups '[[{"type":"EVENT","pattern":"WORKFLOW_JOB_QUEUED"}]]' >/dev/null
  echo "   created project + WORKFLOW_JOB_QUEUED webhook"
}

cat <<DONE

Done. Last step, on the GitHub side (repo Settings -> Secrets and variables ->
Actions -> Variables):

  CI_RUNNER = ${PROJECT}

The PROJECT NAME only — the workflow composes the per-run label
codebuild-${PROJECT}-<runId>-<runAttempt> itself with format(). Do NOT store
the label with \${{ ... }} inside the variable: GitHub never re-expands
expressions stored in a variable, so CodeBuild receives the literal text and
rejects every queued job with HTTP 400 ("a project label matching pattern
codebuild-<projectName>-<runId>-<runAttempt> is required"). Paid for once.

The workflow already reads that variable; unset, it falls back to
ubuntu-latest. Setting it moves the container matrix + verify onto CodeBuild —
zero GitHub-hosted minutes — and deleting the variable reverts instantly.

Phase 2 (optional, faster): point the matrix's container: at
  ${ECR_URI}:${IMAGE_TAG}
instead of docker.io, so image pulls are same-region.
DONE
