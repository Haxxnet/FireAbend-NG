<div align="center" width="100%">
    <h1>🔥 FireAbend-NG 🔥</h1>
    <p>Python3 script that automates the tedious tasks of a penetration tester</p><p>
    <a target="_blank" href="https://github.com/l4rm4nd"><img src="https://img.shields.io/badge/maintainer-LRVT-orange" /></a><br>
    <!--<a target="_blank" href="#"><img src="https://ForTheBadge.com/images/badges/makes-people-smile.svg" /></a><br>-->
    <a href="https://www.buymeacoffee.com/LRVT" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
</div>

## 💎 Features

FireAbend automates various pentesting tasks such as:

- nmap port scanning (tcp + udp)
- ssl/tls auditing of starttls and tls (https) services
- http response header analysis of http(s) services
- lightweight OWASP ZAP baseline scanning of discovered http(s) services
- SSH auditing via ssh-audit
- IKE/VPN auditing via IKESS
- nuclei vulnerability scanning
- converting various output formats to customer friendly result files (html, xlsx, csv, etc.)
- maintaining a strict methodology with less risk of human failure

With support for:

- dependency-aware job scheduling with resource-aware queuing
- resumable scans via `--resume` using persisted job state
- local live dashboard for current scan jobs, logs, findings, and artifacts
- dashboard-only mode for browsing existing scan directories

## 🎓 Usage

````bash
usage: fireabend.py [-h] [--target <host> | --targets <file>]
                    [--nmap-custom-flags-stage1 <nmap-cli-flags>]
                    [--nmap-custom-flags-stage2 <nmap-cli-flags>]
                    [--nuclei-severity <info,low,medium,high,critical,unknown>]
                    [--dns-servers <server1>[,<server2>]]
                    [--additional-http-urls <file>] [--min-rate <rate>]
                    [--disable-fireabend-update-check]
                    [--disable-nuclei-template-update-check]
                    [--enable-nuclei-engine-update-check] [--dashboard]
                    [--no-dashboard] [--resume <scan-dir>] [--disable-udp]
                    [--disable-zap] [--disable-zap-image-check-pull]
                    [--zap-spider-minutes <mins>]
                    [--zap-passive-wait-seconds <secs>]
                    [--zap-max-minutes <mins>] [--check]

options:
  -h, --help            show this help message and exit
  --target <host>       Single hostname or ip address
  --targets, -t <file>  Newline separated file with hostnames (recommended) or
                        ip addresses
  --nmap-custom-flags-stage1, -n1 <nmap-cli-flags>
                        Custom nmap cli flags for stage 1
  --nmap-custom-flags-stage2, -n2 <nmap-cli-flags>
                        Custom nmap cli flags for stage 2
  --nuclei-severity, -ns <info,low,medium,high,critical,unknown>
                        Nuclei severity filters, comma separated; default is
                        medium,high,critical
  --dns-servers, -dns <server1>[,<server2>]
                        Custom dns servers for nmap, comma separated
  --additional-http-urls, --additional-urls, -au <file>
                        Newline separated file with additional http(s) urls to
                        append to stage2_http_urls.txt
  --min-rate, -mr <rate>
                        The min rate for nmap packets sent; default is 5000
  --disable-fireabend-update-check, -dfuc
                        Disable update checks for fireabend
  --disable-nuclei-template-update-check, -dntuc
                        Disable updating nuclei templates
  --enable-nuclei-engine-update-check, -eneuc
                        Enable updating nuclei scan engine
  --dashboard           Start a local dashboard server for the current scan
                        and open it in the browser (default)
  --no-dashboard        Do not start the local dashboard server automatically
  --resume, --resume-scan-dir <scan-dir>
                        Resume an existing FireAbend scan directory and rerun
                        unfinished jobs
  --disable-udp, -dudp  Disable nmap udp scanning
  --disable-zap, -dzap  Disable OWASP ZAP baseline scanning of discovered
                        http(s) urls
  --disable-zap-image-check-pull
                        Do not inspect or pull the OWASP ZAP Docker image
                        before scanning; useful for offline runs
  --zap-spider-minutes, -zsm <mins>
                        OWASP ZAP spider duration per URL in minutes; default
                        is 1
  --zap-passive-wait-seconds, -zpws <secs>
                        OWASP ZAP passive scan wait time per URL in seconds;
                        default is 5
  --zap-max-minutes, -zmm <mins>
                        Maximum minutes to wait for each OWASP ZAP scan;
                        default is 3
  --check               Sanity check, print binary paths and defaults

