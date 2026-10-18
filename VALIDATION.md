# Validation — English release

Date: 18 October 2026, Hong Kong time.

## Live API checks

The actual FastAPI handlers were exercised through an in-process ASGI client using real HTTP connections to official services. The SQLite file used for these checks was temporary and is not included in the release.

| Provider | Sample | Result |
|---|---|---|
| GMB | HKI route list, route 69 variants, route 2000410 direction 1 stops, stop 20003337 coordinates, stop sequence 1 ETA | All HTTP 200; ETA fresh |
| KMB | Route 1A outbound service type 1 stops, stop A3ADFCDF8487ADB9 details and ETA | All HTTP 200; ETA fresh |
| Citybus | Route 1 inbound stops, stop 002403 details and ETA | All HTTP 200; ETA fresh |
| MTR | TKL / TKO Next Train | HTTP 200; fresh |
| HKO | Current weather, English | HTTP 200 |
| Local AI | Less walking and fewer transfers | HTTP 200; local rules, not a credentialed LLM |
| Diagnostics / Lab | Five-provider connection probe and SQLite counts | HTTP 200 |

16 handler requests returned HTTP 200. Observed transport/weather request durations in the full flow ranged from 0.331 to 5.443 seconds, including cache and connection effects. These timings are specific to this run. The separate provider diagnostic returned `all_connected: true` at 08:54 HKT.

Raw per-handler results and provider timestamps are in `verification/live_api_checks.json` and `verification/provider_diagnostics.json`. No production API was replaced because every original provider passed its sample check.

## Automated regression checks

23 Python tests passed in the current release. Coverage includes:

- Original GMB/KMB/Citybus chains, direction filtering, persistence and input validation.
- Stale and disabled ETA handling without fabricated arrivals.
- One transient retry, bounded slow responses and malformed response rejection.
- Failure circuit behaviour and single-request coalescing for concurrent callers.
- English fields, static UI text and backend messages.
- Missing DeepSeek credentials, slow AI fallback disclosure and context-aware cache keys.

JavaScript syntax checks and shell launcher syntax check passed.

## DOM interaction verification

A jsdom simulation with deterministic, mocked API data passed 12 flow checks: GMB lookup and map, ride simulation, KMB, Citybus, MTR, preference interpretation, local report, assistance draft, English screen content, connection diagnostics, offline handling and request abortion.

This verifies DOM state and event handling, not layout or browser rendering. The existing responsive styling is retained with small adjustments for longer English labels. A real-browser visual/mobile rendering check was not available in this environment. `tests/browser_smoke.py` is an optional check for a local environment with Playwright and Chromium installed; it was not run here.

## Practical boundaries

- No API can be guaranteed never to time out. Requests now have finite budgets and recovery states.
- Point-in-time sample success does not verify all routes or future uptime.
- DeepSeek needs a valid key; no credentialed live model was tested.
- Arbitrary origin/destination routing, GPS tracking, shared community reports, validated ETA correction and actual assistance reservations remain outside the implemented prototype.
- Older Chinese reference screenshots are excluded from the English release.

## IDLE launcher update

Added `start.py` for Run → Run Module (F5). It installs missing packages with IDLE's own Python, loads `.env`, starts the local server and opens the browser once the health endpoint responds. It avoids passing IDLE output streams as child-process file descriptors.

The new integration test started the real launcher with stdout/stderr wrappers that provide only `write` and `flush`, then verified the running health endpoint, English homepage and JavaScript asset. This passed. A graphical IDLE session and automatic browser opening were not available for direct testing. The launcher update introduced the nineteenth regression test; the subsequent English audit expanded the suite to 23 tests.

## English-content audit

All delivered text files were scanned for Chinese characters, including HTML, JavaScript, Python, Markdown, JSON, shell scripts and environment examples. System interface text and accompanying documents are English. Chinese input keywords and test data are encoded as Unicode escapes without changing their runtime values.

The frontend optimization plan was rewritten in English with explicit implementation boundaries. Two outdated Chinese reference screenshots were removed. Local report summaries now use English event templates rather than echoing non-English input. Generated CJK prose from the optional AI adapter triggers the disclosed local English fallback; route explanations use English even if another language is requested.

All 23 Python tests passed, including four new English-release tests. The 12 DOM interaction checks passed again. The audit does not translate passenger-authored field values or establish visual layout correctness in a real browser.

An additional live audit checked 16 handler responses: all returned HTTP 200, and none contained Chinese characters in the sampled response payloads. The raw results are in `verification/english_live_api_checks.json`. This is a sample audit, not a guarantee about every future response or route.

## Connection troubleshooting revision (09:19 HKT)

- 26 automated tests pass, including OS proxy discovery, no-proxy exclusions, explicit direct mode and sanitised failure messages.
- Corrected asyncio timeout handling for Python 3.10 in transport and AI requests.
- A real gateway probe returned successful responses from GMB, KMB, Citybus, MTR and HKO using the execution environment's configured proxy. The GMB route/variant/stop/ETA chain returned HTTP 200 and fresh ETA.
- The user's local network remains untested. A screenshot showing only the unavailable badge cannot identify that machine's root cause.

## TLS trust revision (09:38 HKT)

29 tests pass. A real local HTTPS fixture confirms rejection of an untrusted certificate, acceptance after explicitly loading its CA, and rejection of a hostname mismatch. Native system trust plus Certifi roots is applied to official-data clients and proxy transports. Optional managed CA bundles are supported; verification is never disabled. TLS handshake timeouts are no longer labelled as certificate-verification failures. See `verification/tls_provider_diagnostics.json` for the bounded live probe; individual providers may time out. User-machine connectivity is not yet confirmed.
