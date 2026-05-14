#!/usr/bin/env bash
# install.sh — one-liner Linux installer for Gyza.
#
# Usage:
#   curl -sSf https://gyza.network/install.sh | bash
#
# Or, from a local checkout:
#   ./scripts/install.sh
#
# Or, with explicit version:
#   GYZA_VERSION=v0.1.0a1 curl -sSf https://gyza.network/install.sh | bash
#
# What this script does:
#   1. Detects glibc + arch (linux x86_64 / aarch64 only for now)
#   2. Downloads the gyza-netd binary from GitHub Releases into
#      ~/.local/bin/ (or /usr/local/bin/ if root)
#   3. Installs the `gyza` Python package via pipx (creates an isolated
#      venv; works without contaminating system Python)
#   4. Runs `gyza init` to generate the compositor key + config
#   5. Prints next steps
#
# Requirements on the host:
#   * Linux (x86_64 or aarch64); macOS and Windows are not supported in
#     alpha. If you need them, file an issue.
#   * Python 3.14+
#   * pipx (we'll suggest a one-liner if missing)
#   * curl + tar
#
# Idempotent: re-running upgrades the daemon binary and reinstalls the
# Python package without nuking ~/.gyza.

set -euo pipefail

# Customizable via env.
GYZA_VERSION="${GYZA_VERSION:-latest}"
GYZA_REPO="${GYZA_REPO:-aaronamire/gyza}"
INSTALL_PREFIX="${INSTALL_PREFIX:-}"   # auto-detected below if empty

# Pretty colors (only when stdout is a TTY).
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YEL=$'\033[33m'; RESET=$'\033[0m'
else
    BOLD=''; DIM=''; RED=''; GREEN=''; YEL=''; RESET=''
fi

say()  { printf '%s==>%s %s\n' "$BOLD$GREEN" "$RESET" "$*"; }
note() { printf '    %s%s%s\n' "$DIM" "$*" "$RESET"; }
warn() { printf '%s!!  %s%s\n' "$YEL" "$*" "$RESET" >&2; }
die()  { printf '%sERROR:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# -----------------------------------------------------------------------
# Step 1: platform check
# -----------------------------------------------------------------------
say "Checking platform"
os="$(uname -s)"
arch="$(uname -m)"

if [[ "$os" != "Linux" ]]; then
    die "$os is not supported in alpha. Linux only. File an issue if you need macOS/Windows."
fi

case "$arch" in
    x86_64|amd64) arch_tag="amd64" ;;
    aarch64|arm64) arch_tag="arm64" ;;
    *) die "unsupported arch: $arch (expected x86_64 or aarch64)" ;;
esac
note "platform = linux/$arch_tag"

# -----------------------------------------------------------------------
# Step 2: install prefix
# -----------------------------------------------------------------------
if [[ -z "$INSTALL_PREFIX" ]]; then
    if [[ "$(id -u)" == "0" ]]; then
        INSTALL_PREFIX=/usr/local
    else
        INSTALL_PREFIX="$HOME/.local"
    fi
fi
note "install prefix = $INSTALL_PREFIX"
mkdir -p "$INSTALL_PREFIX/bin"

# Check that the bin dir is on PATH.
case ":$PATH:" in
    *":$INSTALL_PREFIX/bin:"*) ;;
    *) warn "$INSTALL_PREFIX/bin is not on your PATH. Add this to your shell rc:"
       warn "    export PATH=\"$INSTALL_PREFIX/bin:\$PATH\"" ;;
esac

# -----------------------------------------------------------------------
# Step 3: required tools
# -----------------------------------------------------------------------
say "Checking required tools"
for tool in curl tar python3; do
    if ! command -v "$tool" &>/dev/null; then
        die "missing required tool: $tool"
    fi
done

# Python 3.10+ is supported. uuid.uuid7 is stdlib in 3.14+; older
# interpreters get a compliant fallback shim that gyza installs at
# package-import time (see gyza/_compat.py).
py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    die "Python 3.10+ required (you have $py_version). Ubuntu 22.04 / Debian 12 / Fedora 38+ ship a compatible interpreter by default; older systems can use \`pyenv install 3.12\` or similar. https://www.python.org/downloads/"
fi
note "python = $py_version"

