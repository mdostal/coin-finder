import pytest

from tools.check_wallet_balances import GLOBAL_MAX_WORKERS, PER_COIN_MAX_CONCURRENCY
from web.scan_settings import (
    auto_analyze_processes,
    auto_search_walk_threads,
    get_auto_profile,
    get_settings,
    resolve_analyze_processes,
    resolve_check_balances_workers,
    resolve_search_walk_threads,
    set_mode,
    set_overrides,
)


def test_default_settings_are_auto_mode_with_no_overrides(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    settings = get_settings(db_path=db_path)

    assert settings["mode"] == "auto"
    assert settings["overrides"]["check_balances_global_workers"] is None
    assert settings["overrides"]["check_balances_per_coin_concurrency"] is None


def test_get_settings_creates_no_file_when_nothing_written(tmp_path):
    """Reading before any set_* call must not itself leave a stray db
    file behind -- a settings page GET should be a true no-op on disk."""
    db_path = tmp_path / "scan_settings.db"

    get_settings(db_path=db_path)

    assert not db_path.exists()


def test_set_mode_persists_across_reads(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    set_mode("custom", db_path=db_path)

    assert get_settings(db_path=db_path)["mode"] == "custom"
    assert db_path.exists()


def test_set_mode_rejects_invalid_value(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    with pytest.raises(ValueError):
        set_mode("bogus", db_path=db_path)


def test_set_overrides_is_a_partial_merge_not_a_full_replace(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    set_overrides({"check_balances_global_workers": 10}, db_path=db_path)
    set_overrides({"check_balances_per_coin_concurrency": 5}, db_path=db_path)

    overrides = get_settings(db_path=db_path)["overrides"]
    assert overrides["check_balances_global_workers"] == 10
    assert overrides["check_balances_per_coin_concurrency"] == 5


def test_set_overrides_can_clear_a_field_back_to_null(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    set_overrides({"check_balances_global_workers": 10}, db_path=db_path)
    set_overrides({"check_balances_global_workers": None}, db_path=db_path)

    assert get_settings(db_path=db_path)["overrides"]["check_balances_global_workers"] is None


def test_set_overrides_rejects_unknown_keys(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    with pytest.raises(ValueError):
        set_overrides({"not_a_real_setting": 1}, db_path=db_path)


def test_resolve_check_balances_workers_defaults_to_todays_tuned_constants_in_auto_mode(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    global_workers, per_coin = resolve_check_balances_workers(db_path=db_path)

    assert (global_workers, per_coin) == (GLOBAL_MAX_WORKERS, PER_COIN_MAX_CONCURRENCY)


def test_resolve_check_balances_workers_ignores_overrides_set_while_still_in_auto_mode(tmp_path):
    """Overrides are only read when mode == custom (per
    structured-outline.md #1.6) -- setting them without switching modes
    must not change what the next job dispatch uses."""
    db_path = tmp_path / "scan_settings.db"

    set_overrides(
        {"check_balances_global_workers": 99, "check_balances_per_coin_concurrency": 42}, db_path=db_path
    )

    global_workers, per_coin = resolve_check_balances_workers(db_path=db_path)
    assert (global_workers, per_coin) == (GLOBAL_MAX_WORKERS, PER_COIN_MAX_CONCURRENCY)


def test_resolve_check_balances_workers_uses_custom_overrides_when_set(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    set_mode("custom", db_path=db_path)
    set_overrides(
        {"check_balances_global_workers": 99, "check_balances_per_coin_concurrency": 42}, db_path=db_path
    )

    global_workers, per_coin = resolve_check_balances_workers(db_path=db_path)
    assert (global_workers, per_coin) == (99, 42)


def test_resolve_check_balances_workers_partial_override_falls_back_for_the_unset_field(tmp_path):
    db_path = tmp_path / "scan_settings.db"

    set_mode("custom", db_path=db_path)
    set_overrides({"check_balances_global_workers": 99}, db_path=db_path)  # per-coin left null

    global_workers, per_coin = resolve_check_balances_workers(db_path=db_path)
    assert global_workers == 99
    assert per_coin == PER_COIN_MAX_CONCURRENCY


def test_settings_persist_across_separate_get_settings_calls(tmp_path):
    """Not just a single-process-lifetime cache -- must actually be
    durable in the sqlite file, since a later process/job dispatch reads
    it fresh."""
    db_path = tmp_path / "scan_settings.db"

    set_mode("custom", db_path=db_path)
    set_overrides({"check_balances_global_workers": 7}, db_path=db_path)

    first = get_settings(db_path=db_path)
    second = get_settings(db_path=db_path)
    assert first == second == {
        "mode": "custom",
        "overrides": {
            "search_walk_threads": None,
            "analyze_processes": None,
            "check_balances_global_workers": 7,
            "check_balances_per_coin_concurrency": None,
        },
    }


# --- sse-06: auto-detection formulas (structured-outline.md #1.6) ---


def test_auto_search_walk_threads_formula_table():
    """min(4, max(1, cpu_count() // 2)) -- passed directly, no os.cpu_count()
    mocking needed since the function takes an explicit override."""
    cases = {1: 1, 2: 1, 3: 1, 4: 2, 6: 3, 8: 4, 16: 4, 32: 4}
    for cpu_count, expected in cases.items():
        assert auto_search_walk_threads(cpu_count=cpu_count) == expected


def test_auto_analyze_processes_formula_table():
    """max(1, cpu_count() - 1)."""
    cases = {1: 1, 2: 1, 4: 3, 8: 7, 16: 15}
    for cpu_count, expected in cases.items():
        assert auto_analyze_processes(cpu_count=cpu_count) == expected


def test_auto_search_walk_threads_reads_live_cpu_count_when_not_overridden(monkeypatch):
    """No cpu_count kwarg given -- must read the current machine's live
    os.cpu_count(), proven here via a mocked value for a deterministic
    assertion (an un-mocked real machine's core count isn't fixed)."""
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    assert auto_search_walk_threads() == 4


def test_auto_analyze_processes_reads_live_cpu_count_when_not_overridden(monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    assert auto_analyze_processes() == 7


def test_auto_formulas_fall_back_to_one_when_cpu_count_is_undetectable(monkeypatch):
    """os.cpu_count() can return None on some machines -- must never
    propagate a None into the formula's arithmetic."""
    monkeypatch.setattr("os.cpu_count", lambda: None)
    assert auto_search_walk_threads() == 1
    assert auto_analyze_processes() == 1


def test_get_auto_profile_computes_all_four_fields_live(monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)

    profile = get_auto_profile()

    assert profile == {
        "search_walk_threads": 4,
        "analyze_processes": 7,
        "check_balances_global_workers": GLOBAL_MAX_WORKERS,
        "check_balances_per_coin_concurrency": PER_COIN_MAX_CONCURRENCY,
    }


@pytest.mark.parametrize("cpu_count", [1, 4, 64, 128])
def test_get_auto_profile_check_balances_fields_stay_fixed_regardless_of_cpu_count(monkeypatch, cpu_count):
    """Confirmed requirement: check_balances' two fields are tuned
    against a real external API's rate limit, not local hardware --
    cpu_count() must never drive them, at any core count."""
    monkeypatch.setattr("os.cpu_count", lambda: cpu_count)

    profile = get_auto_profile()

    assert profile["check_balances_global_workers"] == GLOBAL_MAX_WORKERS
    assert profile["check_balances_per_coin_concurrency"] == PER_COIN_MAX_CONCURRENCY


# --- sse-06: resolve_search_walk_threads / resolve_analyze_processes ---


def test_resolve_search_walk_threads_uses_auto_value_in_auto_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    db_path = tmp_path / "scan_settings.db"

    assert resolve_search_walk_threads(db_path=db_path) == 4


def test_resolve_analyze_processes_uses_auto_value_in_auto_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    db_path = tmp_path / "scan_settings.db"

    assert resolve_analyze_processes(db_path=db_path) == 7


def test_resolve_search_walk_threads_ignores_overrides_set_while_still_in_auto_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    db_path = tmp_path / "scan_settings.db"
    set_overrides({"search_walk_threads": 99}, db_path=db_path)

    assert resolve_search_walk_threads(db_path=db_path) == 4


def test_resolve_search_walk_threads_uses_custom_override_when_set(tmp_path, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)  # auto would be 4 -- proves the override wins, not auto
    db_path = tmp_path / "scan_settings.db"
    set_mode("custom", db_path=db_path)
    set_overrides({"search_walk_threads": 99}, db_path=db_path)

    assert resolve_search_walk_threads(db_path=db_path) == 99


def test_resolve_analyze_processes_uses_custom_override_when_set(tmp_path, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    db_path = tmp_path / "scan_settings.db"
    set_mode("custom", db_path=db_path)
    set_overrides({"analyze_processes": 99}, db_path=db_path)

    assert resolve_analyze_processes(db_path=db_path) == 99


def test_resolve_search_walk_threads_partial_override_falls_back_to_auto_for_unset_field(tmp_path, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    db_path = tmp_path / "scan_settings.db"
    set_mode("custom", db_path=db_path)
    set_overrides({"analyze_processes": 99}, db_path=db_path)  # search_walk_threads left null

    assert resolve_search_walk_threads(db_path=db_path) == 4


def test_custom_mode_with_all_fields_set_never_consults_auto_detection(tmp_path, monkeypatch):
    """The confirmed acceptance criterion: when custom mode is active
    with real values for every field, auto-detection must not be
    consulted at all -- proven by making os.cpu_count() raise if it's
    ever called during resolution."""

    def _boom():
        raise AssertionError("auto-detection must not be consulted in custom mode")

    db_path = tmp_path / "scan_settings.db"
    set_mode("custom", db_path=db_path)
    set_overrides(
        {
            "search_walk_threads": 2,
            "analyze_processes": 3,
            "check_balances_global_workers": 10,
            "check_balances_per_coin_concurrency": 5,
        },
        db_path=db_path,
    )
    monkeypatch.setattr("os.cpu_count", _boom)

    assert resolve_search_walk_threads(db_path=db_path) == 2
    assert resolve_analyze_processes(db_path=db_path) == 3
    assert resolve_check_balances_workers(db_path=db_path) == (10, 5)
