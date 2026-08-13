#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_DOCKER_IMAGE = "ghcr.io/zaproxy/zaproxy:stable"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args():
    parser = argparse.ArgumentParser(description="Run OWASP ZAP baseline scans for a list of URLs.")
    parser.add_argument("--url-file", required=True, help="Text file containing one http(s) URL per line.")
    parser.add_argument("--output-dir", required=True, help="Directory used for logs, raw reports, and summaries.")
    parser.add_argument("--docker-image", default=DEFAULT_DOCKER_IMAGE, help="Docker image that provides zap-baseline.py.")
    parser.add_argument("--spider-minutes", type=int, default=1, help="Traditional spider duration per URL.")
    parser.add_argument("--passive-wait-seconds", type=int, default=5, help="How long ZAP should wait for passive scan completion.")
    parser.add_argument("--max-minutes", type=int, default=3, help="Maximum total runtime per URL.")
    return parser.parse_args()


def read_urls(url_file):
    urls = []
    seen = set()

    with open(url_file, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            candidate = raw_line.strip()
            if not candidate or candidate.startswith("#"):
                continue

            parsed = urlsplit(candidate)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                print(f"[warn] Skipping invalid URL: {candidate}")
                continue

            if candidate not in seen:
                seen.add(candidate)
                urls.append(candidate)

    return urls


def safe_slug(url, used_slugs):
    parsed = urlsplit(url)
    hostname = parsed.hostname or "unknown"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = re.sub(r"[^A-Za-z0-9._-]+", "_", parsed.path.strip("/")) or "root"
    query_hash = hashlib.sha1((parsed.query or "").encode("utf-8")).hexdigest()[:8] if parsed.query else "noquery"
    base = f"{parsed.scheme}_{hostname}_{port}_{path}_{query_hash}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:120]

    if slug not in used_slugs:
        used_slugs.add(slug)
        return slug

    index = 2
    while True:
        candidate = f"{slug}_{index}"
        if candidate not in used_slugs:
            used_slugs.add(candidate)
            return candidate
        index += 1


def docker_command(args, url, output_dir, json_rel, html_rel):
    mount_target = f"{output_dir.resolve()}:/zap/wrk/:rw"
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        mount_target,
        args.docker_image,
        "zap-baseline.py",
        "-t",
        url,
        "-J",
        f"/zap/wrk/{json_rel}",
        "-r",
        f"/zap/wrk/{html_rel}",
        "-m",
        str(args.spider_minutes),
        "-D",
        str(args.passive_wait_seconds),
        "-T",
        str(args.max_minutes),
        "-I",
        "--autooff",
    ]


def stream_command_to_stdout_and_log(command, log_handle, line_prefix=""):
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        message = "docker executable not found in PATH\n"
        log_handle.write(message)
        log_handle.flush()
        print(f"{line_prefix}{message.rstrip()}", flush=True)
        return 127

    if process.stdout is not None:
        for line in process.stdout:
            log_handle.write(line)
            log_handle.flush()
            print(f"{line_prefix}{line.rstrip()}", flush=True)

    return process.wait()


