"""The CI image tag is content-addressed, and test.yml must use it.

The verify, parity and parity-scenarios jobs run in
``ghcr.io/canmet-energy/btap-ci:<openstudio version>-<sha256(Dockerfile)[:12]>``,
published by ``.github/workflows/ci-image.yml``. Editing
``infra/ci-image/Dockerfile`` without moving the tag in test.yml would leave CI
on the old image with nothing saying so; these checks make that a failure.
Stdlib only.
"""

import hashlib
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "infra" / "ci-image" / "Dockerfile"
TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-image.yml"
PYPROJECT = REPO_ROOT / "python" / "pyproject.toml"
GHCR = "ghcr.io/canmet-energy/btap-ci"
#: The same-region mirror the CodeBuild runners pull (infra/aws-ci/README.md).
ECR = "765017559068.dkr.ecr.ca-central-1.amazonaws.com/btap-ci"


def openstudio_version():
    match = re.search(r"^FROM nrel/openstudio:([0-9.]+)\s*$",
                      DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def expected_tag():
    return f"{openstudio_version()}-{hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:12]}"


class TestTheCiImagePin(unittest.TestCase):
    def test_every_job_image_is_the_content_tag_in_both_registries(self):
        workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
        for registry in (GHCR, ECR):
            tags = re.findall(re.escape(registry) + r":([\w.\-]+)", workflow)
            self.assertEqual(3, len(tags),
                             f"verify, parity and parity-scenarios each name {registry}")
            self.assertEqual({expected_tag()}, set(tags),
                             "infra/ci-image/Dockerfile changed: publish it (push the "
                             "change; ci-image.yml runs) and move every test.yml image "
                             f"tag to {expected_tag()}")

    def test_no_job_still_installs_on_the_bare_nrel_image(self):
        workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("container: nrel/openstudio", workflow)

    def test_the_publisher_computes_the_same_tag_for_both_registries(self):
        publisher = IMAGE_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(2, publisher.count('sha256sum "$DOCKERFILE" | cut -c1-12'),
                         "the GHCR publish and the ECR mirror compute the tag the same way")
        self.assertIn("ghcr.io/canmet-energy/btap-ci:${TAG}", publisher)
        self.assertIn('"$REGISTRY/btap-ci:${TAG}"', publisher)
        self.assertIn("REGISTRY=" + ECR.rsplit("/", 1)[0], publisher)

    def test_the_image_carries_the_package_pins(self):
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        pin = re.search(r'^tbd = \["(canmet-tbd==[^"]+)"\]',
                        PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(pin, "the [tbd] extra pin moved in pyproject.toml")
        self.assertIn(f'--no-deps "{pin.group(1)}"', dockerfile)
        self.assertEqual("3.11.0", openstudio_version(),
                         "the image's OpenStudio must be the SDK the project targets")


if __name__ == "__main__":
    unittest.main()
