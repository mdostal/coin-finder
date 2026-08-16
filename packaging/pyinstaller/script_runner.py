"""
Frozen-build helper: runs an arbitrary vendored Python script (btcrecover.py,
exodus2hashcat.py) as if invoked by a real `python3 <script> <args>` call.

Why this exists: inside a frozen PyInstaller build, sys.executable is THIS
APP'S OWN frozen binary (only knows how to run itself, via entrypoint.py) --
not a general-purpose Python interpreter. `subprocess.run([sys.executable,
some_other_script.py, ...])` (the correct call in a normal source/dev
environment, where sys.executable is a real python3) breaks for exactly that
reason once frozen -- confirmed live: the frozen binary received the script
path as if it were its own first CLI arg and crashed trying to parse it as a
port number.

This is a second, separately bundled frozen executable (sharing the same
PyInstaller-bundled Python runtime as the main app, via MERGE() in
coin_finder_ui.spec) whose only job is to runpy.run_path() the real target
script with the real intended argv -- giving run_unlock()/
run_exodus_unlock() (tools/unlock_wallet.py, tools/unlock_exodus_wallet.py)
something they CAN correctly invoke via subprocess once frozen.
"""
import multiprocessing
import os
import runpy
import sys

if __name__ == "__main__":
    # btcrecover spawns multiprocessing worker processes for parallel
    # password checking. In a frozen build, a worker is spawned by
    # re-invoking THIS SAME executable with special bootstrap flags
    # (-B, --multiprocessing-fork, ...) -- freeze_support() detects that
    # pattern and dispatches to Python's real multiprocessing bootstrap
    # instead of falling through to the runpy logic below, which would
    # otherwise misinterpret those flags as "the script path" and crash-
    # loop. Must be the very first thing that runs, per Python's own
    # multiprocessing docs for frozen executables.
    multiprocessing.freeze_support()

    if len(sys.argv) < 2:
        print("usage: coin-finder-script-runner <script.py> [args...]", file=sys.stderr)
        sys.exit(2)
    script_path = sys.argv[1]
    sys.argv = sys.argv[1:]  # the target script sees itself as argv[0], matching a real `python3 script.py ...` invocation

    # A real `python3 script.py` invocation prepends the script's own
    # directory to sys.path[0] -- runpy.run_path() does NOT do this on
    # its own. Confirmed live: btcrecover.py's `import compatibility_check`
    # (a sibling file next to btcrecover.py, found only via this implicit
    # path) failed with ModuleNotFoundError without it.
    sys.path.insert(0, os.path.dirname(os.path.abspath(script_path)))

    runpy.run_path(script_path, run_name="__main__")
