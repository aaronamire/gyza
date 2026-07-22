#!/usr/bin/env bash
# check_glibc_floor.sh — assert a built onedir tree's glibc floor is low
# enough to ship. Makes portability a TESTED invariant, not a hope: a
# local build on a modern distro links libpython / libstdc++ / libcrypto
# against a bleeding-edge glibc and would be "works on my machine, dead on
# theirs". CI runs this on the manylinux-built tree and FAILS the build if
# any bundled ELF requires a glibc newer than the ceiling.
#
# Usage:
#   packaging/check_glibc_floor.sh <onedir-tree> [max_minor]
# e.g.
#   packaging/check_glibc_floor.sh dist/gyza 28      # ceiling = glibc 2.28
#
# Exit 0 if the tree's max GLIBC_2.<n> symbol has n <= max_minor, else 1.

set -euo pipefail

TREE="${1:?usage: check_glibc_floor.sh <onedir-tree> [max_minor]}"
MAX_MINOR="${2:-28}"

if ! command -v objdump >/dev/null 2>&1; then
    echo "check_glibc_floor: objdump not found (need binutils)" >&2
    exit 2
fi
[[ -d "$TREE" ]] || { echo "check_glibc_floor: not a directory: $TREE" >&2; exit 2; }

# Scan every ELF object in the tree for versioned GLIBC_2.<minor> symbol
# requirements and take the maximum minor. (GLIBC_2.NN dominates; the rare
# GLIBC_1.x / no-version symbols never set the floor.)
max=0
worst=""
while IFS= read -r -d '' f; do
    # Only real ELF files; objdump errors on scripts/data are ignored.
    syms="$(objdump -T "$f" 2>/dev/null | grep -oE 'GLIBC_2\.[0-9]+' || true)"
    [[ -z "$syms" ]] && continue
    m="$(printf '%s\n' "$syms" | sed -E 's/GLIBC_2\.//' | sort -n | tail -1)"
    if (( m > max )); then max="$m"; worst="$f"; fi
done < <(find "$TREE" -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) -print0)

echo "glibc floor: GLIBC_2.$max  (ceiling GLIBC_2.$MAX_MINOR)"
[[ -n "$worst" ]] && echo "  set by: $worst"

if (( max > MAX_MINOR )); then
    echo "FAIL: glibc floor GLIBC_2.$max exceeds ceiling GLIBC_2.$MAX_MINOR." >&2
    echo "      This tree will not run on the target baseline. Build inside" >&2
    echo "      the manylinux_2_28 container (packaging/Dockerfile.build)," >&2
    echo "      never on a modern host." >&2
    exit 1
fi
echo "OK: within the glibc_2.$MAX_MINOR portability floor."
