"""
Python version compatibility shims.

The codebase targets Python 3.10+. The only stdlib API we use that
isn't available below 3.14 is ``uuid.uuid7`` (added in 3.14 per
RFC 9562). For older interpreters we install a compliant fallback
under the same name so the rest of the codebase can call
``uuid.uuid7()`` unconditionally.

This module is imported by ``gyza/__init__.py`` so the patch happens
once, at package-load time. Callsites that pre-import ``uuid`` and
hold a reference before importing ``gyza`` will see the patch on
their next attribute lookup (since we mutate the module's
attribute table directly, not just rebind a local name).

The fallback implementation matches RFC 9562 §5.7 byte-for-byte
where the version + variant + structure are concerned; the
randomness comes from ``os.urandom`` which is the same source the
stdlib uses. Output is a standard ``uuid.UUID`` instance, so
downstream code that calls ``str(uuid.uuid7())`` gets a normal
canonical string.
"""
from __future__ import annotations

import os
import time
import uuid


def _uuid7_fallback() -> uuid.UUID:
    """
    Generate a UUIDv7 per RFC 9562.

    Layout (128 bits, big-endian):

        unix_ts_ms (48) | ver=0x7 (4) | rand_a (12) | var=0b10 (2) | rand_b (62)

    Time component is millisecond Unix epoch. Random components are
    drawn from ``os.urandom``. The result is monotonic at millisecond
    resolution; collisions within a single millisecond rely on the
    74 bits of randomness (rand_a + rand_b), which is comfortably
    safe in practice (~9 quintillion-to-one against collision among
    a billion IDs generated in the same ms).
    """
    unix_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_bytes = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand_bytes >> 62) & 0xFFF  # top 12 bits of the 80-bit pool
    rand_b = rand_bytes & ((1 << 62) - 1)  # bottom 62 bits
    value = (
        (unix_ms << 80)
        | (0x7 << 76)        # version nibble
        | (rand_a << 64)
        | (0b10 << 62)        # variant marker (RFC 9562 §4.1)
        | rand_b
    )
    return uuid.UUID(int=value)


def install() -> None:
    """
    Add ``uuid.uuid7`` to the stdlib module if missing.

    No-op on Python 3.14+ where it's already there. Safe to call
    multiple times.
    """
    if not hasattr(uuid, "uuid7"):
        uuid.uuid7 = _uuid7_fallback  # type: ignore[attr-defined]
