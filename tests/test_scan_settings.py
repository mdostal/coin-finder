import pytest

from tools.check_wallet_balances import GLOBAL_MAX_WORKERS, PER_COIN_MAX_CONCURRENCY
from web.scan_settings import get_settings, resolve_check_balances_workers, set_mode, set_overrides


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
