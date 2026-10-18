"""HKOnTransit — FastAPI gateway proxying Hong Kong official transport open-data APIs.

This is the main entry point of the backend. It serves the single-page web UI
(index.html + static assets) and exposes same-origin REST endpoints that
proxy read-only requests to five Hong Kong Government open-data APIs.
No API keys or credentials are required — all upstream APIs are public.

External APIs proxied (all read-only, no auth needed):

  GMB — Transport Department Green Minibus data
        Base URL: https://data.etagmb.gov.hk
        Proxied endpoints:
          GET /api/gmb/routes/{region}
              -> GMB /route/{region}  (region: HKI | KLN | NT)
          GET /api/gmb/route/{region}/{route_code}
              -> GMB /route/{region}/{route_code}
          GET /api/gmb/stops/{route_id}/{route_seq}
              -> GMB /route-stop/{route_id}/{route_seq}
          GET /api/gmb/stop/{stop_id}
              -> GMB /stop/{stop_id}
          GET /api/gmb/eta/{route_id}/{route_seq}/{stop_seq}
              -> GMB /eta/route-stop/{route_id}/{route_seq}/{stop_seq}

  KMB — Kowloon Motor Bus / Long Win Bus data
        Base URL: https://data.etabus.gov.hk/v1/transport/kmb
        Proxied endpoints:
          GET /api/bus/kmb/stops?route=&direction=&service_type=
              -> KMB /route-stop/{route}/{direction}/{service_type}
          GET /api/bus/kmb/eta?route=&stop_id=&service_type=&direction=
              -> KMB /eta/{stop_id}/{route}/{service_type}
          GET /api/bus/kmb/stop/{stop_id}
              -> KMB /stop/{stop_id}

  CTB — Citybus real-time data
        Base URL: https://rt.data.gov.hk/v2/transport/citybus
        Proxied endpoints:
          GET /api/bus/ctb/stops?route=&direction=
              -> CTB /route-stop/CTB/{route}/{direction}
          GET /api/bus/ctb/eta?route=&stop_id=&direction=
              -> CTB /eta/CTB/{stop_id}/{route}
          GET /api/bus/ctb/stop/{stop_id}
              -> CTB /stop/{stop_id}

  MTR — MTR Next Train real-time schedule
        Base URL: https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php
        Proxied endpoints:
          GET /api/mtr/next-train?line=&station=
              -> MTR ?line={line}&sta={station}&lang=TC
        (Pilot supports a curated subset of lines/stations — see MTR_PAIRS.)

  HKO — Hong Kong Observatory open weather data
        Base URL: https://data.weather.gov.hk/weatherAPI/opendata/weather.php
        Proxied endpoints:
          GET /api/weather
              -> HKO ?dataType=rhrread&lang=tc

GenAI integration (v2):
  The AI router (ai.router) is mounted at /api/ai/* for natural-language
  preference interpretation, community-report structuring, and route
  explanation. See ai/adapters/deepseek.py for activation instructions.

Environment variables (all optional — the demo runs fully offline by default):
  HKONTRANSIT_DB          — SQLite database path (default: ./citypulse.sqlite3)
  HKONTRANSIT_AI_PROVIDER — "mock" (default, offline stubs) | "deepseek" (live)
  DEEPSEEK_API_KEY        — required when provider=deepseek (sk-...)
  DEEPSEEK_MODEL          — model id (default: deepseek-chat)
  DEEPSEEK_BASE_URL       — API base override (default: https://api.deepseek.com)

Run:
  uvicorn server:app --host 127.0.0.1 --port 8000
  (or use ./run.sh which also installs requirements first)

Maintainer notes:
  * All upstream calls go through the ``upstream()`` function which applies
    TTL caching, validates response shape, and uses a shared httpx client.
  * Hostnames are hardcoded constants — caller-supplied URLs are never
    forwarded to prevent SSRF.
  * ETA freshness is checked against the official ``generated_timestamp``;
    stale data is hidden from the UI rather than shown as live.
  * Fresh ETA snapshots are persisted to SQLite for the ETA reliability lab.
  * CORS is restricted to local dev origins only (127.0.0.1:8000).
  * To add a new transport operator: add a base-URL constant, write handler
    functions following the GMB/KMB/CTB pattern, and add UI controls in
    index.html + live.js.
"""
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import getproxies, proxy_bypass

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# v2: GenAI interpretation/explanation layer (model-agnostic, hybrid architecture).
from tls_config import ssl_context
from ai.router import router as ai_router
from ai.service import ai_service

HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('HKONTRANSIT_DB', str(HERE / 'citypulse.sqlite3')))
GMB = 'https://data.etagmb.gov.hk'
KMB = 'https://data.etabus.gov.hk/v1/transport/kmb'
CTB = 'https://rt.data.gov.hk/v2/transport/citybus'
MTR = 'https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php'
HKO = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php'
TZ_HK = timezone(timedelta(hours=8))
CACHE: dict[str, tuple[float, Any]] = {}
INFLIGHT: dict[str, asyncio.Task] = {}
CIRCUITS: dict[str, tuple[int, float]] = {}
REQUEST_BUDGET = 10.5
ATTEMPT_TIMEOUT = 5.0
ALLOWED_REGIONS = ('HKI', 'KLN', 'NT')
MTR_PAIRS = {'TKL': {'TKO', 'POA', 'HAH', 'LHP', 'QUB', 'NOP', 'TIK', 'YAT'},
             'ISL': {'CEN', 'ADM', 'SHW', 'SYP', 'HKU', 'KET', 'FOR', 'CWB', 'TIH', 'QUB', 'NOP', 'CHW', 'HFC', 'SKW', 'SWH'},
             'TWL': {'CEN', 'ADM', 'TST', 'JOR', 'YMT', 'MOK', 'PRE', 'SSP', 'CSW', 'LCK', 'MEF', 'LAK', 'KWF', 'KWH', 'TWH', 'TSW'},
             'TML': {'WKS', 'MOS', 'HEO', 'TSH', 'SHM', 'CIO', 'STW', 'CKT', 'TAW', 'HIK', 'DIH', 'KAT', 'SUW', 'TKW', 'HOM', 'HUH', 'ETS', 'AUS', 'NAC', 'MEF', 'TWW', 'KSR', 'YUL', 'LOP', 'TIS', 'HHS', 'TUM'},
             'AEL': {'HOK', 'KOW', 'TSY', 'AIR', 'AWE'},
             'TCL': {'HOK', 'KOW', 'OLY', 'NAC', 'LAK', 'TSY', 'SUN', 'TUC'}}

app = FastAPI(title='HKOnTransit official-data API', version='2.0.0')
# v2: GenAI endpoints are same-origin; allow local dev origins only.
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:8000', 'http://localhost:8000'],
                   allow_methods=['GET', 'POST'], allow_headers=['*'])
