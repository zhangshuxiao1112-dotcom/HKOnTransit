"""Regression tests for bounded requests, caching, English output and honest AI fallback."""
import asyncio
import re
import time
from pathlib import Path
import httpx
import pytest
import server
from test_api import client
from ai.base import AIServiceConfig
from ai.service import AIService


def replace_transport(handler):
    server.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_retry_recovers_transient_failure(client):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200,
                              json={'data': {'routes': ['69']}})
    replace_transport(handler)
    r = client.get('/api/gmb/routes/HKI')
    assert r.status_code == 200 and r.json()['routes'] == ['69']
    assert len(calls) == 2
    assert client.get('/api/gmb/routes/HKI').status_code == 200
    assert len(calls) == 2


def test_unresponsive_upstream_has_deadline(client, monkeypatch):
    monkeypatch.setattr(server, 'ATTEMPT_TIMEOUT', .02)
    monkeypatch.setattr(server, 'REQUEST_BUDGET', .3)
    async def handler(request):
        await asyncio.Event().wait()
    replace_transport(handler)
    start = time.monotonic()
    r = client.get('/api/gmb/routes/HKI')
    assert r.status_code == 503 and time.monotonic() - start < .6
    assert 'Loading' not in r.json()['detail']


def test_repeated_failures_open_circuit(client):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ConnectError('offline', request=request)
    replace_transport(handler)
    for _ in range(3):
        assert client.get('/api/gmb/routes/HKI').status_code == 503
    before = len(calls)
    response = client.get('/api/gmb/routes/HKI')
    assert response.status_code == 503 and len(calls) == before
    assert 'retry-after' in response.headers


def test_duplicate_refreshes_share_one_request():
    async def scenario():
        server.CACHE.clear();server.CIRCUITS.clear();server.INFLIGHT.clear()
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            await asyncio.sleep(.01)
            return httpx.Response(200, json={'data': {'routes': ['69']}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            server.app.state.client = c
            values = await asyncio.gather(*(server.upstream(server.GMB, '/route/HKI') for _ in range(8)))
        assert calls == 1 and all(v == values[0] for v in values)
    asyncio.run(scenario())


def test_malformed_response_is_not_cached(client):
    replace_transport(lambda req: httpx.Response(200, json=['invalid']))
    assert client.get('/api/gmb/routes/HKI').status_code == 503
    assert not server.CACHE


def test_mtr_without_data_returns_unavailable(client):
    replace_transport(lambda req: httpx.Response(200, json={'status': 0, 'message': 'No service'}))
    response = client.get('/api/mtr/next-train?line=TKL&station=TKO')
    assert response.status_code == 200 and response.json()['status'] == 'unavailable'
    assert response.json()['trains'] == []


def test_official_english_fields_are_selected(client):
    assert client.get('/api/gmb/route/HKI/69').json()['variants'][0]['origin'] == 'Cyberport'
    assert server.name({'name_en': 'Central', 'name_tc': '\u4e2d\u74b0'}) == 'Central'
    for path in ('/api/health', '/api/lab/summary', '/api/ai/status'):
        assert not re.search(r'[\u3400-\u9fff]', client.get(path).text)


def test_english_static_release():
    root = Path(__file__).resolve().parents[1]
    for file in ('index.html', 'static/live.js', 'static/ai.js', 'static/network.js'):
        assert not re.search(r'[\u3400-\u9fff]', (root / file).read_text())
    assert '<html lang="en">' in (root / 'index.html').read_text()


def test_missing_deepseek_key_selects_local_adapter(monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    service = AIService(AIServiceConfig(provider='deepseek'))
    assert service.provider_label == 'mock'
    assert service.adapter._fallback_reason == 'deepseek_not_configured'


def test_slow_ai_falls_back_with_disclosure():
    async def scenario():
        service = AIService(AIServiceConfig(provider='mock', request_timeout=.02))
        async def slow(*args, **kwargs):
            await asyncio.Event().wait()
        service.adapter.extract_intent = slow
        result = await service.interpret_preferences('Less walking and fewer transfers')
        assert {p.key for p in result.preferences} == {'less_walking', 'fewer_transfers'}
        assert 'locally' in result.notes
        assert service.last_fallback_reason == 'TimeoutError'
    asyncio.run(scenario())


def test_report_cache_includes_context():
    async def scenario():
        service = AIService(AIServiceConfig(provider='mock'))
        a = await service.structure_community_report('Vehicle passed', context={'route': '1'})
        b = await service.structure_community_report('Vehicle passed', context={'route': '2'})
        assert a.route == '1' and b.route == '2'
    asyncio.run(scenario())
