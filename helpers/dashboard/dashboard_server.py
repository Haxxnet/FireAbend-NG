#!/usr/bin/env python3

import argparse
import html
import json
import mimetypes
import os
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BOOTSTRAP_CSS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css"
BOOTSTRAP_CSS_INTEGRITY = "sha384-sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB"
BOOTSTRAP_JS = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"
BOOTSTRAP_JS_INTEGRITY = "sha384-FKyoEForCGlyvwx9Hj09JcYn3nv7wiPVlz7YYwJrWVcXK/BmnVDxM+D2scQbITxI"
BOOTSTRAP_ICONS = "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/font/bootstrap-icons.min.css"
LOCAL_BOOTSTRAP_CSS_CANDIDATES = [
    Path("/usr/share/javascript/bootstrap5/css/bootstrap.min.css"),
    Path("/usr/share/bootstrap-html/css/bootstrap.min.css"),
]
LOCAL_BOOTSTRAP_JS_CANDIDATES = [
    Path("/usr/share/javascript/bootstrap5/js/bootstrap.bundle.min.js"),
    Path("/usr/share/bootstrap-html/js/bootstrap.bundle.min.js"),
]


def pick_first_existing_path(candidates):
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_dashboard_assets():
    bootstrap_css_path = pick_first_existing_path(LOCAL_BOOTSTRAP_CSS_CANDIDATES)
    bootstrap_js_path = pick_first_existing_path(LOCAL_BOOTSTRAP_JS_CANDIDATES)
    asset_files = {}

    if bootstrap_css_path is not None:
        asset_files["bootstrap.min.css"] = bootstrap_css_path
        bootstrap_css_href = "/assets/bootstrap.min.css"
        bootstrap_css_integrity = None
    else:
        bootstrap_css_href = BOOTSTRAP_CSS
        bootstrap_css_integrity = BOOTSTRAP_CSS_INTEGRITY

    if bootstrap_js_path is not None:
        asset_files["bootstrap.bundle.min.js"] = bootstrap_js_path
        bootstrap_js_src = "/assets/bootstrap.bundle.min.js"
        bootstrap_js_integrity = None
    else:
        bootstrap_js_src = BOOTSTRAP_JS
        bootstrap_js_integrity = BOOTSTRAP_JS_INTEGRITY

    return {
        "bootstrap_css_href": bootstrap_css_href,
        "bootstrap_css_integrity": bootstrap_css_integrity,
        "bootstrap_js_src": bootstrap_js_src,
        "bootstrap_js_integrity": bootstrap_js_integrity,
        "bootstrap_icons_href": BOOTSTRAP_ICONS,
        "asset_files": asset_files,
    }


DASHBOARD_ASSETS = resolve_dashboard_assets()


def parse_args():
    parser = argparse.ArgumentParser(description="Serve a local FireAbend scan dashboard.")
    parser.add_argument("--scan-dir", required=True, help="Path to the FireAbend scan directory.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument("--open-browser", action="store_true", help="Open the dashboard in the default browser after startup.")
    return parser.parse_args()


def load_json(file_path):
    if not file_path.is_file():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def iso_to_local(value):
    if not value:
        return ""

    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def human_size(num_bytes):
    if num_bytes is None:
        return "-"

    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{int(num_bytes)} B"


def describe_file_type(file_path):
    extension = file_path.suffix.lower().lstrip(".")
    extension_map = {
        "csv": "CSV",
        "gnmap": "GNMAP",
        "htm": "HTML",
        "html": "HTML",
        "jpeg": "JPEG",
        "jpg": "JPG",
        "json": "JSON",
        "log": "LOG",
        "md": "Markdown",
        "ods": "ODS",
        "pdf": "PDF",
        "png": "PNG",
        "svg": "SVG",
        "txt": "TXT",
        "xml": "XML",
        "xls": "XLS",
        "xlsx": "XLSX",
        "yaml": "YAML",
        "yml": "YAML",
    }
    if extension in extension_map:
        return extension_map[extension]

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        if mime_type == "text/plain":
            return "TXT"
        return mime_type.split("/")[-1].upper()

    if extension:
        return extension.upper()

    return "FILE"


def tail_file(file_path, lines=200):
    if not file_path.is_file():
        return ""

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.readlines()
        return "".join(content[-lines:])
    except OSError:
        return ""


def collect_jobs(scan_dir):
    manifest_path = scan_dir / "00_runtime" / "jobs_manifest.json"
    jobs_dir = scan_dir / "00_runtime" / "jobs"
    logs_dir = scan_dir / "00_runtime" / "logs"

    manifest = load_json(manifest_path) or {}
    manifest_jobs = {job["job_id"]: job for job in manifest.get("jobs", [])}

    status_jobs = {}
    if jobs_dir.is_dir():
        for item in sorted(jobs_dir.glob("*.json")):
            data = load_json(item)
            if data and data.get("job_id"):
                status_jobs[data["job_id"]] = data

    all_job_ids = sorted(set(manifest_jobs.keys()) | set(status_jobs.keys()))
    jobs = []
    counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
    }

    for job_id in all_job_ids:
        manifest_job = manifest_jobs.get(job_id, {})
        status_job = status_jobs.get(job_id, {})
        state = status_job.get("state", "pending")
        if state not in counts:
            counts[state] = 0
        counts[state] += 1

        log_path = logs_dir / f"{job_id}.log"
        jobs.append(
            {
                "job_id": job_id,
                "description": status_job.get("description") or manifest_job.get("description") or "",
                "resource": status_job.get("resource") or manifest_job.get("resource") or "",
                "deps": status_job.get("deps") or manifest_job.get("deps") or [],
                "state": state,
                "started_at": iso_to_local(status_job.get("started_at")),
                "finished_at": iso_to_local(status_job.get("finished_at")),
                "updated_at": iso_to_local(status_job.get("updated_at")),
                "error": status_job.get("error", ""),
                "reason": status_job.get("reason", ""),
                "log_path": str(log_path.relative_to(scan_dir)) if log_path.exists() else "",
                "log_url": f"/api/job/{job_id}/log",
            }
        )

    return jobs, counts


