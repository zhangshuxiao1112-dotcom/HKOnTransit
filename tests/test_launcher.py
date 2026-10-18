"""Run the real launcher with IDLE-like streams and verify HTTP readiness."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_starts_http_server_with_idle_like_streams():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    code = '''import runpy, sys
class IdleStream:
    def write(self, text): return sys.__stdout__.write(text)
    def flush(self): return sys.__stdout__.flush()
sys.stdout=IdleStream()
sys.stderr=IdleStream()
sys.argv=[sys.argv[1], '--no-browser', '--port', sys.argv[2]]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
    process = subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'start.py'), str(port)],
                               cwd=str(ROOT), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = 'http://127.0.0.1:' + str(port)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError('Launcher stopped early: ' + process.stdout.read())
            try:
                with opener.open(base + '/api/health', timeout=.3) as response:
                    assert json.load(response)['app'] == 'ready'
                break
            except OSError:
                time.sleep(.05)
        else:
            raise AssertionError('Launcher failed to start within 15 seconds')
        with opener.open(base, timeout=1) as response:
            assert '<html lang="en">' in response.read().decode()
        with opener.open(base + '/assets/live.js', timeout=1) as response:
            assert response.status == 200
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
