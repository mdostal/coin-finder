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
from web.mounts import install_rclone, is_mounted, is_rclone_installed, list_mounts, list_remotes, mount, unmount
from tools.check_fork_coins import check_fork_coins_for_addresses, render_fork_coin_report
from tools.crawl_transaction_graph import crawl_wallet_cluster, load_seed_addresses, render_cluster_report
from tools.detect_hidden_volumes import render_hidden_volumes_report, scan_for_hidden_volumes
from tools.find_seed_phrases import find_candidate_phrases, scan_directory
from tools.match_seed_phrases import load_phrases_from_file, match_phrases, render_match_report
from tools.scan_google_drive import get_drive_service, scan_drive_for_wallets
from tools.scan_wallet_dat import check_addresses_balances, scan_wallet_for_addresses
from tools.extract_private_key import extract_wif_for_address
from web.findings import archive, archive_all_zero_balance, list_findings, record_finding, unarchive
from tools.unlock_exodus_wallet import run_exodus_unlock
from tools.unlock_wallet import check_network_status, run_unlock
from web.jobs import consume_job_result, create_job, get_job, list_jobs, report_progress, run_job, running_jobs_count, start_job
from web.native_dialogs import pick_path
from web.paths import app_data_dir, is_frozen
from web.update import check_for_update, perform_update
from web.vault import add_vault_entry, list_vault_entries, resolve_vault_entries_with_values, revoke_vault_entry

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
        )

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

        # Stage 1 only (search + analyze) -- fast, no network calls. See
        # scan_check_balances() for the slow stage, kicked off separately
        # once you've seen what stage 1 actually found.
        job_id = create_job(kind="find", label=input_dir)
        start_job(job_id, _run_find_job, input_dir, job_id)
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

        job_id = run_job(_run_crawl_job, addresses, kind="crawl", label=f"{len(addresses)} address(es)")
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/fork-coins", methods=["POST"])
    def item_fork_coins():
        addresses = _split_lines(request.form.get("addresses"))
        if not addresses:
            return render_template("index.html", error="Enter at least one address."), 400

        job_id = run_job(_run_fork_coins_job, addresses, kind="fork-coins", label=f"{len(addresses)} address(es)")
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
        return render_template("findings.html", findings=list_findings(include_archived=include_archived), include_archived=include_archived)

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

        job_id = run_job(_run_drive_scan_job, output_dir, query, kind="drive-scan", label=output_dir)
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
        return render_template("mounts.html", remotes=list_remotes(), mounts=list_mounts(), rclone_installed=is_rclone_installed(), error=None)

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
            return render_template("mounts.html", remotes=list_remotes(), mounts=list_mounts(), error="Enter both a remote and a mount point."), 400

        mount(remote_name, mount_point)
        return redirect(url_for("mounts_page"))

    @app.route("/mounts/unmount", methods=["POST"])
    def mounts_unmount():
        remote_name = (request.form.get("remote_name") or "").strip()
        unmount(remote_name)
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
                    remotes=list_remotes(),
                    mounts=list_mounts(),
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
        return render_template("wizard_cloud.html", kind=kind, rclone_installed=is_rclone_installed(), remotes=list_remotes())

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
    "sources": {"label": "Sources", "tabs": [("Manage", "targets_page"), ("Cloud — Mounts", "mounts_page"), ("Cloud — Google Drive", "drive_form"), ("Scan", "index")]},
    "unlock": {"label": "Unlock", "tabs": [("Try", "item_unlock_form"), ("Vault", "vault_page"), ("Extract Key", "item_extract_key_form")]},
    "about": {"label": "About", "tabs": [("Update", "update_page"), ("Network", "network_page")]},
}