def collect_files(root_dir, base_dir):
    if not root_dir.is_dir():
        return []

    files = []
    for item in sorted(root_dir.rglob("*")):
        if not item.is_file():
            continue
        file_size = item.stat().st_size
        if file_size == 0:
            continue
        rel_path = item.relative_to(base_dir).as_posix()
        files.append(
            {
                "name": item.name,
                "relative_path": rel_path,
                "parent": item.parent.relative_to(base_dir).as_posix(),
                "file_type": describe_file_type(item),
                "size": human_size(file_size),
                "modified_at": datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "url": "/files/" + rel_path,
            }
        )
    return files


def collect_findings_files(scan_dir):
    findings_dir = scan_dir / "07_findings"
    if not findings_dir.is_dir():
        return []

    relative_paths = []
    for item in sorted(findings_dir.rglob("*")):
        if not item.is_file():
            continue

        rel_path = item.relative_to(scan_dir).as_posix()
        rel_findings_path = item.relative_to(findings_dir).as_posix()

        if rel_findings_path.startswith("zap/"):
            if rel_findings_path == "zap/zap_summary.txt" or rel_findings_path.startswith("zap/raw_html/"):
                relative_paths.append(rel_path)
            continue

        relative_paths.append(rel_path)

    return collect_matching_files(scan_dir, relative_paths)


