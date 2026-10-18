"""Model-agnostic LLM adapter interface and service configuration.

The model is replaceable; this abstract interface is the stable contract every
adapter (DeepSeek, mock, future OpenAI/Anthropic/local) must satisfy. New
models plug in by adding an ``adapters/*`` module and registering it in
``AIService`` -- nothing else in the codebase changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AIServiceConfig:
    """Runtime configuration for the GenAI layer, all env-driven.

    ``provider`` selects the adapter. Defaults to ``mock`` so the demo runs
    fully offline with deterministic, review-safe stubs. Set
    ``HKONTRANSIT_AI_PROVIDER=deepseek`` + ``DEEPSEEK_API_KEY`` to go live.
    """
    provider: str = "mock"                      # "mock" | "deepseek"
    default_language: str = "en"
    request_timeout: float = 12.0
    enable_cache: bool = True                   # cache structured AI outputs
    cache_ttl_seconds: int = 120                # LLM calls are selective, not continuous
    # provider-specific knobs live on the adapter; the key never leaves env.
    extra: dict = field(default_factory=dict)


class LLMAdapter(ABC):
    """Every concrete model adapter implements these three language-heavy tasks.

    Each method returns a *plain dict* (not yet Pydantic-validated); the
    :class:`ai.service.AIService` runs validation + transport rules before the
    result is allowed to reach the transport engine or UI.
    """

    name: str = "abstract"

    @abstractmethod
    async def extract_intent(self, text: str, *, language: str | None = None) -> dict:
        """NL travel preference text -> raw structured-intent dict."""

    @abstractmethod
    async def structure_report(self, text: str, *, context: dict | None = None) -> dict:
        """Free-text community report -> raw mobility-event dict."""

    @abstractmethod
    async def explain_route(self, route_data: dict, *, preferences: dict | None = None,
                            language: str = "zh-Hant") -> dict:
        """Official route payload -> raw passenger-friendly explanation dict."""

    async def close(self) -> None:
        """Release any client resources (httpx, etc.). Override if needed."""
