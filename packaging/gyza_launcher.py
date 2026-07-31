"""
Frozen-binary entry point for the self-contained `gyza` CLI.

PyInstaller freezes this script; the resulting binary's argv is handed
straight to ``gyza.cli.main``. main() detects the sandbox self-re-exec
sentinel before argparse (see gyza/sandbox/runner.py), so the same binary
serves both the operator CLI and the in-sandbox workload runner.
"""
import sys

from gyza.cli import main

if __name__ == "__main__":
    sys.exit(main())