def load_json_report(report_path):
    if not report_path.is_file():
        return None

    try:
        with open(report_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return None


def collect_alert_items(node, items):
    if isinstance(node, dict):
        lowered_keys = {str(key).lower() for key in node.keys()}
        if ("pluginid" in lowered_keys or "alertref" in lowered_keys) and (
            "alert" in lowered_keys or "name" in lowered_keys
        ):
            items.append(node)

        for value in node.values():
            collect_alert_items(value, items)
        return

    if isinstance(node, list):
        for value in node:
            collect_alert_items(value, items)


def normalize_risk(alert):
    risk_desc = str(alert.get("riskdesc") or alert.get("riskDesc") or alert.get("risk") or "").lower()
    if "high" in risk_desc:
        return "High"
    if "medium" in risk_desc:
        return "Medium"
    if "low" in risk_desc:
        return "Low"
    if "info" in risk_desc:
        return "Informational"

    risk_code = str(alert.get("riskcode") or alert.get("riskCode") or "")
    return {
        "3": "High",
        "2": "Medium",
        "1": "Low",
        "0": "Informational",
    }.get(risk_code, "Unknown")


def count_instances(alert):
    instances = alert.get("instances")
    if isinstance(instances, list):
        return len(instances)

    if isinstance(instances, dict):
        nested_instances = instances.get("instance")
        if isinstance(nested_instances, list):
            return len(nested_instances)
        if nested_instances:
            return 1

    instance = alert.get("instance")
    if isinstance(instance, list):
        return len(instance)
    if instance:
        return 1

    return 0


def summarize_report(report_data):
    if not report_data:
        return {
            "alerts": [],
            "counts": {"High": 0, "Medium": 0, "Low": 0, "Informational": 0, "Unknown": 0},
        }

    raw_alerts = []
    collect_alert_items(report_data, raw_alerts)

    normalized_alerts = []
    counts = Counter()

    for alert in raw_alerts:
        normalized = {
            "plugin_id": str(alert.get("pluginid") or alert.get("pluginId") or alert.get("alertRef") or alert.get("alertref") or ""),
            "name": alert.get("alert") or alert.get("name") or "Unknown alert",
            "risk": normalize_risk(alert),
            "confidence": alert.get("confidence") or alert.get("confidencedesc") or alert.get("confidenceDesc"),
            "instances": count_instances(alert),
            "cwe_id": str(alert.get("cweid") or alert.get("cweId") or ""),
            "wasc_id": str(alert.get("wascid") or alert.get("wascId") or ""),
        }
        normalized_alerts.append(normalized)
        counts[normalized["risk"]] += 1

    for severity in ["High", "Medium", "Low", "Informational", "Unknown"]:
        counts.setdefault(severity, 0)

    return {
        "alerts": normalized_alerts,
        "counts": dict(counts),
    }


def write_summary_text(summary_path, aggregate):
    with open(summary_path, "w", encoding="utf-8") as handle:
        handle.write("OWASP ZAP BASELINE SUMMARY\n")
        handle.write("=" * 80 + "\n")
        handle.write(f"Generated: {aggregate['generated_at']}\n")
        handle.write(f"URLs queued: {aggregate['totals']['queued']}\n")
        handle.write(f"URLs scanned: {aggregate['totals']['scanned']}\n")
        handle.write(f"URLs failed: {aggregate['totals']['failed']}\n")
        handle.write("\n")

        total_alerts = aggregate["totals"]["alerts"]
        handle.write(
            "Alerts: "
            f"High={total_alerts['High']} "
            f"Medium={total_alerts['Medium']} "
            f"Low={total_alerts['Low']} "
            f"Informational={total_alerts['Informational']} "
            f"Unknown={total_alerts['Unknown']}\n"
        )
        handle.write("\n")

        for result in aggregate["results"]:
            handle.write("-" * 80 + "\n")
            handle.write(f"URL: {result['url']}\n")
            handle.write(f"Status: {result['status']}\n")
            handle.write(f"Duration: {result['duration_seconds']}s\n")
            handle.write(
                "Alert counts: "
                f"High={result['alerts_count']['High']} "
                f"Medium={result['alerts_count']['Medium']} "
                f"Low={result['alerts_count']['Low']} "
                f"Informational={result['alerts_count']['Informational']} "
                f"Unknown={result['alerts_count']['Unknown']}\n"
            )

            if result.get("error"):
                handle.write(f"Error: {result['error']}\n")

            if result["alerts"]:
                handle.write("Findings:\n")
                for alert in result["alerts"]:
                    handle.write(
                        f"  - [{alert['risk']}] {alert['name']} "
                        f"(plugin {alert['plugin_id']}, instances={alert['instances']})\n"
                    )

            handle.write(f"JSON: {result['json_report']}\n")
            handle.write(f"HTML: {result['html_report']}\n")
            handle.write(f"Log: {result['log_file']}\n")
            handle.write("\n")


def main():
    args = parse_args()

    if args.spider_minutes < 1:
        print("[error] --spider-minutes must be >= 1", file=sys.stderr)
        return 1

    if args.passive_wait_seconds < 0:
        print("[error] --passive-wait-seconds must be >= 0", file=sys.stderr)
        return 1

    if args.max_minutes < 1:
        print("[error] --max-minutes must be >= 1", file=sys.stderr)
        return 1

    url_file = Path(args.url_file)
    output_dir = Path(args.output_dir)
    raw_json_dir = output_dir / "raw_json"
    raw_html_dir = output_dir / "raw_html"
    logs_dir = output_dir / "logs"

    raw_json_dir.mkdir(parents=True, exist_ok=True)
    raw_html_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    urls = read_urls(url_file)

    aggregate = {
        "generated_at": now_iso(),
        "source_url_file": str(url_file),
        "docker_image": args.docker_image,
        "scan_profile": {
            "spider_minutes": args.spider_minutes,
            "passive_wait_seconds": args.passive_wait_seconds,
            "max_minutes": args.max_minutes,
            "mode": "docker_baseline",
        },
        "totals": {
            "queued": len(urls),
            "scanned": 0,
            "failed": 0,
            "alerts": {"High": 0, "Medium": 0, "Low": 0, "Informational": 0, "Unknown": 0},
        },
        "results": [],
    }

    if not urls:
        print("[info] No valid http(s) URLs found for OWASP ZAP scanning.")
        summary_json_path = output_dir / "zap_summary.json"
        summary_txt_path = output_dir / "zap_summary.txt"
        with open(summary_json_path, "w", encoding="utf-8") as handle:
            json.dump(aggregate, handle, indent=2)
        write_summary_text(summary_txt_path, aggregate)
        return 0

    used_slugs = set()

    for index, url in enumerate(urls, start=1):
        slug = safe_slug(url, used_slugs)
        json_rel = f"raw_json/{slug}.json"
        html_rel = f"raw_html/{slug}.html"
        log_rel = f"logs/{slug}.log"

        report_json_path = output_dir / json_rel
        report_html_path = output_dir / html_rel
        log_path = output_dir / log_rel

        started_at = now_iso()
        print(f"[task] ({index}/{len(urls)}) Starting ZAP baseline scan for {url}")

        command = docker_command(args, url, output_dir, json_rel, html_rel)
        with open(log_path, "w", encoding="utf-8") as log_handle:
            log_handle.write(f"[task] Starting ZAP baseline scan for {url}\n")
            log_handle.flush()
            print(f"[info] Streaming detailed ZAP output for {url} from {log_rel}", flush=True)
            returncode = stream_command_to_stdout_and_log(command, log_handle, line_prefix=f"[zap][{slug}] ")

        finished_at = now_iso()
        duration_seconds = int(
            (
                datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ).total_seconds()
        )

        report_data = load_json_report(report_json_path)
        report_summary = summarize_report(report_data)

        status = "completed" if returncode == 0 else "failed"
        result = {
            "url": url,
            "slug": slug,
            "status": status,
            "exit_code": returncode,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "json_report": json_rel,
            "html_report": html_rel,
            "log_file": log_rel,
            "alerts_count": report_summary["counts"],
            "alerts": report_summary["alerts"],
        }

        if returncode != 0:
            result["error"] = "ZAP baseline returned a non-zero exit code. Inspect the per-target log for details."
            aggregate["totals"]["failed"] += 1
            print(f"[warn] ZAP baseline scan failed for {url}. Inspect {log_path}")
        else:
            aggregate["totals"]["scanned"] += 1
            print(f"[task] Finished ZAP baseline scan for {url}")

        for severity, count in report_summary["counts"].items():
            aggregate["totals"]["alerts"][severity] += count

        aggregate["results"].append(result)

    summary_json_path = output_dir / "zap_summary.json"
    summary_txt_path = output_dir / "zap_summary.txt"

    with open(summary_json_path, "w", encoding="utf-8") as handle:
        json.dump(aggregate, handle, indent=2)

    write_summary_text(summary_txt_path, aggregate)

    print(f"[info] Wrote aggregated ZAP summary to {summary_json_path}")
    print(f"[info] Wrote human-readable ZAP summary to {summary_txt_path}")

    return 1 if aggregate["totals"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
