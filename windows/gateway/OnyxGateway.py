"""ONYX CORE v0.5.0 read-only local gateway. Python 3 standard library."""
import argparse
import http.server
import ipaddress
import json
import re
import sys
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

LOCAL_HOST = '127.0.0.1'
ALLOWED_API = {'/api/v1/health', '/api/v1/latest', '/api/v1/history'}
LIMIT_MAX = 500

class Gateway(http.server.BaseHTTPRequestHandler):
    server_version = 'OnyxCoreGateway/0.5.0'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Never log requests, credentials, or untrusted URLs.
        pass

    def send_bytes(self, code, data, content_type='application/json; charset=utf-8', html=False):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Pragma', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" if html else "default-src 'none'; frame-ancestors 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def error(self, code, reason):
        self.send_bytes(code, json.dumps({'error': reason}, separators=(',', ':')).encode('utf-8'))

    def do_GET(self):
        expected = f'{LOCAL_HOST}:{self.server.server_port}'
        if self.headers.get('Host') != expected:
            return self.error(403, 'invalid_host')
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{expected}':
            return self.error(403, 'invalid_origin')
        fetch_site = self.headers.get('Sec-Fetch-Site', '')
        if fetch_site and fetch_site not in ('same-origin', 'none'):
            return self.error(403, 'cross_site_forbidden')
        if self.headers.get('Content-Length') or self.headers.get('Transfer-Encoding'):
            return self.error(400, 'request_body_not_allowed')
        parsed = urlsplit(self.path)
        if parsed.fragment:
            return self.error(400, 'invalid_path')
        if parsed.path in ('/', '/dashboard', '/dashboard/') and not parsed.query:
            return self.send_bytes(200, self.server.dashboard, 'text/html; charset=utf-8', html=True)
        if parsed.path in ('/overlay', '/overlay/') and not parsed.query:
            return self.send_bytes(200, self.server.overlay, 'text/html; charset=utf-8', html=True)
        if parsed.path not in ALLOWED_API:
            return self.error(404, 'not_found')
        if parsed.path != '/api/v1/history' and parsed.query:
            return self.error(400, 'invalid_query')
        if parsed.path == '/api/v1/history':
            q = parse_qs(parsed.query, keep_blank_values=True)
            if set(q) - {'limit'} or len(q.get('limit', ['120'])) != 1:
                return self.error(400, 'invalid_query')
            limit = q.get('limit', ['120'])[0]
            if not re.fullmatch(r'[0-9]{1,3}', limit) or not 1 <= int(limit) <= LIMIT_MAX:
                return self.error(400, 'invalid_query')
            target_path = '/api/v1/history?limit=' + str(int(limit))
        else:
            target_path = parsed.path
        url = self.server.upstream + target_path
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.server.token, 'Accept': 'application/json'}, method='GET')
        try:
            with self.server.opener.open(request, timeout=5) as resp:
                data = resp.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    return self.error(502, 'upstream_too_large')
                return self.send_bytes(200, data)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return self.error(502, 'upstream_authentication_failed')
            return self.error(502, 'upstream_failure')
        except (urllib.error.URLError, TimeoutError, OSError):
            return self.error(502, 'upstream_unavailable')

    def do_POST(self):
        return self.error(405, 'read_only')
    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_HEAD = do_POST


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dashboard', required=True)
    p.add_argument('--overlay', help='Optional local OBS overlay HTML file')
    p.add_argument('--receiver', default='svr-onyxcore.local')
    p.add_argument('--port', type=int, default=18766)
    p.add_argument('--load-dpapi', action='store_true', help='Read protected token via local Windows PowerShell helper')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}', args.receiver):
        p.error('receiver must be a hostname or IPv4 address')
    if not 1024 <= args.port <= 65535:
        p.error('invalid port')
    # Never put the bearer token into arguments, environment, logs, or browser responses.
    if args.load_dpapi:
        if sys.platform != 'win32':
            p.error('--load-dpapi is available only on Windows')
        helper = Path(__file__).with_name('Get-OnyxGatewayToken.ps1')
        if not helper.is_file():
            p.error('DPAPI token helper missing')
        try:
            secret_result = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(helper)],
                capture_output=True, timeout=15, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            p.error('DPAPI helper unavailable')
        if secret_result.returncode != 0:
            p.error('DPAPI credential could not be loaded')
        try:
            token = secret_result.stdout.decode('utf-8-sig').rstrip('\r\n')
        except UnicodeError:
            p.error('DPAPI credential output invalid')
    else:
        # Legacy launcher uses an anonymous stdin pipe.
        token = sys.stdin.readline(4096).rstrip('\r\n')
    if len(token) < 32 or len(token) > 2048 or '\r' in token:
        p.error('invalid protected credential')
    dashboard = Path(args.dashboard).read_bytes()
    if b'ONYX CORE' not in dashboard or b'gatewayMode' not in dashboard:
        p.error('gateway dashboard file missing or invalid')
    overlay_path = Path(args.overlay) if args.overlay else Path(__file__).with_name('overlay.html')
    try:
        overlay = overlay_path.read_bytes()
    except OSError:
        p.error('OBS overlay file missing')
    if b'ONYX CORE' not in overlay or b'id="hud"' not in overlay:
        p.error('OBS overlay file invalid')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    server = http.server.ThreadingHTTPServer((LOCAL_HOST, args.port), Gateway)
    server.daemon_threads = True
    server.dashboard = dashboard
    server.overlay = overlay
    server.token = token
    server.upstream = f'http://{args.receiver}:8765'
    server.opener = opener
    if sys.stdout is not None:
        print(f'ONYX CORE local gateway ready: http://{LOCAL_HOST}:{args.port}/dashboard', flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
