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

# Derived from THIS script's location, not the cwd: postCreateCommand happens to
# run from the workspace root, but a hand-run `bash .devcontainer/setup.sh` from
# anywhere must still find legacy_pin/ — and a wrong path here degrades to
# "triplet not found, skip tbd", which is exactly the silent gap this block
# exists to close.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Claude Code installs BY DEFAULT here. (The fork's setup.sh gates it behind
# --claude but its postCreateCommand passes no flag, so it never actually
# installed — the flag was effectively dead.) --no-claude opts out.
INSTALL_CLAUDE=true
INSTALL_SERENA=false

while [ $# -gt 0 ]; do
  case "$1" in
    --no-claude) INSTALL_CLAUDE=false ;;
    --serena)    INSTALL_SERENA=true ;;
    -h|--help)
      cat <<'USAGE'
Usage: setup.sh [--no-claude] [--serena]
  --no-claude  skip the Claude Code install (it is installed by default)
  --serena     also install uv + the Serena MCP server for code navigation
USAGE
      exit 0 ;;
    *) echo "unknown option: $1 (try --help)"; exit 1 ;;
  esac
  shift
done

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  NECB gem family — devcontainer setup"
echo "═══════════════════════════════════════════════════════════════════"

# ---------------------------------------------------------------------------
# Corporate certificates, FIRST — anything that downloads needs them.
#
# The certs come from the HOST's trust store, staged into .devcontainer/certs/
# by devcontainer.json's initializeCommand. That ordering is the whole point:
# the previous routine cloned linux_nrcan_certs FROM GitHub in order to fix
# GitHub, so on an intercepted network it could never succeed — it printed
# "certificate repo unreachable — continuing without" and left the container
# unable to reach anything. Provenance also matters: the host store is what
# corporate IT installed, so nothing here trusts a CA scraped off the wire.
#
# certctl-safe.sh is shared verbatim with canmet-energy/h2k-hpxml; keep the two
# copies identical rather than patching this one locally.
# ---------------------------------------------------------------------------
CERTCTL_SRC="$REPO_ROOT/.devcontainer/scripts/certctl-safe.sh"
STAGED_CERTS="$REPO_ROOT/.devcontainer/certs"

if [ -x "$CERTCTL_SRC" ]; then
  sudo "$CERTCTL_SRC" install >/dev/null 2>&1 || echo "   ⚠️  certctl install failed"
fi

