#!/usr/bin/env bash
# install.sh — one-command installer for the self-contained `gyza` binary.
#
#   curl -sSf https://gyza.network/install.sh | bash
#   then: gyza demo
#
# This installs the ONEDIR self-contained build: a single directory tree
# that carries its own Python + native deps. No system Python, no pipx, no
# virtualenv. The tree is required (not a lone file) because the enforced
# sandbox re-execs the binary against its own `_internal/` bundle — see
# packaging/gyza.spec. The Go daemon (gyza-netd, for `gyza global`) ships
# separately and is NOT needed for `gyza demo` or the core provenance CLI.
#
# Tamper-evidence, end to end (on-brand for a provenance tool):
#   * SHA256 of the release tarball is verified — MANDATORY, always, and
#     aborts on mismatch. sha256 covers the whole onedir tree transitively.
#   * A minisign signature over the same tarball is verified BEFORE
#     extraction when release signing is configured (see GYZA_MINISIGN_PUBKEY
#     below) and `minisign` is on PATH. Set GYZA_REQUIRE_SIG=1 to make a
#     missing/te unverifiable signature a hard failure.
#
# Env knobs:
#   GYZA_VERSION=vX.Y.Z     install a specific release (default: latest)
#   GYZA_REPO=owner/name    source repo (default: aaronamire/gyza)
#   INSTALL_PREFIX=/path     install root (default: ~/.local, or /usr/local as root)
#   GYZA_REQUIRE_SIG=1       fail unless the signature verifies
#
# Idempotent: re-running installs the requested version alongside any
# existing one and repoints the `gyza` symlink; ~/.gyza is untouched.

set -euo pipefail

GYZA_VERSION="${GYZA_VERSION:-latest}"
GYZA_REPO="${GYZA_REPO:-aaronamire/gyza}"
INSTALL_PREFIX="${INSTALL_PREFIX:-}"
GYZA_REQUIRE_SIG="${GYZA_REQUIRE_SIG:-0}"

# Release signing public key (minisign). PUBLIC — safe to embed. Empty
# until the maintainer generates a keypair (`minisign -G`), commits the
# public key here + into packaging/gyza-release.pub, and adds the secret
# key to the CI signing secret. While empty, install verifies the SHA256
# checksum only and says so plainly. USER-OWNED step (see CLAUDE.md §11).
GYZA_MINISIGN_PUBKEY=""

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

# ---------------------------------------------------------------- platform
say "Checking platform"
os="$(uname -s)"; arch="$(uname -m)"
[[ "$os" == "Linux" ]] || die "$os is not supported. The self-contained binary is Linux-only (bubblewrap enforcement is Linux). On macOS/Windows, use Docker: docker run --rm ghcr.io/$GYZA_REPO gyza demo"
case "$arch" in
    x86_64|amd64)  arch_tag="amd64" ;;
    aarch64|arm64) arch_tag="arm64" ;;
    *) die "unsupported arch: $arch (expected x86_64 or aarch64)" ;;
esac
note "platform = linux/$arch_tag"

# ------------------------------------------------------------------ prefix
if [[ -z "$INSTALL_PREFIX" ]]; then
    if [[ "$(id -u)" == "0" ]]; then INSTALL_PREFIX=/usr/local; else INSTALL_PREFIX="$HOME/.local"; fi
fi
note "install prefix = $INSTALL_PREFIX"
mkdir -p "$INSTALL_PREFIX/bin" "$INSTALL_PREFIX/lib/gyza"
case ":$PATH:" in
    *":$INSTALL_PREFIX/bin:"*) ;;
    *) warn "$INSTALL_PREFIX/bin is not on your PATH. Add to your shell rc:"
       warn "    export PATH=\"$INSTALL_PREFIX/bin:\$PATH\"" ;;
esac

# ------------------------------------------------------------------- tools
for tool in curl tar sha256sum; do
    command -v "$tool" &>/dev/null || {
        # macOS-style shasum fallback for sha256; but we're Linux-only, so
        # sha256sum should exist. Keep the check honest.
        [[ "$tool" == "sha256sum" ]] && command -v shasum &>/dev/null && continue
        die "missing required tool: $tool"
    }
