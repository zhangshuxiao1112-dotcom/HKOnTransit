"""High-level GenAI service: adapter selection + caching + validation gating.

This is the ONLY entry point the FastAPI router (and any future internal
caller) uses. It guarantees the hybrid-architecture invariant:

    * language-heavy tasks (intent / report / explanation) hit the LLM,
    * every LLM result is schema-validated + rule-checked before use,
    * high-frequency operations (ETA, routing, map) never touch the LLM,
    * structured outputs are cached and reused where possible.

Swapping the model is a config change, not a code change.
"""
from __future__ import annotations

import os
import asyncio
import json
import re
import httpx
import time
from typing import Any

from ai.base import AIServiceConfig, LLMAdapter
from ai.schemas import InterpretedIntent, MobilityEvent, RouteExplanation
from ai.validators import validate_explanation, validate_intent, validate_report


def _config_from_env() -> AIServiceConfig:
    """Build GenAI configuration from environment variables.

    All variables are optional; the demo defaults to a fully offline mock
    provider so the app runs with zero configuration.

    Recognised environment variables:
      HKONTRANSIT_AI_PROVIDER  — "mock" (default) | "deepseek" (live, needs key)
      HKONTRANSIT_AI_LANG      — default output language (default: zh-Hant)
      HKONTRANSIT_AI_TIMEOUT   — request timeout in seconds (default: 12)
      HKONTRANSIT_AI_CACHE     — "1" to enable caching (default), "0" to disable
      HKONTRANSIT_AI_CACHE_TTL — cache TTL in seconds (default: 120)

    When provider=deepseek, also set (see ai/adapters/deepseek.py):
      DEEPSEEK_API_KEY   — API key (sk-...)
      DEEPSEEK_MODEL      — model id (default: deepseek-chat)
      DEEPSEEK_BASE_URL   — API base (default: https://api.deepseek.com)
    """
    return AIServiceConfig(
        provider=os.environ.get("HKONTRANSIT_AI_PROVIDER", "mock"),
        default_language="en",
        request_timeout=float(os.environ.get("HKONTRANSIT_AI_TIMEOUT", "8")),
        enable_cache=os.environ.get("HKONTRANSIT_AI_CACHE", "1") != "0",
        cache_ttl_seconds=int(os.environ.get("HKONTRANSIT_AI_CACHE_TTL", "120")),
    )


def build_adapter(config: AIServiceConfig) -> LLMAdapter:
    """Factory for the active adapter. New models register here.

    To add a new LLM provider:
      1. Create ai/adapters/<name>.py exporting an LLMAdapter subclass.
      2. Add an ``elif config.provider == "<name>"`` branch here.
      3. Register the new env vars in .env.example and _config_from_env().
    If a live provider is requested but credentials are missing, the service
    gracefully falls back to the mock adapter so the demo still works.
    """
    if config.provider == "deepseek":
        from ai.adapters.deepseek import DeepSeekAdapter, LLMNotConfigured  # lazy import
        try:
            return DeepSeekAdapter(timeout=config.request_timeout)
        except LLMNotConfigured:
            # Live provider requested but unconfigured -> stay safe on mock.
            from ai.adapters.mock import MockAdapter
            adapter = MockAdapter()
            adapter._fallback_reason = "deepseek_not_configured"  # type: ignore[attr-defined]
            return adapter
    # default + unknown -> mock
    from ai.adapters.mock import MockAdapter
    return MockAdapter()


class _Cache:
    """Tiny TTL cache for structured AI outputs (LLM calls are selective)."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._store.get(key)
        if hit and (time.monotonic() - hit[0]) < self._ttl:
            return hit[1]
        return None

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)
        if len(self._store) > 200:
            self._store.clear()


class AIService:
    """Singleton GenAI service consumed by the router."""

    def __init__(self, config: AIServiceConfig | None = None) -> None:
        self.config = config or _config_from_env()
        self.adapter = build_adapter(self.config)
        self.last_fallback_reason = None
        self._cache = _Cache(self.config.cache_ttl_seconds) if self.config.enable_cache else None

    async def _call(self, method: str, *args, **kwargs):
        try:
            result = await asyncio.wait_for(
                getattr(self.adapter, method)(*args, **kwargs),
                timeout=min(self.config.request_timeout, 8.0))
            generated = []
            if method == 'extract_intent':
                generated = [result.get('notes')] + [p.get('rationale') for p in result.get('preferences', []) if isinstance(p, dict)]
            elif method == 'structure_report':
                generated = [result.get('summary')]
            elif method == 'explain_route':
                generated = [result.get(k) for k in ('route_summary', 'walk_note', 'fare_note', 'accessibility_note')]
                generated += result.get('why_recommended', []) + result.get('trade_offs', [])
            if any(re.search(r'[\u3400-\u9fff]', str(value or '')) for value in generated):
                raise ValueError('Generated output did not follow the English release language.')
            self.last_fallback_reason = None
            return result
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, IndexError) as error:
            from ai.adapters.mock import MockAdapter
            self.last_fallback_reason = type(error).__name__
            result = await getattr(MockAdapter(), method)(*args, **kwargs)
            if method == 'extract_intent':
                result['notes'] = 'Live AI unavailable. Interpreted locally with keyword rules.'
            return result

    @property
    def provider_label(self) -> str:
        return getattr(self.adapter, "name", "mock")

    async def interpret_preferences(self, text: str, *, language: str | None = None) -> InterpretedIntent:
        lang = "en"
        cache_key = 'intent:' + json.dumps([lang, text], ensure_ascii=False)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        raw = await self._call('extract_intent', text, language=lang)
        result = validate_intent(raw, source_text=text)
        if self._cache is not None:
            self._cache.put(cache_key, result)
        return result

    async def structure_community_report(self, text: str, *, context: dict | None = None) -> MobilityEvent:
        cache_key = 'report:' + json.dumps([text, context], sort_keys=True, ensure_ascii=False)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        raw = await self._call('structure_report', text, context=context)
        result = validate_report(raw, source_text=text)
        if self._cache is not None:
            self._cache.put(cache_key, result)
        return result

    async def explain_route(self, route_data: dict, *, preferences: dict | None = None,
                            language: str | None = None) -> RouteExplanation:
        lang = "en"
        cache_key = 'explain:' + json.dumps([lang, route_data, preferences], sort_keys=True, ensure_ascii=False)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        raw = await self._call('explain_route', route_data, preferences=preferences, language=lang)
        result = validate_explanation(raw)
        if self._cache is not None:
            self._cache.put(cache_key, result)
        return result

    async def close(self) -> None:
        await self.adapter.close()


# Module-level singleton the router imports.
ai_service = AIService()
