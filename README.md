
# Cryptocurrency Wallet Pipeline

---

## Overview

This project is a modular pipeline designed to **discover cryptocurrency wallet files**, **analyze them for wallet addresses**, and **check balances for supported cryptocurrencies**. It supports a growing list of cryptocurrencies and is designed for extensibility, allowing easy integration of new coins and processes.

---

## Why?

If anyone is like me and happens to stash crypto coins like a squirrel stashes nuts... often forgetting where they are.... I've created a toolset to help find wallets, check them for coins, and filter the files down to reasonable ones based on what it found on the corresponding blockchain,

The wallet tools I found out there just didn't match up to what I needed them to do and the ones that did often pulled in a number of 3rd party libs that I'd want to check to see if they were trojans (or they straight up had no source code and just an executable that I'm certain was malware).

So, here's a thing!

If you like it and want to support me making community tools, here are some options:

- Star the repo
- Tweet about it

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mdostal)

Feel free to reach out if you have any questions or suggestions! (Or if you'd like to see this as a single downloadable executable)

## File Structure

```plaintext
project/
├── config/                   # Configuration files for search, analysis, and wallet services
│   ├── search.py      # Config for file extensions and keywords to find wallet files
│   ├── analyze.py     # Regex patterns for detecting wallet addresses
│   ├── wallet.py      # Maps cryptocurrencies to their respective service modules
├── services/                 # Individual wallet services for each cryptocurrency
│   ├── __init__.py           # Base WalletService class
│   ├── bitcoin.py            # Bitcoin wallet service
│   ├── ethereum.py           # Ethereum wallet service
│   ├── ripple.py             # Ripple wallet service
│   ├── ... (other services)  # Add additional wallet services here
├── tools/                     # Tools for pipeline stages
│   ├── search_wallets.py     # Finds potential wallet files
│   ├── analyze_wallets.py    # Analyzes files for wallet addresses
│   ├── check_wallet_balances.py  # Checks balances for wallet addresses
├── .env.sample               # Sample env file for API keys (not committed with real values)
├── requirements.txt          # Python dependencies
├── run_pipeline.py           # Orchestrates the entire pipeline
---
```

## Tools

### **1. Search Tool (`search_wallets.py`)**
- **Purpose**: Searches for files that may contain cryptocurrency wallets.
- **How it works**:
  - Uses predefined extensions and keywords from `config/search_config.py`.
  - Recursively scans a directory and outputs a list of potential wallet files.
- **Usage**:
  ```bash
  python tool/search_wallets.py <start_path> <output_file>
  ```
**Example**:
  ```bash
  python tool/search_wallets.py ./wallets ./output/wallet_search_output.txt
  ```

--- 


### 2. Analyze Tool (`analyze_wallets.py`)

- **Purpose**: Analyzes the identified files for cryptocurrency wallet addresses.
- **How it works**:
  - Uses regex patterns defined in `config/analyze_config.py` to detect wallet addresses.
  - Processes files line by line or as binary data to extract addresses.
- **Usage**:
```bash
  python tool/analyze_wallets.py <input_file> <output_file>
```

**Example**:
```bash
  python tool/analyze_wallets.py ./output/wallet_search_output.txt ./output/wallet_analysis.json
```

---

### 3. Wallet Checker Tool (`check_wallet_balances.py`)

- **Purpose**: Checks balances for wallet addresses extracted during analysis.
- **How it works**:
- Dynamically loads services for each cryptocurrency based on `config/wallet_config.py`.
- Fetches balances using APIs or node integrations for each coin.
- Supports filtering coins via the `--coins` argument.
- **Usage**:

```bash
python tool/check_wallet_balances.py <input_file> <output_file> [--coins <coin1> <coin2> ...]
```

**Example**:
```bash
python tool/analyze_wallets.py ./output/wallet_search_output.txt ./output/wallet_analysis.json
```

## Pipeline Overview

### Search
Identifies potential wallet files in a specified directory.

### Analyze
Extracts wallet addresses from the identified files.

### Check Balances
Fetches the balances for the extracted wallet addresses.

### Output
Generates JSON files at each stage for traceability and easy debugging.

---

## Supported Cryptocurrencies
# Supported Cryptocurrencies

| Cryptocurrency       | Address Format (Regex)                                                                                   | API Provider For Checker               |
|-----------------------|---------------------------------------------------------------------------------------------------------|---------------------------------------|
| **Bitcoin (BTC)**     | `1[a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[q|p|z][a-zA-HJ-NP-Z0-9]{38,64}`                                        | Blockstream API                       |
| **Bitcoin Cash (BCH)**| `bitcoincash:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{42}`                                                     | Blockchair                            |
| **Bitcoin Gold (BTG)**| `[AG][a-km-zA-HJ-NP-Z1-9]{26,33}`                                                                       | Blockchair                            |
| **Cosmos (ATOM)**     | `cosmos1[a-z0-9]{38}`                                                                                   | Mintscan                              |
| **Ethereum (ETH)**    | `0x[a-fA-F0-9]{40}`                                                                                     | Etherscan API                         |
| **Ethereum Classic**  | `0x[a-fA-F0-9]{40}`                                                                                     | Blockscout                            |
| **Dogecoin (DOGE)**   | `D{1}[5-9A-HJ-NP-U]{1}[1-9A-HJ-NP-Za-km-z]{32}`                                                         | SoChain API                           |
| **Shiba Inu (SHIB)**  | `0x[a-fA-F0-9]{40}`                                                                                     | Etherscan API                         |
| **Litecoin (LTC)**    | `[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}`                                                                      | Blockcypher API                       |
| **Ripple (XRP)**      | `r[1-9A-HJ-NP-Za-km-z]{25,35}`                                                                          | XRPL.org                              |
| **IOTA (MIOTA)**      | `[A-Z9]{81}`                                                                                           | IOTA Tangle Explorer                  |
| **Tether (USDT)**     | `0x[a-fA-F0-9]{40}` (Ethereum) or `1[a-km-zA-HJ-NP-Z1-9]{25,34}` (Bitcoin Omni Layer)                   | Etherscan or Omni Explorer            |
| **Helium (HNT)**      | `13[a-zA-Z0-9]{45,48}`                                                                                 | Helium Explorer                       |
| **Cardano (ADA)**     | `addr[a-z0-9]{58,90}`                                                                                  | Blockfrost API                        |
| **Zcash (ZEC)**       | `t[1-9A-HJ-NP-Za-km-z]{34}`                                                                            | Zcash Explorer                        |
| **OKCash (OK)**       | `[0-9A-Za-z]{34}`                                                                                      | OKCash Blockchain Explorer            |
| **Binance Coin (BNB)**| `bnb[a-z0-9]{38}`                                                                                      | Binance Explorer                      |
| **Monero (XMR)**      | `[48]{1}[0-9AB][1-9A-HJ-NP-Za-km-z]{93}`        

---

## Configuration

### 1. Search Config (`config/search.py`)

- **Purpose**: Specifies file extensions and keywords to search for potential wallet files.
- **Example**:
  ```python
  WALLET_EXTENSIONS = [".dat", ".key", ".wallet", ".json", ".backup"]
  WALLET_KEYWORDS = ["wallet", "crypto", "bitcoin", "ethereum", "backup"]
  ```
  ---

### 2. Analyze Config (`config/analyze.py`)
- **Purpose**: Specifies file extensions and keywords to search for potential wallet files.
- **Example**:
  ```python
  WALLET_EXTENSIONS = [".dat", ".key", ".wallet", ".json", ".backup"]
  WALLET_KEYWORDS = ["wallet", "crypto", "bitcoin", "ethereum", "backup"]
  ```
  ---

### 3. Analyze Config (`config/analyze.py`)
- **Purpose**: Specifies file extensions and keywords to search for potential wallet files.
- **Example**:
  ```python
  WALLET_EXTENSIONS = [".dat", ".key", ".wallet", ".json", ".backup"]
  WALLET_KEYWORDS = ["wallet", "crypto", "bitcoin", "ethereum", "backup"]
  ```
  ---
  
## Environment Setup

### Required Environment Variables

### **`.env` File**:
```python
ETHERSCAN_API_KEY=your_etherscan_api_key 
BLOCKFROST_API_KEY=your_blockfrost_api_key
```


---

## Changes With and Without Environment Setup

- **With Environment Setup**:
  - APIs requiring authentication (e.g., Etherscan, Blockfrost) work seamlessly.
- **Without Environment Setup**:
  - Tools dependent on API keys will fail, displaying appropriate error messages.

---

## Failsafes

1. **Invalid Coins**:
   - If unsupported coins are passed via `--coins`, the tool reports them and exits gracefully.

2. **API Errors**:
   - If an API call fails (e.g., rate limits, connectivity), the script logs the error and skips that address.

3. **File Processing Errors**:
   - If a file cannot be read (e.g., permission issues), the error is logged, and processing continues.

4. **Empty Results**:
   - If no wallets or balances are found, the output files are still created but remain empty.

---

## Adding New Coins

### Extend `wallet_config.py`

- Add the new cryptocurrency and its corresponding service file:
```python
  WALLET_SERVICES["NewCoin"] = "newcoin"
```

**Example**:
```python
WALLET_SERVICES = {
    "Binance Coin": "binance_coin",
    "Bitcoin": "bitcoin",
    "Cardano": "cardano",
    "Dogecoin": "dogecoin",
    "Ethereum": "ethereum",
    "Litecoin": "litecoin",
    "Monero": "monero",
    "Ripple": "ripple",
    "Shiba Inu": "ethereum",
    "Tether": "ethereum",
}
```

### Implement Service

- Implement the service for the new cryptocurrency.

  Create the Service
Create services/newcoin.py and implement the WalletService interface:

```python
from . import WalletService

class NewCoinService(WalletService):
    def check_balance(self, address):
        # Implement API or node integration to fetch balance
        pass
```
### Add Patterns (if needed) 
Add regex patterns for the new coin in analyze_config.py.
```python
CRYPTO_PATTERNS["NewCoin"] = r"regex_pattern_for_new_coin"
```
**Example**:
```python
CRYPTO_PATTERNS = {
    "Bitcoin": r"(1[a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[q|p|z][a-zA-HJ-NP-Z0-9]{38,64})",
    "Bitcoin Cash": r"bitcoincash:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{42}",
}
```
