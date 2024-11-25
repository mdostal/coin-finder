
# Cryptocurrency Wallet Pipeline

---

## Overview

This project is a modular pipeline designed to **discover cryptocurrency wallet files**, **analyze them for wallet addresses**, and **check balances for supported cryptocurrencies**. It supports a growing list of cryptocurrencies and is designed for extensibility, allowing easy integration of new coins and processes.

---

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

| Cryptocurrency    | Service File      | Address Format (Regex)                                                                                     | API/Method for Balance Check                                 |
|--------------------|-------------------|-----------------------------------------------------------------------------------------------------------|-------------------------------------------------------------|
| Bitcoin (BTC)      | `bitcoin.py`      | `1[a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[q|p|z][a-zA-HJ-NP-Z0-9]{38,64}`                                          | Blockstream API                                             |
| Ethereum (ETH)     | `ethereum.py`     | `0x[a-fA-F0-9]{40}`                                                                                       | Etherscan API                                               |
| Ripple (XRP)       | `ripple.py`       | `r[1-9A-HJ-NP-Za-km-z]{25,35}`                                                                            | Ripple API                                                  |
| Litecoin (LTC)     | `litecoin.py`     | `[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}`                                                                        | Blockcypher API                                             |
| Dogecoin (DOGE)    | `dogecoin.py`     | `D{1}[5-9A-HJ-NP-U]{1}[1-9A-HJ-NP-Za-km-z]{32}`                                                           | SoChain API                                                 |
| Monero (XMR)       | `monero.py`       | `[48]{1}[0-9AB][1-9A-HJ-NP-Za-km-z]{93}`                                                                  | Monero Blocks API                                           |
| Cardano (ADA)      | `cardano.py`      | `addr[a-z0-9]{58,90}`                                                                                     | Blockfrost API                                              |
| Binance Coin (BNB) | `binance_coin.py` | `bnb[a-z0-9]{38}`                                                                                         | Binance Explorer API                                        |
| Shiba Inu (SHIB)   | `ethereum.py`     | `0x[a-fA-F0-9]{40}`                                                                                       | Etherscan API                                               |

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
  
  # Environment Setup

## Required Environment Variables

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

# Failsafes

1. **Invalid Coins**:
   - If unsupported coins are passed via `--coins`, the tool reports them and exits gracefully.

2. **API Errors**:
   - If an API call fails (e.g., rate limits, connectivity), the script logs the error and skips that address.

3. **File Processing Errors**:
   - If a file cannot be read (e.g., permission issues), the error is logged, and processing continues.

4. **Empty Results**:
   - If no wallets or balances are found, the output files are still created but remain empty.

---

# Adding New Coins

## Extend `wallet_config.py`

- Add the new cryptocurrency and its corresponding service file:
  ```python
  WALLET_SERVICES["NewCoin"] = "newcoin"

  Create the Service
Create services/newcoin.py and implement the WalletService interface:
python
Copy code
from . import WalletService

class NewCoinService(WalletService):
    def check_balance(self, address):
        # Implement API or node integration to fetch balance
        pass
Add Patterns (if needed)
Add regex patterns for the new coin in analyze_config.py.
python
Copy code
CRYPTO_PATTERNS["NewCoin"] = r"regex_pattern_for_new_coin"
