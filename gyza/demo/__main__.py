"""Allow ``python -m gyza.demo`` to run the flagship DDIL partition demo."""
from __future__ import annotations

from gyza.demo.ddil_partition import main

if __name__ == "__main__":
    raise SystemExit(main())