def collect_matching_files(base_dir, relative_paths):
    base_dir = base_dir.resolve()
    files = []
    seen = set()

    for relative_path in relative_paths:
        full_path = (base_dir / relative_path).resolve()
        if not full_path.is_file():
            continue
        file_size = full_path.stat().st_size
        if file_size == 0:
            continue

        rel_path = full_path.relative_to(base_dir).as_posix()
        if rel_path in seen:
            continue
        seen.add(rel_path)

        files.append(
            {
                "name": full_path.name,
                "relative_path": rel_path,
                "parent": full_path.parent.relative_to(base_dir).as_posix(),
                "file_type": describe_file_type(full_path),
                "size": human_size(file_size),
                "modified_at": datetime.fromtimestamp(full_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "url": "/files/" + rel_path,
            }
        )

    return sorted(files, key=lambda item: item["relative_path"])


def collect_nmap_report_files(scan_dir):
    nmap_dir = scan_dir / "01_nmap"
    if not nmap_dir.is_dir():
        return []

    html_files = sorted(path.relative_to(scan_dir).as_posix() for path in nmap_dir.glob("*.html"))
    return collect_matching_files(scan_dir, html_files)


def collect_ssl_report_files(scan_dir):
    ssl_dir = scan_dir / "03_ssl"
    if not ssl_dir.is_dir():
        return []

    xlsx_files = sorted(path.relative_to(scan_dir).as_posix() for path in ssl_dir.glob("*.xlsx"))
    return collect_matching_files(scan_dir, xlsx_files)


def collect_service_report_files(scan_dir):
    service_paths = []

    ssh_dir = scan_dir / "06_services" / "ssh"
    if ssh_dir.is_dir():
        service_paths.extend(path.relative_to(scan_dir).as_posix() for path in sorted(ssh_dir.glob("*.xlsx")))

    eyewitness_report = scan_dir / "06_services" / "http" / "0_eyewitness-results" / "report.html"
    if eyewitness_report.is_file():
        service_paths.append(eyewitness_report.relative_to(scan_dir).as_posix())

    vpn_dir = scan_dir / "06_services" / "vpn" / "results"
    if vpn_dir.is_dir():
        service_paths.extend(path.relative_to(scan_dir).as_posix() for path in sorted(vpn_dir.glob("*.html")))

    return collect_matching_files(scan_dir, service_paths)


def collect_sections(scan_dir):
    sections = []
    section_collectors = [
        ("Findings", lambda: collect_findings_files(scan_dir)),
        ("Nmap Reports", lambda: collect_nmap_report_files(scan_dir)),
        ("SSL Reports", lambda: collect_ssl_report_files(scan_dir)),
        ("Header Reports", lambda: collect_files(scan_dir / "04_headers", scan_dir)),
        ("Service Reports", lambda: collect_service_report_files(scan_dir)),
    ]

    for label, collector in section_collectors:
        files = collector()
        if files:
            sections.append({"label": label, "files": files})
    return sections


def build_state(scan_dir):
    jobs, counts = collect_jobs(scan_dir)
    run_summary = load_json(scan_dir / "00_runtime" / "run_summary.json") or {}
    running = [job["job_id"] for job in jobs if job["state"] == "running"]

    return {
        "scan_name": scan_dir.name,
        "scan_dir": str(scan_dir),
        "generated_at": iso_to_local(run_summary.get("generated_at")),
        "counts": counts,
        "running_jobs": running,
        "jobs": jobs,
        "sections": collect_sections(scan_dir),
    }


def render_index():
    bootstrap_css_integrity_attr = (
        f' integrity="{DASHBOARD_ASSETS["bootstrap_css_integrity"]}" crossorigin="anonymous"'
        if DASHBOARD_ASSETS["bootstrap_css_integrity"]
        else ""
    )
    bootstrap_js_integrity_attr = (
        f' integrity="{DASHBOARD_ASSETS["bootstrap_js_integrity"]}" crossorigin="anonymous"'
        if DASHBOARD_ASSETS["bootstrap_js_integrity"]
        else ""
    )
    return f"""<!doctype html>
<html lang="en" data-bs-theme="dark">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>FireAbend Dashboard</title>
    <link href="{DASHBOARD_ASSETS["bootstrap_css_href"]}" rel="stylesheet"{bootstrap_css_integrity_attr}>
    <link rel="stylesheet" href="{DASHBOARD_ASSETS["bootstrap_icons_href"]}">
    <style>
      :root {{
        --fa-bg: #08101c;
        --fa-ink: #e6edf7;
        --fa-panel: rgba(12, 20, 33, 0.82);
        --fa-border: rgba(148, 163, 184, 0.16);
        --fa-accent: #db5a2d;
        --fa-accent-soft: #f6c87a;
        --fa-good: #198754;
        --fa-bad: #b42318;
        --fa-muted: #94a3b8;
      }}
      body {{
        background:
          radial-gradient(circle at top left, rgba(219,90,45,0.18), transparent 28%),
          radial-gradient(circle at top right, rgba(59,130,246,0.14), transparent 26%),
          linear-gradient(180deg, #0f172a 0%, var(--fa-bg) 100%);
        color: var(--fa-ink);
        min-height: 100vh;
      }}
      .shell {{
        max-width: 1760px;
      }}
      .hero {{
        background: linear-gradient(145deg, rgba(8,15,28,0.98), rgba(23,33,52,0.96));
        color: #fff;
        border: 1px solid rgba(255,255,255,0.06);
        box-shadow: 0 24px 60px rgba(2,6,23,0.42);
      }}
      .glass {{
        background: var(--fa-panel);
        backdrop-filter: blur(12px);
        border: 1px solid var(--fa-border);
        box-shadow: 0 18px 42px rgba(2,6,23,0.22);
      }}
      .table {{
        --bs-table-bg: transparent;
        --bs-table-color: var(--fa-ink);
        --bs-table-border-color: rgba(148, 163, 184, 0.14);
        --bs-table-hover-color: var(--fa-ink);
      }}
      .jobs-table {{
        table-layout: fixed;
      }}
      .jobs-table thead th {{
        white-space: nowrap;
      }}
      .jobs-table th:nth-child(1) {{
        width: 28%;
      }}
      .jobs-table th:nth-child(2) {{
        width: 12%;
      }}
      .jobs-table th:nth-child(3) {{
        width: 14%;
      }}
      .jobs-table th:nth-child(4) {{
        width: 21%;
      }}
      .jobs-table th:nth-child(5) {{
        width: 25%;
      }}
      .jobs-table td {{
        overflow-wrap: anywhere;
      }}
      .metric {{
        min-height: 120px;
      }}
      .metric .display-6 {{
        font-weight: 700;
      }}
      .job-row {{
        cursor: pointer;
      }}
      .job-row:hover {{
        background: rgba(246,200,122,0.09);
      }}
      .log-panel {{
        min-height: 260px;
      }}
      .log-view {{
        background: #0b1120;
        color: #d6e3f0;
        border-radius: 1rem;
        min-height: 14.5rem;
        max-height: 14.5rem;
        overflow: auto;
        font-size: 0.92rem;
        line-height: 1.5;
      }}
      .artifact-link {{
        text-decoration: none;
      }}
      .artifact-card {{
        border: 1px solid rgba(148, 163, 184, 0.12);
        border-top: 4px solid var(--artifact-accent, var(--fa-accent));
        background: linear-gradient(180deg, rgba(15,23,42,0.96), color-mix(in srgb, var(--artifact-soft, #172033) 32%, #0f172a));
        transition: transform 0.16s ease, box-shadow 0.16s ease;
        position: relative;
        overflow: hidden;
      }}
      .artifact-card::before {{
        content: "";
        position: absolute;
        inset: 0;
        background:
          radial-gradient(circle at top right, color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 20%, transparent), transparent 38%);
        opacity: 0.9;
        pointer-events: none;
      }}
      .artifact-section-panel {{
        border: 1px solid rgba(148, 163, 184, 0.14);
        background: rgba(15, 23, 42, 0.45);
      }}
      .artifact-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 18px 30px rgba(2,6,23,0.22), 0 0 0 1px color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 18%, transparent);
      }}
      .artifact-icon {{
        width: 3.1rem;
        height: 3.1rem;
        border-radius: 1rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        position: relative;
        background:
          radial-gradient(circle at 30% 25%, rgba(255,255,255,0.18), transparent 35%),
          linear-gradient(160deg, color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 30%, #162033), color-mix(in srgb, var(--artifact-soft, #172033) 24%, #0b1220));
        color: var(--artifact-accent, var(--fa-accent));
        border: 1px solid color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 30%, rgba(148, 163, 184, 0.14));
        box-shadow:
          inset 0 1px 0 rgba(255,255,255,0.08),
          0 10px 20px rgba(2,6,23,0.22),
          0 0 24px color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 16%, transparent);
      }}
      .artifact-icon i {{
        font-size: 1.15rem;
        text-shadow: 0 0 12px color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 28%, transparent);
        transform: translateY(0.5px);
      }}
      .artifact-kind {{
        background: color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 18%, #111827);
        color: color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 72%, #ffffff);
        border: 1px solid color-mix(in srgb, var(--artifact-accent, var(--fa-accent)) 26%, rgba(148, 163, 184, 0.14));
      }}
      .artifact-filetype {{
        background: rgba(148, 163, 184, 0.1);
        color: var(--fa-ink);
        border: 1px solid rgba(148, 163, 184, 0.14);
      }}
      .badge-state {{
        font-size: 0.8rem;
        letter-spacing: 0.02em;
      }}
      .small-muted {{
        color: var(--fa-muted);
      }}
      .sticky-top-card {{
        top: 1rem;
      }}
      .sort-button {{
        border: 0;
        background: transparent;
        padding: 0;
        font: inherit;
        color: inherit;
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        white-space: nowrap;
      }}
      .sort-button.active {{
        color: var(--fa-accent);
      }}
      .sort-button:hover {{
        color: var(--fa-accent);
      }}
      .sort-indicator {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.35rem;
        flex: 0 0 1.35rem;
        text-align: center;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        line-height: 1;
      }}
      .sort-indicator-active {{
        color: var(--fa-accent-soft);
      }}
      .sort-indicator-idle {{
        color: var(--fa-muted);
      }}
      .pagination-summary {{
        color: var(--fa-muted);
        font-size: 0.92rem;
      }}
      .job-search {{
        max-width: 24rem;
        background: rgba(15, 23, 42, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.18);
        color: var(--fa-ink);
      }}
      .job-search::placeholder {{
        color: var(--fa-muted);
      }}
      .job-search:focus {{
        background: rgba(15, 23, 42, 0.9);
        color: var(--fa-ink);
        border-color: rgba(219, 90, 45, 0.45);
        box-shadow: 0 0 0 0.2rem rgba(219, 90, 45, 0.18);
      }}
      .pulse {{
        animation: pulse 1.8s ease-in-out infinite;
      }}
      @keyframes pulse {{
        0% {{ opacity: 0.65; transform: scale(0.98); }}
        50% {{ opacity: 1; transform: scale(1); }}
        100% {{ opacity: 0.65; transform: scale(0.98); }}
      }}
    </style>
  </head>
  <body>
    <div class="container-fluid py-4 py-lg-5 shell">
      <section class="hero rounded-5 p-4 p-lg-5 mb-4">
        <div class="row g-4 align-items-end">
          <div class="col-lg-8">
            <div class="text-uppercase small fw-semibold text-warning-emphasis mb-2">Local Scan Dashboard</div>
            <h1 class="display-5 fw-bold mb-2">FireAbend Live Console</h1>
            <p class="mb-0 text-white-50">Track job execution, inspect logs, and browse scan artifacts as they land on disk.</p>
          </div>
          <div class="col-lg-4 text-lg-end">
            <div id="scanName" class="fs-5 fw-semibold"></div>
            <div id="scanPath" class="small text-white-50"></div>
            <div id="generatedAt" class="small text-white-50 mt-2"></div>
          </div>
        </div>
      </section>

      <section class="row g-3 mb-4" id="metrics"></section>

      <div class="glass rounded-5 p-3 p-lg-4 log-panel mb-4">
        <div class="d-flex justify-content-between align-items-start mb-3">
          <div>
            <h2 class="h4 mb-1">Job Log</h2>
            <div id="selectedJobLabel" class="small-muted">Select a job to load its log output.</div>
          </div>
          <div class="btn-group" role="group" aria-label="Log actions">
            <button class="btn btn-sm btn-outline-secondary" id="copyLogButton" type="button">
              <i class="bi bi-copy"></i> Copy
            </button>
            <button class="btn btn-sm btn-outline-secondary" id="refreshLogButton" type="button">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
          </div>
        </div>
        <pre class="p-3 log-view mb-0" id="logView">Waiting for selection…</pre>
      </div>

      <div class="glass rounded-5 p-3 p-lg-4 mb-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h2 class="h4 mb-1">Jobs</h2>
            <div class="small-muted">Pending jobs appear immediately from the manifest. Click a row to inspect its live log.</div>
          </div>
          <div id="runningBanner" class="small fw-semibold"></div>
        </div>
        <div class="d-flex justify-content-between align-items-center gap-3 mb-3 flex-wrap">
          <label class="visually-hidden" for="jobsSearchInput">Search jobs</label>
          <input class="form-control form-control-sm job-search" id="jobsSearchInput" type="search" placeholder="Search jobs, resources, status, details...">
          <div id="jobsSearchSummary" class="small-muted"></div>
        </div>
        <div class="table-responsive">
          <table class="table jobs-table align-middle mb-0">
            <thead>
              <tr>
                <th>
                  <button class="sort-button fw-semibold" data-sort-key="job" type="button">
                    Job <span class="sort-indicator small text-body-secondary" data-sort-indicator="job">↕</span>
                  </button>
                </th>
                <th>
                  <button class="sort-button fw-semibold" data-sort-key="status" type="button">
                    Status <span class="sort-indicator small text-body-secondary" data-sort-indicator="status">↕</span>
                  </button>
                </th>
                <th>
                  <button class="sort-button fw-semibold" data-sort-key="resource" type="button">
                    Resource <span class="sort-indicator small text-body-secondary" data-sort-indicator="resource">↕</span>
                  </button>
                </th>
                <th>
                  <button class="sort-button fw-semibold" data-sort-key="timing" type="button">
                    Timing <span class="sort-indicator small text-body-secondary" data-sort-indicator="timing">↕</span>
                  </button>
                </th>
                <th>
                  <button class="sort-button fw-semibold" data-sort-key="details" type="button">
                    Details <span class="sort-indicator small text-body-secondary" data-sort-indicator="details">↕</span>
                  </button>
                </th>
              </tr>
            </thead>
            <tbody id="jobsTable"></tbody>
          </table>
        </div>
        <div class="d-flex justify-content-between align-items-center pt-3">
          <div id="jobsPaginationSummary" class="pagination-summary"></div>
          <div class="btn-group" role="group" aria-label="Job pagination">
            <button class="btn btn-sm btn-outline-secondary" id="jobsPrevButton" type="button">
              <i class="bi bi-arrow-left"></i> Prev
            </button>
            <button class="btn btn-sm btn-outline-secondary" id="jobsNextButton" type="button">
              Next <i class="bi bi-arrow-right"></i>
            </button>
          </div>
        </div>
      </div>

      <div class="glass rounded-5 p-3 p-lg-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h2 class="h4 mb-1">Artifacts</h2>
            <div class="small-muted">Browse reports and findings directly from the active scan directory.</div>
          </div>
        </div>
        <div id="artifactSections" class="row g-3"></div>
      </div>
    </div>

    <script src="{DASHBOARD_ASSETS["bootstrap_js_src"]}"{bootstrap_js_integrity_attr}></script>
    <script>
      const stateBadgeClass = {{
        pending: "text-bg-secondary",
        running: "text-bg-primary pulse",
        completed: "text-bg-success",
        failed: "text-bg-danger",
        skipped: "text-bg-warning"
      }};

      const statusOrder = {{
        running: 0,
        pending: 1,
        failed: 2,
        skipped: 3,
        completed: 4
      }};

      const jobsPerPage = 5;
      let selectedJobId = null;
      let allJobs = [];
      let activeRunningJobs = [];
      let currentPage = 1;
      let currentSortKey = "status";
      let currentSortDirection = "asc";
      let jobSearchQuery = "";
      let logAutoScrollEnabled = true;

      function isLogNearBottom(element, threshold = 20) {{
        return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
      }}

      function escapeHtml(value) {{
        return String(value ?? "").replace(/[&<>"']/g, (char) => {{
          return {{
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
          }}[char];
        }});
      }}

      function renderMetrics(counts) {{
        const metrics = [
          ["Pending", counts.pending ?? 0, "bi-hourglass-split", "secondary"],
          ["Running", counts.running ?? 0, "bi-activity", "primary"],
          ["Completed", counts.completed ?? 0, "bi-check2-circle", "success"],
          ["Skipped", counts.skipped ?? 0, "bi-skip-forward-circle", "warning"],
          ["Failed", counts.failed ?? 0, "bi-exclamation-octagon", "danger"]
        ];

        document.getElementById("metrics").innerHTML = metrics.map(([label, value, icon, tone]) => `
          <div class="col-sm-6 col-xl">
            <div class="glass rounded-5 p-3 p-lg-4 metric h-100">
              <div class="d-flex justify-content-between align-items-start mb-3">
                <div class="small text-uppercase fw-semibold text-${{tone}}">${{label}}</div>
                <i class="bi ${{icon}} fs-4 text-${{tone}}"></i>
              </div>
              <div class="display-6 mb-1">${{value}}</div>
              <div class="small-muted">Current job count</div>
            </div>
          </div>
        `).join("");
      }}

      function getJobDetail(job) {{
        return job.error || job.reason || (job.deps.length ? `deps: ${{job.deps.join(", ")}}` : "ready");
      }}

      function parseSortableDate(value) {{
        if (!value) {{
          return 0;
        }}

        const normalized = String(value).trim().replace(" ", "T");
        const parsed = Date.parse(normalized);
        return Number.isNaN(parsed) ? 0 : parsed;
      }}

      function getTimingSortValue(job) {{
        return parseSortableDate(job.started_at) || parseSortableDate(job.updated_at) || parseSortableDate(job.finished_at);
      }}

      function compareSortValues(left, right) {{
        if (typeof left === "number" && typeof right === "number") {{
          return left - right;
        }}

        return String(left ?? "").localeCompare(String(right ?? ""), undefined, {{
          numeric: true,
          sensitivity: "base"
        }});
      }}

      function getJobSortValue(job, sortKey) {{
        switch (sortKey) {{
          case "job":
            return `${{job.job_id || ""}} ${{job.description || ""}}`;
          case "status":
            return statusOrder[job.state] ?? 99;
          case "resource":
            return job.resource || "";
          case "timing":
            return getTimingSortValue(job);
          case "details":
            return getJobDetail(job);
          default:
            return job.job_id || "";
        }}
      }}

      function updateSortIndicators() {{
        document.querySelectorAll("[data-sort-indicator]").forEach((indicator) => {{
          const isActive = indicator.dataset.sortIndicator === currentSortKey;
          indicator.textContent = isActive ? (currentSortDirection === "asc" ? "▲" : "▼") : "↕";
          indicator.classList.toggle("sort-indicator-active", isActive);
          indicator.classList.toggle("sort-indicator-idle", !isActive);
        }});

        document.querySelectorAll("[data-sort-key]").forEach((button) => {{
          button.classList.toggle("active", button.dataset.sortKey === currentSortKey);
        }});
      }}

      function sortJobs(jobs) {{
        const direction = currentSortDirection === "asc" ? 1 : -1;
        return [...jobs].sort((left, right) => {{
          const result = compareSortValues(
            getJobSortValue(left, currentSortKey),
            getJobSortValue(right, currentSortKey)
          );
          if (result !== 0) {{
            return result * direction;
          }}
          return left.job_id.localeCompare(right.job_id);
        }});
      }}

      function getJobSearchValue(job) {{
        return [
          job.job_id || "",
          job.description || "",
          job.state || "",
          job.resource || "",
          getJobDetail(job),
          ...(job.deps || [])
        ].join(" ").toLowerCase();
      }}

      function renderJobs(jobs, runningJobs) {{
        allJobs = [...jobs];
        activeRunningJobs = [...runningJobs];
        const normalizedQuery = jobSearchQuery.trim().toLowerCase();
        const filteredJobs = normalizedQuery
          ? allJobs.filter((job) => getJobSearchValue(job).includes(normalizedQuery))
          : allJobs;
        const sortedJobs = sortJobs(filteredJobs);
        const totalPages = Math.max(1, Math.ceil(sortedJobs.length / jobsPerPage));
        currentPage = Math.min(currentPage, totalPages);
        const startIndex = (currentPage - 1) * jobsPerPage;
        const pagedJobs = sortedJobs.slice(startIndex, startIndex + jobsPerPage);

        document.getElementById("runningBanner").innerHTML = runningJobs.length
          ? `<span class="badge text-bg-primary-subtle border border-primary-subtle text-primary-emphasis">${{runningJobs.length}} running</span>`
          : `<span class="badge text-bg-success-subtle border border-success-subtle text-success-emphasis">Idle</span>`;

        updateSortIndicators();
        document.getElementById("jobsSearchSummary").textContent = normalizedQuery
          ? `${{sortedJobs.length}} match${{sortedJobs.length === 1 ? "" : "es"}} for "${{jobSearchQuery}}"`
          : `${{allJobs.length}} total jobs`;
        document.getElementById("jobsPaginationSummary").textContent = sortedJobs.length
          ? `Showing ${{startIndex + 1}}-${{Math.min(startIndex + jobsPerPage, sortedJobs.length)}} of ${{sortedJobs.length}} jobs`
          : "No jobs available";
        document.getElementById("jobsPrevButton").disabled = currentPage <= 1;
        document.getElementById("jobsNextButton").disabled = currentPage >= totalPages;

        document.getElementById("jobsTable").innerHTML = pagedJobs.map((job) => {{
          const badge = stateBadgeClass[job.state] || "text-bg-secondary";
          const detail = getJobDetail(job);
          return `
            <tr class="job-row" data-job-id="${{escapeHtml(job.job_id)}}">
              <td>
                <div class="fw-semibold">${{escapeHtml(job.job_id)}}</div>
                <div class="small-muted">${{escapeHtml(job.description)}}</div>
              </td>
              <td><span class="badge badge-state ${{badge}}">${{escapeHtml(job.state)}}</span></td>
              <td><span class="small text-uppercase fw-semibold">${{escapeHtml(job.resource || "-")}}</span></td>
              <td>
                <div class="small">${{escapeHtml(job.started_at || "not started")}}</div>
                <div class="small text-body-secondary">${{escapeHtml(job.finished_at || job.updated_at || "")}}</div>
              </td>
              <td class="small">${{escapeHtml(detail)}}</td>
            </tr>
          `;
        }}).join("");

        document.querySelectorAll(".job-row").forEach((row) => {{
          row.addEventListener("click", () => {{
            selectedJobId = row.dataset.jobId;
            logAutoScrollEnabled = true;
            fetchLog();
          }});
        }});
      }}

      function renderArtifacts(sections) {{
        const artifactStyles = {{
          nmap: {{ icon: "bi-diagram-3-fill", accent: "#1d4ed8", soft: "#e8f0ff", label: "Nmap" }},
          ssl: {{ icon: "bi-shield-lock-fill", accent: "#0f766e", soft: "#def7f3", label: "SSL/TLS" }},
          headers: {{ icon: "bi-hdd-network-fill", accent: "#2563eb", soft: "#e9f1ff", label: "Headers" }},
          nuclei: {{ icon: "bi-bug-fill", accent: "#b42318", soft: "#fde8e8", label: "Nuclei" }},
          zap: {{ icon: "bi-shield-exclamation", accent: "#db5a2d", soft: "#fff1e8", label: "OWASP ZAP" }},
          eyewitness: {{ icon: "bi-camera-fill", accent: "#0f766e", soft: "#e0f7f4", label: "EyeWitness" }},
          ssh: {{ icon: "bi-terminal-fill", accent: "#475569", soft: "#edf2f7", label: "SSH" }},
          vpn: {{ icon: "bi-wifi", accent: "#0ea5e9", soft: "#e0f2fe", label: "VPN/IKE" }},
          findings: {{ icon: "bi-file-earmark-text-fill", accent: "#6b7280", soft: "#f3f4f6", label: "Finding" }},
          reports: {{ icon: "bi-file-earmark-richtext-fill", accent: "#7c3aed", soft: "#f3e8ff", label: "Report" }}
        }};

        function getArtifactStyle(section, file) {{
          const label = (section.label || "").toLowerCase();
          const path = (file.relative_path || "").toLowerCase();

          if (path.includes("/zap/")) return artifactStyles.zap;
          if (path.includes("/nuclei/")) return artifactStyles.nuclei;
          if (path.includes("eyewitness")) return artifactStyles.eyewitness;
          if (label.includes("nmap") || path.includes("/01_nmap/")) return artifactStyles.nmap;
          if (label.includes("ssl") || path.includes("/03_ssl/")) return artifactStyles.ssl;
          if (label.includes("header") || path.includes("/04_headers/") || path.includes("header")) return artifactStyles.headers;
          if (path.includes("/06_services/ssh/") || path.includes("ssh")) return artifactStyles.ssh;
          if (path.includes("/06_services/vpn/") || path.includes("ike")) return artifactStyles.vpn;
          if (label.includes("service") || label.includes("report")) return artifactStyles.reports;
          return artifactStyles.findings;
        }}

        document.getElementById("artifactSections").innerHTML = sections.map((section) => `
          <div class="col-12">
            <div class="artifact-section-panel rounded-4 p-3">
              <div class="d-flex justify-content-between align-items-center mb-3">
                <h3 class="h5 mb-0">${{escapeHtml(section.label)}}</h3>
                <span class="badge text-bg-light border">${{section.files.length}} files</span>
              </div>
              <div class="row g-3">
                ${{section.files.map((file) => {{
                  const style = getArtifactStyle(section, file);
                  return `
                  <div class="col-md-6 col-xxl-4">
                    <a class="artifact-link text-reset" href="${{file.url}}" target="_blank" rel="noopener">
                      <div class="artifact-card rounded-4 p-3 h-100" style="--artifact-accent: ${{style.accent}}; --artifact-soft: ${{style.soft}};">
                        <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
                          <div class="artifact-icon fs-5">
                            <i class="bi ${{style.icon}}"></i>
                          </div>
                          <span class="badge artifact-kind rounded-pill">${{escapeHtml(style.label)}}</span>
                        </div>
                        <div class="fw-semibold text-truncate">${{escapeHtml(file.name)}}</div>
                        <div class="small-muted text-truncate">${{escapeHtml(file.parent)}}</div>
                        <div class="d-flex justify-content-between align-items-center gap-2 mt-3 mb-1">
                          <div class="small">${{escapeHtml(file.modified_at)}}</div>
                          <span class="badge artifact-filetype rounded-pill">${{escapeHtml(file.file_type || "FILE")}}</span>
                        </div>
                        <div class="small text-body-secondary">${{escapeHtml(file.size)}}</div>
                      </div>
                    </a>
                  </div>
                `;
                }}).join("")}}
              </div>
            </div>
          </div>
        `).join("");
      }}

      async function fetchState() {{
        const response = await fetch("/api/state", {{ cache: "no-store" }});
        if (!response.ok) {{
          return;
        }}

        const state = await response.json();
        document.getElementById("scanName").textContent = state.scan_name;
        document.getElementById("scanPath").textContent = state.scan_dir;
        document.getElementById("generatedAt").textContent = state.generated_at ? `Run summary updated: ${{state.generated_at}}` : "Run summary not written yet";
        renderMetrics(state.counts);
        renderJobs(state.jobs, state.running_jobs || []);
        renderArtifacts(state.sections || []);

        if (!selectedJobId && state.jobs.length) {{
          const preferred = state.jobs.find((job) => job.state === "running") || state.jobs[0];
          selectedJobId = preferred.job_id;
          fetchLog();
        }}
      }}

      async function fetchLog() {{
        if (!selectedJobId) {{
          return;
        }}

        const logView = document.getElementById("logView");
        const shouldAutoScroll = logAutoScrollEnabled || isLogNearBottom(logView);
        const response = await fetch(`/api/job/${{encodeURIComponent(selectedJobId)}}/log?tail=250`, {{ cache: "no-store" }});
        if (!response.ok) {{
          logView.textContent = "Unable to load log.";
          return;
        }}

        const payload = await response.json();
        document.getElementById("selectedJobLabel").textContent = payload.path || selectedJobId;
        logView.textContent = payload.content || "No log output yet.";
        if (shouldAutoScroll) {{
          logView.scrollTop = logView.scrollHeight;
          logAutoScrollEnabled = true;
        }}
      }}

      document.getElementById("copyLogButton").addEventListener("click", async () => {{
        const button = document.getElementById("copyLogButton");
        const originalMarkup = button.innerHTML;
        const logText = document.getElementById("logView").textContent || "";

        try {{
          await navigator.clipboard.writeText(logText);
          button.innerHTML = '<i class="bi bi-check2"></i> Copied';
        }} catch (error) {{
          button.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Failed';
        }}

        setTimeout(() => {{
          button.innerHTML = originalMarkup;
        }}, 1400);
      }});
      document.getElementById("logView").addEventListener("scroll", (event) => {{
        logAutoScrollEnabled = isLogNearBottom(event.currentTarget);
      }});
      document.getElementById("refreshLogButton").addEventListener("click", fetchLog);
      document.getElementById("jobsSearchInput").addEventListener("input", (event) => {{
        jobSearchQuery = event.target.value || "";
        currentPage = 1;
        renderJobs(allJobs, activeRunningJobs);
      }});
      document.querySelectorAll("[data-sort-key]").forEach((button) => {{
        button.addEventListener("click", () => {{
          const sortKey = button.dataset.sortKey;
          if (currentSortKey === sortKey) {{
            currentSortDirection = currentSortDirection === "asc" ? "desc" : "asc";
          }} else {{
            currentSortKey = sortKey;
            currentSortDirection = sortKey === "timing" ? "desc" : "asc";
          }}
          currentPage = 1;
          renderJobs(allJobs, activeRunningJobs);
        }});
      }});
      document.getElementById("jobsPrevButton").addEventListener("click", () => {{
        if (currentPage > 1) {{
          currentPage -= 1;
          renderJobs(allJobs, activeRunningJobs);
        }}
      }});
      document.getElementById("jobsNextButton").addEventListener("click", () => {{
        const totalPages = Math.max(1, Math.ceil(allJobs.length / jobsPerPage));
        if (currentPage < totalPages) {{
          currentPage += 1;
          renderJobs(allJobs, activeRunningJobs);
        }}
      }});

      fetchState();
      setInterval(fetchState, 4000);
      setInterval(fetchLog, 4000);
    </script>
  </body>
</html>"""


def build_handler(scan_dir):
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "FireAbendDashboard/1.0"

        def log_message(self, format_string, *args):
            return

        def send_json(self, payload, status=200):
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_html(self, markup, status=200):
            body = markup.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_text(self, content, status=200):
            body = content.encode("utf-8", errors="replace")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def serve_file(self, relative_path):
            requested_path = (scan_dir / unquote(relative_path)).resolve()
            if scan_dir not in requested_path.parents and requested_path != scan_dir:
                self.send_error(403)
                return
            if not requested_path.is_file():
                self.send_error(404)
                return

            mime_type, _ = mimetypes.guess_type(str(requested_path))
            mime_type = mime_type or "application/octet-stream"
            data = requested_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def serve_asset_file(self, asset_name):
            requested_path = DASHBOARD_ASSETS["asset_files"].get(unquote(asset_name))
            if requested_path is None or not requested_path.is_file():
                self.send_error(404)
                return

            mime_type, _ = mimetypes.guess_type(str(requested_path))
            mime_type = mime_type or "application/octet-stream"
            data = requested_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_html(render_index())
                return

            if parsed.path == "/api/state":
                self.send_json(build_state(scan_dir))
                return

            if parsed.path.startswith("/api/job/") and parsed.path.endswith("/log"):
                job_id = parsed.path.split("/")[3]
                tail_lines = int(parse_qs(parsed.query).get("tail", ["200"])[0])
                log_path = scan_dir / "00_runtime" / "logs" / f"{job_id}.log"
                payload = {
                    "job_id": job_id,
                    "path": str(log_path.relative_to(scan_dir)) if log_path.exists() else "",
                    "content": tail_file(log_path, tail_lines),
                }
                self.send_json(payload)
                return

            if parsed.path.startswith("/files/"):
                self.serve_file(parsed.path[len("/files/"):])
                return

            if parsed.path.startswith("/assets/"):
                self.serve_asset_file(parsed.path[len("/assets/"):])
                return

            self.send_error(404)

    return DashboardHandler


def main():
    args = parse_args()
    scan_dir = Path(args.scan_dir).resolve()
    if not scan_dir.is_dir():
        raise SystemExit(f"Scan directory not found: {scan_dir}")

    handler = build_handler(scan_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    dashboard_url = f"http://{args.host}:{args.port}/"
    print(f"[dashboard] serving {scan_dir} at {dashboard_url}", flush=True)

    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open_new_tab(dashboard_url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