staged_count=$(find "$STAGED_CERTS" -maxdepth 1 -name '*.crt' 2>/dev/null | wc -l)
if [ "$staged_count" -gt 0 ]; then
  echo "🔐 $staged_count certificate(s) staged from the host — installing..."
  sudo rm -rf /tmp/certs && sudo mkdir -p /tmp/certs
  sudo cp "$STAGED_CERTS"/*.crt /tmp/certs/
  sudo /usr/local/bin/certctl certs-refresh 2>&1 | sed 's/^/   /'
  sudo rm -rf /tmp/certs
elif [ "$(curl -k -o /dev/null -s -w "%{http_code}" "https://intranet.nrcan.gc.ca/" 2>/dev/null || echo 000)" -ge 200 ] &&
     [ "$(curl -k -o /dev/null -s -w "%{http_code}" "https://intranet.nrcan.gc.ca/" 2>/dev/null || echo 000)" -lt 400 ]; then
  # Fallback only. Works on an unintercepted NRCan network; on an intercepted
  # one the clone is exactly what fails, hence the pointed message below.
  echo "🔐 NRCAN network detected, no staged certs — trying linux_nrcan_certs..."
  rm -rf /tmp/linux_nrcan_certs
  if git clone --quiet https://github.com/canmet-energy/linux_nrcan_certs.git /tmp/linux_nrcan_certs 2>/dev/null; then
    (cd /tmp/linux_nrcan_certs && git checkout --quiet ruby_3.2 && ./install_nrcan_certs.sh >/dev/null 2>&1)
    rm -rf /tmp/linux_nrcan_certs
    sudo update-ca-certificates >/dev/null 2>&1
    echo "   ✅ certificates installed"
  else
    echo "   ⚠️  clone failed — the proxy is intercepting TLS, which is the case"
    echo "      this fallback cannot fix. On the WSL host run:"
    echo "        cp /usr/local/share/ca-certificates/*.crt $STAGED_CERTS/"
    echo "      then re-run this script (no rebuild needed)."
  fi
else
  echo "🌐 No staged certs and not on the NRCAN network — skipping cert install"
fi

for var in SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS CURL_CA_BUNDLE; do
  grep -q "export $var=" /home/vscode/.bashrc 2>/dev/null ||
    echo "export $var=/etc/ssl/certs/ca-certificates.crt" >> /home/vscode/.bashrc
done

# Loud either way: a container that silently cannot verify TLS is the failure
# mode this whole block exists to make visible.
if command -v certctl >/dev/null 2>&1; then
  CERTCTL_TOTAL_TIMEOUT=15 certctl banner 2>/dev/null | sed 's/^/   /' || true
fi

# ---------------------------------------------------------------------------
# The tbd/osut/topolys TRIPLET — openstudio-envelope's third-party runtime deps.
#
# It is declared in openstudio-envelope.gemspec, but the suites run under plain
# `ruby`, not `bundle exec`, so nothing enforces gemspec dependencies. The gem
# was therefore absent from this container and from CI, and
# test_uprate_derate_meets_effective_targets — the only test proving the NECB
# 3.1.1.7 uprate/derate math hits the effective-U targets — skipped in both
# while the suite summary stayed green. Install it here so the gate is real;
# CI sets TBD_REQUIRED=1 so a missing tbd fails instead of skipping.
#
# AFTER the certificates, because it downloads. Non-fatal: without tbd the gems
# still work, they just warn that 3.1.1.7 is unaccounted and that one test skips.
# ---------------------------------------------------------------------------
echo ""
TRIPLET="$(ruby "$REPO_ROOT/legacy_pin/tbd_triplet.rb" 2>/dev/null)"
if [ -z "$TRIPLET" ]; then
  echo "🌉 ⚠️  could not read the triplet from legacy_pin/Gemfile.lock — skipping tbd"
elif ruby -e "require 'tbd'" >/dev/null 2>&1 &&
     [ "$(ruby -e "require 'tbd'; puts %w[topolys osut tbd].map { |g| \"#{g}:#{Gem.loaded_specs[g]&.version}\" }.join(' ')" 2>/dev/null)" = "$TRIPLET" ]; then
  echo "🌉 tbd triplet already matches the pinned oracle ($TRIPLET)"
else
  echo "🌉 Installing the tbd triplet pinned by legacy_pin ($TRIPLET)..."
  # --user-install FIRST: it needs no privileges (the system gem dir is
  # root-owned, which is the only reason sudo ever entered this) and keeps the
  # gems in $HOME where the vscode user owns them. sudo is the fallback for
  # images that run as root or lack a writable user gem home.
  #
  # EXACT versions, in dependency order — see legacy_pin/tbd_triplet.rb. Plain
  # `ruby` activates the newest installed gem, so a stray newer osut silently
  # wins over the pin and the parity comparison stops being apples-to-apples.
  # shellcheck disable=SC2086
  if gem install $TRIPLET --user-install --no-document >/dev/null 2>&1 ||
     gem install $TRIPLET --no-document >/dev/null 2>&1 ||
     sudo gem install $TRIPLET --no-document >/dev/null 2>&1; then
    echo "   ✅ $(ruby -e "require 'tbd'; puts %w[topolys osut tbd].map { |g| \"#{g} #{Gem.loaded_specs[g]&.version}\" }.join(', ')" 2>/dev/null)"
  else
    echo "   ⚠️  install failed (offline or blocked) — install manually later:"
    echo "      gem install $TRIPLET --user-install"
    echo "      without it, openstudio-envelope warns that NECB 3.1.1.7 is unaccounted"
    echo "      and test_thermal_bridging.rb skips its uprate/derate case"
  fi
  if ruby -e "require 'tbd'" >/dev/null 2>&1 &&
     [ "$(ruby -e "require 'tbd'; puts %w[topolys osut tbd].map { |g| \"#{g}:#{Gem.loaded_specs[g]&.version}\" }.join(' ')" 2>/dev/null)" != "$TRIPLET" ]; then
    echo "   ⚠️  a NEWER tbd/osut/topolys is installed and wins over the pin."
    echo "      Parity comparisons will measure a library upgrade, not our code."
    echo "      Remove the newer ones:  gem uninstall tbd osut topolys -v <newer>"
  fi
fi

# ---------------------------------------------------------------------------
# GitHub CLI. AFTER the certificates, because it downloads AND because gh has
# no --insecure escape hatch: unlike git (http.sslVerify) it trusts only the
# system store, so on an intercepted network without the corporate CAs
# `gh auth login` dies mid-flow with "x509: certificate signed by unknown
# authority". Certs first is not a preference here, it is the prerequisite.
#
# Ubuntu 24.04 universe carries gh, so no third-party apt repo is needed.
# Non-fatal: gh is for dispatching the parity workflow and reading PR checks,
# not for building or testing the gems.
# ---------------------------------------------------------------------------
echo ""
if command -v gh >/dev/null 2>&1; then
  echo "🐙 GitHub CLI already present ($(gh --version 2>/dev/null | head -1))"
else
  echo "🐙 Installing GitHub CLI..."
  if sudo apt-get update -qq >/dev/null 2>&1 && sudo apt-get install -y -qq gh >/dev/null 2>&1; then
    echo "   ✅ $(gh --version 2>/dev/null | head -1)"
    echo "      authenticate with:  gh auth login"
  else
    echo "   ⚠️  install failed (offline or blocked) — install manually later:"
    echo "      sudo apt-get install -y gh"
  fi
fi

# ---------------------------------------------------------------------------
# Claude Code. AFTER the certificates, because it downloads.
#
# The native installer bundles its own runtime — Node is NOT required (verified:
# the fork's container runs claude 2.1.x with no node on PATH). Only Serena
# needs extra tooling, which is why it is a separate flag.
# ---------------------------------------------------------------------------
if [ "$INSTALL_CLAUDE" = true ]; then
  echo ""
  if command -v claude >/dev/null 2>&1; then
    echo "🤖 Claude Code already present ($(claude --version 2>/dev/null | head -1))"
  else
    echo "🤖 Installing Claude Code..."
    if curl -fsSL https://claude.ai/install.sh | bash >/dev/null 2>&1; then
      echo "   ✅ $( "$HOME/.local/bin/claude" --version 2>/dev/null | head -1 || echo 'installed')"
    else
      # Non-fatal: a container without Claude Code is still a working dev
      # environment for these gems.
      echo "   ⚠️  install failed (offline or blocked) — install manually later:"
      echo "      curl -fsSL https://claude.ai/install.sh | bash"
    fi
  fi
  # The installer drops the binary in ~/.local/bin, which is not always on PATH.
  case ":${PATH}:" in
    *":$HOME/.local/bin:"*) ;;
    *) grep -q '\.local/bin' "$HOME/.bashrc" 2>/dev/null ||
         echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc" ;;
  esac
else
  echo ""
  echo "⏭️  Skipping Claude Code (--no-claude)"
fi

# ---------------------------------------------------------------------------
# MCP servers. .mcp.json stays GITIGNORED (family rule: never stage it), so the
# tracked artifact is .mcp.json.example and we install it here. Claude Code
# expands ${VAR} in url/headers, so even the installed file holds no secret —
# the key comes from NRCAN_MCP_API_KEY in the environment.
# ---------------------------------------------------------------------------
if [ -f .mcp.json ]; then
  echo "🔌 .mcp.json already present — left untouched"
elif [ -f .mcp.json.example ]; then
  cp .mcp.json.example .mcp.json
  echo "🔌 .mcp.json installed from template ($(grep -c '"type": "http"' .mcp.json) NRCan MCP servers)"
  if [ -z "${NRCAN_MCP_API_KEY:-}" ]; then
    echo "   ⚠️  NRCAN_MCP_API_KEY is not set — the servers will fail to authenticate."
    echo "      export NRCAN_MCP_API_KEY=...   (add it to ~/.bashrc to persist)"
  else
    echo "   ✅ NRCAN_MCP_API_KEY is set"
  fi
fi

if [ "$INSTALL_SERENA" = true ]; then
  echo "🧭 Installing uv + Serena MCP (code navigation)..."
  if command -v uv >/dev/null 2>&1 || pip3 install --quiet uv 2>/dev/null || pip install --quiet uv 2>/dev/null; then
    mkdir -p .vscode
    cat > .vscode/mcp.json <<'EOF'
{
  "servers": {
    "serena": {
      "type": "stdio",
      "command": "uv",
      "args": ["tool", "run", "--python", "3.12", "--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server", "--context", "ide-assistant", "--project", "."]
    }
  }
}
EOF
    command -v claude >/dev/null 2>&1 &&
      claude mcp add serena -- uv tool run --python 3.12 --from git+https://github.com/oraios/serena \
        serena start-mcp-server --context ide-assistant --project "$(pwd)" >/dev/null 2>&1
    echo "   ✅ Serena configured for VS Code and Claude"
  else
    echo "   ⚠️  could not install uv — skipping Serena"
  fi
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

if command -v claude >/dev/null 2>&1; then
  printf '   claude       %s\n' "$(claude --version 2>/dev/null | head -1)"
elif [ -x "$HOME/.local/bin/claude" ]; then
  printf '   claude       %s (open a new shell for PATH)\n' "$("$HOME/.local/bin/claude" --version 2>/dev/null | head -1)"
fi

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

   MCP servers: .mcp.json was installed from .mcp.json.example above (codes,
   geocoding, weather, building-stock, modelling, simulation). It holds NO key —
   Claude Code expands ${NRCAN_MCP_API_KEY} from your environment, and .mcp.json
   itself stays gitignored. Set it once:

     export NRCAN_MCP_API_KEY=...          # add to ~/.bashrc to persist

   Two Ruby scripts read their OWN variables rather than that file, so give them
   the same value if you use them:

     CODES_API_KEY / CODES_MCP_URL                    openstudio-necb/scripts/fetch_necb_8_4_text.rb
     BUILDING_STOCK_API_KEY / BUILDING_STOCK_MCP_URL  openstudio-geometry/scripts/building_stock.rb
STEPS
echo ""
echo "═══════════════════════════════════════════════════════════════════"
