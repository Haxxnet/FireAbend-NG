#!/usr/bin/env python3

# shcheck - Security headers check!
# Copyright (C) 2019-2021  santoru
#
# Modified by LRVT

import urllib.request
import urllib.error
import urllib.parse
import http.client
import socket
import sys
import ssl
import os
import json
from optparse import OptionParser
from libnmap.parser import NmapParser


class darkcolours:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class lightcolours:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[95m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


# log - prints unless JSON output is set
def log(string):
    if options.json_output:
        return
    print(string)


# Client headers to send to the server during the request.
client_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:53.0)\
 Gecko/20100101 Firefox/53.0',
    'Accept': 'text/html,application/xhtml+xml,\
 application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US;q=0.8,en;q=0.3',
    'Upgrade-Insecure-Requests': 1
 }


# Security headers that should be enabled
sec_headers = {
    'X-XSS-Protection': 'deprecated',
    'X-Frame-Options': 'warning',
    'X-Content-Type-Options': 'warning',
    'Strict-Transport-Security': 'error',
    'Content-Security-Policy': 'warning',
    'X-Permitted-Cross-Domain-Policies': 'deprecated',
    'Referrer-Policy': 'warning',
    'Expect-CT': 'deprecated',
    'Permissions-Policy': 'warning',
    'Cross-Origin-Embedder-Policy': 'warning',
    'Cross-Origin-Resource-Policy': 'warning',
    'Cross-Origin-Opener-Policy': 'warning'
}

information_headers = {
    'X-Powered-By',
    'Server'
}

cache_headers = {
    'Cache-Control',
    'Pragma',
    'Last-Modified'
    'Expires',
    'ETag'
}

headers = {}
skipped = []


def banner():
    log("")
    log("======================================================")
    log(" > shcheck.py - santoru ..............................")
    log("------------------------------------------------------")
    log(" Simple tool to check security headers on a webserver ")
    log("======================================================")
    log("")


def colorize(string, alert):
    bcolors = darkcolours
    if options.colours == "light":
        bcolors = lightcolours
    elif options.colours == "none":
        return string
    color = {
        'error':    bcolors.FAIL + string + bcolors.ENDC,
        'warning':  bcolors.WARNING + string + bcolors.ENDC,
        'ok':       bcolors.OKGREEN + string + bcolors.ENDC,
        'info':     bcolors.OKBLUE + string + bcolors.ENDC,
        'deprecated': string # No color for deprecated headers or not-an-issue ones
    }
    return color[alert] if alert in color else string


def parse_headers(hdrs):
    global headers
    headers = dict((x.lower(), y) for x, y in hdrs)


def append_port(target, port):
    return target[:-1] + ':' + port + '/' \
        if target[-1:] == '/' \
        else target + ':' + port + '/'


def build_opener(proxy, ssldisabled):
    proxyhnd = urllib.request.ProxyHandler()
    sslhnd = urllib.request.HTTPSHandler()
    if proxy:
        proxyhnd = urllib.request.ProxyHandler({
            'http':  proxy,
            'https': proxy
        })
    if ssldisabled:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sslhnd = urllib.request.HTTPSHandler(context = ctx)

    opener = urllib.request.build_opener(proxyhnd, sslhnd)
    urllib.request.install_opener(opener)


def normalize(target):
    try:
        if (socket.inet_aton(target)):
            target = 'http://' + target
    except (ValueError, socket.error):
        pass
    finally:
        return target


def print_error(target, e):
    sys.stdout = sys.__stdout__
    if isinstance(e, ValueError):
        if not options.json_output and not options.audit:
            print("Unknown url type")

    if isinstance(e, urllib.error.HTTPError):
        if not options.json_output and not options.audit:
            print("[!] URL Returned an HTTP error: {}".format(
                colorize(str(e.code), 'error')))

    if isinstance(e, urllib.error.URLError):
        if "CERTIFICATE_VERIFY_FAILED" in str(e.reason):
            if not options.json_output and not options.audit:
                print("SSL: Certificate validation error.\nIf you want to \
    ignore it run the program with the \"-d\" option.")
        else:
            if not options.json_output and not options.audit:
                print("Target host {} seems to be unreachable ({})".format(target, e.reason))
            else:
                obj = {"target":target, "reason":e.reason}
                skipped.append(obj)
                
