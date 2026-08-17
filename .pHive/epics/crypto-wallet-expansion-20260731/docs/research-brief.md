# Research Brief: Crypto Wallet Finder Expansion

**Epic**: crypto-wallet-expansion-20260731  
**Date**: 2026-07-31  
**Codebase**: /Users/dostal/.minerva/runs/fa860023-de89-4c57-bb9a-77538a50756e/workspace

## Current State Analysis

### Architecture Overview

The project follows a **modular pipeline architecture** with three distinct stages:

1. **Search** (`tools/search_wallets.py`) - Discovers potential wallet files by extension, keyword, and coin name
2. **Analyze** (`tools/analyze_wallets.py`) - Extracts cryptocurrency addresses using regex patterns
3. **Check** (`tools/check_wallet_balances.py`) - Queries blockchain APIs for current balances

### Core Components

**Service Layer** (`services/`):
- 20+ cryptocurrency services inheriting from base `WalletService`
- Each service implements `check_balance(address)` method
- Dynamic loading via `importlib` based on `config/wallet.py` mappings
- Examples: Bitcoin (Blockstream), Ethereum (Etherscan), Dogecoin (SoChain)

**Configuration** (`config/`):
- `search.py` - File extensions (.dat, .key, .wallet, .json, .backup), keywords, coin names, file size constraints (1 byte - 45 MB)
- `analysis.py` - 20+ regex patterns for address detection per cryptocurrency
- `wallet.py` - Maps crypto names to service module names

**Pipeline Orchestration**:
- `run_pipeline.py` - Executes all three stages sequentially
- JSON output at each stage for traceability
- Command-line tools can run stages independently

### Supported Cryptocurrencies (20+)

Bitcoin, Bitcoin Cash, Bitcoin Gold, Ethereum, Ethereum Classic, Litecoin, Dogecoin, Ripple/XRP, Monero, Zcash, Cardano, Cosmos, Binance Coin, Tether, Shiba Inu, IOTA, Helium, OKCash, Diamond Coin (DMD), Digibyte

### Key Technical Patterns

1. **Regex-based address extraction** - Pattern matching on binary file content with error tolerance
2. **API integration** - REST APIs for balance checking (Blockstream, Etherscan, SoChain, etc.)
3. **Error resilience** - Try-catch blocks with logging, continues on individual failures
4. **File filtering** - Size constraints to avoid scanning large non-wallet files
5. **Deduplication** - Set-based deduplication of extracted addresses

### Pain Points & Limitations

**Current Limitations**:
- **No transaction history** - Only current balance, no historical data
- **No wallet relationships** - Cannot trace linked wallets or transaction flows
- **No metadata capture** - File creation dates, modification times not stored
- **Single-direction only** - Can find wallets → addresses → balances, but cannot reverse
- **No persistence layer** - Results stored only in JSON files, no database
- **CLI-only interface** - No web UI or dashboard
- **Limited filtering** - Cannot filter by timeframe, balance threshold, or transaction count

**API Constraints**:
- Rate limiting on free-tier APIs (Etherscan, Blockfrost)
- Some coins lack public explorers with full transaction APIs
- No authentication for most services (relying on public endpoints)

## Requirement Analysis

### 1. Reverse Wallet Tracking & Transaction History

**Goal**: Given a known wallet address, trace backward N hops to find:
- Wallets that sent funds to this address
- Wallets that received funds from this address  
- Transaction amounts, timestamps, and block numbers
- Linked wallet clusters (multi-hop analysis)

**Technical Requirements**:
- Transaction history API integration for each supported coin
- Graph traversal algorithm (BFS/DFS) for N-hop discovery
- Transaction storage (database or structured cache)
- Deduplication & cycle detection for wallet graphs
- Filtering by date range, minimum transaction value

**API Extensions Needed**:
- Bitcoin: Blockstream `/address/{addr}/txs` endpoint
- Ethereum: Etherscan `/api?module=account&action=txlist`
- Other coins: Explorer APIs vary (some lack full TX history)

**Data Model**:
```
Wallet
  - address
  - coin_type
  - first_seen (timestamp)
  - last_active (timestamp)
  
Transaction
  - tx_hash
  - from_address
  - to_address
  - amount
  - timestamp
  - block_number
  - coin_type

WalletLink
  - wallet_a
  - wallet_b
  - relationship_type (sent_to, received_from)
  - transaction_count
  - total_value
```

### 2. Enhanced Discovery with Metadata

**Goal**: Augment search results with:
- File creation/modification timestamps
- File size and location
- Search by date range (e.g., wallets created 2020-2022)
- Confidence scoring for wallet file identification

**Technical Requirements**:
- Extract file metadata via `os.stat()` (ctime, mtime, size)
- Store metadata alongside wallet analysis results
- Add filtering parameters to search tool
- Implement confidence scoring (extension match + keyword + coin name = higher confidence)

**Implementation**:
- Extend `search_for_wallets()` to capture `Path.stat()` data
- Add `--created-after`, `--created-before` CLI flags
- Store in structured format (SQLite or enhanced JSON schema)

### 3. Plugin Architecture & Dashboard Integration

**Goal**: Transform into a plugin-based system integrated with "gig radar" and allergy tools under unified dashboard

**Plugin Architecture Requirements**:
- **Plugin interface** - Standardized API for wallet discovery tools
- **Event bus** - Communication between plugins (e.g., wallet found → trigger balance check)
- **Configuration management** - Per-plugin settings, API keys, enabled/disabled state
- **Data sharing** - Shared data layer accessible to all plugins

