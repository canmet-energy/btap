#!/bin/bash
# Post-create setup for the NECB gem family devcontainer.
#
# Deliberately small. The gems are SDK-only and their tests run with plain
# `ruby test/test_XX.rb` against the image's OpenStudio — there is no root
# Gemfile to install, and each gem's own Gemfile exists for `bundle exec`, not
# for running the suites. So this script verifies the toolchain, handles the
# NRCan certificate case, and tells you what to run. It does NOT clone the
# multi-gigabyte legacy oracle; that is opt-in (see the end).

set -u

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  NECB gem family — devcontainer setup"
echo "═══════════════════════════════════════════════════════════════════"

# ---------------------------------------------------------------------------
# NRCan network certificates, FIRST — anything that downloads needs them.
# Same probe the openstudio-standards fork uses.
# ---------------------------------------------------------------------------
if [ "$(curl -k -o /dev/null -s -w "%{http_code}" "https://intranet.nrcan.gc.ca/" 2>/dev/null || echo 000)" -ge 200 ] &&
   [ "$(curl -k -o /dev/null -s -w "%{http_code}" "https://intranet.nrcan.gc.ca/" 2>/dev/null || echo 000)" -lt 400 ]; then
  echo "🔐 NRCAN network detected — installing certificates..."
  rm -rf /tmp/linux_nrcan_certs
  if git clone --quiet https://github.com/canmet-energy/linux_nrcan_certs.git /tmp/linux_nrcan_certs 2>/dev/null; then
    (cd /tmp/linux_nrcan_certs && git checkout --quiet ruby_3.2 && ./install_nrcan_certs.sh >/dev/null 2>&1)
    rm -rf /tmp/linux_nrcan_certs
    for var in SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS; do
      grep -q "export $var=" /home/vscode/.bashrc 2>/dev/null ||
        echo "export $var=/etc/ssl/certs/ca-certificates.crt" >> /home/vscode/.bashrc
    done
    sudo update-ca-certificates >/dev/null 2>&1
    echo "   ✅ certificates installed"
  else
    echo "   ⚠️  certificate repo unreachable — continuing without"
  fi
else
  echo "🌐 Not on the NRCAN network — skipping certificate install"
fi

# ---------------------------------------------------------------------------
# Toolchain. These are the versions the gems target; a mismatch is worth
# knowing about immediately rather than three test failures later.
# ---------------------------------------------------------------------------
echo ""
echo "🔧 Toolchain:"
printf '   ruby         %s\n' "$(ruby -e 'print RUBY_VERSION' 2>/dev/null || echo 'MISSING')"
printf '   bundler      %s\n' "$(bundle -v 2>/dev/null | awk '{print $3}' || echo 'MISSING')"

if ruby -e "require 'openstudio'" >/dev/null 2>&1; then
  printf '   openstudio   %s (SDK bindings OK)\n' "$(ruby -e "require 'openstudio'; print OpenStudio.openStudioVersion" 2>/dev/null)"
else
  echo "   ❌ openstudio SDK bindings NOT loadable — every gem suite will fail"
fi

if command -v openstudio >/dev/null 2>&1; then
  printf '   CLI          %s\n' "$(openstudio openstudio_version 2>/dev/null)"
  printf '   energyplus   %s\n' "$(openstudio energyplus_version 2>/dev/null)"
else
  echo "   ⚠️  openstudio CLI not on PATH — the EnergyPlus suites will skip"
fi

# LANG is load-bearing; see devcontainer.json.
case "${LANG:-}" in
  *UTF-8|*utf8) printf '   locale       %s\n' "$LANG" ;;
  *) echo "   ⚠️  LANG='${LANG:-unset}' is not UTF-8 — File.read of gem output will raise" ;;
esac

echo ""
echo "📋 Next steps:"
cat <<'STEPS'
   Run one gem's suite         cd openstudio-hvac && ruby test/test_catalog.rb
   Cross-gem rule verification rake necb:verify
   List the gems               rake gems
   What has the fork done?     rake legacy:whatsnew

   Legacy-parity gates need the PINNED oracle, which is a multi-gigabyte clone
   and therefore NOT installed automatically:

     BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install

   Have the openstudio-standards fork checked out already? Point at it instead
   and it is fast and offline — but use the SAME value every time, because the
   remote is part of the resolved lockfile:

     LEGACY_PIN_REMOTE=/path/to/openstudio-standards \
       BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install

   Then, always with LEGACY_PIN_REQUIRED=1 — a skipped parity gate is a
   green-but-vacuous gate:

     cd openstudio-loads && LEGACY_PIN_REQUIRED=1 \
       BUNDLE_GEMFILE=../legacy_pin/Gemfile bundle exec ruby test/test_apply_parity.rb
STEPS
echo ""
echo "═══════════════════════════════════════════════════════════════════"
