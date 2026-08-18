import json
import re
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.address_validators import filter_valid_addresses
from config.analysis import CRYPTO_PATTERNS
from tools.checkpoint_store import CheckpointStore
from tools.scan_index import hash_file_bytes, is_known, record_scanned_file

# Cadence for flushing the (optional) checkpoint store during a long
# analyze run -- same spirit as search_wallets.py's CHECKPOINT_EVERY_DIRS/
# CHECKPOINT_EVERY_SECONDS and check_wallet_balances.py's
# CHECKPOINT_EVERY_ADDRESSES/CHECKPOINT_EVERY_SECONDS: bound how much
# progress a crash can lose without paying a full-transaction commit cost
# per single file.
CHECKPOINT_EVERY_FILES = 50
CHECKPOINT_EVERY_SECONDS = 20


def analyze_wallet_file(file_path):
    """
    Analyze a single file for cryptocurrency addresses.

    Every raw regex match is filtered through that coin's offline
    checksum validator (config/address_validators.py) before it's
    included below -- the earliest possible point in the pipeline, so a
    shape-only false positive (e.g. Rust mangled-symbol strings that
    happen to match Digibyte's pattern) never reaches wallet_analysis.json,
    never burns a balance-check API call, and never becomes a stored
    finding.

    :param file_path: Path to the file to analyze.
    :return: Dictionary of found addresses grouped by cryptocurrency.
    """
    results = {}
    try:
        with open(file_path, "rb") as f:
            content = f.read()
            text = content.decode(errors="ignore")
            for crypto, pattern in CRYPTO_PATTERNS.items():
                matches = filter_valid_addresses(crypto, re.findall(pattern, text))
                if matches:
                    results[crypto] = list(set(matches))  # Deduplicate results
    except Exception as e:
        print(f"Error analyzing {file_path}: {e}")
    return results


def _analyze_one_file(file_path):
    """
    Module-level, picklable worker function dispatched to
    multiprocessing.Pool workers. Deliberately pure -- no shared state,
    and critically, NO interaction with tools/scan_index.py (the existing
    content-hash dedup cache) of any kind, read or write. That's the whole
    point: scan_index.db must never get a concurrent writer once
    multiprocessing is in play, and the simplest way to guarantee that is
    for worker processes to never touch it at all. Every scan_index.py
    read/write and every checkpoint_store.mark_completed() call happens
    back in analyze_wallets()'s own main-process result loop, one at a
    time, exactly as the sequential path already does.

    Any exception raised by analyze_wallet_file propagates unmodified --
    not caught here -- so it surfaces to the main process when the pool's
    result iterator yields it, mirroring check_wallet_balances.py's
    existing future.result() re-raise pattern (a single bad file/worker
    failure is captured and surfaced, not silently swallowed).

    :return: (file_path, results_dict)
    """
    return file_path, analyze_wallet_file(file_path)


def _read_bytes(file_path):
    try:
        with open(file_path, "rb") as fh:
            return fh.read()
    except OSError as e:
        print(f"Error reading {file_path}: {e}")
        return None


