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


# Weights, not a claim of precision -- co-spend is strong evidence (common-
# input-ownership: building the tx requires every input's private key),
# output is weaker (a real transfer, but transfers to third parties happen
# too), cross-run corroboration (independently rediscovered by a separate
# crawl) is a bonus on top of direct evidence, never a standalone signal.
_COSPEND_WEIGHT = 5
_OUTPUT_WEIGHT = 2
_CROSS_RUN_BONUS = 3
_HIGH_THRESHOLD = 10
_MEDIUM_THRESHOLD = 4


def _confidence_label(score):
    if score >= _HIGH_THRESHOLD:
        return "High"
    if score >= _MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def compute_confidence_scores(known_addresses, db_path=DEFAULT_DB_PATH):
    """
    Ranks every discovered address that is NOT already known against how
    strongly it's directly linked -- by real, distinct transactions -- to
    the known set. Deliberately conservative: only DIRECT edges to a known
    address count (no transitive/multi-hop credit), so this never inflates
    a loose, several-hops-away association into a confident suggestion.

    Every entry carries its raw breakdown alongside the label -- a
    confidence_label is never returned without the counts that produced it,
    matching every other confidence signal in this app (crawl_wallet_cluster's
    seed/co-spend/output tags, render_cluster_report's explicit "candidate,
    not certain" framing). These are suggestions to investigate, not
    findings -- a candidate becomes a real finding only once its balance is
    actually checked.

    :param known_addresses: the addresses already confirmed (typically
        every Bitcoin address in web.findings.list_findings()).
    :return: [{"address", "score", "confidence_label",
        "direct_cospend_count", "direct_output_count", "cross_run_count"},
        ...], highest score first. Only addresses with a nonzero score
        (i.e. at least one direct edge to a known address) are included.
    """
    known_addresses = set(known_addresses)

    conn = _connect(db_path)
    try:
        edge_rows = conn.execute("SELECT DISTINCT from_address, to_address, edge_type, txid FROM run_edges").fetchall()
        run_count_rows = conn.execute("SELECT address, COUNT(DISTINCT run_id) AS run_count FROM run_addresses GROUP BY address").fetchall()
    finally:
        conn.close()

    run_counts = {row["address"]: row["run_count"] for row in run_count_rows}

    cospend_txids = {}
    output_txids = {}
    for row in edge_rows:
        frm, to, edge_type, txid = row["from_address"], row["to_address"], row["edge_type"], row["txid"]
        if frm in known_addresses and to not in known_addresses:
            candidate = to
        elif to in known_addresses and frm not in known_addresses:
            candidate = frm
        else:
            continue  # neither side known (no direct evidence yet), or both known (nothing new to suggest)

        bucket = cospend_txids if edge_type == "co-spend" else output_txids
        bucket.setdefault(candidate, set()).add(txid)

    candidates = set(cospend_txids) | set(output_txids)
    scored = []
    for address in candidates:
        cospend_count = len(cospend_txids.get(address, ()))
        output_count = len(output_txids.get(address, ()))
        cross_run_count = run_counts.get(address, 0)
        cross_run_bonus = _CROSS_RUN_BONUS if cross_run_count > 1 else 0

        score = _COSPEND_WEIGHT * cospend_count + _OUTPUT_WEIGHT * output_count + cross_run_bonus
        scored.append(
            {
                "address": address,
                "score": score,
                "confidence_label": _confidence_label(score),
                "direct_cospend_count": cospend_count,
                "direct_output_count": output_count,
                "cross_run_count": cross_run_count,
            }
        )

    scored.sort(key=lambda entry: entry["score"], reverse=True)
    return scored


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


