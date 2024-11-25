import requests
import json
import argparse
import time

# Define API URLs and keys for different cryptocurrencies
API_CONFIG = {
    "Bitcoin": {
        "url": "https://blockstream.info/api/address/{address}",
        "balance_field": "chain_stats",
        "sub_field": None,  # We calculate balance from funded and spent sums
    },
    "Ethereum": {
        "url": "https://api.etherscan.io/api",
        "params": {
            "module": "account",
            "action": "balance",
            "address": "{address}",
            "tag": "latest",
            "apikey": "NK2SZABRZS5VV1HU4WG1KXIZMVNYHBSUUS",
        },
        "balance_field": "result",  # In wei
    },
    "Litecoin": {
        "url": "https://api.blockcypher.com/v1/ltc/main/addrs/{address}/balance",
        "balance_field": "final_balance",  # In litoshis
    },
    "Dogecoin": {
        "url": "https://sochain.com/api/v2/get_address_balance/DOGE/{address}",
        "balance_field": "data",
        "sub_field": "confirmed_balance",  # In DOGE
    },
}

# Function to fetch balance from an API
def fetch_balance(crypto, address):
    config = API_CONFIG[crypto]
    url = config["url"].format(address=address)

    # Handle additional parameters for APIs like Etherscan
    if "params" in config:
        params = {k: (v.format(address=address) if "{address}" in v else v) for k, v in config["params"].items()}
        response = requests.get(url, params=params)
    else:
        response = requests.get(url)

    if response.status_code != 200:
        print(f"Error fetching data for {crypto} address {address}: {response.text}")
        return None

    data = response.json()
    try:
        if crypto == "Bitcoin":
            # Calculate remaining balance for Bitcoin
            funded = data["chain_stats"]["funded_txo_sum"]
            spent = data["chain_stats"]["spent_txo_sum"]
            balance = (funded - spent) / (10 ** 8)  # Convert from satoshis to BTC
            return balance
        elif crypto == "Ethereum":
            # Ethereum balance in wei, converted to ETH
            return float(data.get(config["balance_field"])) / (10 ** 18)
        elif crypto == "Litecoin":
            # Litecoin balance in litoshis, converted to LTC
            return float(data.get(config["balance_field"])) / (10 ** 8)
        elif crypto == "Dogecoin":
            # Dogecoin balance in DOGE
            return float(data.get(config["balance_field"]).get(config["sub_field"]))
    except Exception as e:
        print(f"Error parsing data for {crypto} address {address}: {e}")
        return None

def check_wallet_balances(wallet_file, output_file):
    with open(wallet_file, "r") as f:
        wallet_data = json.load(f)

    results = {}

    for file_path, wallets in wallet_data.items():
        print(f"\nChecking wallets from file: {file_path}")
        results[file_path] = {}

        for crypto, addresses in wallets.items():
            print(f"  Checking {crypto} wallets...")
            results[file_path][crypto] = {}

            for address in addresses:
                print(f"    Checking address: {address}")
                balance = fetch_balance(crypto, address)
                if balance is not None:
                    print(f"      Balance: {balance} {crypto}")
                else:
                    print(f"      Failed to fetch balance for {address}")
                results[file_path][crypto][address] = balance
                time.sleep(1)  # Avoid rate limits

    # Save results to the output file
    with open(output_file, "w") as f:
        json.dump(results, f, indent=4)

    print(f"\nCheck complete. Results saved to {output_file}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check balances of wallet addresses on the blockchain.")
    parser.add_argument("wallet_file", help="Input JSON file containing wallet addresses.")
    parser.add_argument("output_file", help="Output JSON file for saving results.")
    args = parser.parse_args()

    check_wallet_balances(args.wallet_file, args.output_file)