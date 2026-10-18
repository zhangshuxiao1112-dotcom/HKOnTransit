"""FastAPI router for the GenAI interpretation/explanation layer.

Three endpoints, one per language-heavy task identified by the technical team:
  POST /api/ai/interpret-preferences  -- NL -> structured intent
  POST /api/ai/structure-report        -- free-text -> mobility event
  POST /api/ai/explain-route           -- official route -> explanation

All responses are schema-validated + rule-checked (see ``ai.validators``);
raw model output never reaches the client. A GET /api/ai/status endpoint
exposes which provider is active so the UI can show "AI: mock (offline)" vs
"AI: deepseek (live)" honestly.
"""
from __future__ import annotations

from fastapi import APIRouter

from ai.schemas import (
    ExplainRouteRequest,
    InterpretRequest,
    StructureReportRequest,
)
from ai.service import ai_service

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def ai_status():
    """Report the active GenAI provider so the UI is honest about mock vs live."""
    return {
        "provider": ai_service.provider_label,
        "language": ai_service.config.default_language,
        "cache": ai_service.config.enable_cache,
        "model_replaceable": True,
        "fallback_reason": getattr(ai_service.adapter, "_fallback_reason", None) or ai_service.last_fallback_reason,
        "note": "AI interprets language only. Arrivals, routes, stops and fares require official data.",
    }


@router.post("/interpret-preferences")
async def interpret_preferences(req: InterpretRequest):
    """Natural-language journey preference -> structured, validated intent."""
    result = await ai_service.interpret_preferences(req.text)
    return result.model_dump()


@router.post("/structure-report")
async def structure_report(req: StructureReportRequest):
    """Free-text community observation -> standardised, unverified mobility event."""
    result = await ai_service.structure_community_report(req.text, context=req.context)
    return result.model_dump()


@router.post("/explain-route")
async def explain_route(req: ExplainRouteRequest):
    """Official route payload -> passenger-friendly explanation (grounded)."""
    result = await ai_service.explain_route(
        req.route_data, preferences=req.preferences, language=req.language,
    )
    return result.model_dump()
