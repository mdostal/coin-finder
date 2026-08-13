import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import run_pipeline
from tools.check_fork_coins import check_fork_coins_for_addresses, render_fork_coin_report
from tools.crawl_transaction_graph import crawl_wallet_cluster, load_seed_addresses, render_cluster_report
from tools.detect_hidden_volumes import render_hidden_volumes_report, scan_for_hidden_volumes
from tools.find_seed_phrases import find_candidate_phrases, scan_directory
from tools.match_seed_phrases import load_phrases_from_file, match_phrases, render_match_report
from tools.scan_wallet_dat import check_addresses_balances, scan_wallet_for_addresses
from web.jobs import get_job, run_job

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "ui_output"
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

    @app.route("/")
    def index():
        return render_template("index.html", error=request.args.get("error"))

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

        job_id = run_job(_run_scan_job, input_dir)
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

        job_id = run_job(_run_scan_wallet_dat_job, wallet_path)
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

    return app


def _split_lines(raw):
    """Splits textarea input into a list of non-blank, non-comment lines."""
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]


def _run_scan_wallet_dat_job(wallet_path):
    scan = scan_wallet_for_addresses(wallet_path)
    checked = check_addresses_balances(scan["addresses"])
    significant = [r for r in checked["results"] if r.get("balance")]

    lines = [
        f"Encrypted key records: {scan['encrypted_key_count']}",
        f"Checked {len(checked['results'])} of {checked['total_available']} address(es).",
        f"{len(significant)} address(es) with a non-zero balance.",
    ]
    for entry in significant:
        lines.append(f"- {entry['address']}: {entry['balance']}")

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

    return {"report": render_cluster_report(results), "results": results}


def _run_fork_coins_job(addresses):
    results = check_fork_coins_for_addresses(addresses)
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


def _run_scan_job(input_dir):
    """
    Runs the existing default pipeline (search -> analyze -> check_balances
    -> filter -> graph) plus the hidden-volume detector, exactly the same
    functions the CLI tools call -- this job is a thin wrapper, not a
    reimplementation.
    """
    output_dir = str(DEFAULT_OUTPUT_ROOT / Path(input_dir).name)
    run_pipeline.main(input_dir, output_dir)

    hidden_volumes = scan_for_hidden_volumes(input_dir)

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
    create_app().run(host="127.0.0.1", port=5000, debug=False)
