import json
import importlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.wallet import WALLET_SERVICES

MAX_BALANCE_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

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


def check_wallet_balances(input_file, output_file, coins_to_check=None, inconclusive_output=None):
    """
    Check balances of wallet addresses for specified cryptocurrencies. Retries
    each address before giving up, and writes addresses that are still
    inconclusive after retries to a separate file rather than letting them
    silently disappear alongside confirmed-empty wallets.
    :param input_file: Path to the input JSON file containing wallet addresses.
    :param output_file: Path to save the results as a JSON file.
    :param coins_to_check: List of cryptocurrencies to check. Defaults to all supported coins.
    :param inconclusive_output: Path to save addresses still inconclusive after
        retries. Defaults to "inconclusive_balances.json" next to output_file.
    """
    # Use all configured coins if no specific list is provided
    if not coins_to_check:
        coins_to_check = list(WALLET_SERVICES.keys())

    if inconclusive_output is None:
        inconclusive_output = os.path.join(os.path.dirname(output_file), "inconclusive_balances.json")

    with open(input_file, "r") as f:
        wallet_data = json.load(f)

    results = {}
    inconclusive = {}

    for file_path, crypto_wallets in wallet_data.items():
        results[file_path] = {}

        for crypto_name, addresses in crypto_wallets.items():
            if crypto_name not in coins_to_check:
                print(f"Skipping {crypto_name} as it is not in the specified list.")
                continue

            print(f"Checking {crypto_name} wallets...")
            service = load_service(crypto_name)
            if not service:
                print(f"  Skipping {crypto_name}: No valid service found.")
                continue

            results[file_path][crypto_name] = {}
            for address in addresses:
                balance = _check_balance_with_retries(service, address)
                results[file_path][crypto_name][address] = balance
                print(f"    {address}: {balance}")

                if balance is None:
                    inconclusive.setdefault(file_path, {}).setdefault(crypto_name, []).append(address)

    with open(output_file, "w") as f:
        json.dump(results, f, indent=4)

    print(f"Wallet balance check complete. Results saved to {output_file}.")

    if inconclusive:
        with open(inconclusive_output, "w") as f:
            json.dump(inconclusive, f, indent=4)
        print(f"{sum(len(a) for c in inconclusive.values() for a in c.values())} address(es) still inconclusive after retries. Saved to {inconclusive_output}.")

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