def analyze_wallets(
    input_file,
    output_file,
    index_db_path=None,
    progress_callback=None,
    checkpoint_path=None,
    processes=None,
):
    """
    Analyze files listed in the input file for cryptocurrency addresses.

    :param input_file: File containing paths of wallet files to analyze.
    :param output_file: File to save the analysis results.
    :param index_db_path: optional -- when given, skips the regex pass
        entirely for a file whose exact content has already been analyzed
        (by any prior scan, at any path), reusing its recorded result.
        Content-hash based, so a copy on a different drive/backup is
        recognized regardless of its current path. None (the default) is
        a complete no-op -- byte-identical to not having this parameter.
    :param progress_callback: optional callable(current, total, message).
        Unlike search_for_wallets, the file list here is already known
        (it's search's own output) -- real, determinate progress.
    :param checkpoint_path: optional -- makes a long analyze run resumable
        across an app quit/update/crash, backed by
        tools.checkpoint_store.CheckpointStore (the same design that fixed
        tonight's real search-checkpoint OOM), keyed on this exact
        input_file. A file already recorded completed -- this run or a
        prior interrupted one -- is never re-dispatched for analysis.
        Removed once analysis finishes cleanly. None (the default) is a
        complete no-op -- analyze had zero resume support before this.
    :param processes: optional -- when > 1, analyzes files concurrently
        via multiprocessing.Pool. Analyze is CPU-bound regex matching over
        file content, so Python threads provide no real parallelism here
        (GIL) -- multiprocessing is the first genuine multi-core use in
        this pipeline. None or 1 (the default) runs the original
        sequential loop, byte-identical to pre-multiprocessing behavior.
        Regardless of processes, every tools/scan_index.py read/write and
        every checkpoint_store.mark_completed() call happens in the main
        process only -- worker processes (see _analyze_one_file) return
        analysis results and nothing else, so scan_index.db never gets a
        concurrent writer.
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    wallet_analysis = {}

    with open(input_file, "r") as f:
        file_paths = [line.strip() for line in f.readlines()]

    store = None
    if checkpoint_path:
        store = CheckpointStore(str(checkpoint_path), run_key={"input_file": str(input_file)})

    total = len(file_paths)

    if processes and processes > 1:
        _analyze_wallets_parallel(
            file_paths, wallet_analysis, index_db_path, progress_callback, store, total, processes
        )
    else:
        _analyze_wallets_sequential(file_paths, wallet_analysis, index_db_path, progress_callback, store, total)

    if store:
        store.flush()

    # Save results to a JSON file
    with open(output_file, "w") as f:
        json.dump(wallet_analysis, f, indent=4)

    print(f"\nAnalysis complete. Results saved to {output_file}.")

    if store:
        store.delete()


def _analyze_wallets_sequential(file_paths, wallet_analysis, index_db_path, progress_callback, store, total):
    """
    The original loop, unchanged in every branch that existing callers
    (checkpoint_path=None, processes=None) already exercise -- only two
    additions, both no-ops unless a checkpoint store is actually in play:
    a resume-skip at the top of the loop, and a mark_completed() call
    alongside the existing record_scanned_file() call.
    """
    for i, file_path in enumerate(file_paths, start=1):
        if store and store.is_completed(file_path):
            progress_callback(i, total, file_path)
            continue

        if index_db_path is not None:
            content = _read_bytes(file_path)

            if content is not None:
                file_hash = hash_file_bytes(content)
                cached_result = is_known(file_hash, db_path=index_db_path)
                if cached_result is not None:
                    print(f"Already scanned (duplicate content): {file_path} -- reusing prior result")
                    if cached_result:
                        wallet_analysis[file_path] = cached_result
                    if store:
                        store.mark_completed(file_path)
                    progress_callback(i, total, file_path)
                    continue

        print(f"Analyzing file: {file_path}")
        file_results = analyze_wallet_file(file_path)
        if file_results:
            wallet_analysis[file_path] = file_results

        if index_db_path is not None and content is not None:
            record_scanned_file(file_hash, file_path, file_results, db_path=index_db_path)

        if store:
            store.mark_completed(file_path)
            if i % CHECKPOINT_EVERY_FILES == 0:
                store.flush()

        progress_callback(i, total, file_path)


def _analyze_wallets_parallel(file_paths, wallet_analysis, index_db_path, progress_callback, store, total, processes):
    """
    Resume (checkpoint_store.is_completed) and the content-hash dedup
    cache (scan_index.py's is_known) are both checked up front, in the
    main process, before anything is dispatched to the pool -- an
    already-analyzed file (from a prior run OR already cached) is never
    handed to a worker at all. Only files that genuinely need a fresh
    regex pass go into the pool; cache hits and resumed files are
    recorded here directly, identical in effect to the sequential path.
    """
    to_dispatch = []
    hashes = {}
    completed_count = 0

    for file_path in file_paths:
        if store and store.is_completed(file_path):
            completed_count += 1
            progress_callback(completed_count, total, file_path)
            continue

        if index_db_path is not None:
            content = _read_bytes(file_path)
            if content is not None:
                file_hash = hash_file_bytes(content)
                cached_result = is_known(file_hash, db_path=index_db_path)
                if cached_result is not None:
                    print(f"Already scanned (duplicate content): {file_path} -- reusing prior result")
                    if cached_result:
                        wallet_analysis[file_path] = cached_result
                    if store:
                        store.mark_completed(file_path)
                    completed_count += 1
                    progress_callback(completed_count, total, file_path)
                    continue
                hashes[file_path] = file_hash

        to_dispatch.append(file_path)

    if not to_dispatch:
        return

    with Pool(processes) as pool:
        for file_path, file_results in pool.imap_unordered(_analyze_one_file, to_dispatch):
            print(f"Analyzing file: {file_path}")
            if file_results:
                wallet_analysis[file_path] = file_results

            if index_db_path is not None and file_path in hashes:
                record_scanned_file(hashes[file_path], file_path, file_results, db_path=index_db_path)

            if store:
                store.mark_completed(file_path)
                if completed_count % CHECKPOINT_EVERY_FILES == 0:
                    store.flush()

            completed_count += 1
            progress_callback(completed_count, total, file_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze potential wallet files for crypto addresses.")
    parser.add_argument("input_file", help="File containing paths of wallet files to analyze.")
    parser.add_argument("output_file", help="File to save the analysis results.")
    args = parser.parse_args()

    analyze_wallets(args.input_file, args.output_file)
