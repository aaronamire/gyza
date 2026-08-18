#!/usr/bin/env bash
# check_reproducible.sh — build twice and compare the ACTUAL BYTES.
#
# Not a manifest hash. Not a file list. Every regular file in the onedir tree is
# compared byte-for-byte, and the launcher binary's sha256 is printed so the
# claim "same source -> same binary" is checkable by a reader rather than
# asserted by a document.
#
#   packaging/check_reproducible.sh              # 2 builds, default controls
#   N=3 packaging/check_reproducible.sh          # 3 builds
#   NO_CONTROLS=1 packaging/check_reproducible.sh  # negative control: expect FAIL
#
# NO_CONTROLS exists so this script can be shown to have power. A reproducibility
# check that passes because nothing could ever differ is worth nothing; with the
# controls disabled it must FAIL, and that is asserted in CI-friendly form.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
N="${N:-2}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for i in $(seq 1 "$N"); do
    if [[ -n "${NO_CONTROLS:-}" ]]; then
        # DISABLE the load-bearing control by restoring CPython's DEFAULT
        # (randomised hashing). NOTE: `PYTHONHASHSEED=""` does NOT work --
        # build.sh reads `${PYTHONHASHSEED:-0}`, and `:-` treats empty as
        # unset, so the empty string is replaced by 0 and the "negative
        # control" silently reproduces the positive case. That is exactly what
        # happened on the first run of this script: it reported REPRODUCIBLE
        # under NO_CONTROLS, i.e. the check had no power. `random` is the only
        # value that actually restores the default behaviour.
        DIST="$TMP/d$i" WORK="$TMP/w$i" PYTHONHASHSEED=random \
            bash "$REPO/packaging/build.sh" >/dev/null 2>&1
    else
        DIST="$TMP/d$i" WORK="$TMP/w$i" \
            bash "$REPO/packaging/build.sh" >/dev/null 2>&1
    fi
done

echo "launcher sha256:"
for i in $(seq 1 "$N"); do sha256sum "$TMP/d$i/gyza/gyza"; done

rc=0
for i in $(seq 2 "$N"); do
    if ! diff -rq "$TMP/d1/gyza" "$TMP/d$i/gyza" >/dev/null 2>&1; then
        echo "BUILD $i DIFFERS FROM BUILD 1:"
        diff -rq "$TMP/d1/gyza" "$TMP/d$i/gyza" 2>&1 | sed 's/^/    /'
        rc=1
    fi
done

n_files="$(find "$TMP/d1/gyza" -type f | wc -l)"
if [[ $rc -eq 0 ]]; then
    echo "REPRODUCIBLE: $N builds, $n_files files, byte-identical"
else
    echo "NOT REPRODUCIBLE ($n_files files compared)"
fi
exit $rc
