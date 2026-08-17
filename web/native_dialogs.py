import platform
import shutil
import subprocess


def pick_path(mode="file", title=None):
    """
    Opens a native OS file/folder picker (Finder on macOS, a zenity dialog
    on Linux) and returns the chosen absolute path, or None if the user
    cancels. Blocks the calling thread until the dialog closes -- this app
    is single local user, and a modal native picker is the same UX as any
    other desktop app's "Browse..." button.

    :param mode: "file" or "directory".
    :raises RuntimeError: unsupported platform, or (Linux) zenity missing.
    """
    system = platform.system()
    if system == "Darwin":
        return _pick_path_macos(mode, title)
    if system == "Linux":
        return _pick_path_linux(mode, title)
    raise RuntimeError(f"Native file picker isn't supported on this platform ({system}). Type the path directly instead.")


def _pick_path_macos(mode, title):
    chooser = "choose folder" if mode == "directory" else "choose file"
    prompt = f' with prompt "{title}"' if title else ""
    script = f"POSIX path of ({chooser}{prompt})"
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _pick_path_linux(mode, title):
    if shutil.which("zenity") is None:
        raise RuntimeError("Native file picker needs `zenity` (not found on PATH) on Linux. Install it, or type the path directly.")

    args = ["zenity", "--file-selection"]
    if mode == "directory":
        args.append("--directory")
    if title:
        args += ["--title", title]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()
