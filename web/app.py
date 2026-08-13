import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import run_pipeline
from tools.detect_hidden_volumes import render_hidden_volumes_report, scan_for_hidden_volumes
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

    return app


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
