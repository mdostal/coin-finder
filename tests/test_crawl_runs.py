import sqlite3
import time

from web.crawl_runs import (
    clear_all_crawl_runs,
    compute_confidence_scores,
    find_overlap_addresses,
    get_runs_graph_data,
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


def _run_id_for_seed(db_path, seed_address):
    runs = list_crawl_runs(db_path=db_path)
    return next(r["run_id"] for r in runs if r["seed_addresses"] == [seed_address])


def test_get_runs_graph_data_empty_run_ids_returns_empty_without_crash(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    assert get_runs_graph_data([], db_path=db_path) == {"nodes": {}, "edges": []}


def test_get_runs_graph_data_combines_every_node_from_both_runs_not_just_intersection(tmp_path):
    """The whole point of this function vs. find_overlap_addresses: the
    union of nodes across the selected runs, not the intersection."""
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], {"1a": _address_info("seed", 0)}, db_path=db_path)
    record_crawl_run(["1b"], {"1b": _address_info("seed", 0)}, db_path=db_path)
    run_id_a = _run_id_for_seed(db_path, "1a")
    run_id_b = _run_id_for_seed(db_path, "1b")

    data = get_runs_graph_data([run_id_a, run_id_b], db_path=db_path)

    assert set(data["nodes"].keys()) == {"1a", "1b"}


def test_get_runs_graph_data_dedup_has_no_duplicates_when_address_shared(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], {"1shared": _address_info("co-spend", 1)}, db_path=db_path)
    record_crawl_run(["1b"], {"1shared": _address_info("co-spend", 1)}, db_path=db_path)
    run_ids = [r["run_id"] for r in list_crawl_runs(db_path=db_path)]

    data = get_runs_graph_data(run_ids, db_path=db_path)

    assert list(data["nodes"].keys()) == ["1shared"]


def test_get_runs_graph_data_dedup_keeps_higher_confidence_record(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], {"1shared": _address_info("output", 3)}, db_path=db_path)
    record_crawl_run(["1b"], {"1shared": _address_info("co-spend", 1)}, db_path=db_path)
    run_ids = [r["run_id"] for r in list_crawl_runs(db_path=db_path)]

    data = get_runs_graph_data(run_ids, db_path=db_path)

    assert data["nodes"]["1shared"]["confidence"] == "co-spend"


def test_get_runs_graph_data_dedup_keeps_seed_over_cospend_regardless_of_generation(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], {"1shared": _address_info("co-spend", 0)}, db_path=db_path)
    record_crawl_run(["1shared"], {"1shared": _address_info("seed", 0)}, db_path=db_path)
    run_ids = [r["run_id"] for r in list_crawl_runs(db_path=db_path)]

    data = get_runs_graph_data(run_ids, db_path=db_path)

    assert data["nodes"]["1shared"]["confidence"] == "seed"


def test_get_runs_graph_data_dedup_breaks_confidence_tie_by_earliest_generation(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], {"1shared": _address_info("co-spend", 4)}, db_path=db_path)
    record_crawl_run(["1b"], {"1shared": _address_info("co-spend", 1)}, db_path=db_path)
    run_ids = [r["run_id"] for r in list_crawl_runs(db_path=db_path)]

    data = get_runs_graph_data(run_ids, db_path=db_path)

    assert data["nodes"]["1shared"]["generation"] == 1


def test_get_runs_graph_data_filters_edges_to_only_the_selected_runs(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(
        ["1a"],
        {"1a": _address_info("seed", 0), "1a2": _address_info()},
        edges=[{"from": "1a", "to": "1a2", "type": "co-spend", "txid": "tx-a"}],
        db_path=db_path,
    )
    record_crawl_run(
        ["1b"],
        {"1b": _address_info("seed", 0), "1b2": _address_info()},
        edges=[{"from": "1b", "to": "1b2", "type": "output", "txid": "tx-b"}],
        db_path=db_path,
    )
    record_crawl_run(
        ["1c"],
        {"1c": _address_info("seed", 0), "1c2": _address_info()},
        edges=[{"from": "1c", "to": "1c2", "type": "output", "txid": "tx-c"}],
        db_path=db_path,
    )
    run_id_a = _run_id_for_seed(db_path, "1a")
    run_id_b = _run_id_for_seed(db_path, "1b")

    data = get_runs_graph_data([run_id_a, run_id_b], db_path=db_path)

    txids = {edge["txid"] for edge in data["edges"]}
    assert txids == {"tx-a", "tx-b"}


def test_get_runs_graph_data_single_run_case_no_crash_no_cross_run_leakage(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], SAMPLE_RESULTS, db_path=db_path)
    record_crawl_run(["1b"], {"1other": _address_info("seed", 0)}, db_path=db_path)
    run_id_a = _run_id_for_seed(db_path, "1a")

    data = get_runs_graph_data([run_id_a], db_path=db_path)

    assert set(data["nodes"].keys()) == set(SAMPLE_RESULTS.keys())
    assert "1other" not in data["nodes"]


def test_get_runs_graph_data_node_fields_match_run_addresses_columns(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1a"], {"1a": {"confidence": "seed", "generation": 0, "balance": 0.75, "last_activity_timestamp": 123, "dormant_years": 2.5}}, db_path=db_path)
    run_id_a = _run_id_for_seed(db_path, "1a")

    data = get_runs_graph_data([run_id_a], db_path=db_path)

    assert data["nodes"]["1a"] == {
        "confidence": "seed",
        "generation": 0,
        "balance": 0.75,
        "last_activity_timestamp": 123,
        "dormant_years": 2.5,
        "run_id": run_id_a,
    }
