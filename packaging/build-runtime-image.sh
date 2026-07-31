#!/usr/bin/env bash
# build-runtime-image.sh — build the runtime Docker image (packaging/
# Dockerfile) from a MINIMAL staged context.
#
# Why staged: the repo-root .dockerignore excludes dist/ (so the manylinux
# build's `COPY . /src` stays small + never ships a pre-built tree). The
# runtime image, by contrast, needs exactly that onedir tree — so we stage
# {tree, Dockerfile} into a temp dir and build there. Single source of
# truth for both local + CI, mirroring how Dockerfile.build is the single
# source for the binary.
#
# Usage:
#   packaging/build-runtime-image.sh [image-tag]
#   GYZA_ONEDIR=/path/to/gyza-tree packaging/build-runtime-image.sh ghcr.io/aaronamire/gyza:dev
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:-gyza-runtime}"
TREE="${GYZA_ONEDIR:-$REPO/dist/gyza}"

[[ -x "$TREE/gyza" ]] || {
    echo "no onedir tree at $TREE" >&2
    echo "build it first: docker build -f packaging/Dockerfile.build -t gyza-onedir-build . &&" >&2
    echo "  id=\$(docker create gyza-onedir-build) && docker cp \"\$id:/out/dist/gyza\" dist/gyza && docker rm \"\$id\"" >&2
    exit 1
}

ctx="$(mktemp -d)"; trap 'rm -rf "$ctx"' EXIT
mkdir -p "$ctx/dist"
cp -r "$TREE" "$ctx/dist/gyza"
cp "$REPO/packaging/Dockerfile" "$ctx/Dockerfile"
docker build -f "$ctx/Dockerfile" -t "$TAG" "$ctx"
echo "built $TAG"
