"""
Gyza — peer-to-peer compute network with cryptographic provenance
and bilateral settlement.

Package-load side effect: ``_compat.install()`` registers a
``uuid.uuid7`` shim on Python interpreters older than 3.14. Every
internal caller of ``uuid.uuid7()`` lives under this package, so
the shim is in place by the time any of them dispatch.
"""
from . import _compat as _compat

_compat.install()

__version__ = "0.1.1"
