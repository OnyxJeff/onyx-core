"""Loopback-only gateway regression checks using a fake Pi receiver."""
import http.server
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TOKEN='isolated-testing-token-not-production-12345678'
class FakePi(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer '+TOKEN:
            self.send_response(401);self.end_headers();return
        data=json.dumps({'status':'healthy','samples':[]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

def get(url,headers=None,method=None):
    req=urllib.request.Request(url,headers=headers or {},method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as r:
            return r.status,r.read()
    except urllib.error.HTTPError as e: return e.code,e.read()

import socket
try:
    pi=http.server.ThreadingHTTPServer(('127.0.0.1',8765),FakePi)
    upstream_available=True
except OSError:
    pi=http.server.ThreadingHTTPServer(('127.0.0.1',0),FakePi)
    upstream_available=False
t=threading.Thread(target=pi.serve_forever,daemon=True);t.start()
import socket
s=socket.socket();s.bind(('127.0.0.1',0)); port=s.getsockname()[1];s.close()
proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'OnyxGateway.py'),'--dashboard',str(ROOT/'gateway-dashboard.html'),'--receiver','127.0.0.1','--port',str(port)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
# Upstream-positive-path checks use the configured port 8765 if available.
proc.stdin.write(TOKEN+'\n');proc.stdin.close()
try:
    for _ in range(40):
        try:
            code,html=get(f'http://127.0.0.1:{port}/dashboard')
            if code==200:break
        except Exception:time.sleep(.05)
    else: raise RuntimeError('gateway failed to start')
    overlay_code, overlay_html=get(f'http://127.0.0.1:{port}/overlay')
    overlay_slash_code, _=get(f'http://127.0.0.1:{port}/overlay/')
    portrait_code, portrait_html=get(f'http://127.0.0.1:{port}/overlay-portrait')
    portrait_slash_code, _=get(f'http://127.0.0.1:{port}/overlay-portrait/')
    cases=[('dashboard', code==200 and b'gatewayMode' in html),
           ('overlay served', overlay_code==200 and b'id="hud"' in overlay_html),
           ('overlay slash', overlay_slash_code==200),
           ('transparent overlay', b'background:transparent' in overlay_html),
           ('overlay has no token input', b'id="token"' not in overlay_html),
           ('overlay query denied', get(f'http://127.0.0.1:{port}/overlay?token=test')[0]==404),
           ('portrait overlay served', portrait_code==200 and b'id="hud"' in portrait_html),
           ('portrait overlay slash', portrait_slash_code==200),
           ('portrait transparent', b'background: transparent' in portrait_html),
           ('portrait CPU temperature', b'id="cpu-temp"' in portrait_html and b'fmtTemp(m.cpu_temp_c)' in portrait_html),
           ('portrait no token input', b'id="token"' not in portrait_html),
           ('portrait query denied', get(f'http://127.0.0.1:{port}/overlay-portrait?token=test')[0]==404),
           ('portrait original preserved', overlay_code==200 and b'id="cpu-temp"' not in overlay_html),
           ('portrait host-rebinding', get(f'http://127.0.0.1:{port}/overlay-portrait',{'Host':'attacker.test'})[0]==403),
           ('portrait cross-site denied', get(f'http://127.0.0.1:{port}/overlay-portrait',{'Sec-Fetch-Site':'cross-site'})[0]==403),
           ('host-rebinding', get(f'http://127.0.0.1:{port}/api/v1/latest',{'Host':'attacker.test'})[0]==403),
           ('cross-site-fetch',get(f'http://127.0.0.1:{port}/api/v1/latest',{'Sec-Fetch-Site':'cross-site'})[0]==403),
           ('origin',get(f'http://127.0.0.1:{port}/api/v1/latest',{'Origin':'https://evil.example'})[0]==403),
           ('POST blocked',get(f'http://127.0.0.1:{port}/api/v1/latest',method='POST')[0]==405),
           ('telemetry POST blocked',get(f'http://127.0.0.1:{port}/api/v1/telemetry',method='POST')[0]==405),
           ('unapproved path',get(f'http://127.0.0.1:{port}/private')[0]==404),
           ('invalid limit',get(f'http://127.0.0.1:{port}/api/v1/history?limit=999')[0]==400)]
    if upstream_available:
        for path in ('/api/v1/health','/api/v1/latest','/api/v1/history?limit=60'):
            status,body=get(f'http://127.0.0.1:{port}'+path)
            cases.append(('authenticated upstream '+path,status==200 and b'healthy' in body))
    else:
        print('SKIP: upstream-positive-path tests (local port 8765 occupied)')
    for name,result in cases:
        print(('PASS' if result else 'FAIL')+': '+name)
    if not all(v for _,v in cases):sys.exit(1)
finally:
    proc.terminate()
    proc.wait(timeout=3)
    pi.shutdown()
