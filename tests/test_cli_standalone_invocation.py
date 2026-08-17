import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOOLS_IMPORTING_CONFIG_OR_SERVICES = [
    "tools/search_wallets.py",
    "tools/analyze_wallets.py",
    "tools/check_wallet_balances.py",
    "tools/build_wallet_graph.py",
    "tools/crawl_transaction_graph.py",
    "tools/scan_google_drive.py",
]


def _run_help_without_pythonpath(script):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, script, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def test_every_tool_importing_config_or_services_runs_standalone_without_pythonpath():
    failures = []
    for script in TOOLS_IMPORTING_CONFIG_OR_SERVICES:
        result = _run_help_without_pythonpath(script)
        if result.returncode != 0 or "ModuleNotFoundError" in result.stderr:
            failures.append((script, result.returncode, result.stderr))

    assert not failures, f"Standalone invocation failed for: {failures}"
