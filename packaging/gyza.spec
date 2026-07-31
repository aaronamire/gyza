# -*- mode: python ; coding: utf-8 -*-
"""
Onedir PyInstaller build for the self-contained `gyza` binary.

ONEDIR, not onefile: the enforced path re-execs THIS binary inside
bubblewrap to sandbox itself (gyza/sandbox/runner.py). Onedir binds its
`_internal/` bundle read-only into the sandbox at zero per-action cost;
onefile would re-extract ~100MB into the sandbox tmpfs on every bwrap
call. Onefile is offered only as a labelled "one file to scp" convenience
(packaging/build.sh --onefile) with that perf caveat.

Build (dev, from any interpreter that has the gyza runtime deps):
    python -m PyInstaller --noconfirm packaging/gyza.spec

SHIPPABLE builds run inside a manylinux_2_28 container so libpython +
native deps carry a glibc <= 2.28 floor (packaging/Dockerfile.build). A
local build on a modern distro has too high a glibc floor to ship — it is
a functional test artifact only. CI enforces the ceiling with
packaging/check_glibc_floor.sh.
"""
import os

# SPECPATH is injected by PyInstaller = the directory holding this spec
# (packaging/); its parent is the repo root.
REPO = os.path.dirname(SPECPATH)

# Resolved via importlib at RUNTIME, so PyInstaller's static import graph
# cannot see them — declare explicitly or the frozen enforced path breaks:
#   * _entrypoint  — the frozen self-re-exec sandboxee entry
#   * gyza.runner  — the factory (gyza.runner:make_mock_executor) the
#                    sandboxee loads by qualname inside bwrap
hiddenimports = [
    "gyza.sandbox._entrypoint",
    "gyza.sandbox._probes",
    "gyza.runner",
    "gyza.sandbox.executor",
    "gyza.sandbox.runner",
]

# Provably-safe excludes: the `gyza demo` path never imports these at
# runtime (verified via sys.modules), and gyza.runner pulls only numpy of
# the heavy deps. Excluding them keeps the binary lean without touching
# any import site (no refactor). If a future path needs one, remove it
# here — do NOT add a lazy-import workaround in library code.
excludes = [
    "torch", "sentence_transformers", "transformers", "tokenizers",
    "safetensors", "lancedb", "pyarrow", "grpc", "grpcio", "aioquic",
    "scipy", "sklearn", "pandas", "matplotlib", "IPython", "notebook",
    "PIL", "huggingface_hub",
]

a = Analysis(
    [os.path.join(SPECPATH, "gyza_launcher.py")],
    pathex=[REPO],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir
    name="gyza",
    console=True,
    strip=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="gyza",
)
