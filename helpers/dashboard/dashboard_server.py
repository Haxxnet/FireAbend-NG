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
DEFAULT_DASHBOARD_PORT = 42420


def parse_args():
    parser = argparse.ArgumentParser(description="Serve a local FireAbend scan dashboard.")
    parser.add_argument("--scan-dir", required=True, help="Path to the FireAbend scan directory.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--browser-host", default=None, help="Host to use for the printed/opened browser URL. Defaults to the bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_DASHBOARD_PORT, help="Port to bind.")
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
    nuclei_candidates = []
    for item in sorted(findings_dir.rglob("*")):
        if not item.is_file():
            continue

        rel_path = item.relative_to(scan_dir).as_posix()
        rel_findings_path = item.relative_to(findings_dir).as_posix()

        if rel_findings_path.startswith("zap/"):
            if rel_findings_path == "zap/zap_summary.txt" or rel_findings_path.startswith("zap/raw_html/"):
                relative_paths.append(rel_path)
            continue

        if rel_findings_path.startswith("nuclei/"):
            nuclei_candidates.append(rel_path)
            continue

        relative_paths.append(rel_path)

    if nuclei_candidates:
        preferred_nuclei_path = next(
            (
                path
                for suffix in (".json", ".jsonl", ".txt")
                for path in nuclei_candidates
                if path.lower().endswith(suffix)
            ),
            nuclei_candidates[0],
        )
        relative_paths.append(preferred_nuclei_path)

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
      .jobs-table-wrap {{
        overflow-x: auto;
      }}
      .metric {{
        min-height: 96px;
        padding: 0.9rem !important;
      }}
      .metric-header {{
        margin-bottom: 0.5rem;
      }}
      .metric-label {{
        font-size: 0.74rem;
        letter-spacing: 0.08em;
        line-height: 1.1;
      }}
      .metric-value {{
        font-size: clamp(1.45rem, 2.8vw, 1.9rem);
        font-weight: 700;
        line-height: 1.05;
      }}
      .metric-icon {{
        font-size: 1.15rem;
      }}
      .metric-caption {{
        font-size: 0.78rem;
      }}
      @media (max-width: 991.98px) {{
        .metric {{
          min-height: 72px;
          padding: 0.7rem !important;
          border-radius: 1.2rem !important;
        }}
        .metric-header {{
          margin-bottom: 0.35rem;
        }}
        .metric-label {{
          font-size: 0.66rem;
          letter-spacing: 0.07em;
        }}
        .metric-value {{
          font-size: 1.35rem;
        }}
        .metric-icon {{
          font-size: 0.98rem;
        }}
        .metric-caption {{
          display: none;
        }}
      }}
      @media (max-width: 767.98px) {{
        .metric {{
          min-height: 64px;
          padding: 0.6rem !important;
        }}
        .metric-value {{
          font-size: 1.18rem;
        }}
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
      @media (max-width: 767.98px) {{
        .job-search {{
          max-width: none;
          width: 100%;
        }}
        .jobs-footer {{
          flex-direction: column;
          align-items: stretch !important;
          gap: 0.85rem;
        }}
        .jobs-footer .btn-group {{
          width: 100%;
        }}
        .jobs-footer .btn-group > .btn {{
          flex: 1 1 0;
        }}
        .jobs-table-wrap {{
          overflow: visible;
        }}
        .jobs-table,
        .jobs-table tbody,
        .jobs-table tr,
        .jobs-table td {{
          display: block;
          width: 100%;
        }}
        .jobs-table thead {{
          display: none;
        }}
        .jobs-table tbody {{
          display: grid;
          gap: 0.9rem;
        }}
        .jobs-table .job-row {{
          border: 1px solid rgba(148, 163, 184, 0.16);
          border-radius: 1rem;
          overflow: hidden;
          background: rgba(15, 23, 42, 0.56);
          box-shadow: 0 14px 30px rgba(2, 6, 23, 0.16);
        }}
        .jobs-table td {{
          display: grid;
          grid-template-columns: minmax(5.75rem, 7rem) minmax(0, 1fr);
          gap: 0.75rem;
          align-items: start;
          padding: 0.75rem 0.9rem;
          border-bottom: 1px solid rgba(148, 163, 184, 0.12);
        }}
        .jobs-table td:last-child {{
          border-bottom: 0;
        }}
        .jobs-table td::before {{
          content: attr(data-label);
          color: var(--fa-muted);
          font-size: 0.74rem;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }}
        .jobs-table td > * {{
          min-width: 0;
        }}
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
        <div class="table-responsive jobs-table-wrap">
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
        <div class="d-flex justify-content-between align-items-center pt-3 jobs-footer">
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
          <div class="col-6 col-md-4 col-xl">
            <div class="glass rounded-5 p-3 metric h-100">
              <div class="d-flex justify-content-between align-items-start metric-header">
                <div class="metric-label text-uppercase fw-semibold text-${{tone}}">${{label}}</div>
                <i class="bi ${{icon}} metric-icon text-${{tone}}"></i>
              </div>
              <div class="metric-value mb-1">${{value}}</div>
              <div class="small-muted metric-caption">Current job count</div>
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
              <td data-label="Job">
                <div class="fw-semibold">${{escapeHtml(job.job_id)}}</div>
                <div class="small-muted">${{escapeHtml(job.description)}}</div>
              </td>
              <td data-label="Status"><span class="badge badge-state ${{badge}}">${{escapeHtml(job.state)}}</span></td>
              <td data-label="Resource"><span class="small text-uppercase fw-semibold">${{escapeHtml(job.resource || "-")}}</span></td>
              <td data-label="Timing">
                <div class="small">${{escapeHtml(job.started_at || "not started")}}</div>
                <div class="small text-body-secondary">${{escapeHtml(job.finished_at || job.updated_at || "")}}</div>
              </td>
              <td class="small" data-label="Details">${{escapeHtml(detail)}}</td>
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

        function buildArtifactHref(file) {{
          const path = String(file.relative_path || "");
          if (path.toLowerCase().includes("/nuclei/")) {{
            return `/nuclei-viewer?artifact=${{encodeURIComponent(path)}}`;
          }}
          return file.url;
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
                    <a class="artifact-link text-reset" href="${{buildArtifactHref(file)}}" target="_blank" rel="noopener">
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


def render_nuclei_viewer():
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
    return """<!doctype html>
<html lang="en" data-bs-theme="dark">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nuclei Results Viewer</title>
    <link href="__BOOTSTRAP_CSS_HREF__" rel="stylesheet"__BOOTSTRAP_CSS_INTEGRITY__>
    <link rel="stylesheet" href="__BOOTSTRAP_ICONS_HREF__">
    <style>
      :root {
        --nv-bg: #05070c;
        --nv-panel: rgba(13, 16, 23, 0.92);
        --nv-panel-soft: rgba(18, 22, 31, 0.92);
        --nv-border: rgba(148, 163, 184, 0.14);
        --nv-ink: #edf2f8;
        --nv-muted: #8b98ad;
        --nv-accent: #4f46e5;
        --nv-critical: #7c3aed;
        --nv-high: #dc2626;
        --nv-medium: #f97316;
        --nv-low: #eab308;
        --nv-info: #22c55e;
        --nv-unknown: #64748b;
      }
      body {
        background:
          radial-gradient(circle at top left, rgba(79, 70, 229, 0.11), transparent 24%),
          radial-gradient(circle at top right, rgba(124, 58, 237, 0.12), transparent 22%),
          linear-gradient(180deg, #090b10 0%, var(--nv-bg) 100%);
        color: var(--nv-ink);
        min-height: 100vh;
      }
      .shell {
        max-width: 1880px;
      }
      .hero,
      .panel {
        background: var(--nv-panel);
        border: 1px solid var(--nv-border);
        box-shadow: 0 20px 48px rgba(0, 0, 0, 0.28);
      }
      .hero {
        background: linear-gradient(180deg, rgba(19, 23, 33, 0.96), rgba(12, 15, 22, 0.96));
      }
      .panel-soft {
        background: var(--nv-panel-soft);
      }
      .small-muted {
        color: var(--nv-muted);
      }
      .metric-card {
        min-height: 92px;
      }
      .metric-value {
        font-size: clamp(1.35rem, 2.5vw, 1.85rem);
        font-weight: 700;
      }
      .main-grid {
        display: grid;
        grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
        gap: 1.25rem;
      }
      .sidebar-panel {
        padding: 1rem;
      }
      .sidebar-section + .sidebar-section {
        margin-top: 1rem;
      }
      .sidebar-list {
        max-height: 16rem;
        overflow: auto;
        border: 1px solid rgba(148, 163, 184, 0.12);
        border-radius: 1rem;
        background: rgba(10, 13, 19, 0.9);
      }
      .sidebar-row {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr) auto;
        gap: 0.75rem;
        align-items: center;
        padding: 0.72rem 0.85rem;
        border-bottom: 1px solid rgba(148, 163, 184, 0.08);
      }
      .sidebar-row:last-child {
        border-bottom: 0;
      }
      .sidebar-row input[type="checkbox"] {
        accent-color: var(--nv-accent);
      }
      .sidebar-label {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 0.93rem;
      }
      .count-badge {
        min-width: 1.7rem;
        height: 1.7rem;
        padding: 0 0.45rem;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: rgba(148, 163, 184, 0.12);
        color: var(--nv-ink);
        font-size: 0.78rem;
        font-weight: 700;
      }
      .toolbar {
        display: flex;
        gap: 0.85rem;
        align-items: center;
        flex-wrap: wrap;
      }
      .toolbar .form-control,
      .toolbar .form-select {
        background: rgba(10, 13, 19, 0.92);
        border: 1px solid rgba(148, 163, 184, 0.18);
        color: var(--nv-ink);
      }
      .toolbar .form-control::placeholder {
        color: var(--nv-muted);
      }
      .toolbar .form-control:focus,
      .toolbar .form-select:focus {
        background: rgba(10, 13, 19, 0.98);
        color: var(--nv-ink);
        border-color: rgba(79, 70, 229, 0.45);
        box-shadow: 0 0 0 0.2rem rgba(79, 70, 229, 0.16);
      }
      .results-table-wrap {
        border: 1px solid rgba(148, 163, 184, 0.12);
        border-radius: 1rem;
        overflow: auto;
        background: rgba(10, 13, 19, 0.92);
      }
      .results-table {
        margin-bottom: 0;
        --bs-table-bg: transparent;
        --bs-table-color: var(--nv-ink);
        --bs-table-border-color: rgba(148, 163, 184, 0.1);
        --bs-table-hover-color: var(--nv-ink);
      }
      .results-table thead th {
        position: sticky;
        top: 0;
        z-index: 1;
        background: rgba(28, 32, 42, 0.97);
        color: #cfd6e4;
        font-size: 0.79rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
      }
      .results-table tbody tr {
        cursor: pointer;
      }
      .results-table tbody tr:hover td {
        background: rgba(79, 70, 229, 0.08);
      }
      .results-table tbody tr.active-row td {
        background: rgba(79, 70, 229, 0.14);
        box-shadow: inset 0 0 0 999px rgba(79, 70, 229, 0.05);
      }
      .results-table td {
        vertical-align: middle;
      }
      .title-cell {
        min-width: 22rem;
        max-width: 32rem;
      }
      .title-text {
        font-weight: 600;
      }
      .mono-cell {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 0.88rem;
      }
      .severity-pill {
        border: 1px solid color-mix(in srgb, var(--severity-color, var(--nv-unknown)) 44%, transparent);
        background: color-mix(in srgb, var(--severity-color, var(--nv-unknown)) 18%, rgba(19, 23, 33, 0.92));
        color: color-mix(in srgb, var(--severity-color, var(--nv-unknown)) 88%, white);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: 0.75rem;
        font-weight: 700;
      }
      .detail-panel {
        margin-top: 1rem;
      }
      .detail-block {
        border: 1px solid rgba(148, 163, 184, 0.12);
        background: rgba(13, 16, 23, 0.72);
      }
      .detail-code {
        max-height: 14rem;
        overflow: auto;
        background: #090d14;
        color: #dbe7f5;
        border-radius: 0.9rem;
        font-size: 0.88rem;
      }
      .empty-state {
        min-height: 16rem;
        display: grid;
        place-items: center;
        text-align: center;
      }
      .link-subtle {
        color: #b9c4ff;
        text-decoration: none;
      }
      .link-subtle:hover {
        color: #e0e7ff;
      }
      .severity-text-critical { color: var(--nv-critical); }
      .severity-text-high { color: var(--nv-high); }
      .severity-text-medium { color: var(--nv-medium); }
      .severity-text-low { color: var(--nv-low); }
      .severity-text-info { color: var(--nv-info); }
      .severity-text-unknown { color: var(--nv-unknown); }
      @media (max-width: 1199.98px) {
        .main-grid {
          grid-template-columns: 1fr;
        }
      }
      @media (max-width: 767.98px) {
        .toolbar {
          flex-direction: column;
          align-items: stretch;
        }
        .title-cell {
          min-width: 14rem;
        }
      }
    </style>
  </head>
  <body>
    <div class="container-fluid py-4 py-lg-5 shell">
      <section class="hero rounded-5 p-4 p-lg-5 mb-4">
        <div class="row g-4 align-items-end">
          <div class="col-lg-8">
            <div class="text-uppercase small fw-semibold text-primary-emphasis mb-2">Client-side Viewer</div>
            <h1 class="display-6 fw-bold mb-2">Nuclei Results</h1>
            <p class="mb-0 text-white-50">ProjectDiscovery-inspired browser view for filtering and inspecting nuclei findings without a backend parser.</p>
          </div>
          <div class="col-lg-4 text-lg-end">
            <div id="viewerArtifactName" class="fs-5 fw-semibold">Waiting for artifact…</div>
            <div id="viewerArtifactPath" class="small text-white-50"></div>
            <div id="viewerStatus" class="small text-white-50 mt-2"></div>
          </div>
        </div>
      </section>

      <section class="row g-3 mb-4" id="nucleiMetrics"></section>

      <section class="main-grid">
        <aside class="panel panel-soft rounded-5 sidebar-panel">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <div>
              <h2 class="h5 mb-1">Filters</h2>
              <div class="small-muted">Narrow the results like the PD dashboard.</div>
            </div>
            <button id="clearFiltersButton" class="btn btn-sm btn-outline-light" type="button">Reset</button>
          </div>

          <section class="sidebar-section">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <h3 class="h6 mb-0">Severity</h3>
              <span class="small-muted small">Risk</span>
            </div>
            <div id="severityFilters" class="sidebar-list"></div>
          </section>

          <section class="sidebar-section">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <h3 class="h6 mb-0">Host</h3>
              <span id="hostFilterSummary" class="small-muted small"></span>
            </div>
            <div id="hostFilters" class="sidebar-list"></div>
          </section>

          <section class="sidebar-section">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <h3 class="h6 mb-0">Template</h3>
              <span id="templateFilterSummary" class="small-muted small"></span>
            </div>
            <div id="templateFilters" class="sidebar-list"></div>
          </section>
        </aside>

        <section class="panel panel-soft rounded-5 p-3 p-lg-4">
          <div class="toolbar mb-3">
            <div class="flex-grow-1" style="min-width: 16rem;">
              <label class="visually-hidden" for="searchInput">Search findings</label>
              <input id="searchInput" class="form-control" type="search" placeholder="Type to search finding, host, ip, port, or template id">
            </div>
            <div style="min-width: 11rem;">
              <label class="visually-hidden" for="typeFilter">Type</label>
              <select id="typeFilter" class="form-select">
                <option value="">All types</option>
              </select>
            </div>
            <a id="openRawArtifact" class="btn btn-outline-secondary" href="#" target="_blank" rel="noopener">
              <i class="bi bi-file-earmark-text"></i> Raw
            </a>
            <a id="openJsonArtifact" class="btn btn-outline-secondary" href="#" target="_blank" rel="noopener">
              <i class="bi bi-braces"></i> JSON
            </a>
          </div>

          <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
            <div>
              <h2 class="h5 mb-1">Results</h2>
              <div id="resultSummary" class="small-muted">Loading results…</div>
            </div>
            <div class="small-muted">Compact table view, no description clutter</div>
          </div>

          <div class="results-table-wrap">
            <table class="table results-table align-middle">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Host</th>
                  <th>IP Address</th>
                  <th>Port</th>
                  <th>Severity</th>
                  <th>Last Found</th>
                  <th>Template</th>
                </tr>
              </thead>
              <tbody id="resultsTableBody"></tbody>
            </table>
          </div>

          <div class="panel rounded-4 p-3 p-lg-4 detail-panel">
            <div class="d-flex justify-content-between align-items-start gap-3 mb-3">
              <div>
                <h2 class="h5 mb-1">Details</h2>
                <div class="small-muted">Select a row to inspect the underlying nuclei result payload.</div>
              </div>
              <div id="detailSelectionState" class="small-muted">No row selected</div>
            </div>
            <div id="resultDetail"></div>
          </div>
        </section>
      </section>
    </div>

    <script src="__BOOTSTRAP_JS_SRC__"__BOOTSTRAP_JS_INTEGRITY__></script>
    <script>
      const severityOrder = ["critical", "high", "medium", "low", "info", "unknown"];
      const severityColors = {
        critical: "var(--nv-critical)",
        high: "var(--nv-high)",
        medium: "var(--nv-medium)",
        low: "var(--nv-low)",
        info: "var(--nv-info)",
        unknown: "var(--nv-unknown)"
      };

      let allResults = [];
      let filteredResults = [];
      let selectedResultIndex = -1;
      let activeArtifactPath = "";
      let activeJsonArtifactPath = "";
      let activeRawArtifactPath = "";
      let availableNucleiFiles = [];
      const selectedSeverities = new Set(severityOrder);
      const selectedHosts = new Set();
      const selectedTemplates = new Set();

      function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;"
        })[char]);
      }

      function getQueryParam(name) {
        return new URLSearchParams(window.location.search).get(name) || "";
      }

      function normalizeSeverity(value) {
        const normalized = String(value || "unknown").trim().toLowerCase();
        return severityOrder.includes(normalized) ? normalized : "unknown";
      }

      function severityRank(value) {
        const index = severityOrder.indexOf(normalizeSeverity(value));
        return index === -1 ? severityOrder.length : index;
      }

      function uniq(values) {
        return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
      }

      function formatValue(value) {
        if (value == null || value === "") {
          return "-";
        }
        if (Array.isArray(value)) {
          return value.length ? value.join(", ") : "-";
        }
        if (typeof value === "object") {
          return JSON.stringify(value, null, 2);
        }
        return String(value);
      }

      function parseUrlSafe(value) {
        if (!value || !String(value).includes("://")) {
          return null;
        }
        try {
          return new URL(String(value));
        } catch (error) {
          return null;
        }
      }

      function getResultName(result) {
        return result["template-name"] || result.info?.name || result["template-id"] || "Unnamed finding";
      }

      function getResultTemplate(result) {
        return result["template-id"] || "";
      }

      function getResultType(result) {
        return result.type || result.protocol || result.scheme || "";
      }

      function getResultMatchedAt(result) {
        return result["matched-at"] || result.matched || "";
      }

      function getResultHost(result) {
        const parsedHost = parseUrlSafe(result.host);
        if (parsedHost) {
          return parsedHost.hostname;
        }

        const parsedMatched = parseUrlSafe(getResultMatchedAt(result));
        if (parsedMatched) {
          return parsedMatched.hostname;
        }

        if (result.host) {
          return String(result.host).replace(/^https?:\\/\\//, "").split("/")[0];
        }

        return result.ip || "";
      }

      function getResultPort(result) {
        if (result.port) {
          return String(result.port);
        }

        for (const candidate of [result.host, getResultMatchedAt(result)]) {
          const parsed = parseUrlSafe(candidate);
          if (parsed) {
            if (parsed.port) {
              return parsed.port;
            }
            if (parsed.protocol === "https:") {
              return "443";
            }
            if (parsed.protocol === "http:") {
              return "80";
            }
          }
        }

        return "";
      }

      function getLastFound(result) {
        if (!result.timestamp) {
          return "-";
        }
        const date = new Date(result.timestamp);
        if (Number.isNaN(date.getTime())) {
          return String(result.timestamp);
        }
        return date.toLocaleString();
      }

      function getResultSearchValue(result) {
        return [
          getResultName(result),
          getResultTemplate(result),
          getResultHost(result),
          result.ip,
          getResultPort(result),
          getResultType(result),
          getResultMatchedAt(result)
        ].join(" ").toLowerCase();
      }

      function buildCandidatePaths(artifactPath) {
        if (!artifactPath) {
          return [];
        }

        const lower = artifactPath.toLowerCase();
        if (lower.endsWith(".json") || lower.endsWith(".jsonl")) {
          return [artifactPath];
        }

        if (lower.endsWith(".txt")) {
          return [
            artifactPath.slice(0, -4) + ".json",
            artifactPath.slice(0, -4) + ".jsonl"
          ];
        }

        return [artifactPath + ".json", artifactPath + ".jsonl"];
      }

      function resolveArtifactPaths(requestedArtifact) {
        const requested = String(requestedArtifact || "");
        const lower = requested.toLowerCase();
        const fallbackJson = availableNucleiFiles.find((path) => path.toLowerCase().endsWith(".json"))
          || availableNucleiFiles.find((path) => path.toLowerCase().endsWith(".jsonl"))
          || "";
        const fallbackRaw = availableNucleiFiles.find((path) => path.toLowerCase().endsWith(".txt")) || "";

        let jsonArtifact = "";
        for (const candidate of buildCandidatePaths(requested)) {
          if (availableNucleiFiles.includes(candidate)) {
            jsonArtifact = candidate;
            break;
          }
        }

        if (!jsonArtifact && (lower.endsWith(".json") || lower.endsWith(".jsonl")) && availableNucleiFiles.includes(requested)) {
          jsonArtifact = requested;
        }
        if (!jsonArtifact) {
          jsonArtifact = fallbackJson;
        }

        let rawArtifact = "";
        if (lower.endsWith(".txt") && availableNucleiFiles.includes(requested)) {
          rawArtifact = requested;
        } else if (jsonArtifact) {
          const jsonLower = jsonArtifact.toLowerCase();
          if (jsonLower.endsWith(".json")) {
            const candidate = jsonArtifact.slice(0, -5) + ".txt";
            if (availableNucleiFiles.includes(candidate)) {
              rawArtifact = candidate;
            }
          }
          if (!rawArtifact && jsonLower.endsWith(".jsonl")) {
            const candidate = jsonArtifact.slice(0, -6) + ".txt";
            if (availableNucleiFiles.includes(candidate)) {
              rawArtifact = candidate;
            }
          }
        }
        if (!rawArtifact) {
          rawArtifact = fallbackRaw;
        }

        return {
          artifactPath: requested || jsonArtifact || rawArtifact,
          jsonArtifactPath: jsonArtifact,
          rawArtifactPath: rawArtifact
        };
      }

      async function fetchState() {
        const response = await fetch("/api/state", { cache: "no-store" });
        if (!response.ok) {
          throw new Error("Unable to load dashboard state.");
        }
        return response.json();
      }

      async function fetchArtifactText(path) {
        const response = await fetch(`/files/${encodeURIComponent(path)}`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`Unable to load artifact: ${path}`);
        }
        return response.text();
      }

      function parseNucleiResults(rawText) {
        const trimmed = rawText.trim();
        if (!trimmed) {
          return [];
        }

        try {
          const parsed = JSON.parse(trimmed);
          if (Array.isArray(parsed)) {
            return parsed;
          }
          if (Array.isArray(parsed.results)) {
            return parsed.results;
          }
          return [parsed];
        } catch (error) {
          const rows = [];
          const lines = rawText.split(/\\r?\\n/);
          for (const line of lines) {
            const candidate = line.trim();
            if (!candidate) {
              continue;
            }
            rows.push(JSON.parse(candidate));
          }
          return rows;
        }
      }

      function hydrateResult(result, index) {
        const severity = normalizeSeverity(result.info?.severity || result.severity);
        return {
          ...result,
          _index: index,
          _severity: severity,
          _name: getResultName(result),
          _template: getResultTemplate(result),
          _host: getResultHost(result),
          _ip: result.ip || "",
          _port: getResultPort(result),
          _type: getResultType(result),
          _matchedAt: getResultMatchedAt(result),
          _lastFound: getLastFound(result),
          _search: getResultSearchValue(result)
        };
      }

      function renderMetrics(results) {
        const counts = {
          total: results.length,
          hosts: new Set(results.map((result) => result._host).filter(Boolean)).size,
          templates: new Set(results.map((result) => result._template).filter(Boolean)).size,
          critical: 0,
          high: 0,
          medium: 0,
          low: 0,
          info: 0,
          unknown: 0
        };

        results.forEach((result) => {
          counts[result._severity] = (counts[result._severity] || 0) + 1;
        });

        const metricDefs = [
          ["Findings", counts.total, "bi-bug-fill", "#818cf8"],
          ["Hosts", counts.hosts, "bi-hdd-network-fill", "#38bdf8"],
          ["Templates", counts.templates, "bi-grid-1x2-fill", "#cbd5e1"],
          ["Critical", counts.critical, "bi-exclamation-octagon-fill", severityColors.critical],
          ["High", counts.high, "bi-fire", severityColors.high],
          ["Medium", counts.medium, "bi-funnel-fill", severityColors.medium],
          ["Low", counts.low, "bi-arrow-down-circle-fill", severityColors.low],
          ["Info", counts.info, "bi-info-circle-fill", severityColors.info]
        ];

        document.getElementById("nucleiMetrics").innerHTML = metricDefs.map(([label, value, icon, color]) => `
          <div class="col-6 col-md-4 col-xl">
            <div class="panel panel-soft rounded-5 p-3 metric-card h-100">
              <div class="d-flex justify-content-between align-items-start mb-2">
                <div class="small text-uppercase fw-semibold" style="color: ${color};">${escapeHtml(label)}</div>
                <i class="bi ${icon}" style="color: ${color};"></i>
              </div>
              <div class="metric-value">${value}</div>
              <div class="small-muted small">Current result count</div>
            </div>
          </div>
        `).join("");
      }

      function renderCheckboxList(containerId, values, selectedSet, renderer, summaryId = null) {
        const container = document.getElementById(containerId);
        if (!values.length) {
          container.innerHTML = `
            <div class="sidebar-row">
              <div class="small-muted">No entries</div>
            </div>
          `;
          if (summaryId) {
            document.getElementById(summaryId).textContent = "";
          }
          return;
        }

        container.innerHTML = values.map(renderer).join("");

        if (summaryId) {
          const total = values.length;
          const selected = selectedSet.size;
          document.getElementById(summaryId).textContent = selected ? `${selected}/${total}` : `${total}`;
        }
      }

      function renderSidebarFilters() {
        const severityCounts = Object.fromEntries(
          severityOrder.map((severity) => [severity, allResults.filter((result) => result._severity === severity).length])
        );
        const hosts = uniq(allResults.map((result) => result._host));
        const templates = uniq(allResults.map((result) => result._template));
        const hostCounts = Object.fromEntries(
          hosts.map((host) => [host, allResults.filter((result) => result._host === host).length])
        );
        const templateCounts = Object.fromEntries(
          templates.map((template) => [template, allResults.filter((result) => result._template === template).length])
        );

        renderCheckboxList(
          "severityFilters",
          severityOrder,
          selectedSeverities,
          (severity) => `
            <label class="sidebar-row">
              <input type="checkbox" data-filter-group="severity" data-filter-value="${escapeHtml(severity)}" ${selectedSeverities.has(severity) ? "checked" : ""}>
              <span class="sidebar-label severity-text-${severity}">${escapeHtml(severity)}</span>
              <span class="count-badge">${severityCounts[severity] || 0}</span>
            </label>
          `
        );

        renderCheckboxList(
          "hostFilters",
          hosts,
          selectedHosts,
          (host) => `
            <label class="sidebar-row">
              <input type="checkbox" data-filter-group="host" data-filter-value="${escapeHtml(host)}" ${selectedHosts.has(host) ? "checked" : ""}>
              <span class="sidebar-label">${escapeHtml(host)}</span>
              <span class="count-badge">${hostCounts[host] || 0}</span>
            </label>
          `,
          "hostFilterSummary"
        );

        renderCheckboxList(
          "templateFilters",
          templates,
          selectedTemplates,
          (template) => `
            <label class="sidebar-row">
              <input type="checkbox" data-filter-group="template" data-filter-value="${escapeHtml(template)}" ${selectedTemplates.has(template) ? "checked" : ""}>
              <span class="sidebar-label">${escapeHtml(template)}</span>
              <span class="count-badge">${templateCounts[template] || 0}</span>
            </label>
          `,
          "templateFilterSummary"
        );

        document.querySelectorAll("[data-filter-group]").forEach((input) => {
          input.addEventListener("change", (event) => {
            const group = event.currentTarget.dataset.filterGroup;
            const value = event.currentTarget.dataset.filterValue;
            const checked = event.currentTarget.checked;
            const targetSet = group === "severity"
              ? selectedSeverities
              : group === "host"
                ? selectedHosts
                : selectedTemplates;

            if (checked) {
              targetSet.add(value);
            } else {
              targetSet.delete(value);
            }
            renderSidebarFilters();
            applyFilters();
          });
        });
      }

      function renderTypeFilter(results) {
        const typeFilter = document.getElementById("typeFilter");
        const previousValue = typeFilter.value;
        const types = uniq(results.map((result) => result._type));
        typeFilter.innerHTML = `<option value="">All types</option>${types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`).join("")}`;
        typeFilter.value = types.includes(previousValue) ? previousValue : "";
      }

      function applyFilters() {
        const searchValue = document.getElementById("searchInput").value.trim().toLowerCase();
        const typeValue = document.getElementById("typeFilter").value;

        filteredResults = allResults
          .filter((result) => selectedSeverities.has(result._severity))
          .filter((result) => !selectedHosts.size || selectedHosts.has(result._host))
          .filter((result) => !selectedTemplates.size || selectedTemplates.has(result._template))
          .filter((result) => !typeValue || result._type === typeValue)
          .filter((result) => !searchValue || result._search.includes(searchValue))
          .sort((left, right) => {
            const severityDiff = severityRank(left._severity) - severityRank(right._severity);
            if (severityDiff !== 0) {
              return severityDiff;
            }
            return left._name.localeCompare(right._name);
          });

        renderResultsTable();
      }

      function renderResultsTable() {
        const tableBody = document.getElementById("resultsTableBody");
        document.getElementById("resultSummary").textContent = filteredResults.length
          ? `${filteredResults.length} of ${allResults.length} findings shown`
          : `0 of ${allResults.length} findings shown`;

        if (!filteredResults.length) {
          selectedResultIndex = -1;
          tableBody.innerHTML = `
            <tr>
              <td colspan="7" class="py-5">
                <div class="empty-state">
                  <div>
                    <div class="fs-1 mb-3 text-warning"><i class="bi bi-funnel"></i></div>
                    <h3 class="h5">No findings match the current filters</h3>
                    <p class="small-muted mb-0">Reset or broaden the filters to bring findings back into view.</p>
                  </div>
                </div>
              </td>
            </tr>
          `;
          renderDetail(null);
          return;
        }

        if (selectedResultIndex === -1 || !filteredResults.some((result) => result._index === selectedResultIndex)) {
          selectedResultIndex = filteredResults[0]._index;
        }

        tableBody.innerHTML = filteredResults.map((result) => `
          <tr class="${result._index === selectedResultIndex ? "active-row" : ""}" data-result-index="${result._index}">
            <td class="title-cell">
              <div class="title-text">${escapeHtml(result._name)}</div>
            </td>
            <td class="mono-cell">${escapeHtml(result._host || "-")}</td>
            <td class="mono-cell">${escapeHtml(result._ip || "-")}</td>
            <td class="mono-cell">${escapeHtml(result._port || "-")}</td>
            <td>
              <span class="badge severity-pill rounded-pill" style="--severity-color: ${severityColors[result._severity]};">
                ${escapeHtml(result._severity)}
              </span>
            </td>
            <td>${escapeHtml(result._lastFound)}</td>
            <td class="mono-cell">${escapeHtml(result._template || "-")}</td>
          </tr>
        `).join("");

        document.querySelectorAll("[data-result-index]").forEach((row) => {
          row.addEventListener("click", () => {
            selectedResultIndex = Number(row.dataset.resultIndex);
            renderResultsTable();
          });
        });

        const selected = filteredResults.find((result) => result._index === selectedResultIndex) || filteredResults[0];
        renderDetail(selected);
      }

      function renderKeyValue(label, value) {
        return `
          <div class="col-md-6">
            <div class="detail-block rounded-4 p-3 h-100">
              <div class="small text-uppercase fw-semibold small-muted mb-2">${escapeHtml(label)}</div>
              <div>${escapeHtml(formatValue(value))}</div>
            </div>
          </div>
        `;
      }

      function renderListBlock(title, values) {
        if (!values || !values.length) {
          return "";
        }
        return `
          <section class="detail-block rounded-4 p-3">
            <div class="small text-uppercase fw-semibold small-muted mb-2">${escapeHtml(title)}</div>
            <div class="d-flex flex-wrap gap-2">
              ${values.map((value) => `<span class="badge text-bg-secondary rounded-pill">${escapeHtml(value)}</span>`).join("")}
            </div>
          </section>
        `;
      }

      function renderCodeBlock(title, value) {
        if (!value) {
          return "";
        }
        return `
          <details class="detail-block rounded-4 p-3">
            <summary class="fw-semibold">${escapeHtml(title)}</summary>
            <pre class="detail-code p-3 mt-3 mb-0"><code>${escapeHtml(formatValue(value))}</code></pre>
          </details>
        `;
      }

      function renderDetail(result) {
        const container = document.getElementById("resultDetail");
        const selectionState = document.getElementById("detailSelectionState");
        if (!result) {
          selectionState.textContent = "No row selected";
          container.innerHTML = `
            <div class="empty-state detail-block rounded-4 p-4">
              <div>
                <div class="fs-1 mb-3 text-warning"><i class="bi bi-binoculars"></i></div>
                <h3 class="h5">No finding selected</h3>
                <p class="small-muted mb-0">Choose a result row to inspect its full nuclei payload.</p>
              </div>
            </div>
          `;
          return;
        }

        selectionState.textContent = `${result._host || "-"}:${result._port || "-"}`;

        const references = result.info?.reference || result.reference || [];
        const extractedResults = result["extracted-results"] || [];
        const tags = result.info?.tags || [];
        const classification = result.info?.classification || {};

        container.innerHTML = `
          <div class="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-4">
            <div>
              <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
                <h3 class="h4 mb-0">${escapeHtml(result._name)}</h3>
                <span class="badge severity-pill rounded-pill" style="--severity-color: ${severityColors[result._severity]};">
                  ${escapeHtml(result._severity)}
                </span>
              </div>
              <div class="small-muted">${escapeHtml(result._host || "-")} on port ${escapeHtml(result._port || "-")}</div>
            </div>
            <div class="small text-end">
              <div><span class="small-muted">Matched:</span> ${escapeHtml(result._matchedAt || "-")}</div>
              <div><span class="small-muted">Last Found:</span> ${escapeHtml(result._lastFound)}</div>
            </div>
          </div>

          <div class="row g-3 mb-3">
            ${renderKeyValue("Template ID", result._template)}
            ${renderKeyValue("Host", result._host)}
            ${renderKeyValue("IP Address", result._ip)}
            ${renderKeyValue("Port", result._port)}
            ${renderKeyValue("Type", result._type)}
            ${renderKeyValue("Matcher", result["matcher-name"] || result.matcher_name)}
            ${renderKeyValue("Template Path", result["template-path"])}
            ${renderKeyValue("CVE", classification["cve-id"] || classification.cve_id)}
            ${renderKeyValue("CVSS Score", classification["cvss-score"] || classification.cvss_score)}
          </div>

          <div class="d-grid gap-3">
            ${renderListBlock("Tags", tags)}
            ${renderListBlock("Extracted Results", extractedResults)}
            ${references.length ? `
              <section class="detail-block rounded-4 p-3">
                <div class="small text-uppercase fw-semibold small-muted mb-2">References</div>
                <div class="d-grid gap-2">
                  ${references.map((reference) => `
                    <a class="link-subtle" href="${escapeHtml(reference)}" target="_blank" rel="noopener">${escapeHtml(reference)}</a>
                  `).join("")}
                </div>
              </section>
            ` : ""}
            ${renderCodeBlock("Curl Command", result["curl-command"] || result.curl_command)}
            ${renderCodeBlock("Request", result.request)}
            ${renderCodeBlock("Response", result.response)}
            ${renderCodeBlock("Raw Result JSON", result)}
          </div>
        `;
      }

      function clearFilters() {
        document.getElementById("searchInput").value = "";
        document.getElementById("typeFilter").value = "";
        selectedSeverities.clear();
        severityOrder.forEach((severity) => selectedSeverities.add(severity));
        selectedHosts.clear();
        selectedTemplates.clear();
        renderSidebarFilters();
        applyFilters();
      }

      function wireFilterControls() {
        document.getElementById("searchInput").addEventListener("input", applyFilters);
        document.getElementById("typeFilter").addEventListener("change", applyFilters);
        document.getElementById("clearFiltersButton").addEventListener("click", clearFilters);
      }

      async function bootstrapViewer() {
        wireFilterControls();

        const requestedArtifact = getQueryParam("artifact");
        const state = await fetchState();
        availableNucleiFiles = (state.sections || [])
          .flatMap((section) => section.files || [])
          .map((file) => file.relative_path)
          .filter((path) => String(path || "").toLowerCase().includes("/nuclei/"));

        const resolved = resolveArtifactPaths(requestedArtifact);
        activeArtifactPath = resolved.artifactPath;
        activeJsonArtifactPath = resolved.jsonArtifactPath;
        activeRawArtifactPath = resolved.rawArtifactPath;

        document.getElementById("viewerArtifactName").textContent = activeArtifactPath ? activeArtifactPath.split("/").pop() : "No nuclei artifact found";
        document.getElementById("viewerArtifactPath").textContent = activeArtifactPath || "No artifact path available";
        document.getElementById("viewerStatus").textContent = activeJsonArtifactPath
          ? "Rendering nuclei findings from the generated JSON artifact."
          : "No nuclei JSON artifact was found for this scan yet.";
        document.getElementById("openJsonArtifact").href = activeJsonArtifactPath ? `/files/${encodeURIComponent(activeJsonArtifactPath)}` : "#";
        document.getElementById("openJsonArtifact").classList.toggle("disabled", !activeJsonArtifactPath);
        document.getElementById("openRawArtifact").href = activeRawArtifactPath ? `/files/${encodeURIComponent(activeRawArtifactPath)}` : "#";
        document.getElementById("openRawArtifact").classList.toggle("disabled", !activeRawArtifactPath);

        if (!activeJsonArtifactPath) {
          renderMetrics([]);
          renderSidebarFilters();
          renderDetail(null);
          document.getElementById("resultsTableBody").innerHTML = `
            <tr>
              <td colspan="7" class="py-5">
                <div class="empty-state">
                  <div>
                    <div class="fs-1 mb-3 text-warning"><i class="bi bi-braces-asterisk"></i></div>
                    <h3 class="h5">No JSON nuclei artifact available</h3>
                    <p class="small-muted mb-0">Run the updated nuclei job, then reopen this viewer to browse findings in the new table layout.</p>
                  </div>
                </div>
              </td>
            </tr>
          `;
          document.getElementById("resultSummary").textContent = "No JSON artifact available";
          return;
        }

        const rawText = await fetchArtifactText(activeJsonArtifactPath);
        allResults = parseNucleiResults(rawText).map(hydrateResult);
        renderMetrics(allResults);
        renderTypeFilter(allResults);
        renderSidebarFilters();
        applyFilters();
      }

      bootstrapViewer().catch((error) => {
        document.getElementById("viewerStatus").textContent = error.message || "Unable to load nuclei viewer.";
        document.getElementById("resultsTableBody").innerHTML = `
          <tr>
            <td colspan="7" class="py-5">
              <div class="empty-state">
                <div>
                  <div class="fs-1 mb-3 text-danger"><i class="bi bi-exclamation-triangle-fill"></i></div>
                  <h3 class="h5">Viewer error</h3>
                  <p class="small-muted mb-0">${escapeHtml(error.message || "Unknown error")}</p>
                </div>
              </div>
            </td>
          </tr>
        `;
      });
    </script>
  </body>
</html>""".replace("__BOOTSTRAP_CSS_HREF__", DASHBOARD_ASSETS["bootstrap_css_href"]).replace(
        "__BOOTSTRAP_CSS_INTEGRITY__", bootstrap_css_integrity_attr
    ).replace(
        "__BOOTSTRAP_ICONS_HREF__", DASHBOARD_ASSETS["bootstrap_icons_href"]
    ).replace(
        "__BOOTSTRAP_JS_SRC__", DASHBOARD_ASSETS["bootstrap_js_src"]
    ).replace(
        "__BOOTSTRAP_JS_INTEGRITY__", bootstrap_js_integrity_attr
    )


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

            if parsed.path == "/nuclei-viewer":
                self.send_html(render_nuclei_viewer())
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
    browser_host = args.browser_host or args.host
    browser_url = f"http://{browser_host}:{args.port}/"
    print(f"[dashboard] serving {scan_dir} at {dashboard_url}", flush=True)
    if browser_url != dashboard_url:
        print(f"[dashboard] opening browser at {browser_url}", flush=True)

    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open_new_tab(browser_url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
