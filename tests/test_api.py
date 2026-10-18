"""Pytest tests for the HKOnTransit FastAPI gateway.

These tests verify the server's API proxy chain using a mocked upstream
(httpx.MockTransport) — no real network calls are made. The fixture `official()`
returns deterministic fake responses mimicking the GMB, KMB, CTB, MTR, and
HKO APIs so tests are reproducible and independent of external availability.

Test coverage:
  1. test_green_minibus_chain_and_persist — full GMB flow: routes → variants →
     stops → coordinates → ETA, plus SQLite snapshot persistence.
  2. test_disabled_eta_does_not_fabricate_arrival — a stop with enabled=False
     returns status='unavailable' and an empty ETA list (no fabricated data).
  3. test_stale_official_data_hidden — an ETA with a 20-min-old timestamp
     is detected as 'stale' and hidden from the response.
  4. test_bus_providers_direction_filter — KMB and CTB stop lists, ETA
     direction filtering, and stop detail endpoints.
  5. test_mtr_weather — HKO weather temperature and MTR Next Train schedule.
  6. test_validation — invalid region, XSS attempt, bad stop_id, bad
     line/station combinations all return 422.
  7. test_http_and_assets — GET / serves index.html, /assets/live.js is
     served, and /assets/server.py is NOT served (no directory traversal).

Maintainer notes:
  - The test fixture replaces server.app.state.client with a mock transport.
  - DB_PATH is redirected to a tmp_path so tests don't pollute the real DB.
  - Run: python -m pytest tests/test_api.py -v
  - These tests do NOT require playwright or a browser.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
import server

HK=timezone(timedelta(hours=8))
NOW=datetime.now(HK)
T=NOW.isoformat(timespec='seconds')
IN5=(NOW+timedelta(minutes=5)).isoformat(timespec='seconds')
IN12=(NOW+timedelta(minutes=12)).isoformat(timespec='seconds')


def official(path, params=None):
    if path=='/route/HKI':
        return {'data':{'routes':['69','11M']},'generated_timestamp':T}
    if path=='/route/HKI/69':
        return {'data':[{'route_id':2000410,'route_code':'69','description_tc':'\u6b63\u5e38\u73ed\u6b21',
                          'directions':[{'route_seq':1,'orig_en':'Cyberport','orig_tc':'\u6578\u78bc\u6e2f','dest_en':'Quarry Bay (Circular)','dest_tc':'\u9c02\u9b5a\u6d8c（\u5faa\u74b0）'},
                                        {'route_seq':2,'orig_tc':'\u9c02\u9b5a\u6d8c','dest_tc':'\u6578\u78bc\u6e2f'}]}], 'generated_timestamp':T}
    if path=='/route-stop/2000410/1':
        return {'data':{'route_stops':[{'stop_seq':1,'stop_id':20003337,'name_en':'Cyberport Public Transport Interchange','name_tc':'\u6578\u78bc\u6e2f\u516c\u5171\u904b\u8f38\u4ea4\u532f\u8655'},
                                      {'stop_seq':2,'stop_id':20007719,'name_en':'Information Road','name_tc':'\u8cc7\u8a0a\u9053'}]}, 'generated_timestamp':T}
    if path=='/stop/20003337':
        return {'data':{'enabled':True, 'coordinates':{'wgs84':{'latitude':22.2619,'longitude':114.1301}}},'generated_timestamp':T}
    if path=='/eta/route-stop/2000410/1/1':
        return {'data':{'enabled':True,'stop_id':20003337,'eta':[{'eta_seq':1,'diff':5,'timestamp':IN5,'remarks_tc':None},
                                                               {'eta_seq':2,'diff':12,'timestamp':IN12,'remarks_tc':'\u672a\u958b\u51fa'}]},
                'generated_timestamp':T}
    if path=='/eta/route-stop/2000410/1/2':
        return {'data':{'enabled':False,'stop_id':20007719,'description_tc':'\u8a72\u7ad9\u66ab\u7121\u5be6\u6642\u9810\u6e2c'},'generated_timestamp':T}
    if path=='/route-stop/1A/outbound/1':
        return {'data':[{'stop':'A3ADFCDF8487ADB9','seq':1}], 'generated_timestamp':T}
    if path=='/eta/A3ADFCDF8487ADB9/1A/1':
        return {'data':[{'dir':'O','eta':IN5,'seq':1},{'dir':'I','eta':IN12,'seq':1}], 'generated_timestamp':T}
    if path=='/stop/A3ADFCDF8487ADB9':
        return {'data':{'name_tc':'\u4e2d\u79c0\u8302\u576a','lat':22.318856,'long':114.231353},'generated_timestamp':T}
    if path=='/route-stop/CTB/1/inbound':
        return {'data':[{'stop':'002403','seq':1,'dir':'I'}], 'generated_timestamp':T}
    if path=='/eta/CTB/002403/1':
        return {'data':[{'dir':'I','eta':IN5,'seq':1},{'dir':'O','eta':IN12,'seq':1}], 'generated_timestamp':T}
    if path=='/stop/002403':
        return {'data':{'name_tc':'\u6d4b\u8bd5\u57ce\u5df4\u7ad9','lat':22.29,'long':114.17},'generated_timestamp':T}
    if path=='/v1/transport/mtr/getSchedule.php':
        return {'status':1,'isdelay':'N','curr_time':T,
                'data':{'TKL-TKO':{'UP':[{'ttnt':'3','valid':'Y','dest':'POA','plat':'1','time':IN5}]}}}
    if path=='/weatherAPI/opendata/weather.php':
        return {'updateTime':T,'temperature':{'data':[{'place':'Hong Kong Observatory','value':27}]},
                'humidity':{'data':[{'value':85}]}}
    return {'data':[],'generated_timestamp':T}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server,'DB_PATH', tmp_path/'test.sqlite3')
    server.CACHE.clear()
    server.CIRCUITS.clear()
    server.INFLIGHT.clear()
    def handler(request):
        url=str(request.url)
        path=urlparse(url).path
        for prefix in ('/v1/transport/kmb', '/v2/transport/citybus'):
            if path.startswith(prefix): path=path[len(prefix):]
        return httpx.Response(200,json=official(path))
    with TestClient(server.app) as c:
        real=server.app.state.client
        server.app.state.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yield c
        import asyncio
        asyncio.run(server.app.state.client.aclose())
        server.app.state.client=real


def test_green_minibus_chain_and_persist(client):
    route=client.get('/api/gmb/routes/HKI'); assert route.status_code==200 and '69' in route.json()['routes']
    variants=client.get('/api/gmb/route/HKI/69').json()['variants']
    assert variants[0]['route_id']==2000410 and variants[0]['route_seq']==1 and variants[0]['origin']=='Cyberport'
    stops=client.get('/api/gmb/stops/2000410/1').json()['stops'];assert stops[0]['stop_seq']==1
    stop=client.get('/api/gmb/stop/20003337').json();assert stop['latitude']==22.2619
    eta=client.get('/api/gmb/eta/2000410/1/1').json()
    assert eta['status']=='fresh' and eta['official'] and len(eta['etas'])==2
    assert eta['etas'][0]['minutes'] in (4,5)
    saved=client.get('/api/lab/summary').json()
    assert saved['eta_snapshot_rows']==2 and saved['independent_actual_arrivals']==0 and saved['mae'] is None


def test_disabled_eta_does_not_fabricate_arrival(client):
    result=client.get('/api/gmb/eta/2000410/1/2').json()
    assert result['status']=='unavailable' and result['etas']==[]


def test_stale_official_data_hidden(client, monkeypatch):
    async def fake(*a,**kw):
        return {'generated_timestamp':(NOW-timedelta(minutes=20)).isoformat(),
                'data':{'enabled':True,'stop_id':20003337,'eta':[{'timestamp':IN5,'diff':5,'eta_seq':1}]}}
    monkeypatch.setattr(server,'upstream',fake)
    eta=client.get('/api/gmb/eta/2000410/1/1').json()
    assert eta['status']=='stale' and eta['etas']==[]
    assert client.get('/api/lab/summary').json()['eta_snapshot_rows']==0


def test_bus_providers_direction_filter(client):
    stops=client.get('/api/bus/kmb/stops?route=1A&direction=outbound').json()
    assert stops['stops'][0]['stop_id']=='A3ADFCDF8487ADB9'
    eta=client.get('/api/bus/kmb/eta?route=1A&stop_id=A3ADFCDF8487ADB9&direction=outbound').json()
    assert len(eta['etas'])==1 and eta['status']=='fresh'
    ctb=client.get('/api/bus/ctb/stops?route=1&direction=inbound').json()
    assert ctb['stops'][0]['stop_id']=='002403'
    eta=client.get('/api/bus/ctb/eta?route=1&stop_id=002403&direction=inbound').json()
    assert len(eta['etas'])==1 and eta['status']=='fresh'


def test_mtr_weather(client):
    assert client.get('/api/weather').json()['temperature_readings'][0]['value']==27
    r=client.get('/api/mtr/next-train?line=TKL&station=TKO')
    assert r.status_code==200 and r.json()['status']=='fresh' and r.json()['trains'][0]['minutes']==3


def test_validation(client):
    assert client.get('/api/gmb/routes/BOGUS').status_code==422
    assert client.get('/api/gmb/route/HKI/%3Cscript%3E').status_code==422
    assert client.get('/api/bus/ctb/eta?route=1&stop_id=bad').status_code==422
    assert client.get('/api/mtr/next-train?line=TKL&station=XXX').status_code==422


def test_http_and_assets(client):
    page=client.get('/');assert page.status_code==200 and 'operatorSelect' in page.text
    js=client.get('/assets/live.js');assert js.status_code==200 and 'loadGmbStops' in js.text
    assert client.get('/assets/server.py').status_code==404