done
sha256_cmd() { if command -v sha256sum &>/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

# ----------------------------------------------------------------- version
say "Resolving release"
if [[ "$GYZA_VERSION" == "latest" ]]; then
    api="https://api.github.com/repos/$GYZA_REPO/releases?per_page=10"
    GYZA_VERSION=$(curl -sSf "$api" 2>/dev/null | grep -m1 '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || true)
    [[ -n "$GYZA_VERSION" ]] || die "could not resolve latest release. Pass GYZA_VERSION=vX.Y.Z, or check https://github.com/$GYZA_REPO/releases"
fi
note "version = $GYZA_VERSION"

asset="gyza-$GYZA_VERSION-linux-$arch_tag.tar.gz"
base="https://github.com/$GYZA_REPO/releases/download/$GYZA_VERSION"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# --------------------------------------------------------------- download
say "Downloading $asset"
curl -fL --progress-bar -o "$tmp/$asset" "$base/$asset" \
    || die "download failed — does $GYZA_VERSION ship a linux-$arch_tag onedir tarball? See https://github.com/$GYZA_REPO/releases"
curl -fLs -o "$tmp/$asset.sha256" "$base/$asset.sha256" \
    || die "checksum file missing for $asset — refusing to install unverified. (Checksum is mandatory.)"

# --------------------------------------------------- MANDATORY sha256 gate
say "Verifying checksum (mandatory)"
expected=$(awk '{print $1}' "$tmp/$asset.sha256")
actual=$(sha256_cmd "$tmp/$asset" | awk '{print $1}')
[[ -n "$expected" ]] || die "checksum file is empty/malformed — aborting"
if [[ "$expected" != "$actual" ]]; then
    die "CHECKSUM MISMATCH — the download does not match its published SHA256. Someone may have tampered with it, or the download is corrupt. Aborting. expected=$expected got=$actual"
fi
note "sha256 OK ($actual)"

# ------------------------------------------------- signature (whole tree)
# Verify the signature over the SAME tarball, BEFORE extraction, so a
# tampered tarball is never unpacked. Signing the tarball covers the whole
# onedir tree transitively.
if [[ -n "$GYZA_MINISIGN_PUBKEY" ]]; then
    if command -v minisign &>/dev/null; then
        say "Verifying release signature"
        if curl -fLs -o "$tmp/$asset.minisig" "$base/$asset.minisig"; then
            if minisign -Vm "$tmp/$asset" -P "$GYZA_MINISIGN_PUBKEY" -x "$tmp/$asset.minisig" >/dev/null 2>&1; then
                note "signature OK — tarball is authentic and untampered"
            else
                die "SIGNATURE VERIFICATION FAILED — refusing to install. The tarball's checksum matched but its minisign signature did not verify against the pinned key."
            fi
        else
            [[ "$GYZA_REQUIRE_SIG" == "1" ]] && die "no signature published for $asset and GYZA_REQUIRE_SIG=1"
            warn "no signature file published for this release; checksum-verified only"
        fi
    else
        [[ "$GYZA_REQUIRE_SIG" == "1" ]] && die "minisign not installed and GYZA_REQUIRE_SIG=1. Install it: https://jedisct1.github.io/minisign/"
        warn "minisign not installed — verified checksum only. For signature verification: install minisign, then re-run (or set GYZA_REQUIRE_SIG=1 to enforce)."
    fi
else
    [[ "$GYZA_REQUIRE_SIG" == "1" ]] && die "release signing is not configured in this installer but GYZA_REQUIRE_SIG=1 was set"
    note "release signing not yet configured; verified SHA256 checksum only"
fi

# -------------------------------------------------------------- extract
say "Installing"
dest="$INSTALL_PREFIX/lib/gyza/$GYZA_VERSION"
rm -rf "$dest"; mkdir -p "$dest"
tar -xzf "$tmp/$asset" -C "$dest"
# The tarball contains a top-level `gyza/` onedir tree.
bin="$dest/gyza/gyza"
[[ -x "$bin" ]] || die "release tarball is malformed (no executable gyza/gyza inside)"
ln -sfn "$bin" "$INSTALL_PREFIX/bin/gyza"
note "installed to $dest"
note "symlinked $INSTALL_PREFIX/bin/gyza -> $bin"

# ---------------------------------------------------------------- verify
"$INSTALL_PREFIX/bin/gyza" --help >/dev/null 2>&1 || die "installed binary failed to run — the artifact may not match this host's glibc. Report at https://github.com/$GYZA_REPO/issues"

echo
say "Install complete."
cat <<EOF

  ${BOLD}Try it now (offline, ~seconds, zero config):${RESET}
    gyza demo

  ${DIM}On Linux with bubblewrap installed you'll see OS-enforced containment;${RESET}
  ${DIM}otherwise the disclosed no-sandbox path (it says which, honestly).${RESET}

  ${BOLD}Docs:${RESET}    https://github.com/$GYZA_REPO#readme
  ${BOLD}Issues:${RESET}  https://github.com/$GYZA_REPO/issues
EOF
