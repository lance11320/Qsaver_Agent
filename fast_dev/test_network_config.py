import os
import subprocess
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import network_config


def clear_proxies(monkeypatch):
    for key in list(os.environ):
        if key.lower().endswith('_proxy'):
            monkeypatch.delenv(key)


def test_keeps_existing_exclusions_and_is_idempotent(monkeypatch):
    clear_proxies(monkeypatch)
    monkeypatch.setenv('NO_PROXY', 'internal.example,localhost')
    network_config.configure_loopback_bypass()
    once = os.environ['NO_PROXY']
    network_config.configure_loopback_bypass()
    assert os.environ['NO_PROXY'] == once
    assert {'internal.example', 'localhost', '127.0.0.1', '::1'} <= set(once.split(','))


def test_preserves_windows_system_proxy_fallback(monkeypatch):
    clear_proxies(monkeypatch)
    monkeypatch.setattr(network_config, 'getproxies', lambda: {
        'http': 'http://127.0.0.1:12345', 'https': 'http://127.0.0.1:12345',
        'no': 'intranet.example'})
    network_config.configure_loopback_bypass()
    assert os.environ['HTTPS_PROXY'] == 'http://127.0.0.1:12345'
    assert 'intranet.example' in os.environ['NO_PROXY']


def test_proxy_502_reproduction_and_loopback_fix(monkeypatch):
    clear_proxies(monkeypatch)
    class Local(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'local')
        def log_message(self, *args): pass
    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(502); self.end_headers(); self.wfile.write(b'proxy')
        def log_message(self, *args): pass
    local = ThreadingHTTPServer(('127.0.0.1', 0), Local)
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    for server in (local, proxy):
        Thread(target=server.serve_forever, daemon=True).start()
    try:
        proxy_url = f'http://127.0.0.1:{proxy.server_port}'
        monkeypatch.setenv('HTTP_PROXY', proxy_url)
        monkeypatch.setenv('HTTPS_PROXY', proxy_url)
        monkeypatch.setenv('ALL_PROXY', proxy_url)
        url = f'http://127.0.0.1:{local.server_port}/gradio_api/startup-events'
        assert httpx.get(url).status_code == 502  # reproduces the reported symptom
        network_config.configure_loopback_bypass()
        assert httpx.get(url).status_code == 200
        assert httpx.get(f'http://localhost:{local.server_port}/').status_code == 200
        # No internet call: the dummy proxy handles this reserved domain.
        assert httpx.get('http://qsaver-test.invalid/').text == 'proxy'
        with httpx.Client() as client:
            assert client._transport_for_url(httpx.URL('https://dashscope.aliyuncs.com')) is not client._transport
            assert client._transport_for_url(httpx.URL('http://[::1]:7860')) is client._transport
    finally:
        for server in (local, proxy):
            server.shutdown(); server.server_close()


def test_full_qsaver_gradio_startup_with_unreachable_proxy():
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
    env.update(HTTP_PROXY='http://127.0.0.1:1', HTTPS_PROXY='http://127.0.0.1:1',
               ALL_PROXY='http://127.0.0.1:1', GRADIO_ANALYTICS_ENABLED='False',
               PYTHONIOENCODING='utf-8')
    code = '''
import socket
import Qsaver
import httpx
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
try:
    Qsaver.demo.queue().launch(server_name='127.0.0.1', server_port=port,
        share=False, inbrowser=False, prevent_thread_lock=True, quiet=True)
    assert httpx.get(f'http://127.0.0.1:{port}/config').status_code == 200
    print('QSAVER_PROXY_STARTUP_OK')
finally:
    Qsaver.demo.close()
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parent,
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'QSAVER_PROXY_STARTUP_OK' in result.stdout