def check_target(target, options):
    '''
    Just put a protocol to a valid IP and check if connection works,
    returning HEAD response
    '''
    # Recover used options
    ssldisabled = options.ssldisabled
    useget = options.useget
    proxy = options.proxy
    response = None

    target = normalize(target)

    request = urllib.request.Request(target, headers=client_headers)
    # Set method
    method = 'GET' if useget else 'HEAD'
    request.get_method = lambda: method

    # Build opener for proxy and SSL
    build_opener(proxy, ssldisabled)
    try:
        response = urllib.request.urlopen(request, timeout=10)

    # Handling issues with HTTP/2
    except http.client.UnknownProtocol as e:
        print("Unknown protocol: {}. Are you using a proxy? Try disabling it".format(e))
    except Exception as e:
        print_error(target, e)
        return None

    if response is not None:
        return response
    print("Couldn't read a response from server.")
    return None


def is_https(target):
    '''
    Check if target support HTTPS for Strict-Transport-Security
    '''
    return target.startswith('https://')


def report(target, safe, unsafe):
    log("-------------------------------------------------------")
    log("[!] Headers analyzed for {}".format(colorize(target, 'info')))
    log("[+] There are {} security headers".format(colorize(str(safe), 'ok')))
    log("[-] There are not {} security headers".format(
        colorize(str(unsafe), 'error')))
    log("")


def parse_nmapfile(nfile):
    try:
        report = NmapParser.parse_fromfile(nfile)
        urls = []
    except IOError:
        print("Error: Nmap XML file %s not found. Quitting!" % nfile)
        sys.exit(1)

    for host in report.hosts:
        for service in host.services:
            if (service.state == "open") and ("http" in service.service):
                line = "http{s}://{hostname}:{port}"
                line = line.replace("{hostname}", host.address if not host.hostnames else host.hostnames[0]) # TODO: Fix naive code.
                line = line.replace("{hostnames}", host.address if not host.hostnames else ", ".join(list(set(host.hostnames)))) # TODO: Fix naive code.
                line = line.replace("{ip}", host.address)
                line = line.replace("{s}", "s" if (service.tunnel == "ssl" or "https" in service.service) else "")
                line = line.replace("{port}", str(service.port))
                urls.append(line)
    return list(dict.fromkeys(urls))

