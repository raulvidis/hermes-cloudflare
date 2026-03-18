#!/usr/bin/env bash
# One-liner install for hermes-cloudflare plugin into hermes-agent v0.3.0+
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/raulvidis/hermes-cloudflare/main/install.sh | bash
#
set -euo pipefail

PLUGIN_DIR="$HOME/.hermes/plugins/hermes-cloudflare"
REPO="https://github.com/raulvidis/hermes-cloudflare.git"
TMP_DIR="$(mktemp -d)"

echo "Installing hermes-cloudflare plugin..."

# Clone just the plugin directory (shallow, single-branch)
git clone --depth 1 --single-branch "$REPO" "$TMP_DIR" 2>/dev/null

# Copy plugin into place
mkdir -p "$HOME/.hermes/plugins"
rm -rf "$PLUGIN_DIR"
cp -r "$TMP_DIR/hermes-cloudflare-plugin" "$PLUGIN_DIR"

# Install Python dependency (httpx) if missing
if ! python3 -c "import httpx" 2>/dev/null; then
    echo "Installing httpx..."
    pip install httpx 2>/dev/null || pip3 install httpx 2>/dev/null || echo "Warning: could not install httpx — install it manually"
fi

# Cleanup
rm -rf "$TMP_DIR"

echo "hermes-cloudflare plugin installed to $PLUGIN_DIR"
echo "  Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in your environment."
echo "  Restart hermes-gateway, then run /plugins to verify."