app.include_router(ai_router)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS eta_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator TEXT NOT NULL,
            route TEXT NOT NULL,
            direction TEXT NOT NULL,
            stop_id TEXT NOT NULL,
            seq INTEGER,
            fetched_at TEXT NOT NULL,
            generated_at TEXT,
            predicted_at TEXT,
            eta_minutes REAL,
            remark TEXT,
            UNIQUE(operator,route,direction,stop_id,fetched_at,predicted_at)
        )''')
        con.execute('CREATE INDEX IF NOT EXISTS idx_eta_route ON eta_snapshots(operator,route,stop_id,fetched_at)')
        con.execute('''CREATE TABLE IF NOT EXISTS actual_arrivals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, operator TEXT, route TEXT, direction TEXT,
            stop_id TEXT, arrived_at TEXT, observer_note TEXT, created_at TEXT NOT NULL)''')


def transport_options():
    """Use OS proxies too (httpx only discovers environment proxies itself)."""
    ctx = ssl_context()
    mode = os.environ.get('HKONTRANSIT_NETWORK_MODE', 'system').lower()
    if mode == 'direct':
        return {'trust_env': False, 'verify': ctx}, 'direct'
    explicit = os.environ.get('HKONTRANSIT_PROXY', '').strip()
    if explicit:
        return {'proxy': httpx.Proxy(explicit, ssl_context=ctx if urlparse(explicit).scheme == 'https' else None), 'trust_env': True, 'verify': ctx}, 'configured-proxy'
    if mode != 'system':
        raise RuntimeError('HKONTRANSIT_NETWORK_MODE must be system or direct.')
    proxies = getproxies()
    mounts = {}
    for base in (GMB, KMB, CTB, MTR, HKO):
        host = urlparse(base).hostname
        proxy = proxies.get('https') or proxies.get('all')
        if proxy and not proxy_bypass(host):
            mounts['https://' + host] = httpx.AsyncHTTPTransport(proxy=httpx.Proxy(proxy, ssl_context=ctx if urlparse(proxy).scheme == 'https' else None), verify=ctx)
    return {'trust_env': True, 'mounts': mounts, 'verify': ctx}, 'system-proxy' if mounts else 'system'


def connection_error(error):
    """Actionable, sanitised diagnostics; never expose proxy credentials or URLs."""
    chain = []
    current = error
    while current is not None and len(chain) < 8:
        chain.append(str(current).lower())
        current = current.__cause__ or current.__context__
    message = ' '.join(chain)
    if any(marker in message for marker in ('certificate_verify_failed', 'certificate verify failed',
                                         'certificate verification', 'hostname mismatch',
                                         'self-signed certificate', 'unable to get local issuer')):
        return 'TLS certificate verification failed with system and public roots. Check your device date/time and trusted network CA, or try another network. A managed CA can be configured with HKONTRANSIT_CA_FILE; HTTPS verification remains enabled.'
    if isinstance(error, httpx.ProxyError) or 'proxy' in message:
        return 'Proxy connection failed. Check your system proxy or HKONTRANSIT_PROXY setting, then restart start.py.'
    if any(x in message for x in ('name resolution', 'getaddrinfo', 'nodename', 'name or service')):
        return 'DNS lookup failed. Check your network, DNS and proxy settings, then retry.'
    if isinstance(error, (asyncio.TimeoutError, httpx.TimeoutException)):
        return 'Official source timed out. Check your network or proxy, then retry.'
    if isinstance(error, httpx.HTTPStatusError):
        return f'Official source returned HTTP {error.response.status_code}. Retry later or check network filtering.'
    if isinstance(error, httpx.ConnectError):
        return 'Cannot connect to the official source. Check your network, firewall and proxy settings.'
    return 'Official source returned an invalid response. Retry later or check network filtering.'


@app.on_event('startup')
async def startup():
    init_db()
    options, app.state.network_mode = transport_options()
    app.state.client = httpx.AsyncClient(**options, timeout=httpx.Timeout(4.8, connect=3.0, pool=1.0), follow_redirects=False,
                                          headers={'Accept': 'application/json', 'User-Agent': 'HKOnTransit-StudentPilot/1.0'})


@app.on_event('shutdown')
async def shutdown():
    for task in list(INFLIGHT.values()):
        task.cancel()
    if INFLIGHT:
        await asyncio.gather(*list(INFLIGHT.values()), return_exceptions=True)
    INFLIGHT.clear()
    await app.state.client.aclose()
    await ai_service.close()  # v2: release GenAI adapter resources


async def upstream(base: str, path: str = '', *, params: dict | None = None, ttl: int = 60) -> dict:
    """One bounded refresh per cache key, one transient retry, no stale live ETA."""
    url = base + path
    key = url + repr(sorted((params or {}).items()))
    now = time.monotonic()
    cached = CACHE.get(key)
    if cached and now - cached[0] < ttl:
        return cached[1]
    failures, retry_at = CIRCUITS.get(base, (0, 0))
    if retry_at > now:
        raise HTTPException(503, detail='Official source is temporarily unavailable. Retry shortly.',
                            headers={'Retry-After': str(max(1, round(retry_at - now)))})

    async def refresh():
        last_error = None
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(
                    app.state.client.get(url, params=params), timeout=ATTEMPT_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or ('data' not in data and base not in (HKO, MTR)):
                    raise ValueError('Invalid official response shape')
                CACHE[key] = (time.monotonic(), data)
                if len(CACHE) > 1500:
                    oldest = min(CACHE, key=lambda k: CACHE[k][0])
                    CACHE.pop(oldest, None)
                CIRCUITS.pop(base, None)
                return data
            except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as err:
                last_error = err
                if isinstance(err, httpx.HTTPStatusError) and err.response.status_code < 500 and err.response.status_code != 429:
                    break
                if attempt == 0:
                    await asyncio.sleep(0.1)
        count = CIRCUITS.get(base, (0, 0))[0] + 1
        CIRCUITS[base] = (count, time.monotonic() + 15 if count >= 3 else 0)
        raise HTTPException(503, detail=connection_error(last_error),
                            headers={'Retry-After': '15' if count >= 3 else '1'})

    task = INFLIGHT.get(key)
    if task is None:
        task = asyncio.create_task(refresh())
        INFLIGHT[key] = task
        def finished(done):
            if INFLIGHT.get(key) is done:
                INFLIGHT.pop(key, None)
            if not done.cancelled():
                done.exception()  # retrieve errors even after a disconnected caller
        task.add_done_callback(finished)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=REQUEST_BUDGET)
    except asyncio.TimeoutError as err:
        raise HTTPException(503, detail='Official source did not respond in time. Please retry.') from err


def require_code(value: str, pattern: str = r'[A-Za-z0-9]{1,12}') -> str:
    if not re.fullmatch(pattern, value):
        raise HTTPException(422, detail='Invalid route or stop code.')
    return value


def name(obj: dict, field: str = 'name') -> str:
    return obj.get(field + '_en') or ''


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=TZ_HK)
    except (ValueError, TypeError):
        return None


def freshness(ts: str | None, threshold_seconds: int = 180) -> str:
    t = parse_dt(ts)
    if t is None:
        return 'unknown'
    seconds = (datetime.now(timezone.utc) - t.astimezone(timezone.utc)).total_seconds()
    return 'fresh' if -60 <= seconds <= threshold_seconds else 'stale'


def save_etas(operator: str, route: str, direction: str, stop_id: str,
              generated: str | None, etas: list[dict]) -> None:
    fetched = datetime.now(timezone.utc).isoformat()
    rows = [(operator, route, direction, stop_id, it.get('sequence'), fetched,
             generated, it.get('timestamp'), it.get('minutes'), it.get('remark')) for it in etas]
    if rows:
        with sqlite3.connect(DB_PATH) as con:
            con.executemany('''INSERT OR IGNORE INTO eta_snapshots
              (operator,route,direction,stop_id,seq,fetched_at,generated_at,predicted_at,eta_minutes,remark)
              VALUES (?,?,?,?,?,?,?,?,?,?)''', rows)


def normalize_entries(items: list, *, provider: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(TZ_HK)
    result = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ts = it.get('timestamp') if provider == 'gmb' else it.get('eta')
        parsed = parse_dt(ts)
        # Use absolute ETA for all operators; diff may be stale due to caching.
        mins = round((parsed - now).total_seconds() / 60) if parsed else None
        if parsed and mins < -2:
            continue
        result.append({'sequence': it.get('eta_seq') if provider == 'gmb' else it.get('seq'),
                       'timestamp': ts, 'minutes': max(0, mins) if mins is not None else None,
                       'remark': name(it, 'remarks') if provider == 'gmb' else (it.get('rmk_en') or ''),
                       'destination': it.get('dest_en') or ''})
    return result[:5]


@app.get('/api/health')
def health():
    return {'app': 'ready', 'mode': 'live-api-gateway', 'upstream': 'not_probed',
            'message': 'Gateway ready. Check /api/diagnostics for actual upstream connectivity.'}


@app.get('/api/gmb/routes/{region}')
async def gmb_routes(region: str):
    region = region.upper()
    if region not in ALLOWED_REGIONS:
        raise HTTPException(422, detail='Region must be HKI, KLN or NT.')
    raw = await upstream(GMB, '/route/' + region, ttl=1800)
    payload = raw.get('data') or {}
    routes = payload.get('routes') or []
    if not isinstance(routes, list):
        raise HTTPException(502, detail='Invalid minibus route list.')
    return {'region': region, 'routes': routes, 'source': 'TD GMB', 'generated_at': raw.get('generated_timestamp')}


@app.get('/api/gmb/route/{region}/{route_code}')
async def gmb_route(region: str, route_code: str):
    region = region.upper()
    if region not in ALLOWED_REGIONS:
        raise HTTPException(422, detail='Invalid region.')
    route_code = require_code(route_code.upper())
    raw = await upstream(GMB, '/route/' + region + '/' + quote(route_code), ttl=900)
    items = raw.get('data') or []
    if not isinstance(items, list):
        raise HTTPException(502, detail='Invalid route details.')
    variants = []
    for route in items:
        for d in route.get('directions', []):
            variants.append({'route_id': route['route_id'], 'route_code': route.get('route_code', route_code),
                             'route_seq': d['route_seq'], 'origin': name(d, 'orig'), 'destination': name(d, 'dest'),
                             'description': name(route, 'description'), 'remark': name(d, 'remarks')})
    return {'region': region, 'variants': variants, 'source': 'TD GMB', 'generated_at': raw.get('generated_timestamp')}


@app.get('/api/gmb/stops/{route_id}/{route_seq}')
async def gmb_stops(route_id: int, route_seq: int):
    if route_id < 1 or route_seq not in (1, 2):
        raise HTTPException(422, detail='Invalid route ID or direction.')
    raw = await upstream(GMB, f'/route-stop/{route_id}/{route_seq}', ttl=900)
    data = raw.get('data') or {}
    stops = data.get('route_stops') or []
    return {'route_id': route_id, 'route_seq': route_seq,
            'stops': [{'stop_id': item['stop_id'], 'stop_seq': item['stop_seq'], 'name': name(item) or f"Stop {item['stop_id']}"} for item in stops],
            'source': 'TD GMB', 'generated_at': raw.get('generated_timestamp')}


@app.get('/api/gmb/stop/{stop_id}')
async def gmb_stop(stop_id: int):
    if stop_id < 1:
        raise HTTPException(422, detail='Invalid stop ID.')
    raw = await upstream(GMB, f'/stop/{stop_id}', ttl=7200)
    data = raw.get('data') or {}
    wgs = (data.get('coordinates') or {}).get('wgs84') or {}
    return {'stop_id': stop_id, 'latitude': wgs.get('latitude'), 'longitude': wgs.get('longitude'),
            'enabled': data.get('enabled'), 'remarks': name(data, 'remarks'),
            'verified_location': 'official_coordinates', 'source': 'TD GMB',
            'generated_at': raw.get('generated_timestamp')}


@app.get('/api/gmb/eta/{route_id}/{route_seq}/{stop_seq}')
async def gmb_eta(route_id: int, route_seq: int, stop_seq: int):
    if route_id < 1 or route_seq not in (1, 2) or stop_seq < 1:
        raise HTTPException(422, detail='Invalid route, direction or stop sequence.')
    raw = await upstream(GMB, f'/eta/route-stop/{route_id}/{route_seq}/{stop_seq}', ttl=20)
    data = raw.get('data') or {}
    if not isinstance(data, dict):
        raise HTTPException(502, detail='Invalid minibus ETA response.')
    generated = raw.get('generated_timestamp')
    status = freshness(generated)
    enabled = data.get('enabled') is True
    etas = normalize_entries(data.get('eta') or [], provider='gmb') if enabled else []
    # Only accumulate fresh official snapshots. Never use stale data for live board.
    if status == 'fresh':
        save_etas('GMB', str(route_id), str(route_seq), str(data.get('stop_id') or ''), generated, etas)
    return {'operator': 'GMB', 'route_id': route_id, 'direction': route_seq, 'stop_seq': stop_seq,
            'stop_id': data.get('stop_id'), 'enabled': enabled, 'status': status if enabled else 'unavailable',
            'message': name(data, 'description') if not enabled else '', 'etas': etas if status == 'fresh' else [],
            'generated_at': generated, 'source': 'Transport Department / GMB', 'official': True}


async def _warm_kmb_catalogue():
    try:
        await upstream(KMB, '/stop', ttl=86400)
    except HTTPException:
        pass


async def bus_stop_names(rows: list, base: str) -> list[dict]:
    names = {}
    if base == KMB:
        try:
            catalogue_key = KMB + '/stop' + repr([])
            raw = CACHE.get(catalogue_key, (0, {'data': []}))[1]
            names = {str(x.get('stop')): name(x) for x in raw.get('data', [])}
        except HTTPException:
            pass
    # Citybus only publishes individual stop details. Show stable IDs initially;
    # selected stop details are resolved separately without an N-request waterfall.
    return [{'stop_id': row.get('stop'), 'stop_seq': row.get('seq'),
             'name': names.get(str(row.get('stop'))) or f"Stop {row.get('stop')}"}
            for row in rows]


@app.get('/api/bus/kmb/stops')
async def kmb_stops(route: str = Query(...), direction: str = Query('outbound'), service_type: int = Query(1)):
    route = require_code(route.upper())
    if direction not in ('outbound', 'inbound') or service_type < 1 or service_type > 99:
        raise HTTPException(422, detail='Invalid bus direction or service type.')
    raw, _ = await asyncio.gather(
        upstream(KMB, f'/route-stop/{route}/{direction}/{service_type}', ttl=900),
        _warm_kmb_catalogue())
    rows = raw.get('data') or []
    return {'operator': 'KMB', 'route': route, 'direction': direction, 'service_type': service_type,
            'stops': await bus_stop_names(rows, KMB),
            'source': 'KMB', 'generated_at': raw.get('generated_timestamp')}


@app.get('/api/bus/kmb/eta')
async def kmb_eta(route: str, stop_id: str, service_type: int = 1, direction: str = 'outbound'):
    route = require_code(route.upper()); stop_id = require_code(stop_id, r'[A-Fa-f0-9]{16}')
    if direction not in ('inbound', 'outbound') or not 1 <= service_type <= 99:
        raise HTTPException(422, detail='Invalid parameters.')
    raw = await upstream(KMB, f'/eta/{stop_id}/{route}/{service_type}', ttl=20)
    d = 'I' if direction == 'inbound' else 'O'
    entries = [x for x in (raw.get('data') or []) if x.get('dir') == d]
    stamp = raw.get('generated_timestamp')
    state = freshness(stamp)
    result = normalize_entries(entries, provider='bus')
    if state == 'fresh':
        save_etas('KMB', route, d, stop_id, stamp, result)
    return {'operator': 'KMB', 'route': route, 'direction': direction, 'stop_id': stop_id,
            'etas': result if state == 'fresh' else [], 'status': state, 'generated_at': stamp,
            'source': 'KMB / LWB', 'official': True}


@app.get('/api/bus/ctb/stops')
async def ctb_stops(route: str, direction: str = 'outbound'):
    route = require_code(route.upper())
    if direction not in ('inbound', 'outbound'):
        raise HTTPException(422, detail='Invalid direction.')
    raw = await upstream(CTB, f'/route-stop/CTB/{route}/{direction}', ttl=900)
    rows = raw.get('data') or []
    return {'operator': 'CTB', 'route': route, 'direction': direction,
            'stops': await bus_stop_names(rows, CTB),
            'source': 'Citybus', 'generated_at': raw.get('generated_timestamp')}


@app.get('/api/bus/ctb/eta')
async def ctb_eta(route: str, stop_id: str, direction: str = 'outbound'):
    route = require_code(route.upper()); stop_id = require_code(stop_id, r'\d{6}')
    if direction not in ('inbound', 'outbound'):
        raise HTTPException(422, detail='Invalid direction.')
    raw = await upstream(CTB, f'/eta/CTB/{stop_id}/{route}', ttl=20)
    d = 'I' if direction == 'inbound' else 'O'
    entries = [x for x in (raw.get('data') or []) if x.get('dir') == d]
    stamp = raw.get('generated_timestamp')
    state = freshness(stamp)
    result = normalize_entries(entries, provider='bus')
    if state == 'fresh':
        save_etas('CTB', route, d, stop_id, stamp, result)
    return {'operator': 'CTB', 'route': route, 'direction': direction, 'stop_id': stop_id,
            'etas': result if state == 'fresh' else [], 'status': state, 'generated_at': stamp,
            'source': 'Citybus', 'official': True}


@app.get('/api/bus/ctb/stop/{stop_id}')
async def ctb_stop(stop_id: str):
    stop_id = require_code(stop_id, r'\d{6}')
    raw = await upstream(CTB, f'/stop/{stop_id}', ttl=3600)
    d = raw.get('data') or {}
    return {'stop_id': stop_id, 'name': name(d), 'latitude': d.get('lat'),
            'longitude': d.get('long'), 'source': 'Citybus'}


@app.get('/api/bus/kmb/stop/{stop_id}')
async def kmb_stop(stop_id: str):
    stop_id = require_code(stop_id, r'[A-Fa-f0-9]{16}')
    raw = await upstream(KMB, f'/stop/{stop_id}', ttl=3600)
    d = raw.get('data') or {}
    return {'stop_id': stop_id, 'name': name(d), 'latitude': d.get('lat'),
            'longitude': d.get('long'), 'source': 'KMB'}


@app.get('/api/weather')
async def weather():
    raw = await upstream(HKO, params={'dataType': 'rhrread', 'lang': 'en'}, ttl=600)
    data = raw
    return {'source': 'Hong Kong Observatory', 'update_time': data.get('updateTime'),
            'warnings': data.get('warningMessage') or [],
            'temperature_readings': (data.get('temperature') or {}).get('data', [])[:5],
            'humidity': (data.get('humidity') or {}).get('data', [])[:2],
            'note': 'Weather station observations, not conditions at a specific stop.'}


@app.get('/api/mtr/next-train')
async def mtr_next_train(line: str, station: str):
    line = line.upper(); station = station.upper()
    if station not in MTR_PAIRS.get(line, set()):
        raise HTTPException(422, detail='This line/station combination is not supported.')
    raw = await upstream(MTR, params={'line': line, 'sta': station, 'lang': 'EN'}, ttl=15)
    rows = (raw.get('data') or {}).get(f'{line}-{station}') or {}
    schedule = []
    for direction in ('UP', 'DOWN'):
        for r in (rows.get(direction) or []):
            if r.get('valid') == 'N':
                continue
            schedule.append({'direction': direction, 'destination_code': r.get('dest'),
                             'minutes': int(r['ttnt']) if str(r.get('ttnt', '')).isdigit() else None,
                             'platform': r.get('plat'), 'at': r.get('time')})
    return {'line': line, 'station': station, 'status': 'fresh' if str(raw.get('status')) == '1' and raw.get('isdelay') != 'Y' and freshness(raw.get('curr_time')) == 'fresh' else 'unavailable',
            'message': raw.get('message'), 'trains': schedule, 'source': 'MTR Next Train', 'generated_at': raw.get('curr_time')}


@app.get('/api/diagnostics')
async def diagnostics():
    """Read-only probes of each configured provider; not a readiness claim."""
    probes = [
        ('GMB', GMB, '/route/HKI', None),
        ('KMB', KMB, '/route-stop/1A/outbound/1', None),
        ('Citybus', CTB, '/route-stop/CTB/1/inbound', None),
        ('MTR', MTR, '', {'line': 'TKL', 'sta': 'TKO', 'lang': 'EN'}),
        ('HKO', HKO, '', {'dataType': 'rhrread', 'lang': 'en'}),
    ]
    async def probe(label, base, path, params):
        started = time.monotonic()
        try:
            data = await upstream(base, path, params=params, ttl=0)
            return {'provider': label, 'connection': 'ok',
                    'elapsed_ms': round((time.monotonic() - started) * 1000),
                    'generated_at': data.get('generated_timestamp') or data.get('curr_time') or data.get('updateTime')}
        except HTTPException as err:
            return {'provider': label, 'connection': 'unavailable', 'message': err.detail,
                    'elapsed_ms': round((time.monotonic() - started) * 1000)}
    results = await asyncio.gather(*(probe(*p) for p in probes))
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'providers': results,
            'all_connected': all(p['connection'] == 'ok' for p in results),
            'ai_provider': ai_service.provider_label, 'network_mode': getattr(app.state, 'network_mode', 'unknown'),
            'tls_trust': 'system-and-certifi', 'tls_verification': True,
            'request_budget_seconds': REQUEST_BUDGET}


@app.get('/api/lab/summary')
def lab_summary():
    with sqlite3.connect(DB_PATH) as con:
        total, = con.execute('SELECT COUNT(*) FROM eta_snapshots').fetchone()
        count, = con.execute('SELECT COUNT(*) FROM actual_arrivals').fetchone()
    return {'eta_snapshot_rows': total, 'independent_actual_arrivals': count,
            'mae': None, 'prediction_model': 'not_trained',
            'message': 'Snapshots are predictions. MAE requires independently observed arrivals.'}


@app.get('/')
def home():
    return FileResponse(HERE / 'index.html')


app.mount('/assets', StaticFiles(directory=HERE / 'static'), name='assets')
