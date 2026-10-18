"""HKOnTransit GenAI integration layer.

GenAI is the *interpretation & explanation* layer between passengers and Hong
Kong's fragmented transport data. It does NOT replace the transport engine.
Official APIs and deterministic rules remain authoritative for ETA, fares,
routes and stop information; the LLM only handles language-heavy tasks:

  1. interpreting natural-language travel preferences  -> structured intent
  2. structuring free-text community reports            -> mobility events
  3. explaining complex route recommendations            -> passenger-friendly text

The model itself is replaceable (see ``base.LLMAdapter``). The durable value
lives in the transport-specific schemas, validation logic and mobility context
built around it.

Public surface (imported by the FastAPI router)::

    from ai.service import ai_service
    from ai.schemas import InterpretedIntent, MobilityEvent, RouteExplanation
"""
from __future__ import annotations

from ai.schemas import (  # noqa: F401
    InterpretedIntent,
    MobilityEvent,
    RouteExplanation,
    TravelPreference,
)
from ai.service import AIService, ai_service  # noqa: F401

__all__ = [
    "AIService",
    "ai_service",
    "InterpretedIntent",
    "MobilityEvent",
    "RouteExplanation",
    "TravelPreference",
]