**Dashboard Requirements**:
- **Web UI framework** - Flask/FastAPI backend + React/Vue frontend
- **Wallet visualization** - Display wallet files, addresses, balances, transaction graphs
- **Multi-plugin view** - Tabbed or sidebar navigation for wallet, gig radar, allergy tools
- **Real-time updates** - WebSocket support for live balance monitoring
- **Export capabilities** - CSV/JSON download of results

**Integration Touchpoints**:
- Shared authentication/user management
- Unified configuration file format
- Common database schema for cross-plugin queries
- Shared API client pool for rate limiting

## Technical Stack Assessment

**Current Stack**:
- Python 3.x
- `requests` for HTTP
- `re` for pattern matching
- `json` for data serialization
- `dotenv` for environment variables
- `argparse` for CLI

**Recommended Additions**:
- **Database**: SQLite (for single-user) or PostgreSQL (for multi-user)
- **ORM**: SQLAlchemy for data modeling
- **Web framework**: FastAPI (async, type hints, auto docs)
- **Frontend**: React + Recharts (for transaction graphs)
- **Task queue**: Celery (for background balance checks & transaction syncing)
- **Caching**: Redis (for API response caching & rate limit management)
- **Graph library**: NetworkX (for wallet relationship analysis)

## Architectural Recommendations

### Phase 1: Foundation (Reverse Tracking Core)

1. **Database layer** - SQLite schema for wallets, transactions, links
2. **Transaction history module** - New `services/base.py` method `get_transactions(address)`
3. **Graph traversal service** - `tools/trace_wallet_relationships.py`
4. **Extended service implementations** - Add TX history to top 5 coins (BTC, ETH, LTC, XRP, DOGE)

### Phase 2: Enhanced Discovery & Metadata

1. **Metadata capture** - Extend search tool with file stats
2. **Enhanced storage** - Upgrade JSON outputs to SQLite
3. **Advanced filtering** - Date range, confidence score, balance threshold filters
4. **CLI improvements** - Rich output formatting, progress bars

### Phase 3: Plugin Architecture

1. **Plugin interface design** - `BasePlugin` class with standard hooks
2. **Event system** - Simple pub/sub for plugin communication
3. **Configuration management** - YAML-based plugin config
4. **Refactor existing code** - Convert pipeline to plugin pattern

### Phase 4: Dashboard Integration

1. **API layer** - FastAPI backend exposing wallet data
2. **Frontend scaffold** - React app with routing
3. **Visualization components** - Wallet list, balance charts, transaction graph
4. **Multi-plugin integration** - Plugin registry, navigation, shared state

## Risk Factors

**API Dependencies**:
- Public explorers may change endpoints or impose stricter rate limits
- Some coins have unreliable or missing transaction history APIs
- Mitigation: Fallback to local node queries for critical coins, implement exponential backoff

**Performance**:
- N-hop traversal can explode combinatorially (wallet with 1000 TXs → 1000 wallets → 1M TXs)
- Mitigation: Configurable hop limit (default 2-3), transaction count cap per wallet, pagination

**Data Volume**:
- Bitcoin wallets can have thousands of transactions
- Mitigation: Incremental loading, background sync jobs, date range filtering

**Security**:
- Storing wallet addresses creates privacy risk
- Mitigation: Local-only storage (no cloud sync), optional encryption, clear data retention policy

## Existing Patterns to Preserve

✅ **Modular service design** - Each coin is isolated, easy to add new coins  
✅ **Dynamic loading** - Config-driven service instantiation  
✅ **Error resilience** - Graceful degradation on API failures  
✅ **CLI-first design** - Tools work independently, composable  
✅ **Regex-based extraction** - Robust pattern matching with fallback

## External Dependencies

**New API Integrations**:
- Blockstream: `/address/{addr}/txs` (Bitcoin transaction history)
- Etherscan: `/api?module=account&action=txlist` (Ethereum TXs)
- XRP Ledger: `/api/v1/accounts/{addr}/transactions` (Ripple TXs)
- Blockcypher: `/addrs/{addr}/full` (Litecoin/Dogecoin TXs)

**Required API Keys** (extend `.env`):
```
ETHERSCAN_API_KEY=existing
BLOCKFROST_API_KEY=existing
BLOCKCYPHER_API_KEY=new_required
XRPL_API_KEY=optional (public endpoints available)
```

## Inconsistency Risk Signals

⚠️ **Config duplication** - Coin names appear in both `search.py` and `wallet.py`, potential mismatch  
⚠️ **Regex reliability** - OKCash pattern `[0-9A-Za-z]{34}` is too broad, may false-positive  
⚠️ **Service naming** - `"Shiba Inu": "shiba"` but pattern reuses Ethereum (both are ERC-20)  
⚠️ **File size limits** - 45 MB cap targets Helium but may exclude large multi-wallet files  
⚠️ **No test coverage** - No unit tests found, regex patterns unvalidated against known addresses

## Conclusion

The existing codebase provides a **solid foundation** for expansion:
- Clean separation of concerns (search → analyze → check)
- Extensible service architecture
- 20+ coins already supported
- Robust error handling

The expansion to **reverse tracking** requires:
- Database layer (major architectural change)
- Transaction history APIs (20+ integrations)
- Graph traversal logic (new complexity)

The **plugin architecture & dashboard** are orthogonal features that can be developed in parallel with reverse tracking or sequentially depending on priorities.

**Recommended approach**: Incremental vertical slices, starting with reverse tracking for Bitcoin only, validating the data model and graph traversal, then expanding to other coins and finally integrating the dashboard.
