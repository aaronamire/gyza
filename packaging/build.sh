#!/usr/bin/env bash
# build.sh — local dev build of the `gyza` binary (FUNCTIONAL TEST ONLY).
#
# A build on a modern distro links libpython/libstdc++/libcrypto against a
# bleeding-edge glibc, so it is NOT shippable — it will not run on older
# targets. check_glibc_floor.sh reports the floor at the end. For a
# release artifact, build inside manylinux_2_28 (packaging/Dockerfile.build).
#
# Usage:
#   packaging/build.sh              # onedir (the shipped shape)
#   packaging/build.sh --onefile    # single file — "one file to scp"
#                                   # convenience ONLY. The enforced path
#                                   # re-extracts ~100MB into the sandbox
#                                   # tmpfs on EVERY bwrap call; use onedir
#                                   # for any real enforced workload.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
DIST="${DIST:-$REPO/dist}"
WORK="${WORK:-$REPO/build/pyinstaller}"

command -v "$PY" >/dev/null || { echo "no python interpreter (set PYTHON=)" >&2; exit 1; }
"$PY" -c "import PyInstaller" 2>/dev/null \
    || { echo "PyInstaller missing: $PY -m pip install 'pyinstaller>=6.0'" >&2; exit 1; }

if [[ "${1:-}" == "--onefile" ]]; then
    excludes=(torch sentence_transformers transformers tokenizers safetensors
              lancedb pyarrow grpc grpcio aioquic scipy sklearn pandas
              matplotlib IPython notebook PIL huggingface_hub)
    args=()
    for m in "${excludes[@]}"; do args+=(--exclude-module "$m"); done
    "$PY" -m PyInstaller --noconfirm --onefile \
        --distpath "$DIST" --workpath "$WORK" --specpath "$REPO/build" \
        --name gyza --paths "$REPO" \
        --hidden-import gyza.sandbox._entrypoint \
        --hidden-import gyza.sandbox._probes \
        --hidden-import gyza.runner \
        --hidden-import gyza.sandbox.executor \
        --hidden-import gyza.sandbox.runner \
        "${args[@]}" \
        "$REPO/packaging/gyza_launcher.py"
    echo "onefile -> $DIST/gyza   (perf caveat: per-action re-extraction under bwrap)"
else
    "$PY" -m PyInstaller --noconfirm \
        --distpath "$DIST" --workpath "$WORK" \
        "$REPO/packaging/gyza.spec"
    echo "onedir -> $DIST/gyza/gyza"
    bash "$REPO/packaging/check_glibc_floor.sh" "$DIST/gyza" 28 \
        || echo "(local floor too high to SHIP — expected off-manylinux; functional test only)"
fi
