import json
import importlib
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.wallet import WALLET_SERVICES
from tools.checkpoint_store import CheckpointPaused, CheckpointStore

MAX_BALANCE_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

# Concurrent requests allowed to one coin's API at once. Bounded (not
# unlimited) so a real public API like blockstream.info doesn't get
# hammered into rate-limiting or an IP ban -- but > 1, which is the whole
# point: a scan that's mostly one coin (the realistic case) used to run
# every one of that coin's addresses strictly one at a time, no matter how
# many were found.
#
# 15, not a round guess: blockstream.info's real public rate limit is
# ~50 req/s (shared across everyone using the public instance, not per-IP
# -- see github.com/Blockstream/esplora issues #449/#302), and a live
# benchmark (40 real addresses, 5 vs 10 vs 15 concurrent) showed 15 more
# than doubled throughput over 5 with zero increase in errors/inconclusive
# results. 15 leaves ~35 req/s of headroom for everyone else on the same
# public endpoint.
PER_COIN_MAX_CONCURRENCY = 15

# Hard cap on total worker threads regardless of how many addresses are
# queued -- per-coin semaphores already bound how many of those threads
# can do real work at once (PER_COIN_MAX_CONCURRENCY each); this just
# stops a single coin with thousands of addresses from spinning up
# thousands of mostly-blocked threads.
GLOBAL_MAX_WORKERS = 64

CHECKPOINT_EVERY_ADDRESSES = 20
CHECKPOINT_EVERY_SECONDS = 15

def load_service(crypto_name):
    """
    Dynamically load a wallet service for the given cryptocurrency.
    :param crypto_name: The name of the cryptocurrency (e.g., "Bitcoin Gold").
    :return: An instance of the wallet service class.
    """
    try:
        # Map crypto name to the corresponding module and class
        module_name = WALLET_SERVICES.get(crypto_name)
        if not module_name:
            raise ValueError(f"No service defined for cryptocurrency: {crypto_name}")

        module_path = f"services.{module_name}"
        # Convert to PascalCase for the class name
        class_name = "".join(word.capitalize() for word in module_name.split("_")) + "Service"

        # Dynamically import the module and load the class
        module = importlib.import_module(module_path)
        service_class = getattr(module, class_name)
        return service_class()
    except Exception as e:
        print(f"Error loading service for {crypto_name}: {e}")
        return None

def _check_balance_with_retries(service, address, max_retries=MAX_BALANCE_RETRIES, backoff_seconds=RETRY_BACKOFF_SECONDS):
    """
    Call service.check_balance(address), retrying while the result is None (the
    existing "couldn't confirm" signal every service returns on API/network
    failure). A confirmed float -- including 0.0 -- returns immediately without
    retrying. Never sleeps after the final attempt.

    :param service: A WalletService instance.
    :param address: The address to check.
    :param max_retries: Total attempts before giving up.
    :param backoff_seconds: Seconds to sleep between attempts.
    :return: The first non-None balance, or None if every attempt failed.
    """
    for attempt in range(1, max_retries + 1):
        balance = service.check_balance(address)
        if balance is not None:
            return balance
        if attempt < max_retries:
            time.sleep(backoff_seconds)
    return None


def _checkpoint_unit_id(crypto_name, file_path, address, balance):
    """
    Encodes a confirmed (non-None) balance into CheckpointStore's single
    opaque string primary key. CheckpointStore itself has no separate
    "value" column -- by design, it only ever needs to know whether a unit
    is done, never what a unit "means" (see its class docstring) -- so the
    balance has to travel inside unit_id for a resumed run to recover it
    without re-checking. Only ever called for a confirmed balance (see
    check_one()): the encoded value here is always a real number, never
    None -- inconclusive addresses are never marked completed at all, so
    they're retried on resume exactly like a never-checked address.
    """
    return f"{crypto_name}|{file_path}|{address}|{json.dumps(balance)}"


