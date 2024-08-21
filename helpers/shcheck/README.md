# shcheck - Security Header Check

Forked from original repo [shcheck](https://github.com/santoru/shcheck) and added following features:
- added new `--audit` cli flag to display urls with missing headers grouped by each security header
- added new `--nfile` cli flag to support passing an nmap xml file. The nmap xml will be parsed by [nmap-query-xml](https://github.com/honze-net/nmap-query-xml) and (nearly) all http(s) service urls are extracted for analyzation.
- adjusted the Dockerfile and configured automatic builds by GitHub Actions. You can use the Docker image `l4rm4nd/shcheck:latest` from DockerHub if you want

<p align="center">
    <img src="screenshot.png" alt="Output on Facebook" />
</p>

## Usage
```
Usage: ./shcheck.py [options] <target>

Options:
  -h, --help            show this help message and exit
  -p PORT, --port=PORT  Set a custom port to connect to
  -c COOKIE_STRING, --cookie=COOKIE_STRING
                        Set cookies for the request
  -a HEADER_STRING, --add-header=HEADER_STRING
                        Add headers for the request e.g. 'Header: value'
  -d, --disable-ssl-check
                        Disable SSL/TLS certificate validation
  -g, --use-get-method  Use GET method instead HEAD method
  -j, --json-output     Print the output in JSON format
  -i, --information     Display information headers
  -x, --caching         Display caching headers
  -k, --deprecated      Display deprecated headers
  --proxy=PROXY_URL     Set a proxy (Ex: http://127.0.0.1:8080)
  --hfile=PATH_TO_FILE  Load a list of hosts from a flat file
  --nfile=PATH_TO_FILE  Use http/https urls extracted from an nmap xml file
  --audit               Print target urls with missing headers group by header name
  --colours=COLOURS     Set up a colour profile [dark/light/none]
  --colors=COLOURS      Alias for colours for US English
```

## Docker Run Examples
````
# scan a single url
docker run --rm l4rm4nd/shcheck:latest -d -g -k <URL>

# scan multiple urls by using a urls.txt file (colored output)
docker run -v ${PWD}:/app/urls --rm l4rm4nd/shcheck:latest -d -g -k --hfile /app/urls/urls.txt

# scan multiple urls by using a urls.txt file (show urls with missing headers grouped by header)
docker run -v ${PWD}:/app/urls --rm l4rm4nd/shcheck:latest -d -g -k --hfile /app/urls/urls.txt --audit

# scan multiple urls by using an nmap xml file (show urls with missing headers grouped by header)
docker run -v ${PWD}:/app/urls --rm l4rm4nd/shcheck:latest -d -g -k --nfile /app/urls/nmap-results.xml --audit
````
