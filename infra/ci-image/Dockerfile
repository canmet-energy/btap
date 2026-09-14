# The image the verify, parity and parity-scenarios jobs run in
# (.github/workflows/test.yml): nrel/openstudio:3.11.0 plus everything those
# jobs used to install on every run — about four minutes of apt and pip per
# job. Published by .github/workflows/ci-image.yml as
#   ghcr.io/canmet-energy/btap-ci:<openstudio version>-<sha256 of this file, 12>
# so editing this file means moving the tag in test.yml
# (python/tests/test_ci_image_pin.py fails until you do).
FROM nrel/openstudio:3.11.0

# python3-venv for the virtual environments below; librsvg2-bin because the
# floor-plan raster test needs an SVG rasterizer on PATH (M8) and
# BTAP_RASTERIZER_REQUIRED keeps it from going vacuous.
RUN apt-get update -qq \
 && apt-get install -y -qq python3-venv librsvg2-bin > /dev/null \
 && rm -rf /var/lib/apt/lists/*

# verify: the test runner, pytest-cov (verify measures line coverage of btap),
# and the pure-Python thermal-bridging stack. The SDK
# still comes from the image via PYTHONPATH. canmet-tbd goes in with --no-deps
# because its openstudio requirement would pull the PyPI wheel into the venv
# and SHADOW the image SDK (venv site-packages beat PYTHONPATH). Every other
# dependency is pure Python; the py-topolys pin mirrors the one inside
# canmet-tbd's own pyproject.
RUN python3 -m venv /opt/btap-ci/venv \
 && /opt/btap-ci/venv/bin/pip install -q --no-cache-dir pytest pytest-xdist pytest-cov \
      "oslg==0.4.0" "osut==0.9.1" "jsonschema>=4" "py-topolys==0.1.0" \
 && /opt/btap-ci/venv/bin/pip install -q --no-cache-dir --no-deps "canmet-tbd==3.5.2"

# parity: plain pytest only, as the SmallOffice gate and Live Leg C have always
# run — thermal bridging stays unimportable there, so those gates cannot change
# behaviour merely because the image gained a package.
RUN python3 -m venv /opt/btap-ci/pytest \
 && /opt/btap-ci/pytest/bin/pip install -q --no-cache-dir pytest