def _decode_checkpoint_unit_id(unit_id):
    """
    Inverse of _checkpoint_unit_id(). Splits off the balance from the
    *last* '|' -- json.dumps() of a float/int never itself contains '|',
    so this is unambiguous even though crypto_name/file_path/address are
    joined with that same separator without escaping (the same accepted
    risk already inherent to that three-way join).
    """
    identity, _, balance_json = unit_id.rpartition("|")
    crypto_name, file_path, address = identity.split("|", 2)
    return crypto_name, file_path, address, json.loads(balance_json)


def _load_resume_state(store):
    """
    One-time read of every confirmed unit a prior (possibly interrupted)
    run recorded against this same input_file -- cost proportional only
    to how many addresses were already confirmed, exactly like the old
    full-JSON checkpoint load this replaces. Called once at startup only,
    never from the per-address hot path (see check_one()'s flush cadence),
    so this does not reintroduce the growing per-flush write cost this
    story fixes -- it's a single read, not a repeated write.

    :return: (results_prepopulated, already_confirmed) where
        results_prepopulated is {file_path: {crypto_name: {address: balance}}}
        for every already-confirmed unit, and already_confirmed is the
        {(file_path, crypto_name, address)} set used to skip re-checking
        them -- the same two things the old JSON-backed checkpoint load
        built by hand from its "results" dict.
    """
    results_prepopulated = {}
    already_confirmed = set()
    rows = store.conn.execute(f"SELECT {store.unit_column} FROM {store.units_table}").fetchall()
    for (unit_id,) in rows:
        crypto_name, file_path, address, balance = _decode_checkpoint_unit_id(unit_id)
        results_prepopulated.setdefault(file_path, {}).setdefault(crypto_name, {})[address] = balance
        already_confirmed.add((file_path, crypto_name, address))
    return results_prepopulated, already_confirmed


