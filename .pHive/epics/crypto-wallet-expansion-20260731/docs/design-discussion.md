# Design Discussion: Crypto Wallet Finder Expansion

**Epic**: crypto-wallet-expansion-20260731  
**Date**: 2026-07-31

## §0 Prelude

### Research Context

The existing coin-finder codebase implements a three-stage pipeline (search → analyze → check balances) supporting 20+ cryptocurrencies with regex-based address extraction and API balance checking. The architecture is modular with dynamic service loading and CLI-first design.

**Key Strengths**: Clean separation of concerns, extensible service pattern, robust error handling.

**Key Limitations**: No transaction history, no wallet relationship mapping, no persistence layer beyond JSON files, no web UI.

## §1 Goal

Transform coin-finder from a **single-direction balance checker** into a **comprehensive wallet discovery and analysis platform** with:

1. **Reverse transaction tracking** - Trace wallet relationships N hops backward/forward through transaction history
2. **Enhanced metadata discovery** - Capture file timestamps, enable date-range filtering, confidence scoring
3. **Plugin architecture** - Modular design enabling integration with other tools (gig radar, allergy tracker)
4. **Unified dashboard** - Web UI for visualization, multi-tool navigation, transaction graph rendering

**Success Criteria**:
- Can trace Bitcoin wallet relationships 2-3 hops deep
- Can filter wallet discovery by file creation date range
- Plugin system supports at least 3 tools (wallet finder, gig radar, allergy)
- Dashboard displays transaction graphs and cross-tool data

## §2 Proposed Approach

### 2.1 Database Layer (Foundation)

**Decision**: Migrate from JSON files to SQLite for persistence.

**Rationale**:
- Transaction history and wallet graphs require relational queries
- Date-range filtering needs indexed timestamps
- Multi-plugin architecture needs shared data layer
- SQLite requires no external dependencies, suitable for single-user deployment

**Schema** (core entities):
```sql
CREATE TABLE wallets (
  address TEXT PRIMARY KEY,
  coin_type TEXT NOT NULL,
  balance REAL,
  first_seen TIMESTAMP,
  last_updated TIMESTAMP,
  metadata_json TEXT  -- file path, confidence score, etc.
);

CREATE TABLE transactions (
  tx_hash TEXT NOT NULL,
  coin_type TEXT NOT NULL,
  from_address TEXT,
  to_address TEXT,
  amount REAL,
  fee REAL,
  timestamp TIMESTAMP,
  block_number INTEGER,
  PRIMARY KEY (tx_hash, coin_type)
);

CREATE TABLE wallet_links (
  wallet_a TEXT,
  wallet_b TEXT,
  relationship_type TEXT,  -- 'sent_to', 'received_from'
  transaction_count INTEGER,
  total_value REAL,
  first_tx TIMESTAMP,
  last_tx TIMESTAMP,
  PRIMARY KEY (wallet_a, wallet_b, relationship_type)
);
```

**Migration Path**:
- Phase 1: Add SQLite alongside existing JSON outputs (dual-write)
- Phase 2: Migrate tools to read from DB, deprecate JSON inputs
- Phase 3: Remove JSON I/O code

### 2.2 Transaction History Module

**Extend `WalletService` base class**:
```python
class WalletService:
    def check_balance(self, address):
        # existing
    
    def get_transactions(self, address, limit=100, offset=0):
        """Fetch transaction history for address."""
        raise NotImplementedError
    
    def get_transaction_detail(self, tx_hash):
        """Fetch details of a specific transaction."""
        raise NotImplementedError
```

**Implementation Priority** (top 5 coins by market cap & user likelihood):
1. Bitcoin - Blockstream `/address/{addr}/txs`
2. Ethereum - Etherscan `/api?module=account&action=txlist`
3. Litecoin - Blockcypher `/addrs/{addr}/full`
4. Ripple - XRPL `/api/v1/accounts/{addr}/transactions`
5. Dogecoin - SoChain `/address/{network}/{addr}`

**Caching Strategy**:
- Transactions are immutable once confirmed → cache indefinitely
- Only fetch TXs newer than `last_updated` timestamp on subsequent syncs
- Store raw API responses in `transaction_cache` table for debugging

### 2.3 Graph Traversal Service

