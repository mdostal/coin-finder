import json
import sqlite3
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_DB_PATH = app_data_dir() / "crawl_runs.db"

# Two tables, not one denormalized blob: the group-view overlap query
# (find_overlap_addresses) needs "GROUP BY address HAVING COUNT(DISTINCT
# run_id) > 1" as a plain indexed SQL query -- a JSON-blob-per-run design
# would force scanning and parsing every saved run in Python instead.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_addresses TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS run_addresses (
    run_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    confidence TEXT,
    generation INTEGER,
    balance REAL,
    last_activity_timestamp REAL,
    dormant_years REAL
);
CREATE TABLE IF NOT EXISTS run_edges (
    run_id INTEGER NOT NULL,
    from_address TEXT NOT NULL,
    to_address TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    txid TEXT NOT NULL
);
"""

# Same migration discipline as web/findings.py: a table that doesn't exist
# yet in a pre-existing db file (e.g. only `runs` was ever created) must be
# added in place, not crash. `_SCHEMA`'s CREATE TABLE IF NOT EXISTS already
# covers a brand new db; this loop covers a db that predates a table this
# module didn't originally ship with.
_MIGRATIONS = []


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass  # already migrated
    return conn


def record_crawl_run(seed_addresses, results, edges=None, db_path=DEFAULT_DB_PATH):
    """
    Persists one crawl_wallet_cluster() run in full: one row in `runs`
    (the seed addresses that triggered it), one row per discovered
    address in `run_addresses` (confidence/generation/balance/dormancy,
    exactly as crawl_wallet_cluster() returned them -- nothing recomputed),
    and, when given, one row per edges_out entry in `run_edges` -- the
    "numerous transactions and interactions" evidence confidence scoring
    (compute_confidence_scores) aggregates across every saved run.

    Called from web/app.py's _run_crawl_job() alongside (not instead of)
    its existing record_finding() loop -- this captures the *run* (which
    seed found which addresses, at what confidence), which record_finding()
    alone throws away once the job's in-memory result is gone.

    :param seed_addresses: the addresses the crawl was started from.
    :param results: crawl_wallet_cluster()'s return value.
    :param edges: crawl_wallet_cluster()'s edges_out list, or None (the
        default) -- writes nothing to run_edges, exactly matching every
        call site that predates edge tracking.
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO runs (seed_addresses, created_at) VALUES (?, ?)",
            (json.dumps(list(seed_addresses)), time.time()),
        )
        run_id = cursor.lastrowid
        conn.executemany(
            """
            INSERT INTO run_addresses
                (run_id, address, confidence, generation, balance, last_activity_timestamp, dormant_years)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    address,
                    info.get("confidence"),
                    info.get("generation"),
                    info.get("balance"),
                    info.get("last_activity_timestamp"),
                    info.get("dormant_years"),
                )
                for address, info in results.items()
            ],
        )
        if edges:
            conn.executemany(
                "INSERT INTO run_edges (run_id, from_address, to_address, edge_type, txid) VALUES (?, ?, ?, ?, ?)",
                [(run_id, edge["from"], edge["to"], edge["type"], edge["txid"]) for edge in edges],
            )
        conn.commit()
    finally:
        conn.close()


def list_crawl_runs(db_path=DEFAULT_DB_PATH):
    """:return: [{"run_id", "seed_addresses", "created_at", "address_count"}, ...], newest first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT r.run_id, r.seed_addresses, r.created_at, COUNT(ra.address) AS address_count
            FROM runs r
            LEFT JOIN run_addresses ra ON ra.run_id = r.run_id
            GROUP BY r.run_id
            ORDER BY r.created_at DESC
            """
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "seed_addresses": json.loads(row["seed_addresses"]),
                "created_at": row["created_at"],
                "address_count": row["address_count"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def list_run_edges(db_path=DEFAULT_DB_PATH):
    """:return: [{"run_id", "from_address", "to_address", "edge_type", "txid"}, ...], every edge ever saved."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT run_id, from_address, to_address, edge_type, txid FROM run_edges").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def find_overlap_addresses(db_path=DEFAULT_DB_PATH):
    """
    The actual group-view signal: every address discovered by MORE THAN ONE
    separate crawl run, grouped with which run(s)/seed(s) found it and at
    what confidence/generation each time. Empty (never an error) with zero
    or one saved run -- overlap requires at least two.

    :return: {address: {"balance": float|None, "runs": [{"run_id",
        "seed_addresses", "confidence", "generation"}, ...]}}
    """
    conn = _connect(db_path)
    try:
        overlapping = conn.execute(
            "SELECT address FROM run_addresses GROUP BY address HAVING COUNT(DISTINCT run_id) > 1"
        ).fetchall()
        if not overlapping:
            return {}

        addresses = [row["address"] for row in overlapping]
        placeholders = ",".join("?" * len(addresses))
        rows = conn.execute(
            f"""
            SELECT ra.address, ra.confidence, ra.generation, ra.balance, ra.run_id, r.seed_addresses
            FROM run_addresses ra
            JOIN runs r ON r.run_id = ra.run_id
            WHERE ra.address IN ({placeholders})
            ORDER BY ra.address, r.created_at
            """,
            addresses,
        ).fetchall()

        result = {}
        for row in rows:
            entry = result.setdefault(row["address"], {"balance": row["balance"], "runs": []})
            if row["balance"] is not None:
                entry["balance"] = row["balance"]
            entry["runs"].append(
                {
                    "run_id": row["run_id"],
                    "seed_addresses": json.loads(row["seed_addresses"]),
                    "confidence": row["confidence"],
                    "generation": row["generation"],
                }
            )
        return result
    finally:
        conn.close()


def clear_all_crawl_runs(db_path=DEFAULT_DB_PATH):
    """Hard-deletes every saved crawl run -- mirrors web.findings.clear_all_findings()."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM run_edges")
        conn.execute("DELETE FROM run_addresses")
        conn.execute("DELETE FROM runs")
        conn.commit()
    finally:
        conn.close()