# pipx is the recommended Python installer for CLI tools.
if ! command -v pipx &>/dev/null; then
    warn "pipx not found. Install it with:"
    warn "    python3 -m pip install --user pipx && python3 -m pipx ensurepath"
    die "re-run install.sh after pipx is on PATH"
fi
note "pipx = $(pipx --version)"

# -----------------------------------------------------------------------
# Step 4: download gyza-netd binary
# -----------------------------------------------------------------------
say "Downloading gyza-netd daemon"

if [[ "$GYZA_VERSION" == "latest" ]]; then
    tag_url="https://api.github.com/repos/$GYZA_REPO/releases/latest"
    GYZA_VERSION=$(curl -sSf "$tag_url" 2>/dev/null \
        | grep -m1 '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || true)
    if [[ -z "$GYZA_VERSION" ]]; then
        die "could not resolve latest release tag. Network issue? Pass GYZA_VERSION=vX.Y.Z explicitly."
    fi
fi
note "version = $GYZA_VERSION"

asset="gyza-netd-$GYZA_VERSION-linux-$arch_tag.tar.gz"
url="https://github.com/$GYZA_REPO/releases/download/$GYZA_VERSION/$asset"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

note "downloading $url"
if ! curl -fL --progress-bar -o "$tmpdir/$asset" "$url"; then
    die "download failed. Check that $GYZA_VERSION exists at https://github.com/$GYZA_REPO/releases"
fi

tar -xzf "$tmpdir/$asset" -C "$tmpdir"
if [[ ! -f "$tmpdir/gyza-netd" ]]; then
    die "release tarball is malformed (no gyza-netd binary inside)"
fi

install -m 0755 "$tmpdir/gyza-netd" "$INSTALL_PREFIX/bin/gyza-netd"
note "installed gyza-netd to $INSTALL_PREFIX/bin/gyza-netd"

# -----------------------------------------------------------------------
# Step 5: install gyza Python CLI via pipx
# -----------------------------------------------------------------------
say "Installing gyza Python CLI"
# Use `--force` so re-runs upgrade in place. pipx default Python is
# whatever `python3` points to.
if ! pipx install --force "gyza==${GYZA_VERSION#v}" 2>/dev/null; then
    # PyPI might not have a release matching this tag yet (open-source
    # alpha workflow ships via GitHub Releases first). Fall back to the
    # sdist or wheel from the release.
    note "PyPI install failed; trying GitHub Release wheel"
    wheel_asset="gyza-${GYZA_VERSION#v}-py3-none-any.whl"
    wheel_url="https://github.com/$GYZA_REPO/releases/download/$GYZA_VERSION/$wheel_asset"
    if ! curl -fLs -o "$tmpdir/$wheel_asset" "$wheel_url"; then
        die "could not fetch wheel from $wheel_url"
    fi
    pipx install --force "$tmpdir/$wheel_asset"
fi

# pipx puts the script in ~/.local/bin by default. Verify.
if ! command -v gyza &>/dev/null; then
    die "gyza CLI not on PATH after pipx install (expected ~/.local/bin to be on PATH)"
fi
note "installed gyza CLI"

# -----------------------------------------------------------------------
# Step 6: gyza init
# -----------------------------------------------------------------------
if [[ ! -f "$HOME/.gyza/compositor.key" ]]; then
    say "Generating compositor identity"
    gyza init
else
    note "compositor.key already exists; skipping init"
fi

# -----------------------------------------------------------------------
# Done.
# -----------------------------------------------------------------------
echo
say "Install complete."
cat <<EOF

  ${BOLD}Next:${RESET}
    ${DIM}# Start the daemon (joins the public bootstrap network)${RESET}
    gyza global start

    ${DIM}# In another shell, check status${RESET}
    gyza status

    ${DIM}# Run the integration demo (single-machine, two daemons)${RESET}
    python -m gyza.cli demo single-machine-global

  ${BOLD}Docs:${RESET}    https://github.com/$GYZA_REPO#readme
  ${BOLD}Issues:${RESET}  https://github.com/$GYZA_REPO/issues
EOF