**New Tool**: `tools/trace_wallet_relationships.py`

**Algorithm** (Breadth-First Search with configurable depth):
```python
def trace_relationships(seed_address, coin_type, max_hops=2, max_txs_per_wallet=100):
    """
    BFS traversal from seed_address.
    
    Returns:
      - Set of discovered wallet addresses
      - List of transactions connecting them
      - Relationship graph (adjacency list)
    """
    queue = [(seed_address, 0)]  # (address, hop_depth)
    visited = set()
    relationships = defaultdict(list)
    
    while queue:
        current_addr, depth = queue.pop(0)
        if depth > max_hops or current_addr in visited:
            continue
        
        visited.add(current_addr)
        service = load_service(coin_type)
        txs = service.get_transactions(current_addr, limit=max_txs_per_wallet)
        
        for tx in txs:
            # Add incoming relationships
            if tx['to'] == current_addr and tx['from'] not in visited:
                relationships[tx['from']].append(current_addr)
                queue.append((tx['from'], depth + 1))
            
            # Add outgoing relationships
            if tx['from'] == current_addr and tx['to'] not in visited:
                relationships[current_addr].append(tx['to'])
                queue.append((tx['to'], depth + 1))
    
    return visited, relationships
```

**Optimizations**:
- `max_txs_per_wallet` prevents explosion on high-activity exchange wallets
- Transaction amount threshold (e.g., ignore dust < 0.001 BTC) reduces noise
- Cycle detection via `visited` set prevents infinite loops
- Date range filter (e.g., only TXs from last 6 months) bounds scope

### 2.4 Enhanced Discovery & Metadata

**Extend `search_for_wallets()` output**:
```python
{
  "file_path": "/path/to/wallet.dat",
  "file_size": 24567,
  "created_at": "2021-03-15T10:32:00Z",
  "modified_at": "2022-06-20T14:05:00Z",
  "confidence_score": 0.85,  # extension + keyword + coin name match
  "matched_extensions": [".dat"],
  "matched_keywords": ["bitcoin", "wallet"],
  "matched_coins": ["bitcoin"]
}
```

**New CLI Flags**:
- `--created-after YYYY-MM-DD`
- `--created-before YYYY-MM-DD`
- `--min-confidence 0.0-1.0`
- `--exclude-large-files` (skip > 10 MB to avoid false positives)

**Confidence Scoring**:
```python
score = 0.0
if extension in WALLET_EXTENSIONS: score += 0.4
if any(kw in filename for kw in WALLET_KEYWORDS): score += 0.3
if any(coin in filename for coin in COIN_NAMES): score += 0.3
```

### 2.5 Plugin Architecture

**Plugin Interface** (`plugins/base.py`):
```python
class BasePlugin:
    name: str
    version: str
    config: dict
    
    def initialize(self):
        """Called when plugin is loaded."""
        pass
    
    def get_routes(self):
        """Return FastAPI routes for this plugin."""
        return []
    
    def get_nav_items(self):
        """Return dashboard navigation items."""
        return []
    
    def on_event(self, event_type, data):
        """Handle events from other plugins."""
        pass
```

**Wallet Finder Plugin** (`plugins/wallet_finder/plugin.py`):
```python
class WalletFinderPlugin(BasePlugin):
    name = "wallet_finder"
    version = "2.0.0"
    
    def get_routes(self):
        return [
            ("GET", "/api/wallets", self.list_wallets),
            ("POST", "/api/wallets/scan", self.start_scan),
            ("GET", "/api/wallets/{address}/graph", self.get_relationship_graph),
        ]
    
    def get_nav_items(self):
        return [
            {"label": "Wallet Scanner", "path": "/wallets"},
            {"label": "Transaction Graphs", "path": "/wallets/graphs"},
        ]
```

**Plugin Registry** (`plugins/registry.py`):
- Auto-discover plugins in `plugins/` directory
- Load enabled plugins from `config/plugins.yaml`
- Provide `get_plugin(name)` accessor
- Event bus for inter-plugin communication

**Configuration** (`config/plugins.yaml`):
```yaml
plugins:
  wallet_finder:
    enabled: true
    config:
      max_hop_depth: 2
      default_coins: ["Bitcoin", "Ethereum"]
  
  gig_radar:
    enabled: true
    config:
      scan_interval: 3600
  
  allergy_tracker:
    enabled: false
```

