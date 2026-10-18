"""DeepSeek adapter -- the technical team's target backend ("DeepSeek V4.1 Flash").

Uses DeepSeek's OpenAI-compatible chat-completions API. Structured output is
enforced via a strict system prompt + JSON response mode; the result is still
run through :mod:`ai.validators` before use (defence in depth, per the hybrid
architecture: the model is never trusted outright).

The model id is configurable via ``DEEPSEEK_MODEL`` so the team can move to a
newer Flash revision without code changes -- the durable contract is the
schema + prompts + validators, not the model string.

Activation:
    HKONTRANSIT_AI_PROVIDER=deepseek
    DEEPSEEK_API_KEY=sk-...
    DEEPSEEK_MODEL=deepseek-chat          # or the team's V4.1 Flash revision
    DEEPSEEK_BASE_URL=https://api.deepseek.com   # optional override

Without a key, the adapter raises ``LLMNotConfigured``; the service then keeps
the demo on the mock provider rather than surfacing a broken AI feature.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from tls_config import ssl_context

from ai.base import LLMAdapter
from ai.prompts import (
    EXPLAIN_SYSTEM,
    EXPLAIN_USER,
    INTENT_SYSTEM,
    INTENT_USER,
    REPORT_SYSTEM,
    REPORT_USER,
)


class LLMNotConfigured(RuntimeError):
    """Raised when a live adapter is selected but credentials are missing."""


def _json_schema_response(message_content: str) -> dict:
    """Best-effort parse of an LLM message that should be pure JSON.

    Tolerates a stray ```json fence; on total failure returns an empty dict
    so validators downgrade the result safely instead of crashing.
    """
    if not message_content:
        return {}
    text = message_content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # last-ditch: grab the first {...} block
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
    return data if isinstance(data, dict) else {}


class DeepSeekAdapter(LLMAdapter):
    name = "deepseek"
    BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    def __init__(self, *, api_key: str | None = None, client: httpx.AsyncClient | None = None,
                 timeout: float = 12.0):
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self._client = client
        self._timeout = timeout
        self._ensure()

    def _ensure(self) -> None:
        if not self._api_key:
            raise LLMNotConfigured("DEEPSEEK_API_KEY is not set; cannot call the live model.")

    async def _chat(self, system: str, user: str) -> dict:
        self._ensure()
        client = self._client or httpx.AsyncClient(timeout=self._timeout, verify=ssl_context())
        owns_client = self._client is None
        try:
            resp = await client.post(
                f"{self.BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self.MODEL,
                    "messages": [{"role": "system", "content": system},
                                  {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,   # low -- we want deterministic structure
                    "max_tokens": 700,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            content = (((payload.get("choices") or [{}])[0]).get("message") or {}).get("content")
            return _json_schema_response(content or "")
        finally:
            if owns_client:
                await client.aclose()

    # -- LLMAdapter ----------------------------------------------------------

    async def extract_intent(self, text: str, *, language: str | None = None) -> dict:
        user = INTENT_USER.format(text=text)
        data = await self._chat(INTENT_SYSTEM, user)
        if language:  # honour explicit request over the model's guess
            data["language_detected"] = language
        return data

    async def structure_report(self, text: str, *, context: dict | None = None) -> dict:
        user = REPORT_USER.format(context_json=json.dumps(context or {}, ensure_ascii=False), text=text)
        return await self._chat(REPORT_SYSTEM, user)

    async def explain_route(self, route_data: dict, *, preferences: dict | None = None,
                            language: str = "zh-Hant") -> dict:
        user = EXPLAIN_USER.format(
            language=language,
            preferences_json=json.dumps(preferences or {}, ensure_ascii=False),
            route_data_json=json.dumps(route_data, ensure_ascii=False),
        )
        return await self._chat(EXPLAIN_SYSTEM, user)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