def get_cross_group_overlap(run_ids, db_path=DEFAULT_DB_PATH):
    """
    The run_id-set-scoped sibling of find_overlap_addresses: every address
    discovered by 2+ of the SPECIFIC given run_ids -- not globally across
    every saved run ever (that's find_overlap_addresses' job). This is
    what makes an address "cross-group" for one particular combined-graph
    view (e.g. the 3 runs a user just checked together), which can be a
    very different answer than whether that address overlaps globally --
    an address shared by two runs neither of which is in the current
    selection must NOT show up here.

    Empty (never an error) when fewer than two distinct run_ids are given,
    or when none of the given runs' addresses overlap with each other.

    :param run_ids: iterable of int run_id values to check for overlap
        within. Order and duplicates don't matter -- deduplicated
        internally, same as get_runs_graph_data.
    :return: {address: [{"run_id", "seed_addresses", "confidence",
        "generation"}, ...]} -- only addresses found in 2+ of the given
        run_ids, each mapped to the real evidence (never fewer than 2
        entries) for exactly which of the selected runs/seeds found it --
        never a bare "overlap" label with nothing behind it.
    """
    run_ids = sorted({int(run_id) for run_id in run_ids})
    if len(run_ids) < 2:
        return {}

    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" * len(run_ids))
        overlapping = conn.execute(
            f"""
            SELECT address FROM run_addresses
            WHERE run_id IN ({placeholders})
            GROUP BY address HAVING COUNT(DISTINCT run_id) > 1
            """,
            run_ids,
        ).fetchall()
        if not overlapping:
            return {}

        addresses = [row["address"] for row in overlapping]
        addr_placeholders = ",".join("?" * len(addresses))
        rows = conn.execute(
            f"""
            SELECT ra.address, ra.confidence, ra.generation, ra.run_id, r.seed_addresses
            FROM run_addresses ra
            JOIN runs r ON r.run_id = ra.run_id
            WHERE ra.address IN ({addr_placeholders}) AND ra.run_id IN ({placeholders})
            ORDER BY ra.address, r.created_at
            """,
            addresses + run_ids,
        ).fetchall()

        result = {}
        for row in rows:
            result.setdefault(row["address"], []).append(
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


# Same strength ordering crawl_wallet_cluster/compute_confidence_scores
# already use for these exact tag strings (seed is the address you started
# from -- maximally confident; co-spend is strong direct evidence;
# output is weaker). Lower rank number wins in get_runs_graph_data's dedup.
_CONFIDENCE_DEDUP_RANK = {"seed": 0, "co-spend": 1, "output": 2}


def _dedup_sort_key(candidate):
    """Lower sorts first/wins. An unrecognized or missing confidence value
    sorts last (worst), never crashes. Generation is the tiebreak when
    confidence ranks equal (lower generation = closer to a seed = more
    directly connected); a missing generation also sorts last."""
    confidence_rank = _CONFIDENCE_DEDUP_RANK.get(candidate["confidence"], len(_CONFIDENCE_DEDUP_RANK))
    generation = candidate["generation"] if candidate["generation"] is not None else float("inf")
    return (confidence_rank, generation)


def get_runs_graph_data(run_ids, db_path=DEFAULT_DB_PATH):
    """
    The real combined-group graph dataset: every address discovered by ANY
    of the given run_ids (deduplicated), plus every edge belonging to those
    same runs. Deliberately NOT find_overlap_addresses -- that function is
    globally-scoped and intersection-only (addresses found by 2+ runs out
    of every run ever saved, discarding everything else); this returns the
    full UNION of nodes across exactly the selected runs, which is what a
    real combined-view graph needs to render (every node from every
    selected group, not just where they overlap).

    Dedup rule when the same address appears in run_addresses for more
    than one selected run: keep the record with the highest-confidence
    discovery tag -- seed beats co-spend beats output, the same evidence-
    strength ordering already used elsewhere in this file (_COSPEND_WEIGHT
    > _OUTPUT_WEIGHT, seed == generation 0). When confidence ties, the
    earliest (lowest) generation wins. If both are tied too, the record
    seen first in run_id order is kept -- deterministic, never an
    arbitrary "whichever the SQL happened to return last."

    :param run_ids: iterable of int run_id values to combine. Order and
        duplicates don't matter -- deduplicated internally.
    :return: {"nodes": {address: {"confidence", "generation", "balance",
        "last_activity_timestamp", "dormant_years", "run_id"}, ...},
        "edges": [{"run_id", "from_address", "to_address", "edge_type",
        "txid"}, ...]}. "run_id" on a node is whichever run's record won
        the dedup, not necessarily every run the address appeared in.
        Empty nodes/edges (not an error) when run_ids is empty or none of
        them have saved data.
    """
    run_ids = sorted({int(run_id) for run_id in run_ids})
    if not run_ids:
        return {"nodes": {}, "edges": []}

    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" * len(run_ids))
        address_rows = conn.execute(
            f"""
            SELECT run_id, address, confidence, generation, balance, last_activity_timestamp, dormant_years
            FROM run_addresses
            WHERE run_id IN ({placeholders})
            ORDER BY run_id
            """,
            run_ids,
        ).fetchall()
        edge_rows = conn.execute(
            f"""
            SELECT run_id, from_address, to_address, edge_type, txid
            FROM run_edges
            WHERE run_id IN ({placeholders})
            """,
            run_ids,
        ).fetchall()
    finally:
        conn.close()

    nodes = {}
    for row in address_rows:
        candidate = {
            "confidence": row["confidence"],
            "generation": row["generation"],
            "balance": row["balance"],
            "last_activity_timestamp": row["last_activity_timestamp"],
            "dormant_years": row["dormant_years"],
            "run_id": row["run_id"],
        }
        existing = nodes.get(row["address"])
        if existing is None or _dedup_sort_key(candidate) < _dedup_sort_key(existing):
            nodes[row["address"]] = candidate

    return {"nodes": nodes, "edges": [dict(row) for row in edge_rows]}


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
