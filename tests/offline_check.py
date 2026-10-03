"""Run integration checks with outbound server network blocked and isolated data."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment['STUDY_DATA_DIR'] = str(ROOT / '.cache/offline-test-data')
environment['STUDY_TEST_URL'] = 'http://127.0.0.1:8001'
environment['TEMP'] = environment['TMP'] = str(ROOT / '.cache/tmp')
(ROOT / '.cache/tmp').mkdir(parents=True, exist_ok=True)
bootstrap = '''
import socket
original_connect = socket.socket.connect
original_resolve = socket.getaddrinfo
def local_connect(self, address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('External network blocked during offline test')
    return original_connect(self, address)
def local_resolve(host, *args, **kwargs):
    if host not in ('127.0.0.1', 'localhost', '::1', None):
        raise RuntimeError('External DNS blocked during offline test')
    return original_resolve(host, *args, **kwargs)
socket.socket.connect = local_connect
socket.getaddrinfo = local_resolve
import uvicorn
uvicorn.run('backend.app:app', host='127.0.0.1', port=8001, access_log=False)
'''
with (ROOT / '.cache/offline-test.log').open('w', encoding='utf-8') as log:
    server = subprocess.Popen([sys.executable, '-c', bootstrap], cwd=ROOT, env=environment, stdout=log, stderr=log)
    try:
        ready = False
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError('Offline test server exited. See .cache/offline-test.log')
            try:
                urllib.request.urlopen(environment['STUDY_TEST_URL'] + '/api/health', timeout=1).close()
                ready = True
                break
            except OSError:
                time.sleep(.1)
        if not ready:
            raise RuntimeError('Offline test server did not start.')
        subprocess.run([sys.executable, 'tests/smoke.py'], cwd=ROOT, env=environment, check=True)
        # Verify all reader resources required at runtime are locally served.
        for path in ['/', '/static/app.js', '/static/style.css', '/static/vendor/pdfjs/build/pdf.mjs',
                     '/static/vendor/pdfjs/build/pdf.worker.mjs', '/static/vendor/pdfjs/web/pdf_viewer.mjs',
                     '/static/vendor/pdfjs/web/pdf_viewer.css', '/static/vendor/pdfjs/standard_fonts/LiberationSans-Regular.ttf']:
            with urllib.request.urlopen(environment['STUDY_TEST_URL'] + path, timeout=10) as response:
                assert response.status == 200
                assert "connect-src 'self'" in response.headers['Content-Security-Policy']
        print('PASS: all integration checks with outbound server networking blocked; reader assets served locally.')
    finally:
        server.terminate()
        server.wait(timeout=10)
