import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.search import WALLET_EXTENSIONS, WALLET_KEYWORDS, MAX_FILE_SIZE, MIN_FILE_SIZE, COIN_NAMES

CHECKPOINT_EVERY_DIRS = 200
CHECKPOINT_EVERY_SECONDS = 20


def _load_checkpoint(checkpoint_path, start_path):
    if not checkpoint_path or not Path(checkpoint_path).exists():
        return set(), []
    try:
        with open(checkpoint_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set(), []
    if data.get("start_path") != str(start_path):
        return set(), []
    return set(data.get("completed_dirs", [])), list(data.get("potential_wallets", []))


def search_for_wallets(start_path, output_file, checkpoint_path=None):
    """
    Walks start_path looking for likely wallet files. A long walk over a
    huge mounted drive is exactly the kind of job that used to be thrown
    away entirely by an app quit/update/crash mid-scan -- os.walk had no
    notion of "already checked this directory," so any interruption meant
    starting over from nothing.

    checkpoint_path, when given, makes this resumable: after every
    CHECKPOINT_EVERY_DIRS directories (or CHECKPOINT_EVERY_SECONDS,
    whichever comes first), the directories already checked and the
    wallets found so far are flushed to checkpoint_path and output_file.
    If checkpoint_path already exists and matches start_path, those
    directories are skipped this run instead of being re-walked --
    picking back up close to where a prior, interrupted run left off
    instead of restarting from zero. The checkpoint is removed once the
    walk finishes cleanly.
    """
    completed_dirs, potential_wallets = _load_checkpoint(checkpoint_path, start_path)
    if completed_dirs:
        print(f"Resuming scan of {start_path}: {len(completed_dirs)} directory(ies) already checked, {len(potential_wallets)} wallet(s) found so far.")

    def _flush():
        with open(output_file, "w") as f:
            for wallet in potential_wallets:
                f.write(wallet + "\n")
        if checkpoint_path:
            with open(checkpoint_path, "w") as f:
                json.dump(
                    {"start_path": str(start_path), "completed_dirs": sorted(completed_dirs), "potential_wallets": potential_wallets},
                    f,
                )

    dirs_since_checkpoint = 0
    last_checkpoint_at = time.time()

    for root, dirs, files in os.walk(start_path):
        if root in completed_dirs:
            continue

        for file in files:
            file_path = Path(root) / file
            try:
                file_size = file_path.stat().st_size

                # Skip files outside the size range
                if file_size > MAX_FILE_SIZE:
                    print(f"Skipping large file: {file_path} ({file_size / (1024 * 1024):.2f} MB)")
                    continue
                if file_size < MIN_FILE_SIZE:
                    print(f"Skipping empty or very small file: {file_path}")
                    continue

                # Check if the file matches extensions or keywords
                if any(file_path.suffix.lower() == ext for ext in WALLET_EXTENSIONS) or \
                   any(coin_name in file.lower() for coin_name in COIN_NAMES) or \
                   any(keyword in file.lower() for keyword in WALLET_KEYWORDS):
                    potential_wallets.append(str(file_path))
            except Exception as e:
                print(f"Error accessing file {file_path}: {e}")

        completed_dirs.add(root)
        dirs_since_checkpoint += 1
        if checkpoint_path and (dirs_since_checkpoint >= CHECKPOINT_EVERY_DIRS or time.time() - last_checkpoint_at >= CHECKPOINT_EVERY_SECONDS):
            _flush()
            dirs_since_checkpoint = 0
            last_checkpoint_at = time.time()

    _flush()
    if checkpoint_path:
        Path(checkpoint_path).unlink(missing_ok=True)

    print(f"Search complete. Found {len(potential_wallets)} potential wallet files.")
    print(f"Results saved to {output_file}.")
    return potential_wallets

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Search for potential crypto wallet files.")
    parser.add_argument("start_path", help="Path to start searching from.")
    parser.add_argument("output_file", help="File to save the list of wallet files.")
    args = parser.parse_args()

    search_for_wallets(args.start_path, args.output_file)
