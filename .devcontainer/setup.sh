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
