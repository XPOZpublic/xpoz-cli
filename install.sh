#!/bin/sh
# xpoz-cli installer for Linux and macOS.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/XPOZpublic/xpoz-cli/main/install.sh | sh
#
# Environment overrides:
#   XPOZ_VERSION       — release tag (default: "latest"), e.g. "v0.2.0"
#   XPOZ_INSTALL_DIR   — install directory (default: "$HOME/.local/bin")
#   XPOZ_REPO          — GitHub repo (default: "XPOZpublic/xpoz-cli")
#
# The script:
#   1. Detects your OS and CPU architecture.
#   2. Downloads the matching binary from GitHub Releases.
#   3. Verifies it against the published SHA256SUMS file.
#   4. Installs it to XPOZ_INSTALL_DIR/xpoz-cli and makes it executable.

set -eu

XPOZ_REPO="${XPOZ_REPO:-XPOZpublic/xpoz-cli}"
XPOZ_VERSION="${XPOZ_VERSION:-latest}"
XPOZ_INSTALL_DIR="${XPOZ_INSTALL_DIR:-$HOME/.local/bin}"

err() { printf 'error: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

# Detect OS
os="$(uname -s)"
case "$os" in
  Linux)  os_tag=linux ;;
  Darwin) os_tag=macos ;;
  *)      err "unsupported OS '$os'. Use Homebrew, pip, or a manual download." ;;
esac

# Detect arch
arch="$(uname -m)"
case "$arch" in
  x86_64|amd64)  arch_tag=amd64 ;;
  aarch64|arm64) arch_tag=arm64 ;;
  *)             err "unsupported architecture '$arch'." ;;
esac

# macOS Intel isn't shipped as a prebuilt
if [ "$os_tag" = macos ] && [ "$arch_tag" = amd64 ]; then
  err "no prebuilt binary for macOS Intel. Install via 'pip install xpoz-cli' instead."
fi

asset="xpoz-cli-${os_tag}-${arch_tag}"

if [ "$XPOZ_VERSION" = latest ]; then
  url_base="https://github.com/${XPOZ_REPO}/releases/latest/download"
else
  url_base="https://github.com/${XPOZ_REPO}/releases/download/${XPOZ_VERSION}"
fi

# Pick a downloader
if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fsSL "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -qO "$2" "$1"; }
else
  err "need curl or wget"
fi

# Pick a SHA256 tool
if command -v sha256sum >/dev/null 2>&1; then
  hash_of() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  hash_of() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  hash_of() { echo SKIP; }
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT HUP TERM

info "Downloading $asset (version: $XPOZ_VERSION)..."
fetch "${url_base}/${asset}" "${tmp}/${asset}" || err "failed to download ${url_base}/${asset}"

info "Verifying integrity..."
if fetch "${url_base}/SHA256SUMS" "${tmp}/SHA256SUMS" 2>/dev/null; then
  expected="$(grep "  ${asset}$" "${tmp}/SHA256SUMS" | awk '{print $1}')"
  actual="$(hash_of "${tmp}/${asset}")"
  if [ "$actual" = SKIP ]; then
    warn "no sha256sum/shasum tool found; skipped integrity check"
  elif [ -z "$expected" ]; then
    warn "no entry for ${asset} in SHA256SUMS; skipped integrity check"
  elif [ "$expected" != "$actual" ]; then
    err "SHA256 mismatch for $asset (expected $expected, got $actual)"
  else
    info "  $actual  (verified)"
  fi
else
  warn "could not fetch SHA256SUMS; skipped integrity check"
fi

mkdir -p "$XPOZ_INSTALL_DIR" || err "could not create $XPOZ_INSTALL_DIR"
target="${XPOZ_INSTALL_DIR}/xpoz-cli"
mv "${tmp}/${asset}" "$target"
chmod +x "$target"

info ""
info "Installed: $target"

case ":${PATH}:" in
  *":${XPOZ_INSTALL_DIR}:"*) ;;
  *)
    info ""
    warn "$XPOZ_INSTALL_DIR is not on your PATH. Add it to your shell profile:"
    info "  export PATH=\"${XPOZ_INSTALL_DIR}:\$PATH\""
    ;;
esac

info ""
info "Next steps:"
info "  xpoz-cli auth login    # store your API key"
info "  xpoz-cli --help        # see commands"