def main(options, targets):

    # Getting options
    port = options.port
    cookie = options.cookie
    custom_headers = options.custom_headers
    information = options.information
    cache_control = options.cache_control
    show_deprecated = options.show_deprecated
    hfile = options.hfile
    nfile = options.nfile
    json_output = options.json_output

    if options.audit:
        json_output = True

    # Disabling printing if json output is requested
    if json_output:
        global json_headers
        sys.stdout = open(os.devnull, 'w')

    banner()
    # Set a custom port if provided
    if cookie is not None:
        client_headers.update({'Cookie': cookie})

    # Set custom headers if provided
    if custom_headers is not None:
        for header in custom_headers:
            # Split supplied string of format 'Header: value'
            header_split = header.split(': ')
            # Add to existing headers using header name and header value
            try:
                client_headers.update({header_split[0]: header_split[1]})
            except IndexError:
                s = "[!] Header strings must be of the format 'Header: value'"
                print(s)
                raise SystemExit(1)

    if hfile is not None:
        with open(hfile) as f:
            targets = f.read().splitlines()

    if nfile is not None:
        targets = parse_nmapfile(nfile)
        print(targets)

    json_out = {}
    for target in targets:
        json_headers = {}
        if port is not None:
            target = append_port(target, port)

        safe = 0
        unsafe = 0

        # Check if target is valid
        response = check_target(target, options)
        if not response:
            continue
        rUrl = response.geturl()
        json_results = {}

        log("[*] Analyzing headers of {}".format(colorize(target, 'info')))
        log("[*] Effective URL: {}".format(colorize(rUrl, 'info')))
        parse_headers(response.getheaders())
        json_headers[f"{rUrl}"] = json_results
        json_results["present"] = {}
        json_results["missing"] = []

        for safeh in sec_headers:
            lsafeh = safeh.lower()
            if lsafeh in headers:
                safe += 1
                json_results["present"][safeh] = headers.get(lsafeh)

                # Taking care of special headers that could have bad values

                # X-XSS-Protection Should be enabled
                if safeh == 'X-XSS-Protection' and headers.get(lsafeh) == '0':
                    log("[*] Header {} is present! (Value: {})".format(
                            colorize(safeh, 'ok'),
                            colorize(headers.get(lsafeh), 'warning')))

                # Printing generic message if not specified above
                else:
                    log("[*] Header {} is present! (Value: {})".format(
                            colorize(safeh, 'ok'),
                            headers.get(lsafeh)))
            else:
                unsafe += 1
                json_results["missing"].append(safeh)
                # HSTS works obviously only on HTTPS
                if safeh == 'Strict-Transport-Security' and not is_https(rUrl):
                    unsafe -= 1
                    json_results["missing"].remove(safeh)
                    continue
                # Hide deprecated
                if not show_deprecated and sec_headers.get(safeh) == "deprecated":
                    unsafe -= 1
                    json_results["missing"].remove(safeh)            
                    continue
                log('[!] Missing security header: {}'.format(
                    colorize(safeh, sec_headers.get(safeh))))

        if information:
            json_headers["information_disclosure"] = {}
            i_chk = False
            log("")
            for infoh in information_headers:
                linfoh = infoh.lower()
                if linfoh in headers:
                    json_headers["information_disclosure"][infoh] = headers.get(linfoh)
                    i_chk = True
                    log("[!] Possible information disclosure: \
header {} is present! (Value: {})".format(
                            colorize(infoh, 'warning'),
                            headers.get(linfoh)))
            if not i_chk:
                log("[*] No information disclosure headers detected")

        if cache_control:
            json_headers["caching"] = {}
            c_chk = False
            log("")
            for cacheh in cache_headers:
                lcacheh = cacheh.lower()
                if lcacheh in headers:
                    json_headers["caching"][cacheh] = headers.get(lcacheh)
                    c_chk = True
                    log("[!] Cache control header {} is present! \
Value: {})".format(
                            colorize(cacheh, 'info'),
                            headers.get(lcacheh)))
            if not c_chk:
                log("[*] No caching headers detected")

        report(rUrl, safe, unsafe)
        json_out.update(json_headers)

    if json_output:
        sys.stdout = sys.__stdout__
        data = json_out

        if (not options.audit):
            print(json.dumps(data))
        else:
            print(json.dumps(data))
            # Initialize Arrays
            MISSING_CONTENT_TYPES_ARRAY=[]
            MISSING_HSTS_ARRAY=[]
            MISSING_XFRAME_ARRAY=[]
            MISSING_REFERER_ARRAY=[]
            MISSING_PERMISSIONS_ARRAY=[]
            MISSING_CSP_ARRAY=[]

            print()
            print("[SUCCESS] - Analyzed the following targets:")

            for url_object in data:
                url=url_object
                print(url)
                url_missing_arr=data[url]["missing"]

                if "Strict-Transport-Security" in url_missing_arr:
                    MISSING_HSTS_ARRAY.append(url)
                if "X-Frame-Options" in url_missing_arr:
                    MISSING_XFRAME_ARRAY.append(url)
                if "X-Content-Type-Options" in url_missing_arr:
                    MISSING_CONTENT_TYPES_ARRAY.append(url)
                if "Referrer-Policy" in url_missing_arr:
                    MISSING_REFERER_ARRAY.append(url)
                if "Permissions-Policy" in url_missing_arr:
                    MISSING_PERMISSIONS_ARRAY.append(url)
                if "Content-Security-Policy" in url_missing_arr:
                    MISSING_CSP_ARRAY.append(url)

            print("")
            print("[FAIL] - Following targets failed:")
            for failed_url in skipped:
                print(failed_url)
            print()
            print("------------------EVALUATION---------------------------")
            ### Sort the arrays
            MISSING_CONTENT_TYPES_ARRAY.sort()
            MISSING_HSTS_ARRAY.sort()
            MISSING_XFRAME_ARRAY.sort()
            MISSING_REFERER_ARRAY.sort()
            MISSING_PERMISSIONS_ARRAY.sort()
            MISSING_CSP_ARRAY.sort()


            print()
            print("[Missing HTTP Strict Transport Security (HSTS)]:")
            print(*MISSING_HSTS_ARRAY, sep ="\n")
            print("\n\n")
            print("[Missing X-Frame-Options (XFO)]:")
            print(*MISSING_XFRAME_ARRAY, sep ="\n")
            print("\n\n")
            print("[Missing X-Content-Type-Options (XCTO)]:")
            print(*MISSING_CONTENT_TYPES_ARRAY, sep ="\n")
            print("\n\n")
            print("[Missing Content-Security-Policy (CSP)]:")
            print(*MISSING_CSP_ARRAY, sep ="\n")
            print("\n\n")
            print("[Missing Permissions-Policy]:")
            print(*MISSING_PERMISSIONS_ARRAY, sep ="\n")
            print("\n\n")
            print("[Missing Referer-Policy]:")
            print(*MISSING_REFERER_ARRAY, sep ="\n")
            print("\n\n")

