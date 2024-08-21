<div align="center" width="100%">
    <h1>🔥 FireAbend 🔥</h1>
    <p>Python3 script that automates the tedious tasks of a penetration tester</p><p>
    <a target="_blank" href="https://github.com/l4rm4nd"><img src="https://img.shields.io/badge/maintainer-LRVT-orange" /></a><br>
    <!--<a target="_blank" href="#"><img src="https://ForTheBadge.com/images/badges/makes-people-smile.svg" /></a><br>-->
    <a href="https://www.buymeacoffee.com/LRVT" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>
</div>

## 💎 Features

FireAbend automates various pentesting tasks such as:

- nmap port scanning (tcp + udp)
- ssl/tls auditing of starttls and https services
- http response header analysis of http(s) services
- SSH auditing via ssh-audit
- nuclei vulnerability scanning
- converting various output formats to customer friendly result files (html, xlsx, csv, etc.)
- maintaining a strict methodology with no risk of human failure

## 🎓 Usage

````bash
usage: fireabend.py [-h] --targets <file> [--nmap-custom-flags-stage1 <nmap-cli-flags>]
                    [--nmap-custom-flags-stage2 <nmap-cli-flags>]
                    [--nuclei-severity <info,low,medium,high,critical,unknown>]
                    [--min-rate <rate>]
                    [--dns-servers <server1>[,<server2>]] [--check]

options:
  -h, --help            show this help message and exit
  --targets <file>, -t <file>
                        Newline separated file with hostnames (recommended) or ip addresses
  --nmap-custom-flags-stage1 <nmap-cli-flags>, -n1 <nmap-cli-flags>
                        Custom nmap cli flags for stage 1
  --nmap-custom-flags-stage2 <nmap-cli-flags>, -n2 <nmap-cli-flags>
                        Custom nmap cli flags for stage 2
  --nuclei-severity <info,low,medium,high,critical,unknown>, -ns <info,low,medium,high,critical,unknown>
                        Nuclei severity filters, comma separated; default is low,medium,high,critical
  --dns-servers <server1>[,<server2>], -dns <server1>[,<server2>]
                        Custom dns servers for nmap, comma separated
  --min-rate <rate>, -mr <rate>
                        The min rate for nmap packets sent; default is 5000
  --check               Sanity check, print binary paths and defaults

````
## 🐍 Example 1 - Native Python

### Installation

````bash
# clone this repo
git clone https://github.com/Haxxnet/FireAbend-NG && cd FireAbend-NG

# install helper tools - Kali Linux recommended
sudo apt install xsltproc nmap eyewitness

# create python virtual environment
virtualenv venv
source venv/bin/activate

# install python dependencies
pip3 install -r requirements.txt
````

### Running

````
python3 dist/<your-python-version>/fireabend.py --targets targets.txt --nuclei-severity high,critical --dns-servers 1.1.1.1
````

You will find your scan results in the /scans directory.

## 🔎 Methodology

1. Run basic nmap scan to enumerate top-250 open udp ports. No version detection, no nse script scans.
2. Convert udp nmap xml output file into convenient html report.
3. Run basic nmap scan to enumerate open tcp ports. No version detection, no nse script scans.
4. Extract open ports and probe for http/s urls from basic nmap portscan results.
5. Convert tcp nmap xml output file into convenient html report.
6. Pass enumerated tcp ports into advanced nmap scan. Version detection and nse scripts enabled.
7. Extract open ports and probe for http/s urls from detailed nmap portscan results.
8. Convert tcp nmap xml output file into convenient html report.
9. Run shcheck to enumerate http response headers by passing in the extracted http/s urls from nmap file.
10. Convert shcheck json output files into convenient xlsx report.
11. Run eyewitness against the extracted http/s urls from detailed nmap portscan results. Save html report as output.
12. Run testssl.sh for auditing ssl/tls configuration by passing in the detailed nmap results file.
13. Run testssl.sh for auditing ssl/tls configuration by passing in the extracted https urls from nmap file.
14. Convert all testssl.sh json output files into convenient xlsx report. Autofit columns and conditionally format cells.
15. Update and run nuclei vulnerability scanner against extracted http/s urls. Save identified vulnerabilites into txt outfile.
16. Run ssh-audit against identified SSH network services. Convert JSON results to XLSX.
