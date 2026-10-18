# ai/ — GenAI interpretation & explanation layer

GenAI is the **interpretation and explanation layer** between passengers and
Hong Kong's fragmented transport data. It does **not** replace the transport
engine. Official APIs and deterministic rules remain authoritative for ETA,
fares, routes and stop information. The LLM only handles three language-heavy
tasks (per the technical team's hybrid architecture):

| Task | Endpoint | NL → Structured |
|---|---|---|
| Interpret preferences | `POST /api/ai/interpret-preferences` | "I want less walking, even if it costs more" → `less_walking@0.9`, `cheaper@0.2` |
| Structure community report | `POST /api/ai/structure-report` | free text → standardised, **unverified** mobility event |
| Explain route | `POST /api/ai/explain-route` | official route payload → passenger-friendly explanation |
| Status | `GET /api/ai/status` | active provider (mock / deepseek) |

## Architecture

```
ai/
  schemas.py     Pydantic models = the model-agnostic I/O contract (core value)
  prompts.py     transport-specific prompts (prompt-constrained extraction)
  validators.py  schema + deterministic-rule gating (defence in depth)
  base.py        LLMAdapter ABC + AIServiceConfig (model is replaceable)
  adapters/
    mock.py      offline, deterministic stubs (default — runs with no key)
    deepseek.py  DeepSeek (OpenAI-compatible) adapter — the team's target backend
  service.py     AIService: adapter selection + caching + validation gating
  router.py      FastAPI router mounting the 3 endpoints + status
```

## Activation

The demo defaults to `mock` (fully offline, deterministic, review-safe):

```bash
cp .env.example .env
# then run.sh as usual — AI works with zero network/keys
```

Go live with DeepSeek (the technical team's "DeepSeek V4.1 Flash" target):

```bash
export HKONTRANSIT_AI_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-...
export DEEPSEEK_MODEL=deepseek-chat   # or a newer Flash revision
```

The model id is configurable so a newer revision drops in without code changes.
The durable value is the schemas + prompts + validators, not the model string.

## Frontend integration

`static/ai.js` is a **progressive enhancement**: if `/api/ai/*` is unreachable,
the existing chip-based preference UI keeps working untouched. It exposes:

- `window.__hkExplainRoute(routeData, prefs)` — reserved hook for the results screen
- `window.__hkStructureReport(text, context)` — reserved hook for the report form

## Invariants (enforced in code)

1. Raw model output never reaches the UI/transport engine — `validators.py` gates it.
2. Community events are always `unverified` — corroboration is a deterministic decision.
3. High-frequency ops (ETA refresh, routing, map) never call the LLM; structured outputs are cached.
4. The LLM may not invent ETA/fares/stops — only explain/extract/summarise injected official data.