### 2.6 Dashboard

**Tech Stack**:
- **Backend**: FastAPI (async, auto-docs, WebSocket support)
- **Frontend**: React + TypeScript
- **Visualization**: Recharts (charts), ReactFlow (transaction graphs)
- **State Management**: Zustand (lightweight Redux alternative)

**Architecture**:
```
Frontend (React)
  ↓ HTTP/WebSocket
Backend (FastAPI)
  ↓ Plugin Registry
Plugins (wallet_finder, gig_radar, allergy)
  ↓ Shared DB Layer
SQLite
```

**Key Views**:
1. **Wallet List** - Table of discovered wallets with filters (coin, balance range, date)
2. **Wallet Detail** - Address, balance, metadata, transaction list
3. **Transaction Graph** - Interactive graph visualization of wallet relationships
4. **Scan Dashboard** - Trigger scans, view progress, export results
5. **Plugin Marketplace** - Enable/disable plugins, configure settings

**Real-Time Updates**:
- WebSocket connection to backend
- Backend publishes events when:
  - New wallet discovered during scan
  - Balance updated
  - Transaction synced
- Frontend updates UI without polling

## §3 Technical Risks

### 3.1 API Rate Limits

**Risk**: Public blockchain explorers impose strict rate limits (e.g., Etherscan: 5 req/sec on free tier).

**Mitigation**:
- Implement exponential backoff with jitter
- Redis caching layer (cache TX history for 24h)
- Batch requests where supported
- Paid API tier support for power users
- Fallback to local node queries (Bitcoin Core RPC)

### 3.2 Graph Explosion

**Risk**: High-activity wallets (exchanges, faucets) have thousands of TXs → exponential growth in BFS.

**Mitigation**:
- `max_txs_per_wallet` cap (default 100)
- Transaction value threshold (ignore < $1 equivalent)
- Hop limit (default 2, configurable)
- Heuristic detection of exchange wallets (many unique counterparties) → skip
- User confirmation for graphs > 1000 wallets

### 3.3 Data Volume

**Risk**: Storing full TX history for active wallets can grow to GB-scale.

**Mitigation**:
- Pagination for transaction fetches (100 per page)
- Lazy loading (only fetch on user request, not automatic)
- Date range filtering (default to last 12 months)
- Periodic cleanup of old cached data
- Upgrade path to PostgreSQL for multi-user deployments

### 3.4 Plugin Compatibility

**Risk**: Breaking changes in plugin interface disrupt third-party plugins (gig radar, allergy).

**Mitigation**:
- Semantic versioning for plugin API
- Deprecation warnings before removal
- Plugin compatibility matrix in docs
- Sandbox environment for plugin testing

### 3.5 Frontend Complexity

**Risk**: Transaction graphs with 500+ nodes become unresponsive.

**Mitigation**:
- Server-side graph layout computation
- Canvas rendering (not SVG) for large graphs
- Clustering/aggregation of low-value nodes
- Progressive loading (render top N nodes first)
- WebGL acceleration via ReactFlow

## §4 Dependencies

**New Python Packages**:
- `sqlalchemy` - ORM for database
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `pydantic` - Data validation
- `networkx` - Graph algorithms
- `redis` (optional) - Caching layer

**New API Keys** (extend `.env`):
```
BLOCKCYPHER_API_KEY=for LTC/DOGE transaction history
REDIS_URL=redis://localhost:6379 (optional)
```

**Frontend Dependencies**:
- `react` + `react-dom`
- `react-router-dom` - Navigation
- `recharts` - Charts
- `reactflow` - Graph visualization
- `zustand` - State management
- `axios` - HTTP client

## §5 Open Questions

1. **Multi-coin graph traversal**: Should the graph traverse across different coins (e.g., BTC → exchange → ETH)? Or stay single-coin?
   - **Recommendation**: Single-coin for MVP, cross-coin in Phase 2 (requires exchange detection heuristics)

2. **Wallet ownership clustering**: Should we attempt to cluster addresses likely owned by the same person?
   - **Recommendation**: Not in MVP (privacy-invasive, heuristics unreliable), add as opt-in advanced feature later

