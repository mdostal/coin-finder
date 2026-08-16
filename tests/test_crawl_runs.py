import sqlite3
import time

from web.crawl_runs import (
    clear_all_crawl_runs,
    compute_confidence_scores,
    find_overlap_addresses,
    list_crawl_runs,
    list_run_edges,
    record_crawl_run,
)

SAMPLE_RESULTS = {
    "1seed": {"confidence": "seed", "generation": 0, "balance": 0.5, "last_activity_timestamp": 1000, "dormant_years": 5.0},
    "1cospend": {"confidence": "co-spend", "generation": 1, "balance": 0.1, "last_activity_timestamp": 900, "dormant_years": 6.0},
}


def test_record_crawl_run_then_list_includes_it(tmp_path):
    db_path = tmp_path / "crawl_runs.db"

    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)

    runs = list_crawl_runs(db_path=db_path)
    assert len(runs) == 1
    assert runs[0]["seed_addresses"] == ["1seed"]
    assert runs[0]["address_count"] == 2


def test_list_crawl_runs_newest_first(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1old"], {"1old": {"confidence": "seed", "generation": 0, "balance": 0.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)
    time.sleep(0.01)
    record_crawl_run(["1new"], {"1new": {"confidence": "seed", "generation": 0, "balance": 0.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)

    runs = list_crawl_runs(db_path=db_path)
    assert runs[0]["seed_addresses"] == ["1new"]
    assert runs[1]["seed_addresses"] == ["1old"]


def test_record_crawl_run_persists_per_address_fields(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)

    # No public getter for raw run_addresses rows other than find_overlap_addresses
    # (which requires >1 run) -- verify directly via a second run sharing an address.
    record_crawl_run(["1other"], {"1cospend": SAMPLE_RESULTS["1cospend"]}, db_path=db_path)

    overlaps = find_overlap_addresses(db_path=db_path)
    assert "1cospend" in overlaps
    entry = overlaps["1cospend"]["runs"][0]
    assert entry["confidence"] == "co-spend"
    assert entry["generation"] == 1


def test_find_overlap_addresses_empty_with_zero_or_one_run(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    assert find_overlap_addresses(db_path=db_path) == {}

    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert find_overlap_addresses(db_path=db_path) == {}


def test_find_overlap_addresses_finds_address_shared_across_runs(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1walletA"], {"1shared": {"confidence": "co-spend", "generation": 1, "balance": 2.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)
    record_crawl_run(["1walletB"], {"1shared": {"confidence": "output", "generation": 2, "balance": 2.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)

    overlaps = find_overlap_addresses(db_path=db_path)

    assert set(overlaps.keys()) == {"1shared"}
    assert len(overlaps["1shared"]["runs"]) == 2
    seeds_seen = {tuple(r["seed_addresses"]) for r in overlaps["1shared"]["runs"]}
    assert seeds_seen == {("1walletA",), ("1walletB",)}


def test_find_overlap_addresses_ignores_addresses_seen_in_only_one_run(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1walletA"], SAMPLE_RESULTS, db_path=db_path)
    record_crawl_run(["1walletB"], {"1unrelated": {"confidence": "seed", "generation": 0, "balance": 0.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)

    overlaps = find_overlap_addresses(db_path=db_path)

    assert overlaps == {}


def test_clear_all_crawl_runs_deletes_everything(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, edges=[{"from": "1cospend", "to": "1seed", "type": "co-spend", "txid": "tx1"}], db_path=db_path)

    clear_all_crawl_runs(db_path=db_path)

    assert list_crawl_runs(db_path=db_path) == []
    assert find_overlap_addresses(db_path=db_path) == {}
    assert list_run_edges(db_path=db_path) == []


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert db_path.exists()


def test_migration_does_not_crash_on_pre_existing_schema_less_db(tmp_path):
    """A crawl_runs.db that only has the `runs` table (simulating a future
    schema addition landing on an older db) must not crash -- same
    ALTER TABLE + OperationalError-catch discipline as web/findings.py."""
    db_path = tmp_path / "crawl_runs.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, seed_addresses TEXT NOT NULL, created_at REAL NOT NULL)")
    conn.commit()
    conn.close()

    # Should not raise even though run_addresses doesn't exist yet.
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert list_crawl_runs(db_path=db_path)[0]["address_count"] == 2


SAMPLE_EDGES = [
    {"from": "1cospend", "to": "1seed", "type": "co-spend", "txid": "tx1"},
    {"from": "1seed", "to": "1output", "type": "output", "txid": "tx2"},
]


def test_record_crawl_run_with_edges_none_writes_nothing_new(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert list_run_edges(db_path=db_path) == []


def test_record_crawl_run_persists_edges(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, edges=SAMPLE_EDGES, db_path=db_path)

    edges = list_run_edges(db_path=db_path)
    assert len(edges) == 2
    assert {"from_address": "1cospend", "to_address": "1seed", "edge_type": "co-spend", "txid": "tx1"} in [
        {k: e[k] for k in ("from_address", "to_address", "edge_type", "txid")} for e in edges
    ]


def test_record_crawl_run_with_empty_edges_list_writes_nothing(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, edges=[], db_path=db_path)
    assert list_run_edges(db_path=db_path) == []


def _address_info(confidence="co-spend", generation=1, balance=None):
    return {"confidence": confidence, "generation": generation, "balance": balance, "last_activity_timestamp": None, "dormant_years": None}


def test_compute_confidence_scores_excludes_addresses_with_no_edge_evidence(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1known"], {"1known": _address_info("seed", 0), "1unrelated": _address_info()}, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)

    assert scores == []


def test_compute_confidence_scores_weighs_co_spend_evidence_with_a_known_address(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    results = {"1known": _address_info("seed", 0), "1candidate": _address_info()}
    edges = [{"from": "1known", "to": "1candidate", "type": "co-spend", "txid": "tx1"}]
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)

    assert len(scores) == 1
    assert scores[0]["address"] == "1candidate"
    assert scores[0]["direct_cospend_count"] == 1
    assert scores[0]["direct_output_count"] == 0
    assert scores[0]["score"] > 0


def test_compute_confidence_scores_ranks_co_spend_above_output_evidence(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    results = {
        "1known": _address_info("seed", 0),
        "1cospend_candidate": _address_info(),
        "1output_candidate": _address_info("output"),
    }
    edges = [
        {"from": "1known", "to": "1cospend_candidate", "type": "co-spend", "txid": "tx1"},
        {"from": "1known", "to": "1output_candidate", "type": "output", "txid": "tx2"},
    ]
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)
    by_address = {s["address"]: s for s in scores}

    assert by_address["1cospend_candidate"]["score"] > by_address["1output_candidate"]["score"]


def test_compute_confidence_scores_additional_transactions_increase_score_but_not_linearly_per_bonus(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    results = {"1known": _address_info("seed", 0), "1candidate": _address_info()}
    two_tx_edges = [
        {"from": "1known", "to": "1candidate", "type": "co-spend", "txid": "tx1"},
        {"from": "1known", "to": "1candidate", "type": "co-spend", "txid": "tx2"},
    ]
    record_crawl_run(["1known"], results, edges=two_tx_edges, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)

    assert scores[0]["direct_cospend_count"] == 2


def test_compute_confidence_scores_excludes_addresses_already_known(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    results = {"1known": _address_info("seed", 0), "1alsoknown": _address_info()}
    edges = [{"from": "1known", "to": "1alsoknown", "type": "co-spend", "txid": "tx1"}]
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)

    scores = compute_confidence_scores(["1known", "1alsoknown"], db_path=db_path)

    assert scores == []


def test_compute_confidence_scores_deduplicates_edges_across_separate_runs(tmp_path):
    """Same txid recorded by two separate saved runs (e.g. the candidate
    was independently re-discovered) must not double the transaction
    count -- it's the same real-world transaction."""
    db_path = tmp_path / "crawl_runs.db"
    results = {"1known": _address_info("seed", 0), "1candidate": _address_info()}
    edges = [{"from": "1known", "to": "1candidate", "type": "co-spend", "txid": "tx1"}]
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)

    assert scores[0]["direct_cospend_count"] == 1


def test_compute_confidence_scores_cross_run_bonus_requires_direct_evidence_too(tmp_path):
    """Cross-run corroboration is a bonus on top of direct evidence, not a
    standalone signal -- an address appearing in multiple runs but never
    directly linked to a known address in the recorded edges scores 0."""
    db_path = tmp_path / "crawl_runs.db"
    results = {"1seed": _address_info("seed", 0), "1candidate": _address_info()}
    record_crawl_run(["1seed"], results, db_path=db_path)
    record_crawl_run(["1otherseed"], results, db_path=db_path)

    scores = compute_confidence_scores(["1known-address-not-present"], db_path=db_path)

    assert scores == []


def test_compute_confidence_scores_sorted_highest_first(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    results = {
        "1known": _address_info("seed", 0),
        "1strong": _address_info(),
        "1weak": _address_info("output"),
    }
    edges = [
        {"from": "1known", "to": "1strong", "type": "co-spend", "txid": "tx1"},
        {"from": "1known", "to": "1weak", "type": "output", "txid": "tx2"},
    ]
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)

    assert [s["address"] for s in scores] == ["1strong", "1weak"]


def test_compute_confidence_scores_labels_are_derived_from_score_not_arbitrary(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    results = {"1known": _address_info("seed", 0), "1candidate": _address_info()}
    edges = [{"from": "1known", "to": "1candidate", "type": "co-spend", "txid": "tx1"}]
    record_crawl_run(["1known"], results, edges=edges, db_path=db_path)

    scores = compute_confidence_scores(["1known"], db_path=db_path)

    assert scores[0]["confidence_label"] in ("High", "Medium", "Low")
