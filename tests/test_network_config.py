"""User-machine proxy configuration and safe failure messages."""
import asyncio
import httpx
import server


def test_os_proxy_is_used_without_environment_proxy(monkeypatch):
    monkeypatch.delenv('HKONTRANSIT_PROXY', raising=False)
    monkeypatch.setenv('HKONTRANSIT_NETWORK_MODE', 'system')
    monkeypatch.setattr(server, 'getproxies', lambda: {'https': 'http://127.0.0.1:7890'})
    monkeypatch.setattr(server, 'proxy_bypass', lambda host: False)
    options, mode = server.transport_options()
    assert mode == 'system-proxy'
    assert 'https://data.etagmb.gov.hk' in options['mounts']
    async def close():
        for transport in options['mounts'].values():
            await transport.aclose()
    asyncio.run(close())


def test_os_proxy_exclusions_and_direct_mode(monkeypatch):
    monkeypatch.delenv('HKONTRANSIT_PROXY', raising=False)
    monkeypatch.setenv('HKONTRANSIT_NETWORK_MODE', 'system')
    monkeypatch.setattr(server, 'getproxies', lambda: {'https': 'http://127.0.0.1:7890'})
    monkeypatch.setattr(server, 'proxy_bypass', lambda host: True)
    assert server.transport_options()[0]['mounts'] == {}
    monkeypatch.setenv('HKONTRANSIT_NETWORK_MODE', 'direct')
    options, mode = server.transport_options()
    assert options['trust_env'] is False and mode == 'direct'
    assert options['verify'].check_hostname


def test_errors_are_actionable_and_do_not_expose_proxy_secrets():
    assert 'DNS' in server.connection_error(httpx.ConnectError('[Errno -3] Temporary failure in name resolution'))
    message = server.connection_error(httpx.ProxyError('http://user:secret@proxy.example:7890'))
    assert 'Proxy connection failed' in message and 'secret' not in message
    assert 'TLS certificate' in server.connection_error(httpx.ConnectError('CERTIFICATE_VERIFY_FAILED'))
    assert 'timed out' in server.connection_error(asyncio.TimeoutError())


def test_ssl_handshake_timeout_is_not_misreported_as_certificate_failure():
    error = httpx.ConnectTimeout('SSL handshake timed out')
    assert 'timed out' in server.connection_error(error)
    assert 'certificate verification failed' not in server.connection_error(error)