_NAV_GROUP_BY_ENDPOINT = {
    # Sources -- everything about acquiring/choosing what to scan, plus the scan action itself.
    "index": "sources",
    "wizard_start": "sources",
    "wizard_choose": "sources",
    "wizard_cloud": "sources",
    "targets_page": "sources",
    "targets_add": "sources",
    "targets_remove": "sources",
    "mounts_page": "sources",
    "mounts_install_rclone": "sources",
    "mounts_mount": "sources",
    "mounts_unmount": "sources",
    "mounts_bind": "sources",
    "drive_form": "sources",
    "drive_scan": "sources",
    "start_scan": "sources",
    "scan_status": "sources",
    "scan_check_balances": "sources",
    "scan_balances_status": "sources",
    "item_scan_wallet_dat": "sources",
    # Unlock -- testing/saving passwords, extracting keys.
    "item_unlock_form": "unlock",
    "item_unlock": "unlock",
    "item_unlock_status": "unlock",
    "item_unlock_result": "unlock",
    "item_extract_key_form": "unlock",
    "item_extract_key": "unlock",
    "item_extract_key_status": "unlock",
    "item_extract_key_result": "unlock",
    "vault_page": "unlock",
    "vault_add": "unlock",
    "vault_revoke": "unlock",
    # Findings -- standalone, no tab strip.
    "findings_page": "findings",
    "findings_archive": "findings",
    "findings_unarchive": "findings",
    "findings_archive_all_zero": "findings",
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


def _run_crawl_job(addresses):
    """
    Writes the submitted addresses to a local temp file before calling
    load_seed_addresses -- reuses the CLI's exact file-or-literal contract
    instead of forwarding raw request data directly into it.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(addresses))
        temp_path = f.name

    try:
        seeds = load_seed_addresses(temp_path)
        results = crawl_wallet_cluster(seeds)
    finally:
        Path(temp_path).unlink(missing_ok=True)

    for address, info in results.items():
        record_finding("Bitcoin", address, info.get("balance"), source_label="crawl_transaction_graph")

    return {"report": render_cluster_report(results), "results": results}


def _run_fork_coins_job(addresses):
    results = check_fork_coins_for_addresses(addresses)

    for address, coin_balances in results.items():
        for coin, balance in coin_balances.items():
            record_finding(coin, address, balance, source_label="check_fork_coins")

    return {"report": render_fork_coin_report(results), "results": results}


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


def _run_install_rclone_job(job_id):
    return install_rclone(progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message))


def _run_drive_scan_job(output_dir, query):
    """
    Reuses tools/scan_google_drive.py's exact OAuth + direct-Drive-API-to-
    disk functions -- no reimplementation. Runs in a background job because
    get_drive_service() can open a real local browser window for one-time
    OAuth consent, which would otherwise block the request thread.
    """
    service = get_drive_service()
    manifest = scan_drive_for_wallets(service, output_dir, query=query)

    lines = [f"Downloaded {len(manifest)} candidate file(s) to {output_dir}."]
    for entry in manifest:
        lines.append(f"- {entry['name']} -> {entry['local_path']}")
    lines.append(f"Scan {output_dir} next (from the home page) to check balances and everything else.")

    return {"report": "\n".join(lines), "manifest": manifest, "output_dir": output_dir}


def _run_find_job(input_dir, job_id):
    """
    Stage 1 -- search + analyze + hidden-volume detection. Fast: no
    network calls. Deliberately does NOT run check_wallet_balances --
    that's _run_check_balances_job, a separate job kicked off only once
    you've seen these results and decided it's worth the slow stage.
    """
    output_dir = str(DEFAULT_OUTPUT_ROOT / Path(input_dir).name)
    summary = run_pipeline.find(input_dir, output_dir)

    hidden_volumes = scan_for_hidden_volumes(input_dir)
    summary["hidden_volumes_report"] = render_hidden_volumes_report(hidden_volumes)
    return summary


def _run_check_balances_job(output_dir, job_id):
    """Stage 2 -- the slow part. Requires _run_find_job to have already populated output_dir."""
    run_pipeline.check_balances(
        output_dir,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )

    balances_path = Path(output_dir) / "checks" / "wallet_balances.json"
    balances = _read_json(balances_path)
    if balances:
        for file_path, crypto_wallets in balances.items():
            for coin, addresses in crypto_wallets.items():
                for address, balance in addresses.items():
                    record_finding(coin, address, balance, source_path=file_path, source_label="scan")

    return {"output_dir": output_dir}


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
