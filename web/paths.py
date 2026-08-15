import sys
from pathlib import Path


def is_frozen():
    return getattr(sys, "frozen", False)


def app_data_dir():
    """
    Where persistent app state lives -- findings.db, bound targets, mount
    state, the vault fallback store, scan output, staged files.

    A frozen desktop build's own directory gets replaced wholesale on
    every reinstall/update (it's inside the .app bundle) -- confirmed the
    hard way: findings.db and a scan's output were found written inside
    Contents/Resources/.../_internal/, which a future update would wipe
    without warning. Persistent state for a frozen build must live outside
    the bundle, in the OS's standard per-user app-data location instead.

    Source/dev installs keep using this file's own directory (`web/`),
    unchanged -- already gitignored, and what every existing dev workflow
    and script expects.
    """
    if not is_frozen():
        return Path(__file__).resolve().parent

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "coin-finder"
    elif sys.platform == "win32":
        import os

        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "coin-finder"
    else:
        base = Path.home() / ".local" / "share" / "coin-finder"

    base.mkdir(parents=True, exist_ok=True)
    return base