````

## 🐍 Native Python

### Installation

````bash
# clone this repo
git clone https://github.com/Haxxnet/FireAbend-NG && cd FireAbend-NG

# install helper tools - Kali Linux recommended
sudo apt install xsltproc nmap eyewitness docker.io

# create python virtual environment
virtualenv venv
source venv/bin/activate

# install python dependencies
pip3 install -r requirements.txt
````

### Running

````
python3 dist/<your-python-version>/fireabend.py --targets targets.txt
````

You will find your scan results in the `scans/` directory.

---

Since `v2`, FireAbend executes work as dependency-aware jobs instead of a single linear shell flow. Jobs are queued with lightweight resource limits, persist their state and logs under `00_runtime/`, and can be resumed with `--resume` after interruption or failure.

For the FireAbend password gate, the script now checks in this order:

- `FIREABEND_PASSWORD` from the current process environment
- `FIREABEND_PASSWORD` from a local `.env`
- interactive password prompt

If pending nmap jobs require elevated privileges and you are not already running as root, FireAbend prompts once for sudo before the scheduler starts and keeps that sudo timestamp refreshed for the nmap stages.

Example `.env`:

```bash
FIREABEND_PASSWORD=your-password-here
```

---

FireAbend writes orchestration metadata to `00_runtime/`, including:

- per-job logs
- per-job status JSON
- job manifest JSON
- overall run summary JSON

The CLI also prints a regular scheduler heartbeat showing running, pending, completed, failed, and skipped jobs so long-running scans are easier to follow.

If `--dashboard` is enabled (default), FireAbend starts a detached local web server for the active scan, opens it in your browser, and serves:

- live job state from `00_runtime/jobs/`
- per-job logs from `00_runtime/logs/`
- findings and reports from the scan directory

If you run `python3 dist/<your-python-version>/fireabend.py --dashboard` without `--target` or `--targets`, FireAbend enters dashboard-only mode and prompts you to choose an existing scan directory from `scans/`.

You may use `--resume <path-to-scan-dir>` to resume a failed or aborted scan. Jobs in the status `failed` or `pending` are then re-run and produce new (override mode) output files and logs. Already `completed` jobs are ignored and stay untouched.

### Updating

You can upgrade FireAbend by simply issuing a git pull. This will fetch the latest stable release.

````
# remove local version of nuclei templates
rm -rf helpers/nuclei/nuclei-templates

# pull the latest repo updates
git pull
````

> [!WARNING]
> Nuclei templates are automatically updated each time fireabend.py runs. Requires an internet connection.
>
> However, this repo also provides a somewhat deprecated version of nuclei templates in case you are on a box with no internet access. In such a case, you can use the CLI flag `--disable-nuclei-update-checks` to prevent freezing and timeout warnings.

## 🔎 Methodology

Since `v2`, the methodology still follows three phases, but each phase is executed as dependency-aware jobs with queueing, persisted state, and resume support.

1. Discover
   - Resolve a single `--target` or a `--targets` file into a runtime target list, run TCP and optional UDP stage-1 discovery, and normalize the first inventory artifacts as soon as upstream scan files exist.
3. Enumerate
   - Run TCP stage-2 version detection and NSE work, extract and probe discovered HTTP(S) URLs, append any operator-supplied additional URLs, and build service inventories for the downstream web, SSH, VPN, and reporting jobs.
4. Analyze And Report
   - Fan out the web workflow across header checks, EyeWitness, nuclei, OWASP ZAP, and URL-based testssl; fan out the service workflow across SSH and IKE/VPN auditing; then convert and publish artifacts while recording per-job logs and statuses so interrupted runs can be resumed and failed dependencies can skip downstream jobs cleanly.