def check_wallet_balances(
    input_file,
    output_file,
    coins_to_check=None,
    inconclusive_output=None,
    progress_callback=None,
    checkpoint_path=None,
    global_max_workers=GLOBAL_MAX_WORKERS,
    per_coin_max_concurrency=PER_COIN_MAX_CONCURRENCY,
    mount_health_check=None,
):
    """
    Check balances of wallet addresses for specified cryptocurrencies. Retries
    each address before giving up, and writes addresses that are still
    inconclusive after retries to a separate file rather than letting them
    silently disappear alongside confirmed-empty wallets.

    Every (coin, address) pair is its own task in one shared thread pool --
    concurrency happens at the address level, not just the coin level, with
    each coin's own tasks capped at PER_COIN_MAX_CONCURRENCY so one coin's
    API can't be hammered by an unbounded number of simultaneous requests.
    Different coins' tasks are fully independent of each other and always
    run concurrently regardless of that per-coin cap.

    :param input_file: Path to the input JSON file containing wallet addresses.
    :param output_file: Path to save the results as a JSON file.
    :param coins_to_check: List of cryptocurrencies to check. Defaults to all supported coins.
    :param inconclusive_output: Path to save addresses still inconclusive after
        retries. Defaults to "inconclusive_balances.json" next to output_file.
    :param progress_callback: Optional callable(current, total, message) invoked
        once per address checked. Defaults to a no-op -- every existing call
        site (CLI, tests) is unaffected by this parameter's presence.
    :param checkpoint_path: Optional -- makes a long balance check resumable
        across an app quit/update/crash, backed by
        tools.checkpoint_store.CheckpointStore (the same design that fixed
        search's and analyze's checkpoint OOM risk). Confirmed (non-None)
        balances are skipped on the next run against the same input_file;
        addresses still inconclusive after retries are retried rather than
        skipped, since a fresh run may succeed where a stale one didn't.
        Removed once the check finishes cleanly.
    :param global_max_workers: Hard cap on total worker threads regardless
        of how many addresses are queued. Defaults to GLOBAL_MAX_WORKERS
        (today's tuned value, 64) -- a caller that doesn't pass this sees
        no behavior change.
    :param per_coin_max_concurrency: Concurrent requests allowed to one
        coin's API at once. Defaults to PER_COIN_MAX_CONCURRENCY (today's
        tuned value, 15) -- a caller that doesn't pass this sees no
        behavior change.
    :param mount_health_check: optional callable() -> bool, checked at the
        same points a checkpoint flush already happens (sse-05: same
        cadence family as search_for_wallets' own mount_health_check, no
        new polling loop). None (the default) means "not mount-backed" --
        skipped entirely. When it returns False, whatever progress exists
        is flushed and this raises a clear error instead of finishing
        looking indistinguishable from a clean run.
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    # Use all configured coins if no specific list is provided
    if not coins_to_check:
        coins_to_check = list(WALLET_SERVICES.keys())

    if inconclusive_output is None:
        inconclusive_output = os.path.join(os.path.dirname(output_file), "inconclusive_balances.json")

    with open(input_file, "r") as f:
        wallet_data = json.load(f)

    results = {file_path: {} for file_path in wallet_data}
    inconclusive = {}

    store = None
    already_confirmed = set()  # {(file_path, crypto_name, address)}
    if checkpoint_path:
        store = CheckpointStore(str(checkpoint_path), run_key={"input_file": str(input_file)})
        results_prepopulated, already_confirmed = _load_resume_state(store)
        for file_path, coins in results_prepopulated.items():
            results.setdefault(file_path, {})
            for crypto_name, addresses in coins.items():
                results[file_path].setdefault(crypto_name, {}).update(addresses)

    # Every (coin, address) pair is its own task, grouped by coin only to
    # build a per-coin semaphore below -- "grouped by coin" no longer means
    # "one thread per coin."
    pairs_by_coin = {}
    for file_path, crypto_wallets in wallet_data.items():
        for crypto_name, addresses in crypto_wallets.items():
            if crypto_name not in coins_to_check:
                print(f"Skipping {crypto_name} as it is not in the specified list.")
                continue
            pairs_by_coin.setdefault(crypto_name, []).extend((file_path, address) for address in addresses)

    total_addresses = sum(len(pairs) for pairs in pairs_by_coin.values())
    checked_count = len(already_confirmed)
    if checked_count:
        print(f"Resuming balance check: {checked_count}/{total_addresses} address(es) already confirmed.")
    progress_lock = threading.Lock()

    last_checkpoint_at = time.time()

    remaining_by_coin = {}
    for crypto_name, pairs in pairs_by_coin.items():
        remaining = [(file_path, address) for file_path, address in pairs if (file_path, crypto_name, address) not in already_confirmed]
        if remaining:
            remaining_by_coin[crypto_name] = remaining

    services = {}
    for crypto_name in remaining_by_coin:
        print(f"Checking {crypto_name} wallets...")
        service = load_service(crypto_name)
        if service:
            services[crypto_name] = service
        else:
            print(f"  Skipping {crypto_name}: No valid service found.")

    semaphores = {
        crypto_name: threading.Semaphore(min(per_coin_max_concurrency, len(pairs)))
        for crypto_name, pairs in remaining_by_coin.items()
    }

    # sse-04: set only from inside check_one()'s own existing flush block,
    # right after store.flush() has already durably committed progress --
    # so nothing observing this afterward can be interrupted mid-write.
    # Checked at the very top of check_one(), before the per-coin
    # semaphore is even acquired, so once set, no NEW API request starts;
    # every check_one() call already past this point (mid network-request,
    # bounded by the per-coin semaphore) runs to completion normally,
    # confirmed pause semantics (structured-outline.md Q4): "let
    # in-flight work finish."
    paused_event = threading.Event()

    # sse-05: same idea as paused_event immediately above, one failure mode
    # later -- set only from inside check_one()'s own flush block, right
    # after store.flush() has already durably committed progress.
    mount_disconnected_event = threading.Event()

    def check_one(crypto_name, file_path, address):
        nonlocal checked_count, last_checkpoint_at

        if paused_event.is_set() or mount_disconnected_event.is_set():
            return

        service = services[crypto_name]
        with semaphores[crypto_name]:
            balance = _check_balance_with_retries(service, address)

        with progress_lock:
            results[file_path].setdefault(crypto_name, {})[address] = balance
            print(f"    {address}: {balance}")
            checked_count += 1
            progress_callback(checked_count, total_addresses, f"{crypto_name}: {address}")
            if balance is None:
                inconclusive.setdefault(file_path, {}).setdefault(crypto_name, []).append(address)
            elif store:
                # Only ever mark a CONFIRMED balance completed -- an
                # inconclusive address is deliberately never written to
                # the store at all, so it's retried on resume exactly
                # like a never-checked address (see _checkpoint_unit_id).
                store.mark_completed(_checkpoint_unit_id(crypto_name, file_path, address, balance))

            if store and (
                checked_count % CHECKPOINT_EVERY_ADDRESSES == 0 or time.time() - last_checkpoint_at >= CHECKPOINT_EVERY_SECONDS
            ):
                store.flush()
                last_checkpoint_at = time.time()
                if store.is_paused():
                    paused_event.set()
                # sse-05: same "no new polling loop" rule as search_for_wallets --
                # reuses this exact flush point. Only ever non-None for a
                # target under a currently-tracked mount.
                if mount_health_check is not None and not mount_health_check():
                    mount_disconnected_event.set()

    tasks = [
        (crypto_name, file_path, address)
        for crypto_name, pairs in remaining_by_coin.items()
        if crypto_name in services
        for file_path, address in pairs
    ]

    if tasks:
        with ThreadPoolExecutor(max_workers=min(len(tasks), global_max_workers)) as executor:
            futures = [executor.submit(check_one, crypto_name, file_path, address) for crypto_name, file_path, address in tasks]
            for future in as_completed(futures):
                future.result()  # re-raise any worker exception on the main thread

    if store:
        store.flush()

    if mount_disconnected_event.is_set():
        # Same "never delete the checkpoint" reasoning as a pause -- there
        # is something left to resume once the drive is reconnected, and
        # every confirmed balance up to this point is already durable in
        # the checkpoint store (flushed just above).
        print(f"Balance check stopped: drive disconnected. {checked_count}/{total_addresses} address(es) confirmed so far.")
        raise RuntimeError(f"drive disconnected mid-scan -- balance check stopped after {checked_count}/{total_addresses} address(es) confirmed")

    if paused_event.is_set():
        # No output_file/inconclusive_output write on a pause, and the
        # checkpoint is left in place -- unlike analyze's output_file,
        # this isn't a completeness concern: every confirmed balance is
        # already durable in the checkpoint store itself and gets
        # restored via _load_resume_state() the moment this same
        # checkpoint_path is resumed, so nothing found before the pause
        # is at risk of being lost.
        print(f"Balance check paused. {checked_count}/{total_addresses} address(es) confirmed so far.")
        raise CheckpointPaused(f"check_balances paused after {checked_count}/{total_addresses}")

    with open(output_file, "w") as f:
        json.dump(results, f, indent=4)

    print(f"Wallet balance check complete. Results saved to {output_file}.")

    if inconclusive:
        with open(inconclusive_output, "w") as f:
            json.dump(inconclusive, f, indent=4)
        print(f"{sum(len(a) for c in inconclusive.values() for a in c.values())} address(es) still inconclusive after retries. Saved to {inconclusive_output}.")

    if store:
        store.delete()

    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Check balances of wallet addresses.")
    parser.add_argument("input_file", help="Input JSON file containing wallet addresses.")
    parser.add_argument("output_file", help="Output JSON file for wallet balances.")
    parser.add_argument(
        "--coins",
        nargs="*",
        help="Optional list of cryptocurrencies to check (e.g., Bitcoin Ethereum). Defaults to all."
    )
    args = parser.parse_args()

    # If specific coins are passed, validate them against the config
    coins_to_check = args.coins if args.coins else list(WALLET_SERVICES.keys())
    invalid_coins = [coin for coin in coins_to_check if coin not in WALLET_SERVICES]
    if invalid_coins:
        print(f"Invalid cryptocurrencies specified: {invalid_coins}")
        print(f"Supported cryptocurrencies are: {list(WALLET_SERVICES.keys())}")
        exit(1)

    check_wallet_balances(args.input_file, args.output_file, coins_to_check)
