import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import run_pipeline
from web.bound_targets import add_target, list_mounted_volumes, list_targets, remove_target
from web.mounts import install_rclone, is_mounted, is_rclone_installed, list_mounts, list_remotes, mount, remote_status, remove_remote, unmount
from tools.check_fork_coins import check_fork_coins_for_addresses, render_fork_coin_report
from tools.check_wallet_balances import check_wallet_balances, load_service, _check_balance_with_retries
from config.wallet import WALLET_SERVICES
from tools.crawl_transaction_graph import crawl_wallet_cluster, load_seed_addresses, render_cluster_report
from tools.detect_hidden_volumes import render_hidden_volumes_report, scan_for_hidden_volumes
from tools.find_seed_phrases import find_candidate_phrases, scan_directory
from tools.match_seed_phrases import load_phrases_from_file, match_phrases, render_match_report
from tools.scan_google_drive import get_drive_service, scan_drive_for_wallets
from tools.scan_gmail import (
    DEFAULT_QUERIES as DEFAULT_GMAIL_QUERIES,
    bind_gmail_account,
    is_gmail_bound,
    scan_gmail_for_wallet_clues,
    unbind_gmail_account,
)
from tools.scan_wallet_dat import check_addresses_balances, scan_wallet_for_addresses
from tools.extract_private_key import extract_wif_for_address
from web.findings import archive, archive_all_zero_balance, clear_all_findings, list_findings, record_finding, set_watched, unarchive
from tools.unlock_exodus_wallet import run_exodus_unlock
from tools.unlock_wallet import check_network_status, run_unlock
from web.jobs import consume_job_result, create_job, get_job, list_jobs, report_progress, run_job, running_jobs_count, start_job
from web.native_dialogs import pick_path
from web.paths import app_data_dir, is_frozen
from web.update import check_for_update, perform_update
from web.vault import add_vault_entry, edit_vault_entry, list_vault_entries, resolve_vault_entries_with_values, revoke_vault_entry
from web.rclone_wizard import DEFAULT_SCOPE, SCOPE_CHOICES, create_remote
from web.crawl_runs import clear_all_crawl_runs, compute_confidence_scores, find_overlap_addresses, list_crawl_runs, record_crawl_run
from web.scan_history import clear_scan_history, list_scan_history, record_scan
from tools.scan_index import DEFAULT_DB_PATH as SCAN_INDEX_DB_PATH, clear_scan_index, list_scanned_files
from web import ai_assist