3. **Mobile support**: Should the dashboard be mobile-responsive?
   - **Recommendation**: Desktop-first for MVP (graph visualization difficult on mobile), add responsive design in Phase 2

4. **Multi-user support**: Should multiple users be able to share the same database with access control?
   - **Recommendation**: Single-user for MVP (SQLite limitation), upgrade to PostgreSQL + auth in Phase 2 if demand exists

5. **Export formats**: What export formats beyond JSON/CSV should be supported (e.g., GraphML for Gephi)?
   - **Recommendation**: JSON + CSV for MVP, add GraphML/GEXF in Phase 2 based on user feedback

6. **Real-time price data**: Should balances be shown in USD equivalent alongside native units?
   - **Recommendation**: Yes - integrate CoinGecko API for real-time pricing (free tier: 10-50 req/min)

7. **Historical balance snapshots**: Should we track balance changes over time?
   - **Recommendation**: Not in MVP (requires daily/hourly polling), add as opt-in feature later

8. **Notification system**: Should users be alerted when balances change?
   - **Recommendation**: Phase 2 feature (requires background jobs, email/push notification setup)

## §6 Scale Assessment

**Recommended Scale**: **Medium**

**Justification**:
- Multi-file, multi-layer change (database, backend, frontend, plugin system)
- Cross-stack work (Python backend + React frontend)
- New architectural patterns (plugins, graph traversal)
- BUT: Core pipeline logic is well-understood, no distributed systems complexity
- Incremental delivery is feasible (vertical slices per feature)

**Not Large because**:
- No multi-system coordination (single monolithic app)
- No migration of production data (greenfield DB)
- Team size = 1, no cross-team dependencies

**Estimated Effort**: 15-20 stories, 40-60 hours of development

## §7 Alternatives Considered

### Alt 1: Use Existing Blockchain Analysis Tools

**Option**: Integrate with Chainalysis, Elliptic, or open-source alternatives (BlockSci)

**Pros**: Battle-tested graph analysis, regulatory compliance features

**Cons**: Expensive licensing (Chainalysis: $10k+/year), overkill for personal use, loss of control

**Decision**: ✗ Rejected - requirement is personal wallet recovery, not forensic analysis

### Alt 2: Client-Side Only (No Backend)

**Option**: Build dashboard as static SPA, all processing in browser (IndexedDB for storage)

**Pros**: No server maintenance, easy deployment (GitHub Pages)

**Cons**: Cannot run long-running scans, limited storage (IndexedDB ~50 MB), no background jobs

**Decision**: ✗ Rejected - transaction history syncing requires server-side processing

### Alt 3: Microservices Architecture

**Option**: Split into separate services (scanner, analyzer, balance-checker, graph-builder, dashboard)

**Pros**: Independent scaling, language flexibility, clearer boundaries

**Cons**: Massive complexity overhead, deployment burden, overkill for single user

**Decision**: ✗ Rejected - monolithic plugin architecture sufficient for current scale

### Alt 4: GraphQL API

**Option**: Use GraphQL instead of REST for API layer

**Pros**: Flexible queries, reduce over-fetching, better frontend experience

**Cons**: Added complexity, FastAPI REST is simpler, no strong need for complex queries yet

**Decision**: ✗ Rejected - REST sufficient for MVP, can add GraphQL layer later if needed

## §8 Success Metrics

1. **Reverse tracking coverage**: Successfully trace relationships for 80%+ of Bitcoin wallets with ≥1 transaction
2. **Graph performance**: Render graphs of 100 wallets in <2 seconds, 500 wallets in <10 seconds
3. **Plugin adoption**: At least 2 additional plugins (gig radar, allergy) integrated within 3 months
4. **User retention**: 70%+ of users who run initial scan return to check wallet status within 30 days
5. **API reliability**: 95%+ success rate on transaction history fetches (accounting for rate limits)

## §9 Next Steps

1. User feedback on:
   - Confirm priority: Reverse tracking → Enhanced discovery → Dashboard → Plugin architecture
   - Clarify hop depth preference (2-3 hops reasonable?)
   - Dashboard framework preference (React vs Vue vs Svelte)

2. If approved, proceed to:
   - Horizontal/Vertical planning (medium scope)
   - Story decomposition with dependency tracking
   - Implementation starting with database layer + Bitcoin transaction history
