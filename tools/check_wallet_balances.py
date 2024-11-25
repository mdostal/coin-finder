import json
import importlib
import os
from pathlib import Path
from config.wallet import WALLET_SERVICES

def load_service(crypto_name):
    """
    Dynamically load a wallet service for the given cryptocurrency.
    :param crypto_name: The name of the cryptocurrency.
    :return: An instance of the wallet service.
    """
    try:
        module_name = WALLET_SERVICES.get(crypto_name)
        if not module_name:
            raise ValueError(f"No service defined for cryptocurrency: {crypto_name}")
        module_path = f"services.{module_name}"
        module = importlib.import_module(module_path)
        service_class = getattr(module, f"{module_name.capitalize()}Service")
        return service_class()
    except Exception as e:
        print(f"Error loading service for {crypto_name}: {e}")
        return None

def check_wallet_balances(input_file, output_file, coins_to_check=None):
    """
    Check balances of wallet addresses for specified cryptocurrencies.
    :param input_file: Path to the input JSON file containing wallet addresses.
    :param output_file: Path to save the results as a JSON file.
    :param coins_to_check: List of cryptocurrencies to check. Defaults to all supported coins.
    """
    # Use all configured coins if no specific list is provided
    if not coins_to_check:
        coins_to_check = list(WALLET_SERVICES.keys())

    with open(input_file, "r") as f:
        wallet_data = json.load(f)

    results = {}

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
                balance = service.check_balance(address)
                results[file_path][crypto_name][address] = balance
                print(f"    {address}: {balance}")

    with open(output_file, "w") as f:
        json.dump(results, f, indent=4)

    print(f"Wallet balance check complete. Results saved to {output_file}.")
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