REPO_ROOT = Path(__file__).resolve().parent.parent
# Unchanged (REPO_ROOT/ui_output) for a source install -- only a frozen
# desktop build's output moves to the persistent app-data dir, since only
# that case has the "gets wiped on every reinstall" problem app_data_dir()
# exists to fix.
DEFAULT_OUTPUT_ROOT = (app_data_dir() if is_frozen() else REPO_ROOT) / "ui_output"
DEFAULT_STAGING_DIR = DEFAULT_OUTPUT_ROOT / "staged"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def create_app(host="127.0.0.1"):
    """
    Flask app factory. Refuses to construct an app bound to anything but
    127.0.0.1/localhost -- this app handles local wallet files and
    (transiently, for unlock flows) real password/seed candidates, and must
    never be reachable beyond this machine. Enforced here, not left to
    whatever `app.run(host=...)` is called with later.
    """
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(
            f"Refusing to create app bound to host={host!r}. This app handles local "
            "wallet files and unlock candidates -- it must only bind to "
            f"{'/'.join(ALLOWED_HOSTS)}."
        )

    app = Flask(__name__)
    app.jinja_env.filters["timestamp_to_local"] = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

    @app.context_processor
    def inject_running_jobs_count():
        # Powers the always-visible "N running" header chip on every page
        # (base.html) -- the fix for a background job looking "cancelled"
        # just because you navigated away from its own status page.
        return {"running_jobs_count": running_jobs_count()}

    @app.context_processor
    def inject_active_nav_group():
        # Which of the 4 top-level nav groups (base.html) the current page
        # belongs to, so its group link and in-page tab strip can render
        # active -- purely presentational, computed from the endpoint so
        # no route needs to pass this explicitly.
        return {"active_nav_group": _NAV_GROUP_BY_ENDPOINT.get(request.endpoint), "nav_groups": _NAV_GROUPS}

    @app.route("/healthz")
    def healthz():
        """
        Deliberately cheap liveness check -- zero I/O, not a repurposing of
        `/` (which loads targets/volumes/findings). Exists so the desktop
        app shell (src-tauri/) can cheaply poll "is the sidecar up yet"
        without that poll itself being slow.
        """
        return jsonify({"status": "ok"})

    @app.route("/api/status")
    def api_status():
        status = check_network_status()
        return jsonify(
            {
                "network_status": status,
                "features": {
                    "unlock": "requires OFFLINE -- refuses to run otherwise" if status != "OFFLINE" else "available",
                    "scan": "available (uses public blockchain/coin APIs -- needs network)" if status != "OFFLINE" else "unavailable while offline (balance checks need network)",
                    "drive_scan": "available (needs network for Google's API)" if status != "OFFLINE" else "unavailable while offline",
                },
            }
        )

    @app.route("/")
    def index():
        findings = list_findings()
        return render_template(
            "index.html",
            error=request.args.get("error"),
            targets=list_targets(),
            volumes=list_mounted_volumes(),
            findings_count=len(findings),
            findings_needs_review_count=sum(1 for f in findings if f["balance"] != 0.0),
            scan_index_count=len(list_scanned_files()),
            interrupted_scans=_interrupted_scans(),
            interrupted_balance_checks=_interrupted_balance_checks(),
        )

    @app.route("/scan-index/clear", methods=["POST"])
    def scan_index_clear():
        clear_scan_index()
        return redirect(url_for("index"))

    @app.route("/api/browse")
    def browse():
        raw_path = request.args.get("path") or str(Path.home())
        try:
            target = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError) as e:
            return jsonify({"error": f"Could not resolve path: {e}"}), 400

        if not target.exists() or not target.is_dir():
            return jsonify({"error": f"Not a directory: {target}"}), 400

        try:
            subdirectories = sorted(
                str(child) for child in target.iterdir() if child.is_dir() and not child.is_symlink()
            )
        except OSError as e:
            return jsonify({"error": f"Could not list directory: {e}"}), 400

        return jsonify({"path": str(target), "subdirectories": subdirectories})

    @app.route("/api/pick-path", methods=["POST"])
    def api_pick_path():
        mode = request.form.get("mode") or "file"
        try:
            path = pick_path(mode=mode)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"path": path})

    @app.route("/scan", methods=["POST"])
    def start_scan():
        input_dir = (request.form.get("input_dir") or "").strip()
        if not input_dir or not Path(input_dir).is_dir():
            return render_template("index.html", error=f"Not a directory: {input_dir}"), 400

        # A real unchecked HTML checkbox submits nothing at all -- "on by
        # default" is achieved in index.html by rendering the checkbox
        # pre-checked (main scan form) or as a hidden field fixed to "1"
        # (the per-target quick-scan buttons, which show no checkbox at
        # all), not by treating an absent field as "on" here.
        index_db_path = SCAN_INDEX_DB_PATH if request.form.get("dedup_index") else None

        # Stage 1 only (search + analyze) -- fast, no network calls. See
        # scan_check_balances() for the slow stage, kicked off separately
        # once you've seen what stage 1 actually found.
        job_id = create_job(kind="find", label=input_dir)
        start_job(job_id, _run_find_job, input_dir, job_id, index_db_path)
        return redirect(url_for("scan_status", job_id=job_id))

    @app.route("/scan/<job_id>")
    def scan_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return render_template("scan.html", job_id=job_id, job=job)

    @app.route("/scan/<job_id>/check-balances", methods=["POST"])
    def scan_check_balances(job_id):
        job = get_job(job_id)
        if job is None or job.get("kind") != "find" or job["status"] != "done":
            abort(404)

        output_dir = job["result"]["output_dir"]
        balances_job_id = create_job(kind="check-balances", label=job["label"])
        start_job(balances_job_id, _run_check_balances_job, output_dir, balances_job_id)
        return redirect(url_for("scan_balances_status", job_id=balances_job_id))

    @app.route("/scan/<job_id>/check-balances-selected", methods=["POST"])
    def scan_check_balances_selected(job_id):
        job = get_job(job_id)
        if job is None or job.get("kind") != "find" or job["status"] != "done":
            abort(404)

        selected_files = request.form.getlist("files")
        if not selected_files:
            return render_template("scan.html", job_id=job_id, job=job, error="Select at least one file first."), 400

        output_dir = job["result"]["output_dir"]
        balances_job_id = create_job(kind="check-balances", label=f"{len(selected_files)} selected file(s)")
        start_job(balances_job_id, _run_check_balances_selected_job, output_dir, selected_files, balances_job_id)
        return redirect(url_for("scan_balances_status", job_id=balances_job_id))

    @app.route("/scans")
    def scans_page():
        return render_template("scans.html", scans=list_scan_history())

    @app.route("/scans/clear", methods=["POST"])
    def scans_clear():
        clear_scan_history()
        return redirect(url_for("scans_page"))

    @app.route("/scans/view")
    def scan_view():
        # Durable counterpart to scan_status() -- reads find_summary.json
        # straight off disk instead of an in-memory job, so it works after
        # a restart / from a different session. output_dir doubles as
        # scan_history's own primary key, so no separate ID scheme needed.
        output_dir = (request.args.get("output_dir") or "").strip()
        result = _read_json(Path(output_dir) / "find_summary.json") if output_dir else None
        if result is None:
            abort(404)

        balances = _load_scan_results(output_dir)
        return render_template("scan.html", job=None, job_id=None, output_dir=output_dir, result=result, balances=balances, error=None)

    @app.route("/scans/view/check-balances", methods=["POST"])
    def scans_view_check_balances():
        output_dir = (request.form.get("output_dir") or "").strip()
        if not output_dir or not Path(output_dir).is_dir():
            abort(404)

        balances_job_id = create_job(kind="check-balances", label=output_dir)
        start_job(balances_job_id, _run_check_balances_job, output_dir, balances_job_id)
        return redirect(url_for("scan_balances_status", job_id=balances_job_id))

    @app.route("/scans/view/check-balances-selected", methods=["POST"])
    def scans_view_check_balances_selected():
        output_dir = (request.form.get("output_dir") or "").strip()
        if not output_dir or not Path(output_dir).is_dir():
            abort(404)

        selected_files = request.form.getlist("files")
        if not selected_files:
            result = _read_json(Path(output_dir) / "find_summary.json")
            balances = _load_scan_results(output_dir)
            return (
                render_template(
                    "scan.html", job=None, job_id=None, output_dir=output_dir, result=result, balances=balances, error="Select at least one file first."
                ),
                400,
            )

        balances_job_id = create_job(kind="check-balances", label=f"{len(selected_files)} selected file(s)")
        start_job(balances_job_id, _run_check_balances_selected_job, output_dir, selected_files, balances_job_id)
        return redirect(url_for("scan_balances_status", job_id=balances_job_id))

    @app.route("/scan/balances/<job_id>")
    def scan_balances_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)

        results = None
        if job["status"] == "done":
            results = _load_scan_results(job["result"]["output_dir"])

        return render_template("scan_balances.html", job_id=job_id, job=job, results=results)

    @app.route("/api/jobs/<job_id>")
    def job_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return jsonify(job)

    @app.route("/item/scan-wallet-dat", methods=["POST"])
    def item_scan_wallet_dat():
        wallet_path = (request.form.get("wallet_path") or "").strip()
        if not wallet_path or not Path(wallet_path).is_file():
            return render_template("index.html", error=f"Not a file: {wallet_path}"), 400

        job_id = create_job(kind="scan-wallet-dat", label=wallet_path)
        start_job(job_id, _run_scan_wallet_dat_job, wallet_path, job_id)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/crawl", methods=["POST"])
    def item_crawl():
        addresses = _split_lines(request.form.get("addresses"))
        if not addresses:
            return render_template("index.html", error="Enter at least one address."), 400

        generations = _clamp_generations(request.form.get("generations"))
        job_id = run_job(_run_crawl_job, addresses, generations, kind="crawl", label=f"{len(addresses)} address(es)")
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/fork-coins", methods=["POST"])
    def item_fork_coins():
        addresses = _split_lines(request.form.get("addresses"))
        if not addresses:
            return render_template("index.html", error="Enter at least one address."), 400

        job_id = run_job(_run_fork_coins_job, addresses, kind="fork-coins", label=f"{len(addresses)} address(es)")
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/lookup")
    def lookup_form():
        return render_template("lookup.html", coins=sorted(WALLET_SERVICES.keys()), error=None)

    @app.route("/lookup", methods=["POST"])
    def lookup_submit():
        coin = (request.form.get("coin") or "").strip()
        address = (request.form.get("address") or "").strip()
        if not coin or not address:
            return render_template("lookup.html", coins=sorted(WALLET_SERVICES.keys()), error="Enter both a coin and an address."), 400

        job_id = run_job(_run_quick_lookup_job, coin, address, kind="quick-lookup", label=f"{coin}: {address}")
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/find-seed-phrases", methods=["POST"])
    def item_find_seed_phrases():
        target_path = (request.form.get("target_path") or "").strip()
        if not target_path or not Path(target_path).exists():
            return render_template("index.html", error=f"Not found: {target_path}"), 400

        job_id = run_job(_run_find_seed_phrases_job, target_path, kind="find-seed-phrases", label=target_path)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/match-seed-phrases", methods=["POST"])
    def item_match_seed_phrases():
        phrases_file = (request.form.get("phrases_file") or "").strip()
        if not phrases_file or not Path(phrases_file).is_file():
            return render_template("index.html", error=f"Not a file: {phrases_file}"), 400

        job_id = run_job(_run_match_seed_phrases_job, phrases_file, kind="match-seed-phrases", label=phrases_file)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item-result/<job_id>")
    def item_result(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return render_template("item_result.html", job_id=job_id, job=job)

    @app.route("/item/unlock", methods=["GET"])
    def item_unlock_form():
        return render_template("unlock.html", network_status=check_network_status(), vault_entries=list_vault_entries(), error=None)

    @app.route("/item/unlock", methods=["POST"])
    def item_unlock():
        # Re-checked here, at the moment of the actual request -- never
        # trusted from the GET page load or from anything the client sent.
        # Default behavior (checkbox unchecked) still refuses when online --
        # but the user can explicitly choose to proceed anyway. This is an
        # informed-choice override, not a silent bypass: we ask, they decide.
        network_status = check_network_status()
        allow_online = request.form.get("allow_online") == "1"

        if network_status != "OFFLINE" and not allow_online:
            return (
                render_template(
                    "unlock.html",
                    network_status=network_status,
                    vault_entries=list_vault_entries(),
                    error=(
                        f"Network status is {network_status}, not OFFLINE. Testing real passwords "
                        "against a real wallet is safest with network disabled. Disconnect and try "
                        'again, or check "run anyway" below if you understand the risk and want to '
                        "proceed online."
                    ),
                ),
                409,
            )

        target_path = (request.form.get("target_path") or "").strip()
        candidates = request.form.get("candidates") or ""
        kind = request.form.get("kind") or "btcrecover"
        vault_names = request.form.getlist("vault_entries")

        if not target_path or not Path(target_path).is_file():
            return render_template("unlock.html", network_status=network_status, vault_entries=list_vault_entries(), error=f"Not a file: {target_path}"), 400
        if not candidates.strip() and not vault_names:
            return (
                render_template(
                    "unlock.html",
                    network_status=network_status,
                    vault_entries=list_vault_entries(),
                    error="Enter at least one candidate password/phrase, or select a saved vault entry to try.",
                ),
                400,
            )

        # Free-text candidates and resolved vault values are combined into
        # one local file -- never placed in the URL/query string, matching
        # the CLI tools' file-only-candidates rule. vault_pairs is kept only
        # in memory, for this job's own after-the-fact "which label matched"
        # comparison -- never written to disk.
        vault_pairs = resolve_vault_entries_with_values(vault_names) if vault_names else []
        lines = _split_lines(candidates) + [value for _, value in vault_pairs]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n".join(lines))
            candidates_path = f.name

        job_fn = _run_exodus_unlock_job if kind == "exodus" else _run_btcrecover_unlock_job
        job_id = run_job(
            job_fn, target_path, candidates_path, allow_online=allow_online, vault_pairs=vault_pairs, secret=True, kind="unlock", label=target_path
        )
        return redirect(url_for("item_unlock_status", job_id=job_id))

    @app.route("/item/unlock-status/<job_id>")
    def item_unlock_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return render_template("unlock_status.html", job_id=job_id, job=job)

    @app.route("/item/unlock-result/<job_id>")
    def item_unlock_result(job_id):
        job = consume_job_result(job_id)
        if job is None:
            abort(404)
        return render_template("unlock_result.html", job_id=job_id, job=job)

    @app.route("/auto-unlock", methods=["GET"])
    def auto_unlock_form():
        # Deliberately does NOT call list_vault_entries() here -- confirmed
        # live (same root cause as the 0.32.2 wizard-page fix): a vault
        # round-trip can take 10-15s from this app's own subprocess
        # context, and this app's server is single-threaded, so that would
        # block this page's render (a frequent, should-be-instant action)
        # for everyone. The real vault-entries check still happens in
        # auto_unlock_submit() below -- a less frequent action where
        # "wait a moment before the job starts" is already the expected
        # shape, same as any other job-starting POST in this app.
        #
        # ?wallet_path=<path> scopes the list to just that one known
        # wallet -- the "click a finding, try unlock" entry point
        # (findings.html), instead of requiring the full list every time.
        # Silently ignored if it isn't actually a known wallet path (no
        # error banner for a stale/malformed link -- just shows every
        # known wallet, same as the plain /auto-unlock page).
        wallet_path = (request.args.get("wallet_path") or "").strip()
        wallet_paths = _known_wallet_paths()
        if wallet_path and wallet_path in wallet_paths:
            wallet_paths = [wallet_path]

        return render_template(
            "auto_unlock.html",
            network_status=check_network_status(),
            wallet_paths=wallet_paths,
            scoped_wallet_path=wallet_path if wallet_path in wallet_paths else None,
            error=None,
        )

    @app.route("/auto-unlock", methods=["POST"])
    def auto_unlock_submit():
        # Same re-check, at the moment of the actual request, as
        # item_unlock() -- never trusted from the GET page load. Default
        # (checkbox unchecked) still refuses when online; an explicit
        # allow_online=1 is an informed-choice override, not a bypass.
        network_status = check_network_status()
        allow_online = request.form.get("allow_online") == "1"

        # Carries the GET form's scoping through the POST -- a hidden
        # field, not re-derived from the query string (this is a POST).
        wallet_path = (request.form.get("wallet_path") or "").strip()
        known_wallet_paths = _known_wallet_paths()
        scoped_wallet_paths = [wallet_path] if wallet_path and wallet_path in known_wallet_paths else None

        if network_status != "OFFLINE" and not allow_online:
            return (
                render_template(
                    "auto_unlock.html",
                    network_status=network_status,
                    wallet_paths=scoped_wallet_paths or known_wallet_paths,
                    scoped_wallet_path=wallet_path if scoped_wallet_paths else None,
                    error=(
                        f"Network status is {network_status}, not OFFLINE. Testing real passwords "
                        "against real wallets is safest with network disabled. Disconnect and try "
                        'again, or check "run anyway" below if you understand the risk and want to '
                        "proceed online."
                    ),
                ),
                409,
            )

        vault_entries = list_vault_entries()
        if not vault_entries:
            return (
                render_template(
                    "auto_unlock.html",
                    network_status=network_status,
                    wallet_paths=scoped_wallet_paths or known_wallet_paths,
                    scoped_wallet_path=wallet_path if scoped_wallet_paths else None,
                    error="No enabled vault entries to try. Save at least one password in the vault first.",
                ),
                400,
            )

        label = wallet_path if scoped_wallet_paths else "all known wallets"
        job_id = run_job(
            _run_auto_unlock_job, allow_online=allow_online, wallet_paths=scoped_wallet_paths, secret=True, kind="auto-unlock", label=label
        )
        return redirect(url_for("auto_unlock_status", job_id=job_id))

    @app.route("/auto-unlock/status/<job_id>")
    def auto_unlock_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return render_template("auto_unlock_status.html", job_id=job_id, job=job)

    @app.route("/auto-unlock/result/<job_id>")
    def auto_unlock_result(job_id):
        job = consume_job_result(job_id)
        if job is None:
            abort(404)
        return render_template("auto_unlock_result.html", job_id=job_id, job=job)

    @app.route("/item/extract-key", methods=["GET"])
    def item_extract_key_form():
        return render_template("extract_key.html", network_status=check_network_status(), error=None)

    @app.route("/item/extract-key", methods=["POST"])
    def item_extract_key():
        # Re-checked here, at the moment of the actual request -- same
        # discipline as /item/unlock, including the same informed-choice
        # override: default (checkbox unchecked) still refuses, an explicit
        # opt-in is honored.
        network_status = check_network_status()
        allow_online = request.form.get("allow_online") == "1"

        if network_status != "OFFLINE" and not allow_online:
            return (
                render_template(
                    "extract_key.html",
                    network_status=network_status,
                    error=(
                        f"Network status is {network_status}, not OFFLINE. Extracting a real private "
                        "key is safest with network disabled. Disconnect and try again, or check "
                        '"run anyway" below if you understand the risk and want to proceed online.'
                    ),
                ),
                409,
            )

        wallet_path = (request.form.get("wallet_path") or "").strip()
        address = (request.form.get("address") or "").strip()

        if not wallet_path or not Path(wallet_path).is_file():
            return render_template("extract_key.html", network_status=network_status, error=f"Not a file: {wallet_path}"), 400
        if not address:
            return render_template("extract_key.html", network_status=network_status, error="Enter the address to extract a key for."), 400

        job_id = run_job(
            extract_wif_for_address, wallet_path, address, allow_online=allow_online, secret=True, kind="extract-key", label=f"{address} ({wallet_path})"
        )
        return redirect(url_for("item_extract_key_status", job_id=job_id))

    @app.route("/item/extract-key-status/<job_id>")
    def item_extract_key_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return render_template("extract_key_status.html", job_id=job_id, job=job)

    @app.route("/item/extract-key-result/<job_id>")
    def item_extract_key_result(job_id):
        job = consume_job_result(job_id)
        if job is None:
            abort(404)
        return render_template("extract_key_result.html", job_id=job_id, job=job)

    @app.route("/findings")
    def findings_page():
        include_archived = request.args.get("include_archived") == "1"
        return render_template(
            "findings.html",
            findings=list_findings(include_archived=include_archived),
            include_archived=include_archived,
            overlap_count=len(find_overlap_addresses()),
            related_count=len(compute_confidence_scores(_known_bitcoin_addresses())),
        )

    @app.route("/findings/related")
    def findings_related():
        return render_template("related_accounts.html", candidates=compute_confidence_scores(_known_bitcoin_addresses()))

    @app.route("/findings/archive", methods=["POST"])
    def findings_archive():
        archive(request.form.get("coin"), request.form.get("address"))
        return redirect(url_for("findings_page"))

    @app.route("/findings/unarchive", methods=["POST"])
    def findings_unarchive():
        unarchive(request.form.get("coin"), request.form.get("address"))
        return redirect(url_for("findings_page", include_archived="1"))

    @app.route("/findings/archive-all-zero", methods=["POST"])
    def findings_archive_all_zero():
        archive_all_zero_balance()
        return redirect(url_for("findings_page"))

    @app.route("/findings/watch", methods=["POST"])
    def findings_watch():
        set_watched(request.form.get("coin"), request.form.get("address"), True, note=(request.form.get("note") or "").strip())
        return redirect(url_for("findings_page", include_archived="1" if request.form.get("include_archived") == "1" else None))

    @app.route("/findings/unwatch", methods=["POST"])
    def findings_unwatch():
        set_watched(request.form.get("coin"), request.form.get("address"), False)
        return redirect(url_for("findings_page", include_archived="1" if request.form.get("include_archived") == "1" else None))

    @app.route("/findings/clear-all", methods=["POST"])
    def findings_clear_all():
        clear_all_findings()
        return redirect(url_for("findings_page"))

    @app.route("/findings/group-view")
    def group_view_page():
        return render_template("group_view.html", overlaps=find_overlap_addresses(), runs=list_crawl_runs())

    @app.route("/findings/group-view/clear", methods=["POST"])
    def group_view_clear():
        clear_all_crawl_runs()
        return redirect(url_for("group_view_page"))

    @app.route("/item/stage", methods=["POST"])
    def item_stage():
        file_path = (request.form.get("file_path") or "").strip()
        staging_dir = (request.form.get("staging_dir") or "").strip() or str(DEFAULT_STAGING_DIR)

        source = Path(file_path)
        if not file_path or not source.is_file():
            return render_template("index.html", error=f"Not a file: {file_path}"), 400

        destination_dir = Path(staging_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name

        if destination.exists():
            return (
                render_template(
                    "index.html",
                    error=f"Refusing to overwrite existing staged file: {destination}",
                ),
                409,
            )

        shutil.copy2(source, destination)
        return render_template("index.html", error=None, staged=str(destination))

    @app.route("/drive")
    def drive_form():
        return render_template("drive.html", error=None)

    @app.route("/drive/scan", methods=["POST"])
    def drive_scan():
        output_dir = (request.form.get("output_dir") or "").strip()
        query = (request.form.get("query") or "").strip() or None
        if not output_dir:
            return render_template("drive.html", error="Enter a local output directory."), 400

        job_id = create_job(kind="drive-scan", label=output_dir)
        start_job(job_id, _run_drive_scan_job, output_dir, query, job_id)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/gmail")
    def gmail_form():
        return render_template(
            "gmail.html",
            bound=is_gmail_bound(),
            default_queries=DEFAULT_GMAIL_QUERIES,
            default_output_dir=str(DEFAULT_OUTPUT_ROOT / "gmail"),
            error=None,
        )

    @app.route("/gmail/connect", methods=["POST"])
    def gmail_connect():
        client_id = (request.form.get("client_id") or "").strip()
        client_secret = request.form.get("client_secret") or ""
        if not client_id or not client_secret:
            return (
                render_template(
                    "gmail.html",
                    bound=is_gmail_bound(),
                    default_queries=DEFAULT_GMAIL_QUERIES,
                    default_output_dir=str(DEFAULT_OUTPUT_ROOT / "gmail"),
                    error="Enter both the client ID and client secret.",
                ),
                400,
            )

        job_id = create_job(kind="gmail-connect", label="Gmail")
        start_job(job_id, _run_gmail_connect_job, client_id, client_secret, job_id)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/gmail/disconnect", methods=["POST"])
    def gmail_disconnect():
        unbind_gmail_account()
        return redirect(url_for("gmail_form"))

    @app.route("/gmail/search", methods=["POST"])
    def gmail_search():
        if not is_gmail_bound():
            abort(409)

        output_dir = (request.form.get("output_dir") or "").strip() or str(DEFAULT_OUTPUT_ROOT / "gmail")
        queries = [q.strip() for q in (request.form.get("queries") or "").splitlines() if q.strip()] or None

        job_id = create_job(kind="gmail-scan", label="Gmail search")
        start_job(job_id, _run_gmail_scan_job, output_dir, queries, job_id)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/targets")
    def targets_page():
        return render_template("targets.html", targets=list_targets(), volumes=list_mounted_volumes(), error=None)

    @app.route("/targets/add", methods=["POST"])
    def targets_add():
        label = (request.form.get("label") or "").strip()
        path = (request.form.get("path") or "").strip()
        kind = (request.form.get("kind") or "local").strip()
        if not label or not path:
            return render_template("targets.html", targets=list_targets(), volumes=list_mounted_volumes(), error="Enter both a label and a path."), 400

        add_target(label, path, kind)
        return redirect(url_for("targets_page"))

    @app.route("/targets/remove", methods=["POST"])
    def targets_remove():
        label = (request.form.get("label") or "").strip()
        remove_target(label)
        return redirect(url_for("targets_page"))

    @app.route("/mounts")
    def mounts_page():
        return render_template(
            "mounts.html",
            remotes=_remote_summaries(),
            mounts=_mounts_with_log_tail(),
            rclone_installed=is_rclone_installed(),
            default_mount_point=str(Path.home() / "gdrive-mount"),
            error=None,
        )

    @app.route("/mounts/install-rclone", methods=["POST"])
    def mounts_install_rclone():
        job_id = create_job(kind="install-rclone", label="rclone")
        start_job(job_id, _run_install_rclone_job, job_id)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/mounts/mount", methods=["POST"])
    def mounts_mount():
        remote_name = (request.form.get("remote_name") or "").strip()
        mount_point = (request.form.get("mount_point") or "").strip()
        if not remote_name or not mount_point:
            return render_template("mounts.html", remotes=_remote_summaries(), mounts=_mounts_with_log_tail(), error="Enter both a remote and a mount point."), 400

        mount(remote_name, mount_point)
        return redirect(url_for("mounts_page"))

    @app.route("/mounts/unmount", methods=["POST"])
    def mounts_unmount():
        remote_name = (request.form.get("remote_name") or "").strip()
        unmount(remote_name)
        return redirect(url_for("mounts_page"))

    @app.route("/mounts/remove", methods=["POST"])
    def mounts_remove():
        remote_name = (request.form.get("remote_name") or "").strip()
        if remote_name:
            remove_remote(remote_name)
        return redirect(url_for("mounts_page"))

    @app.route("/mounts/bind", methods=["POST"])
    def mounts_bind():
        remote_name = (request.form.get("remote_name") or "").strip()
        mount_point = (request.form.get("mount_point") or "").strip()
        kind = (request.form.get("kind") or "gdrive-mount").strip()

        if not is_mounted(remote_name):
            return (
                render_template(
                    "mounts.html",
                    remotes=_remote_summaries(),
                    mounts=_mounts_with_log_tail(),
                    error=f"{remote_name} is not actually mounted right now -- refusing to bind it as a scan target. Mount it first.",
                ),
                409,
            )

        add_target(remote_name, mount_point, kind)
        return redirect(url_for("targets_page"))

    @app.route("/vault")
    def vault_page():
        return render_template("vault.html", entries=list_vault_entries(), error=None)

    @app.route("/vault/add", methods=["POST"])
    def vault_add():
        name = (request.form.get("name") or "").strip()
        value = request.form.get("value") or ""
        description = (request.form.get("description") or "").strip()

        if not name or not value:
            return render_template("vault.html", entries=list_vault_entries(), error="Enter both a label and a value."), 400

        # Written to a local temp file server-side, then handed to Portunus
        # by path -- the raw value never travels as a CLI argument or in
        # this route's own memory beyond this call.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(value)
            value_path = f.name

        try:
            add_vault_entry(name, value_path, description=description)
        finally:
            Path(value_path).unlink(missing_ok=True)
        return redirect(url_for("vault_page"))

    @app.route("/vault/revoke", methods=["POST"])
    def vault_revoke():
        revoke_vault_entry((request.form.get("name") or "").strip())
        return redirect(url_for("vault_page"))

    @app.route("/vault/edit", methods=["POST"])
    def vault_edit():
        edit_vault_entry((request.form.get("name") or "").strip(), (request.form.get("description") or "").strip())
        return redirect(url_for("vault_page"))

    @app.route("/wizard")
    def wizard_start():
        return render_template("wizard_start.html")

    @app.route("/wizard/choose", methods=["POST"])
    def wizard_choose():
        target_type = (request.form.get("target_type") or "").strip()
        if target_type == "local":
            return redirect(url_for("index"))
        if target_type == "volume":
            return redirect(url_for("targets_page"))
        if target_type in ("gdrive", "gcs"):
            return redirect(url_for("wizard_cloud", kind=target_type))
        return redirect(url_for("wizard_start"))

    @app.route("/wizard/cloud")
    def wizard_cloud():
        kind = request.args.get("kind", "gdrive")
        return render_template(
            "wizard_cloud.html",
            kind=kind,
            rclone_installed=is_rclone_installed(),
            remotes=_remote_summaries(),
            scope_choices=SCOPE_CHOICES,
            default_scope=DEFAULT_SCOPE,
        )

    @app.route("/wizard/cloud/connect", methods=["POST"])
    def wizard_cloud_connect():
        kind = (request.form.get("kind") or "gdrive").strip()
        remote_name = (request.form.get("remote_name") or "").strip()
        scope = (request.form.get("scope") or DEFAULT_SCOPE).strip()
        client_id = (request.form.get("client_id") or "").strip()
        client_secret = request.form.get("client_secret") or ""

        if not remote_name:
            return (
                render_template(
                    "wizard_cloud.html",
                    kind=kind,
                    rclone_installed=is_rclone_installed(),
                    remotes=_remote_summaries(),
                    scope_choices=SCOPE_CHOICES,
                    default_scope=DEFAULT_SCOPE,
                    error="Enter a name for this connection.",
                ),
                400,
            )

        job_id = create_job(kind="connect-remote", label=remote_name)
        start_job(job_id, _run_connect_remote_job, job_id, remote_name, kind, client_id, client_secret, scope)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/ai-assist/status")
    def ai_assist_status():
        """
        Deliberately its own endpoint, fetched by JS after the wizard page
        has already rendered, never inline in wizard_cloud()'s own render.
        has_api_key() calls into the vault (Portunus), which -- confirmed
        live -- can take upwards of 10-15s to answer from this app's own
        subprocess context (its own agent-facing gating, not a bug in this
        call), even though the same call from a normal terminal is instant.
        Blocking the wizard's main page render on that would make the
        whole page look hung for that long; this way only the small AI
        panel waits, while the actual setup form is usable immediately.
        """
        return {"has_key": ai_assist.has_api_key()}

    @app.route("/ai-assist/ask", methods=["POST"])
    def ai_assist_ask():
        question = (request.get_json(silent=True) or {}).get("question", "").strip()
        if not question:
            return {"ok": False, "error": "Ask something first."}, 400
        try:
            answer = ai_assist.ask(question)
        except RuntimeError as err:
            return {"ok": False, "error": str(err)}, 400
        return {"ok": True, "answer": answer}

    @app.route("/ai-assist/key", methods=["POST"])
    def ai_assist_key():
        api_key = (request.form.get("api_key") or "").strip()
        if api_key:
            ai_assist.set_api_key(api_key)
        return redirect(url_for("wizard_cloud", kind=request.form.get("kind", "gdrive")))

    @app.route("/ai-assist/key/clear", methods=["POST"])
    def ai_assist_key_clear():
        ai_assist.clear_api_key()
        return redirect(url_for("wizard_cloud", kind=request.form.get("kind", "gdrive")))

    @app.route("/jobs")
    def jobs_page():
        return render_template("jobs.html", jobs=list_jobs(), status_endpoint=_job_status_endpoint)

    @app.route("/network")
    def network_page():
        return render_template("network.html", network_status=check_network_status())

    @app.route("/update")
    def update_page():
        return render_template("update.html", status=check_for_update(), result=None)

    @app.route("/update/run", methods=["POST"])
    def update_run():
        result = perform_update()
        return render_template("update.html", status=check_for_update(), result=result)

    return app


# Single source of truth for both the top nav (base.html, one link per
# group, pointing at the group's first tab) and each grouped page's own
# in-page tab strip (_macros.html's group_tabs()) -- one list to keep in
# sync instead of two. Update is listed before Network on purpose (top of
# About): the two used to be a dropdown where the "About" link and the
# "Network" item landed on the same page, which read as pointless -- real
# on-page tabs plus a deliberate order fixes both complaints at once.
_NAV_GROUPS = {
    "sources": {"label": "Sources", "tabs": [("Scan", "index"), ("Cloud — Mounts", "mounts_page"), ("Cloud — Google Drive", "drive_form"), ("Email", "gmail_form"), ("Manage", "targets_page")]},
    "unlock": {"label": "Unlock", "tabs": [("Try", "item_unlock_form"), ("Vault", "vault_page"), ("Extract Key", "item_extract_key_form")]},
    "about": {"label": "About", "tabs": [("Update", "update_page"), ("Network", "network_page")]},
}

_NAV_GROUP_BY_ENDPOINT = {
    # Sources -- everything about acquiring/choosing what to scan, plus the scan action itself.
    "index": "sources",
    "scan_index_clear": "sources",
    "lookup_form": "sources",
    "lookup_submit": "sources",
    "wizard_start": "sources",
    "wizard_choose": "sources",
    "wizard_cloud": "sources",
    "wizard_cloud_connect": "sources",
    "ai_assist_status": "sources",
    "ai_assist_ask": "sources",
    "ai_assist_key": "sources",
    "ai_assist_key_clear": "sources",
    "targets_page": "sources",
    "targets_add": "sources",
    "targets_remove": "sources",
    "mounts_page": "sources",
    "mounts_install_rclone": "sources",
    "mounts_mount": "sources",
    "mounts_unmount": "sources",
    "mounts_remove": "sources",
    "mounts_bind": "sources",
    "drive_form": "sources",
    "drive_scan": "sources",
    "gmail_form": "sources",
    "gmail_connect": "sources",
    "gmail_disconnect": "sources",
    "gmail_search": "sources",
    "start_scan": "sources",
    "scan_status": "sources",
    "scan_check_balances": "sources",
    "scan_check_balances_selected": "sources",
    "scan_balances_status": "sources",
    "scans_page": "sources",
    "scans_clear": "sources",
    "scan_view": "sources",
    "scans_view_check_balances": "sources",
    "scans_view_check_balances_selected": "sources",
    "item_scan_wallet_dat": "sources",
    # Unlock -- testing/saving passwords, extracting keys.
    "item_unlock_form": "unlock",
    "item_unlock": "unlock",
    "item_unlock_status": "unlock",
    "item_unlock_result": "unlock",
    "auto_unlock_form": "unlock",
    "auto_unlock_submit": "unlock",
    "auto_unlock_status": "unlock",
    "auto_unlock_result": "unlock",
    "item_extract_key_form": "unlock",
    "item_extract_key": "unlock",
    "item_extract_key_status": "unlock",
    "item_extract_key_result": "unlock",
    "vault_page": "unlock",
    "vault_add": "unlock",
    "vault_revoke": "unlock",
    "vault_edit": "unlock",
    # Findings -- standalone, no tab strip.
    "findings_page": "findings",
    "findings_archive": "findings",
    "findings_unarchive": "findings",
    "findings_archive_all_zero": "findings",
    "findings_watch": "findings",
    "findings_unwatch": "findings",
    "findings_clear_all": "findings",
    "group_view_page": "findings",
    "group_view_clear": "findings",
    "findings_related": "findings",
    # About -- update mechanics + network transparency.
    "network_page": "about",
    "update_page": "about",
    "update_run": "about",
}

_STATUS_ENDPOINT_BY_KIND = {
    "find": "scan_status",
    "check-balances": "scan_balances_status",
    "unlock": "item_unlock_status",
    "extract-key": "item_extract_key_status",
}


def _job_status_endpoint(kind):
    """Every job kind not listed here shares the generic item_result status page -- true for scan-wallet-dat, crawl, fork-coins, find/match-seed-phrases, drive-scan, and install-rclone."""
    return _STATUS_ENDPOINT_BY_KIND.get(kind, "item_result")


def _split_lines(raw):
    """Splits textarea input into a list of non-blank, non-comment lines."""
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]


def _remote_summaries():
    """
    [{"name", "status"}, ...] for every configured rclone remote -- status
    via remote_status()'s fast, local, per-remote check. list_remotes()
    itself stays a bare name list (used as-is for the mount-point <select>
    and the already-exists check) -- status is layered on only where a
    template actually displays it.
    """
    return [{"name": name, "status": remote_status(name)} for name in list_remotes()]


def _mounts_with_log_tail(lines=15):
    """
    list_mounts(), with a log_tail added for any entry that isn't
    currently healthy -- surfaces the real rclone error (e.g. the
    Homebrew/FUSE incompatibility confirmed live this session) instead
    of a bare "ERROR" pill with no information. Skipped for healthy
    mounts -- no reason to read a log file nobody needs to see.
    """
    mounts = list_mounts()
    for mnt in mounts:
        mnt["log_tail"] = None
        if mnt["is_mounted"] or not mnt.get("log_path"):
            continue
        try:
            with open(mnt["log_path"]) as f:
                mnt["log_tail"] = "".join(f.readlines()[-lines:])
        except OSError:
            pass
    return mounts


def _known_bitcoin_addresses():
    """
    The "known accounts" set for confidence scoring -- Bitcoin findings
    with a real, nonzero balance, or explicitly watched. NOT every
    Bitcoin finding: _run_crawl_job already record_finding()s every
    single address a crawl discovers (co-spend/output partners included,
    regardless of balance) -- caught live, this meant every scored
    candidate was already "known" the instant its own discovery crawl
    finished, making scoring return nothing. A zero-balance address a
    crawl happened to touch isn't one of "our other accounts"; a real
    balance or an explicit watch is.
    """
    return [f["address"] for f in list_findings(include_archived=True) if f["coin"] == "Bitcoin" and (f.get("balance") or f.get("watched"))]


DEFAULT_CRAWL_GENERATIONS = 2
MAX_CRAWL_GENERATIONS = 5


def _clamp_generations(raw):
    """
    Hop-depth control for a Graph crawl -- a real, possibly slow live-
    network BFS, so this is clamped server-side (not just a UI dropdown)
    to [1, MAX_CRAWL_GENERATIONS] regardless of what a request sends.
    Missing/unparseable falls back to DEFAULT_CRAWL_GENERATIONS,
    matching exactly what every caller got before this control existed.
    """
    try:
        return max(1, min(MAX_CRAWL_GENERATIONS, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_CRAWL_GENERATIONS


def _run_scan_wallet_dat_job(wallet_path, job_id):
    scan = scan_wallet_for_addresses(wallet_path)
    checked = check_addresses_balances(
        scan["addresses"],
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )
    significant = [r for r in checked["results"] if r.get("balance")]

    lines = [
        f"Encrypted key records: {scan['encrypted_key_count']}",
        f"Checked {len(checked['results'])} of {checked['total_available']} address(es).",
        f"{len(significant)} address(es) with a non-zero balance.",
    ]
    for entry in significant:
        lines.append(f"- {entry['address']}: {entry['balance']}")

    for entry in checked["results"]:
        record_finding("Bitcoin", entry["address"], entry.get("balance"), source_path=wallet_path, source_label="scan_wallet_dat")

    return {
        "report": "\n".join(lines),
        "encrypted_key_count": scan["encrypted_key_count"],
        "results": checked["results"],
    }


def _run_crawl_job(addresses, max_generations=DEFAULT_CRAWL_GENERATIONS):
    """
    Writes the submitted addresses to a local temp file before calling
    load_seed_addresses -- reuses the CLI's exact file-or-literal contract
    instead of forwarding raw request data directly into it.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(addresses))
        temp_path = f.name

    edges = []
    try:
        seeds = load_seed_addresses(temp_path)
        results = crawl_wallet_cluster(seeds, max_generations=max_generations, edges_out=edges)
    finally:
        Path(temp_path).unlink(missing_ok=True)

    for address, info in results.items():
        record_finding("Bitcoin", address, info.get("balance"), source_label="crawl_transaction_graph")
    record_crawl_run(seeds, results, edges=edges)

    return {"report": render_cluster_report(results), "results": results}


def _run_fork_coins_job(addresses):
    results = check_fork_coins_for_addresses(addresses)

    for address, coin_balances in results.items():
        for coin, balance in coin_balances.items():
            record_finding(coin, address, balance, source_label="check_fork_coins")

    return {"report": render_fork_coin_report(results), "results": results}


def _run_quick_lookup_job(coin, address):
    """
    Skips the whole file-scan pipeline: check ONE address on ONE coin
    directly, reusing tools/check_wallet_balances.py's own
    load_service()/_check_balance_with_retries() unmodified -- the same
    two calls check_wallet_balances() makes per address, just for one
    address instead of a whole file's worth.
    """
    service = load_service(coin)
    balance = _check_balance_with_retries(service, address)
    record_finding(coin, address, balance, source_label="quick_lookup")

    balance_str = "inconclusive (couldn't confirm)" if balance is None else str(balance)
    return {"report": f"{address} ({coin}): {balance_str}"}


def _run_find_seed_phrases_job(target_path):
    """
    Strips phrase text before it ever enters the job registry -- stricter
    than the CLI's own "never printed" rule, since a job result lives in
    server memory rendered into a browser tab rather than a local file only
    the same user can read.
    """
    path = Path(target_path)
    if path.is_dir():
        raw_results = scan_directory(str(path))
    else:
        with open(path, "r", errors="ignore") as f:
            text = f.read()
        candidates = find_candidate_phrases(text)
        raw_results = {str(path): candidates} if candidates else {}

    counts = {file_path: len(candidates) for file_path, candidates in raw_results.items()}
    total = sum(counts.values())

    lines = [f"Found {total} candidate phrase(s) across {len(counts)} file(s)."]
    for file_path, count in counts.items():
        lines.append(f"- {file_path}: {count} candidate(s)")

    return {"report": "\n".join(lines), "counts": counts}


def _run_match_seed_phrases_job(phrases_file):
    phrases = load_phrases_from_file(phrases_file)
    results = match_phrases(phrases)
    return {"report": render_match_report(results), "phrase_count": len(phrases)}


def _match_vault_label(stdout, vault_pairs):
    """
    Ephemeral, in-memory-only comparison against the vault values resolved
    for this run -- never persisted, matching the once-only-secret result
    discipline. Lets the once-only result page say "this was your saved
    'password-1'" without us keeping any password/match history on disk.
    """
    for name, value in vault_pairs or []:
        if value and value in stdout:
            return name
    return None


def _run_btcrecover_unlock_job(wallet_path, candidates_path, allow_online=False, vault_pairs=None):
    try:
        result = run_unlock(wallet_path, candidates_path, allow_online=allow_online)
    finally:
        Path(candidates_path).unlink(missing_ok=True)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "vault_label": _match_vault_label(result.stdout, vault_pairs),
    }


def _run_exodus_unlock_job(seed_seco_path, candidates_path, allow_online=False, vault_pairs=None):
    try:
        result = run_exodus_unlock(seed_seco_path, candidates_path, allow_online=allow_online)
    finally:
        Path(candidates_path).unlink(missing_ok=True)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "vault_label": _match_vault_label(result.stdout, vault_pairs),
    }


def _known_wallet_paths():
    """Every distinct, still-existing source_path recorded on a finding --
    the "known wallet files" set for a batch auto-unlock run. Archived
    findings are included: archived means "reviewed," not "not a real
    wallet file."""
    paths = {f["source_path"] for f in list_findings(include_archived=True) if f.get("source_path")}
    return sorted(p for p in paths if Path(p).is_file())


def _run_auto_unlock_job(allow_online=False, wallet_paths=None):
    """
    Batch unlock: every enabled vault entry tried against every known
    wallet file, in one job. Deliberately does NOT reuse
    _run_btcrecover_unlock_job/_run_exodus_unlock_job -- those each delete
    their own candidates file after one use, correct for a single-wallet
    job but wrong here, where the same candidates file (built once from
    every vault entry) must be reused across every wallet in the batch.
    Calls run_unlock/run_exodus_unlock directly instead, unmodified, and
    owns its own single cleanup after the whole loop -- same file-only-
    secrets discipline as item_unlock(), just batched.

    :param wallet_paths: optional -- restricts the run to exactly these
        wallets (the "Try unlock" action from a single Findings row)
        instead of every known wallet file.
    """
    wallet_paths = wallet_paths if wallet_paths is not None else _known_wallet_paths()
    vault_pairs = resolve_vault_entries_with_values([e["name"] for e in list_vault_entries()])

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(value for _, value in vault_pairs))
        candidates_path = f.name

    # {label: value} for the O(1) lookup below -- the actual matched
    # password is already resolved in vault_pairs at this point, it just
    # never used to reach the result. Consistent with the single-wallet
    # /item/unlock flow, which already shows a real matched value via its
    # raw stdout -- this brings the batch flow in line with that existing
    # precedent, not a new, less-conservative exposure.
    value_by_label = dict(vault_pairs)

    results = {}
    try:
        for i, wallet_path in enumerate(wallet_paths, start=1):
            runner = run_exodus_unlock if wallet_path.endswith(".seco") else run_unlock
            result = runner(wallet_path, candidates_path, allow_online=allow_online)
            label = _match_vault_label(result.stdout, vault_pairs)
            results[wallet_path] = {"vault_label": label, "value": value_by_label.get(label)}
    finally:
        Path(candidates_path).unlink(missing_ok=True)

    return {"results": results}


def _run_install_rclone_job(job_id):
    return install_rclone(progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message))


def _run_connect_remote_job(job_id, remote_name, kind, client_id, client_secret, scope):
    return create_remote(
        remote_name,
        kind=kind,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )


def _run_drive_scan_job(output_dir, query, job_id):
    """
    Reuses tools/scan_google_drive.py's exact OAuth + direct-Drive-API-to-
    disk functions -- no reimplementation. Runs in a background job because
    get_drive_service() can open a real local browser window for one-time
    OAuth consent, which would otherwise block the request thread.
    """
    service = get_drive_service()
    manifest = scan_drive_for_wallets(
        service,
        output_dir,
        query=query,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )

    lines = [f"Downloaded {len(manifest)} candidate file(s) to {output_dir}."]
    for entry in manifest:
        lines.append(f"- {entry['name']} -> {entry['local_path']}")
    lines.append(f"Scan {output_dir} next (from the home page) to check balances and everything else.")

    return {"report": "\n".join(lines), "manifest": manifest, "output_dir": output_dir}


def _run_gmail_connect_job(client_id, client_secret, job_id):
    """
    Reuses tools/scan_gmail.py's exact vault-bound OAuth flow -- no
    reimplementation. Runs in a background job because it can open a real
    local browser window for one-time OAuth consent, which would
    otherwise block the request thread.
    """
    return bind_gmail_account(
        client_id, client_secret, progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message)
    )


def _run_gmail_scan_job(output_dir, queries, job_id):
    results = scan_gmail_for_wallet_clues(
        output_dir,
        queries=queries,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )
    report = f"{len(results)} matching email(s) found. Results (and any wallet-like attachments) saved to {output_dir}."
    return {"report": report, "results": results, "output_dir": output_dir}


def _find_checkpoint_path(output_dir):
    return str(Path(output_dir) / "checks" / "scan_checkpoint.json")


def _interrupted_balance_checks():
    """
    Same idea as _interrupted_scans() but for the balance-check stage --
    every balance_checkpoint.json left behind by a check that never
    finished. Resuming is a POST to /scans/view/check-balances with the
    same output_dir, same route the "Check balances" button already uses.
    """
    if not DEFAULT_OUTPUT_ROOT.is_dir():
        return []
    interrupted = []
    for checkpoint_path in DEFAULT_OUTPUT_ROOT.glob("*/checks/balance_checkpoint.json"):
        try:
            with open(checkpoint_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        output_dir = str(checkpoint_path.parent.parent)
        confirmed = sum(
            1
            for coins in data.get("results", {}).values()
            for addresses in coins.values()
            for balance in addresses.values()
            if balance is not None
        )
        interrupted.append({"output_dir": output_dir, "addresses_confirmed_so_far": confirmed})
    return interrupted


def _interrupted_scans():
    """
    Every scan_checkpoint.json left behind by a scan that never finished
    -- app quit, update, crash, mid-walk -- across every scan this app has
    ever started. Surfaced on the scan page so resuming one is a click,
    not "remember the exact folder path and re-run scan yourself."
    _run_find_job resumes automatically (same input_dir -> same
    output_dir -> same checkpoint_path) the moment that same folder is
    scanned again -- this is purely the "so the user knows to" discovery
    layer on top of that.
    """
    if not DEFAULT_OUTPUT_ROOT.is_dir():
        return []
    interrupted = []
    for checkpoint_path in DEFAULT_OUTPUT_ROOT.glob("*/checks/scan_checkpoint.json"):
        try:
            with open(checkpoint_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        start_path = data.get("start_path")
        if not start_path or not Path(start_path).is_dir():
            continue
        interrupted.append(
            {
                "input_dir": start_path,
                "dirs_checked": len(data.get("completed_dirs", [])),
                "wallets_found_so_far": len(data.get("potential_wallets", [])),
            }
        )
    return interrupted


def _run_find_job(input_dir, job_id, index_db_path=None):
    """
    Stage 1 -- search + analyze + hidden-volume detection. Fast: no
    network calls (the walk itself can still take a long time against a
    huge mounted drive, which is what checkpoint_path is for). Deliberately
    does NOT run check_wallet_balances -- that's _run_check_balances_job, a
    separate job kicked off only once you've seen these results and
    decided it's worth the slow stage.

    :param index_db_path: see run_pipeline.find() -- None disables the
        content-hash dedup index, a path enables it.
    """
    output_dir = str(DEFAULT_OUTPUT_ROOT / Path(input_dir).name)
    Path(output_dir, "checks").mkdir(parents=True, exist_ok=True)
    summary = run_pipeline.find(
        input_dir,
        output_dir,
        index_db_path=index_db_path,
        checkpoint_path=_find_checkpoint_path(output_dir),
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )

    hidden_volumes = scan_for_hidden_volumes(
        input_dir,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, f"Checking for hidden volumes: {message}"),
    )
    summary["hidden_volumes_report"] = render_hidden_volumes_report(hidden_volumes)

    # Durable, restart-proof copy of this exact summary -- web/jobs.py's
    # job registry is a plain in-memory dict, wiped on every app restart.
    # wallet_analysis.json (written by run_pipeline.find() itself) already
    # survives restarts; this is the missing piece: the computed summary
    # built from it, plus a discoverable index of which scans exist.
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(output_dir) / "find_summary.json", "w") as f:
        json.dump(summary, f)
    record_scan(input_dir, output_dir, summary["files_found"])

    return summary


def _balance_checkpoint_path(output_dir):
    return str(Path(output_dir) / "checks" / "balance_checkpoint.json")


def _run_check_balances_job(output_dir, job_id):
    """
    Stage 2 -- the slow part (real network calls). Requires _run_find_job
    to have already populated output_dir. checkpoint_path makes this
    resumable across a quit/update/crash the same way the scan stage is:
    addresses already confirmed a real balance don't get re-checked when
    this same output_dir's balance check is run again.
    """
    run_pipeline.check_balances(
        output_dir,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
        checkpoint_path=_balance_checkpoint_path(output_dir),
    )

    balances_path = Path(output_dir) / "checks" / "wallet_balances.json"
    balances = _read_json(balances_path)
    if balances:
        for file_path, crypto_wallets in balances.items():
            for coin, addresses in crypto_wallets.items():
                for address, balance in addresses.items():
                    record_finding(coin, address, balance, source_path=file_path, source_label="scan")

    return {"output_dir": output_dir}


def _run_check_balances_selected_job(output_dir, selected_files, job_id):
    """
    Same finding-recording step as _run_check_balances_job, but scoped to
    a chosen subset of files -- and, critically, writing to an isolated
    location (output_dir/selections/<job_id>/), never
    output_dir/checks/wallet_balances.json. That path belongs to the
    whole-scan flow and may already hold real results for files outside
    this selection; overwriting it here would silently destroy them.

    No filter/relationship-graph stage (unlike run_pipeline.check_balances) --
    both are about correlating across the whole scan, which a hand-picked
    subset doesn't need, and skipping keeps a "just check these files" run
    fast.
    """
    full_analysis = _read_json(Path(output_dir) / "checks" / "wallet_analysis.json") or {}
    subset = {path: full_analysis[path] for path in selected_files if path in full_analysis}

    selection_dir = Path(output_dir) / "selections" / job_id
    checks_dir = selection_dir / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)

    subset_input_path = checks_dir / "wallet_analysis.json"
    with open(subset_input_path, "w") as f:
        json.dump(subset, f)

    balances_path = checks_dir / "wallet_balances.json"
    check_wallet_balances(
        str(subset_input_path),
        str(balances_path),
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )

    balances = _read_json(balances_path)
    if balances:
        for file_path, crypto_wallets in balances.items():
            for coin, addresses in crypto_wallets.items():
                for address, balance in addresses.items():
                    record_finding(coin, address, balance, source_path=file_path, source_label="scan")

    return {"output_dir": str(selection_dir)}


def _read_json(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _flatten_balance_dict(data):
    """
    balances/filtered are shaped {file: {coin: {address: balance}}} --
    m.table() (web/templates/_macros.html) needs a flat list of row dicts,
    not a 3-level-nested one. Caught live: rendering a real (non-empty)
    balances dict through the old unflattened template 500'd with
    "dict object has no element 0" -- table() indexed it like a list.
    """
    rows = []
    for file_path, coins in (data or {}).items():
        for coin, addresses in coins.items():
            for address, balance in addresses.items():
                rows.append({"file": file_path, "coin": coin, "address": address, "balance": balance})
    return rows


def _flatten_inconclusive_dict(data):
    """Same shape problem as _flatten_balance_dict, but inconclusive's leaves are address lists, not {address: balance}."""
    rows = []
    for file_path, coins in (data or {}).items():
        for coin, addresses in coins.items():
            for address in addresses:
                rows.append({"file": file_path, "coin": coin, "address": address})
    return rows


def _load_scan_results(output_dir):
    output_dir = Path(output_dir)
    checks_dir = output_dir / "checks"
    relationships_report_path = output_dir / "wallet_relationships.md"

    return {
        "balances": _flatten_balance_dict(_read_json(checks_dir / "wallet_balances.json")),
        "inconclusive": _flatten_inconclusive_dict(_read_json(checks_dir / "inconclusive_balances.json")),
        "filtered": _flatten_balance_dict(_read_json(output_dir / "filtered_wallets.json")),
        "relationships_report": relationships_report_path.read_text()
        if relationships_report_path.exists()
        else None,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Local web UI for coin-finder.")
    parser.add_argument(
        "--port",
        type=int,
        default=5050,
        help="Port to listen on (default: 5050 -- not 5000, which macOS's AirPlay Receiver "
        "occupies by default on most Macs, silently blocking the default Flask port).",
    )
    args = parser.parse_args()

    print(f"Starting coin-finder's local web UI at http://127.0.0.1:{args.port}")
    create_app().run(host="127.0.0.1", port=args.port, debug=False)
