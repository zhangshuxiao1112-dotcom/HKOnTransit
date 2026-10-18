"""Open this file in IDLE and choose Run > Run Module (F5).

Keep the whole extracted folder together. This launcher starts the local
website; the interface itself runs in your web browser, not inside IDLE.
"""
import argparse
import importlib.util
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def ensure_dependencies():
    modules = ('fastapi', 'uvicorn', 'httpx', 'pydantic', 'dotenv', 'socksio', 'truststore', 'certifi')
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if not missing:
        import pydantic
        if int(pydantic.__version__.split('.')[0]) >= 2:
            return
    print('Installing the required Python packages. First launch needs internet…', flush=True)
    # Capture child output: IDLE Shell streams do not provide normal file descriptors.
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--use-feature=truststore', '-r', str(ROOT / 'requirements.txt')],
        cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, errors='replace', timeout=180,
    )
    if result.returncode:
        print(result.stdout)
        raise RuntimeError('Package installation failed. Copy the message above for troubleshooting.')
    importlib.invalidate_caches()
    print('Required packages installed.', flush=True)


def ready_browser(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(60):
        try:
            with opener.open(url + '/api/health', timeout=.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(.25)
    print('Automatic browser opening did not finish. Open ' + url + ' manually.', flush=True)


def main(argv=None):
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required. Check the Python version shown in your IDLE Shell.')
    parser = argparse.ArgumentParser(description='Start HKOnTransit from IDLE or a terminal.')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if not (ROOT / 'index.html').exists() or not (ROOT / 'ai').is_dir():
        raise RuntimeError('Extract the entire ZIP first. Do not run start.py from inside the ZIP or move it out of the project folder.')
    ensure_dependencies()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    import uvicorn
    from server import app
    if args.check_only:
        print('Startup check passed: Python, packages, application and static files are ready.', flush=True)
        return
    # Bind an available local port before starting; F5 after an old instance
    # need not fail merely because port 8000 is still occupied.
    bound = None
    for port in range(args.port, min(args.port + 11, 65536)):
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            candidate.bind(('127.0.0.1', port))
            candidate.listen(128)
        except OSError:
            candidate.close()
            continue
        bound = candidate
        break
    if bound is None:
        raise RuntimeError('No free local port found. Close older server instances and try again.')
    url = 'http://127.0.0.1:' + str(bound.getsockname()[1])
    # Standard logging works with IDLE's output stream without fileno/isatty.
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s', stream=sys.stdout, force=True)
    print('\nHKOnTransit is starting: ' + url, flush=True)
    print('Use the website in your browser. Keep IDLE Shell open while using it.', flush=True)
    print('To stop: choose Shell > Interrupt Execution, or press Ctrl+C in the Shell.\n', flush=True)
    if not args.no_browser:
        threading.Thread(target=ready_browser, args=(url,), daemon=True).start()
    try:
        config = uvicorn.Config(app, host='127.0.0.1', port=bound.getsockname()[1],
                                log_config=None, access_log=False, loop='asyncio')
        uvicorn.Server(config).run(sockets=[bound])
    finally:
        bound.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nHKOnTransit stopped.')
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print('\nSTARTUP FAILED: ' + str(error))
        print('Please copy the full message above, including your Python version.')
