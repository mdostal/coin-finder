# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for coin-finder's web UI sidecar, frozen as --onedir.

Built with:
    pyinstaller packaging/pyinstaller/coin_finder_ui.spec

--onedir, not --onefile -- same reasoning as this project's other desktop
apps (e.g. cleanup-tools): a onedir build's reported pid IS the real
Flask/Werkzeug process, so the desktop shell's kill-on-quit reliably frees
the port. A onefile build's pid is its bootloader's; a SIGKILL to it can
orphan the real interpreter still holding the port. onedir's extra size is
a worthwhile trade for that reliability guarantee.

datas -- globbed from disk, not hand-listed
--------------------------------------------
Every file under web/templates/ and web/static/ is included via a real
`glob` over the actual directories at spec-build time, not a manually
maintained list -- so a template/static file added later can't silently
go missing from a future build the way a hand-maintained list could drift.

hiddenimports -- services/*.py are the load-bearing one
----------------------------------------------------------
tools/check_wallet_balances.py loads each coin's balance-checker via
`importlib.import_module(f"services.{module_path}")`, resolved at RUNTIME
from config/wallet.py's WALLET_SERVICES mapping -- PyInstaller's static
import scanner cannot see these (they're never a literal `import
services.bitcoin` anywhere in source), so every one of them must be listed
explicitly below or balance checking silently breaks in the frozen build
for every coin. Generated from config/wallet.py's own mapping rather than
hand-typed, so it can't drift from the real coin list either.
"""

import glob
import os

block_cipher = None

REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))


def _collect_datas(src_dir, dest_prefix):
    entries = []
    for path in glob.glob(os.path.join(REPO_ROOT, src_dir, "**", "*"), recursive=True):
        if os.path.isfile(path):
            rel_dir = os.path.relpath(os.path.dirname(path), os.path.join(REPO_ROOT, src_dir))
            dest = dest_prefix if rel_dir == "." else os.path.join(dest_prefix, rel_dir)
            entries.append((path, dest))
    return entries


datas = (
    _collect_datas("web/templates", "web/templates")
    + _collect_datas("web/static", "web/static")
    # BTCRecover/hashcat-tools -- run_unlock()/run_exodus_unlock()
    # (tools/unlock_wallet.py, tools/unlock_exodus_wallet.py) locate these
    # at a REPO_ROOT-relative path and fail with "not installed" if
    # they're missing -- confirmed live: never bundled before, so every
    # unlock attempt in every installed build this session has failed
    # with exactly that error, the whole feature was non-functional.
    + _collect_datas("vendor/btcrecover", "vendor/btcrecover")
    + _collect_datas("vendor/hashcat-tools", "vendor/hashcat-tools")
)

# config/wallet.py's WALLET_SERVICES values are the services/<name>.py
# module names actually loaded dynamically at runtime -- read directly
# from the real file rather than duplicated by hand here.
_wallet_config_ns = {}
with open(os.path.join(REPO_ROOT, "config", "wallet.py")) as f:
    exec(f.read(), _wallet_config_ns)
_service_modules = sorted(set(_wallet_config_ns["WALLET_SERVICES"].values()))

hiddenimports = [f"services.{name}" for name in _service_modules] + [
    "services",
    "bip_utils",
    "mnemonic",
    "googleapiclient",
    "google_auth_httplib2",
    "google_auth_oauthlib",
    # coincurve's CFFI-compiled extensions -- imported dynamically (not a
    # literal `import coincurve._cffi_backend` anywhere in source), so
    # PyInstaller's static scanner misses them without this. Confirmed by
    # a real ModuleNotFoundError on a first build attempt.
    "coincurve._cffi_backend",
    "coincurve._libsecp256k1",
]

a = Analysis(
    [os.path.join(SPECPATH, "entrypoint.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

# A second, separately bundled executable -- see script_runner.py's own
# docstring for why this exists. Inside a frozen build, sys.executable is
# the main app's own binary (only knows how to run itself), so
# run_unlock()/run_exodus_unlock() cannot shell out to btcrecover.py/
# exodus2hashcat.py via `[sys.executable, script.py, ...]` the way they do
# in a normal source/dev environment -- confirmed live (a real crash).
# This ships as a sibling executable in the same onedir output (via
# MERGE(), sharing the bundled Python runtime/stdlib instead of doubling
# the ~150MB build), whose only job is to runpy.run_path() whatever
# script it's given with the given argv.
a_runner = Analysis(
    # btcrecover.py/exodus2hashcat.py are listed here too -- NOT as
    # separate entry points (only script_runner.py becomes an EXE below),
    # but so PyInstaller's static import scanner actually traces their
    # real dependency trees (multiprocessing, their own vendored crypto
    # libs, etc.) at build time. runpy.run_path() loads them dynamically
    # at RUNTIME, invisible to the scanner otherwise -- confirmed live,
    # every such import was missing without this.
    [
        os.path.join(SPECPATH, "script_runner.py"),
        os.path.join(REPO_ROOT, "vendor", "btcrecover", "btcrecover.py"),
        os.path.join(REPO_ROOT, "vendor", "hashcat-tools", "exodus2hashcat.py"),
    ],
    pathex=[REPO_ROOT, os.path.join(REPO_ROOT, "vendor", "btcrecover"), os.path.join(REPO_ROOT, "vendor", "hashcat-tools")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

MERGE((a, "entrypoint", "coin-finder-onedir"), (a_runner, "script_runner", "coin-finder-script-runner"))

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="coin-finder-onedir",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    cipher=block_cipher,
)

pyz_runner = PYZ(a_runner.pure, a_runner.zipped_data, cipher=block_cipher)

exe_runner = EXE(
    pyz_runner,
    a_runner.scripts,
    [],
    exclude_binaries=True,
    name="coin-finder-script-runner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    cipher=block_cipher,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    exe_runner,
    a_runner.binaries,
    a_runner.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="coin-finder-onedir",
)
