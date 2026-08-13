## OWASP ZAP Helper

FireAbend runs OWASP ZAP via the official Docker image:

- Image: `ghcr.io/zaproxy/zaproxy:stable`
- Entrypoint: `zap-baseline.py`
- Wrapper: `helpers/zap/run_zap_baseline.py`

This keeps the repository lightweight while still giving FireAbend a reproducible ZAP runtime.

### What gets scanned

`fireabend.py` passes `scans/<timestamp>_FIREABEND/01_nmap/stage2_http_urls.txt` into the helper.

Each discovered `http://` or `https://` URL is scanned individually with a lightweight ZAP baseline profile:

- passive-focused scan
- 1 minute traditional spider per URL by default
- short passive scan wait
- JSON and HTML report output per target

### Output

ZAP results are written to:

- `scans/<timestamp>_FIREABEND/07_findings/zap/zap_summary.json`
- `scans/<timestamp>_FIREABEND/07_findings/zap/zap_summary.txt`
- `scans/<timestamp>_FIREABEND/07_findings/zap/raw_json/`
- `scans/<timestamp>_FIREABEND/07_findings/zap/raw_html/`
- `scans/<timestamp>_FIREABEND/07_findings/zap/logs/`
