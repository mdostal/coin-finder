import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import run_pipeline
from web.bound_targets import add_target, list_mounted_volumes, list_targets, remove_target
from web.mounts import is_mounted, list_mounts, list_remotes, mount, unmount
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
from web.jobs import consume_job_result, create_job, get_job, report_progress, run_job, start_job

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "ui_output"
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

    @app.route("/scan", methods=["POST"])
    def start_scan():
        input_dir = (request.form.get("input_dir") or "").strip()
        if not input_dir or not Path(input_dir).is_dir():
            return render_template("index.html", error=f"Not a directory: {input_dir}"), 400

        job_id = create_job()
        start_job(job_id, _run_scan_job, input_dir, job_id)
        return redirect(url_for("scan_status", job_id=job_id))

    @app.route("/scan/<job_id>")
    def scan_status(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)

        results = None
        if job["status"] == "done":
            results = _load_scan_results(job["result"]["output_dir"])
            results["hidden_volumes_report"] = job["result"]["hidden_volumes_report"]

        return render_template("scan.html", job_id=job_id, job=job, results=results)

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

        job_id = create_job()
        start_job(job_id, _run_scan_wallet_dat_job, wallet_path, job_id)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/crawl", methods=["POST"])
    def item_crawl():
        addresses = _split_lines(request.form.get("addresses"))
        if not addresses:
            return render_template("index.html", error="Enter at least one address."), 400

        job_id = run_job(_run_crawl_job, addresses)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/fork-coins", methods=["POST"])
    def item_fork_coins():
        addresses = _split_lines(request.form.get("addresses"))
        if not addresses:
            return render_template("index.html", error="Enter at least one address."), 400

        job_id = run_job(_run_fork_coins_job, addresses)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/find-seed-phrases", methods=["POST"])
    def item_find_seed_phrases():
        target_path = (request.form.get("target_path") or "").strip()
        if not target_path or not Path(target_path).exists():
            return render_template("index.html", error=f"Not found: {target_path}"), 400

        job_id = run_job(_run_find_seed_phrases_job, target_path)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item/match-seed-phrases", methods=["POST"])
    def item_match_seed_phrases():
        phrases_file = (request.form.get("phrases_file") or "").strip()
        if not phrases_file or not Path(phrases_file).is_file():
            return render_template("index.html", error=f"Not a file: {phrases_file}"), 400

        job_id = run_job(_run_match_seed_phrases_job, phrases_file)
        return redirect(url_for("item_result", job_id=job_id))

    @app.route("/item-result/<job_id>")
    def item_result(job_id):
        job = get_job(job_id)
        if job is None:
            abort(404)
        return render_template("item_result.html", job_id=job_id, job=job)

    @app.route("/item/unlock", methods=["GET"])
    def item_unlock_form():
        return render_template("unlock.html", network_status=check_network_status(), error=None)

    @app.route("/item/unlock", methods=["POST"])
    def item_unlock():
        # Re-checked here, at the moment of the actual request -- never
        # trusted from the GET page load or from anything the client sent.
        # This is the real gate; a disabled-looking button is just a UX
        # nicety on top of it.
        network_status = check_network_status()
        if network_status != "OFFLINE":
            return (
                render_template(
                    "unlock.html",
                    network_status=network_status,
                    error=(
                        f"Refusing to run: network status is {network_status}, not OFFLINE. "
                        "Testing real passwords against a real wallet must happen with network "
                        "disabled -- disconnect and try again."
                    ),
                ),
                409,
            )

        target_path = (request.form.get("target_path") or "").strip()
        candidates = request.form.get("candidates") or ""
        kind = request.form.get("kind") or "btcrecover"

        if not target_path or not Path(target_path).is_file():
            return render_template("unlock.html", network_status=network_status, error=f"Not a file: {target_path}"), 400
        if not candidates.strip():
            return (
                render_template("unlock.html", network_status=network_status, error="Enter at least one candidate password/phrase."),
                400,
            )

        # Written to a local temp file server-side -- never placed in the
        # URL/query string, matching the CLI tools' file-only-candidates rule.
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(candidates)
            candidates_path = f.name

        job_fn = _run_exodus_unlock_job if kind == "exodus" else _run_btcrecover_unlock_job
        job_id = run_job(job_fn, target_path, candidates_path, secret=True)
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
        # discipline as /item/unlock. Never trusted from the GET page load.
        network_status = check_network_status()
        if network_status != "OFFLINE":
            return (
                render_template(
                    "extract_key.html",
                    network_status=network_status,
                    error=(
                        f"Refusing to extract a private key: network status is {network_status}, not OFFLINE. "
                        "Handling real key material must happen with network disabled -- disconnect and try again."
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

        job_id = run_job(extract_wif_for_address, wallet_path, address, secret=True)
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

        job_id = run_job(_run_drive_scan_job, output_dir, query)
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
        return render_template("mounts.html", remotes=list_remotes(), mounts=list_mounts(), error=None)

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
        return render_template("wizard_cloud.html", kind=kind, rclone_installed=_is_rclone_installed(), remotes=list_remotes())

    return app


def _is_rclone_installed():
    return shutil.which("rclone") is not None


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


def _run_btcrecover_unlock_job(wallet_path, candidates_path):
    try:
        result = run_unlock(wallet_path, candidates_path)
    finally:
        Path(candidates_path).unlink(missing_ok=True)
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


def _run_exodus_unlock_job(seed_seco_path, candidates_path):
    try:
        result = run_exodus_unlock(seed_seco_path, candidates_path)
    finally:
        Path(candidates_path).unlink(missing_ok=True)
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


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


def _run_scan_job(input_dir, job_id):
    """
    Runs the existing default pipeline (search -> analyze -> check_balances
    -> filter -> graph) plus the hidden-volume detector, exactly the same
    functions the CLI tools call -- this job is a thin wrapper, not a
    reimplementation.
    """
    output_dir = str(DEFAULT_OUTPUT_ROOT / Path(input_dir).name)
    run_pipeline.main(
        input_dir,
        output_dir,
        progress_callback=lambda current, total, message="": report_progress(job_id, current, total, message),
    )

    hidden_volumes = scan_for_hidden_volumes(input_dir)

    balances_path = Path(output_dir) / "checks" / "wallet_balances.json"
    balances = _read_json(balances_path)
    if balances:
        for file_path, crypto_wallets in balances.items():
            for coin, addresses in crypto_wallets.items():
                for address, balance in addresses.items():
                    record_finding(coin, address, balance, source_path=file_path, source_label="scan")

    return {
        "output_dir": output_dir,
        "hidden_volumes_report": render_hidden_volumes_report(hidden_volumes),
    }


def _read_json(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _load_scan_results(output_dir):
    output_dir = Path(output_dir)
    checks_dir = output_dir / "checks"
    relationships_report_path = output_dir / "wallet_relationships.md"

    return {
        "analysis": _read_json(checks_dir / "wallet_analysis.json"),
        "balances": _read_json(checks_dir / "wallet_balances.json"),
        "inconclusive": _read_json(checks_dir / "inconclusive_balances.json"),
        "filtered": _read_json(output_dir / "filtered_wallets.json"),
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
