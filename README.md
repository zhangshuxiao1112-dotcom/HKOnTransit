# HKOnTransit × CityPulse — English release

[![Tests](https://github.com/zhangshuxiao1112-dotcom/HKOnTransit/actions/workflows/tests.yml/badge.svg)](https://github.com/zhangshuxiao1112-dotcom/HKOnTransit/actions/workflows/tests.yml)

[Deploy the complete app](DEPLOYMENT.md) · [Deploy to Render](https://render.com/deploy?repo=https://github.com/zhangshuxiao1112-dotcom/HKOnTransit)

This repository contains the frontend **and** Python API gateway. Uploading source to GitHub does not launch the backend. Use the deployment guide to obtain a working public website.

The revised UI/UX is retained, with English screens, dynamic messages, accessibility labels, speech prompts and official English API fields.

Five official providers were successfully contacted on 18 October 2026 (Hong Kong time). The complete GMB, KMB and Citybus route/stop/ETA/location flows returned HTTP 200; their sampled arrival feeds and the sampled MTR feed were fresh. Weather also returned HTTP 200. See `VALIDATION.md` and `verification/` for the actual check results. These are point-in-time checks, not an uptime guarantee or a test of every route.

## Start in IDLE (recommended if you use IDLE)

1. Extract the **entire ZIP** into a normal folder. Keep `start.py`, `server.py`, `index.html`, `ai/` and `static/` together.
2. In IDLE choose **File → Open**, then open `start.py`.
3. Choose **Run → Run Module (F5)**. First launch installs missing packages using the same Python interpreter as IDLE.
4. A browser should open automatically. If not, copy the local URL printed in IDLE Shell into your browser.
5. Keep IDLE Shell running. Interact with the app in the browser. To stop, use **Shell → Interrupt Execution**.

Python 3.10+ is required. Do not open `run.sh` in IDLE and do not run `server.py` directly with F5: it defines the app but does not start the web server. If launch fails, copy the full error message and the Python version displayed by IDLE.

The launcher uses logging compatible with IDLE output streams and tries another local port when the default port is occupied. The delivered environment verified its HTTP startup with simulated IDLE-style streams; a graphical IDLE session was not available for direct testing.

## Start in a terminal

Requires Python 3.10+ and internet access.

```bash
# From the extracted project folder:
bash run.sh
```

Open **http://127.0.0.1:8000** and keep the terminal running. Do not double-click `index.html`: the API gateway must be running.

Alternatively:

```bash
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

`run.sh` loads `.env` automatically when present. For a manual launch using an edited `.env`, add `--env-file .env` to the uvicorn command.

## Live lookup

1. Open **Query** or **Find Routes & Stops**.
2. Select Green minibus, KMB or Citybus. For minibuses choose region and route; for buses type the route number and choose direction.
3. Choose **Find arrivals and stop**. For a bus this first loads the stops and queries the initial stop; select a different boarding stop and query again if needed.
4. Check arrival estimates, official timestamps and map coordinates. The active arrivals screen refreshes every minute.
5. Open **More → Real-time Info** for weather, MTR and **Check connections**.

KMB stop names use one cached official stop catalogue. Citybus stop names load progressively, with four concurrent requests; stable stop IDs remain visible if names cannot be fetched.

## Reliability

- The gateway makes at most two attempts per refresh: a 5-second total attempt limit, a 0.1-second retry delay and a 10.5-second caller budget.
- The browser aborts an uncompleted request after 12 seconds, including response-body reading. It shows an English recovery message instead of waiting indefinitely.
- Repeated failures open a 15-second circuit after three failed refreshes for a provider.
- Concurrent refreshes for the same endpoint share one upstream request.
- Route metadata and predictions have separate cache lifetimes. Stale predictions are hidden based on official timestamps; cached values are not relabelled as new.
- Changing a route, operator or stop invalidates older ETA responses.
- `/api/health` reports gateway readiness only. `/api/diagnostics` actively checks all five provider connections in parallel. Connection success is separate from prediction availability and freshness.

Public APIs and internet connections can still fail. This release bounds waiting and reports failures; it cannot guarantee permanent connectivity.

## Optional live AI

Transport APIs need no keys. The default language assistant uses **local keyword rules**, clearly labelled as a demo. A live LLM has not been tested with credentials.

```bash
cp .env.example .env
# Edit .env: HKONTRANSIT_AI_PROVIDER=deepseek and DEEPSEEK_API_KEY=...
bash run.sh
```

Missing credentials select the local adapter. Live AI failures or an 8-second deadline also fall back to local rules, with an explicit result note. AI never generates live vehicle arrivals. AI output defaults to English.

## Sources

| Provider | Official source |
|---|---|
| Green minibus | https://data.etagmb.gov.hk |
| KMB / LWB | https://data.etabus.gov.hk/v1/transport/kmb |
| Citybus | https://rt.data.gov.hk/v2/transport/citybus |
| MTR | https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php |
| HKO | https://data.weather.gov.hk/weatherAPI/opendata/weather.php |

The existing official sources passed live checks, so replacing them was unnecessary. Hosts remain fixed in the gateway; visitors cannot use it as an arbitrary URL proxy.

## Verification

```bash
python -m pytest tests -q
```

23 tests cover route chains, timestamps, persistence, input validation, transient retries, hanging upstreams, circuit behaviour, concurrent refreshes, English text, AI fallback and HTTP startup with IDLE-like streams.

DOM interaction checks (simulated APIs; no visual rendering):

```bash
npm install --no-audit --no-fund
python tests/export_dom_fixtures.py /tmp/hkot-fixtures.json
node tests/ui_dom_smoke.cjs /tmp/hkot-fixtures.json
```

Optional real-browser test: install Playwright and Chromium in your own environment, start the server and run `python tests/browser_smoke.py`. This real-browser check was **not run** in the delivery environment. Older Chinese reference screenshots have been removed from the English release.

## Prototype scope

The sample journey planner does not calculate arbitrary real itineraries. Sample travel times, manual Ride Mode, local-only community reports and assistance drafts remain labelled as prototypes. There is no GPS tracking, confirmed wheelchair booking, live occupancy feed, verified discount engine or released ETA correction model. ETA Lab stores predictions; accuracy needs independently observed arrivals. KMB currently queries service type 1. MTR supports only the combinations validated by the gateway and a curated subset in the UI.

## English-content audit

The delivery includes English page text, controls, placeholders, accessibility labels, notifications, error states, generated AI summaries and accompanying documentation. Official API requests use English fields or English language parameters. The older frontend plan is now English and older Chinese screenshots are excluded. Internal Chinese-input recognition and regression fixtures retain their original runtime values as Unicode escapes. Passenger-authored text and original names supplied by passengers are preserved as input.

23 regression tests and the DOM interaction checks passed after this audit. Generated Chinese AI text is rejected in favour of the labelled English local fallback. Real-browser visual rendering remains unverified.

## Connection troubleshooting update

If the API badge reports unavailable, use **More → Real-time Info → Check connections**.
The new release reads macOS/Windows system proxy settings as well as environment proxies.
It distinguishes DNS failures, proxy failures, certificate errors, HTTP rejection and timeouts.
Use **Download diagnostics** to share the provider results without proxy addresses or credentials.
After restoring connectivity, choose **Retry route lookup**; the route badge resets after recovery.

Launch with `start.py` in IDLE (F5) and use its printed HTTP address. Opening `index.html` directly cannot connect to the backend.
If needed, copy `.env.example` to `.env` and set `HKONTRANSIT_PROXY` to your working proxy URL.
Only set `HKONTRANSIT_NETWORK_MODE=direct` if you intend to bypass the proxy. Restart after configuration changes.
TLS verification stays enabled. This update does not establish the cause of an individual user's connection failure.

## TLS certificate repair

All official-data requests now use native system certificate trust plus public Certifi roots. The same verified SSL context is applied to direct connections, proxy transports and optional DeepSeek clients. Certificate and hostname verification remain enabled.

The IDLE launcher installs the additional `truststore` dependency automatically, using pip's system-certificate support. Fully extract the updated ZIP and restart `start.py`; do not reuse an old running server.

If verification still fails, check your device date and time. A university/company proxy may require its administrator-provided CA certificate to be trusted. You can set `HKONTRANSIT_CA_FILE` in `.env` to that PEM bundle and restart. Do not download arbitrary certificates. If dependency installation itself fails on python.org macOS Python, run the matching Python folder's `Install Certificates.command`, then rerun `start.py`.

Implementation references: https://www.python-httpx.org/advanced/ssl/ and https://truststore.readthedocs.io/en/stable/
