"""
PyInstaller entrypoint for the coin-finder web UI sidecar.

This is what `Analysis()` in `coin_finder_ui.spec` targets as the frozen
binary's `__main__`. Its only job is to build the Flask app (via the
existing `create_app()` factory, same as `python web/app.py` uses) and
bind it to 127.0.0.1 -- the desktop app shell (`src-tauri/`) is
responsible for opening its own window pointed at the bound host:port, so
this sidecar must never pop a real OS browser window itself, and Flask's
own `debug`/reloader must stay off (it forks a second process, which would
break the "one pid == the real server" assumption the desktop shell's
kill-on-quit logic depends on).

`port`/`host` are optionally overridable via CLI args (`sys.argv[1]`/
`sys.argv[2]`), matching src-tauri's sidecar spawn call -- not expected to
be passed in normal operation, present so a frozen binary can still be run
standalone (e.g. for the smoke test) without colliding with a real dev
server on the default port.
"""

import sys

from web.app import create_app

DEFAULT_PORT = 5050
LOCALHOST = "127.0.0.1"


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    host = sys.argv[2] if len(sys.argv) > 2 else LOCALHOST
    create_app(host=host).run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
