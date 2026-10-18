"""Exercise certificate verification with a real local HTTPS handshake."""
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
import pytest
from tls_config import ssl_context


def test_custom_ca_trust_and_untrusted_or_wrong_hostname_rejection(tmp_path, monkeypatch):
    if not shutil.which('openssl'):
        pytest.skip('openssl is needed for the local TLS fixture')
    for key in ('HKONTRANSIT_CA_FILE', 'SSL_CERT_FILE', 'SSL_CERT_DIR'):
        monkeypatch.delenv(key, raising=False)
    cert, key = tmp_path/'ca.pem', tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
                    '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost',
                    '-addext','subjectAltName=DNS:localhost',
                    '-addext','basicConstraints=critical,CA:TRUE'],
                   check=True, capture_output=True)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    port = server.server_port
    try:
        with httpx.Client(verify=ssl_context(), trust_env=False, timeout=2) as client:
            with pytest.raises(httpx.ConnectError):
                client.get(f'https://localhost:{port}')
        monkeypatch.setenv('HKONTRANSIT_CA_FILE', str(cert))
        verified = ssl_context()
        assert verified.check_hostname and verified.verify_mode == ssl.CERT_REQUIRED
        with httpx.Client(verify=verified, trust_env=False, timeout=2) as client:
            assert client.get(f'https://localhost:{port}').status_code == 200
            with pytest.raises(httpx.ConnectError):
                client.get(f'https://127.0.0.1:{port}')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_missing_custom_ca_has_clear_startup_error(monkeypatch):
    monkeypatch.setenv('HKONTRANSIT_CA_FILE', '/nonexistent/hkot-ca.pem')
    with pytest.raises(RuntimeError, match='HKONTRANSIT_CA_FILE'):
        ssl_context()