if __name__ == "__main__":

    parser = OptionParser("Usage: %prog [options] <target>", prog=sys.argv[0])

    parser.add_option("-p", "--port", dest="port",
                      help="Set a custom port to connect to",
                      metavar="PORT")
    parser.add_option("-c", "--cookie", dest="cookie",
                      help="Set cookies for the request",
                      metavar="COOKIE_STRING")
    parser.add_option("-a", "--add-header", dest="custom_headers",
                      help="Add headers for the request e.g. 'Header: value'",
                      metavar="HEADER_STRING",
                      action="append")
    parser.add_option('-d', "--disable-ssl-check", dest="ssldisabled",
                      default=False,
                      help="Disable SSL/TLS certificate validation",
                      action="store_true")
    parser.add_option('-g', "--use-get-method", dest="useget",
                      default=False, help="Use GET method instead HEAD method",
                      action="store_true")
    parser.add_option("-j", "--json-output", dest="json_output",
                      default=False, help="Print the output in JSON format",
                      action="store_true")
    parser.add_option("-i", "--information", dest="information", default=False,
                      help="Display information headers",
                      action="store_true")
    parser.add_option("-x", "--caching", dest="cache_control", default=False,
                      help="Display caching headers",
                      action="store_true")
    parser.add_option("-k", "--deprecated", dest="show_deprecated", default=False,
                      help="Display deprecated headers",
                      action="store_true")
    parser.add_option("--proxy", dest="proxy",
                      help="Set a proxy (Ex: http://127.0.0.1:8080)",
                      metavar="PROXY_URL")
    parser.add_option("--hfile", dest="hfile",
                      help="Load a list of hosts from a flat file",
                      metavar="PATH_TO_FILE")
    parser.add_option("--nfile", dest="nfile",
                      help="Use http/https urls extracted from an nmap xml file",
                      metavar="PATH_TO_FILE")
    parser.add_option("--audit", dest="audit",
                      default=False, help="Print target urls with missing headers group by header name",
                      action="store_true")
    parser.add_option("--colours", dest="colours",
                      help="Set up a colour profile [dark/light/none]",
                      default="dark")
    parser.add_option("--colors", dest="colours",
                      help="Alias for colours for US English")
    (options, args) = parser.parse_args()

    if len(args) < 1 and options.hfile is None and options.nfile is None:
        parser.print_help()
        sys.exit(1)
    main(options, args)
